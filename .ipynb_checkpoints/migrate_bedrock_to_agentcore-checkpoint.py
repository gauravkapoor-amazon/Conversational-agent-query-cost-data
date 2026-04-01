
#!/usr/bin/env python3
"""
Migrate a Bedrock Agent (with Action Groups) to AgentCore Runtime + Gateway.

Usage:
    python migrate_bedrock_to_agentcore.py \
        --agent-id AGENT_ID \
        --agent-version DRAFT \
        --gateway-role-arn arn:aws:iam::ACCOUNT:role/GatewayRole \
        --runtime-role-arn arn:aws:iam::ACCOUNT:role/RuntimeRole \
        --region us-east-1 \
        [--dry-run]
"""

import boto3
import json
import argparse
import time
import os
import textwrap

# ---------------------------------------------------------------------------
# 1. Extract existing Bedrock Agent config
# ---------------------------------------------------------------------------

def extract_agent_config(bedrock_agent, agent_id, agent_version):
    """Pull agent definition + all action groups from Bedrock Agents."""
    agent = bedrock_agent.get_agent(agentId=agent_id)["agent"]
    print(f"✅ Found agent: {agent['agentName']} (model: {agent.get('foundationModel', 'N/A')})")

    # List and fetch all action groups
    action_groups = []
    paginator_args = {"agentId": agent_id, "agentVersion": agent_version}
    while True:
        resp = bedrock_agent.list_agent_action_groups(**paginator_args)
        for summary in resp.get("actionGroupSummaries", []):
            ag = bedrock_agent.get_agent_action_group(
                agentId=agent_id,
                agentVersion=agent_version,
                actionGroupId=summary["actionGroupId"]
            )["agentActionGroup"]
            action_groups.append(ag)
            print(f"  📦 Action Group: {ag['actionGroupName']} (state: {ag['actionGroupState']})")
        if "nextToken" not in resp:
            break
        paginator_args["nextToken"] = resp["nextToken"]

    # List knowledge bases
    kb_list = []
    kb_args = {"agentId": agent_id, "agentVersion": agent_version}
    while True:
        resp = bedrock_agent.list_agent_knowledge_bases(**kb_args)
        for kb in resp.get("agentKnowledgeBaseSummaries", []):
            kb_list.append(kb)
            print(f"  📚 Knowledge Base: {kb['knowledgeBaseId']}")
        if "nextToken" not in resp:
            break
        kb_args["nextToken"] = resp["nextToken"]

    return agent, action_groups, kb_list


# ---------------------------------------------------------------------------
# 2. Create AgentCore Gateway + migrate action groups as targets
# ---------------------------------------------------------------------------

def create_gateway(agentcore, agent_name, role_arn):
    """Create an AgentCore Gateway with IAM auth."""
    gateway = agentcore.create_gateway(
        name=f"{agent_name}-gateway",
        description=f"Migrated from Bedrock Agent: {agent_name}",
        protocolType="MCP",
        authorizerType="AWS_IAM",
        roleArn=role_arn
    )
    gw_id = gateway["gatewayId"]
    print(f"✅ Gateway created: {gw_id}")
    print(f"   URL: {gateway.get('gatewayUrl', 'pending...')}")

    # Wait for gateway to be ready
    #_wait_for_status(agentcore, gw_id, "get_gateway", "gatewayId", "status", "READY")
    time.sleep(30)
    return gateway


def _wait_for_status(client, resource_id, get_method, id_param, status_field, target, timeout=120):
    """Poll until resource reaches target status."""
    start = time.time()
    while time.time() - start < timeout:
        resp = getattr(client, get_method)(**{id_param: resource_id})
        status = resp.get(status_field, "")
        if status == target:
            return resp
        if "FAIL" in status.upper():
            raise RuntimeError(f"Resource {resource_id} failed: {resp.get('statusReasons', '')}")
        print(f"   ⏳ Status: {status}... waiting")
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {resource_id} to reach {target}")


def extract_tools_from_action_group(ag):
    """Convert Bedrock action group schema to AgentCore Gateway tool definitions."""
    tools = []

    # Case 1: Function schema (newer format)
    func_schema = ag.get("functionSchema", {})
    if "functions" in func_schema:
        for func in func_schema["functions"]:
            tool = {
                "name": func["name"],
                "description": func.get("description", func["name"]),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            for param_name, param_def in func.get("parameters", {}).items():
                tool["inputSchema"]["properties"][param_name] = {
                    "type": param_def.get("type", "string"),
                    "description": param_def.get("description", "")
                }
                if param_def.get("required", False):
                    tool["inputSchema"]["required"].append(param_name)
            tools.append(tool)
        return tools

    # Case 2: OpenAPI schema (inline payload)
    api_schema = ag.get("apiSchema", {})
    if "payload" in api_schema:
        openapi = json.loads(api_schema["payload"]) if isinstance(api_schema["payload"], str) else api_schema["payload"]
        for path, methods in openapi.get("paths", {}).items():
            for method, spec in methods.items():
                if method.lower() in ("get", "post", "put", "delete", "patch"):
                    tool_name = spec.get("operationId", f"{method}_{path.replace('/', '_').strip('_')}")
                    properties = {}
                    required = []
                    for param in spec.get("parameters", []):
                        properties[param["name"]] = {
                            "type": param.get("schema", {}).get("type", "string"),
                            "description": param.get("description", "")
                        }
                        if param.get("required", False):
                            required.append(param["name"])
                    # Request body
                    req_body = spec.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                    if "properties" in req_body:
                        for prop_name, prop_def in req_body["properties"].items():
                            properties[prop_name] = {
                                "type": prop_def.get("type", "string"),
                                "description": prop_def.get("description", "")
                            }
                        required.extend(req_body.get("required", []))

                    tools.append({
                        "name": tool_name,
                        "description": spec.get("summary", spec.get("description", tool_name)),
                        "inputSchema": {"type": "object", "properties": properties, "required": required}
                    })
        return tools

    # Case 3: S3-based schema — flag for manual handling
    if "s3" in api_schema:
        print(f"    ⚠️  OpenAPI schema in S3: s3://{api_schema['s3'].get('s3BucketName')}/{api_schema['s3'].get('s3ObjectKey')}")
        print(f"       Download and convert manually, or pass --fetch-s3-schemas")
    return tools


def create_gateway_targets(agentcore, gateway_id, action_groups):
    """Create a Gateway target for each action group's Lambda."""
    targets = []
    for ag in action_groups:
        if ag.get("actionGroupState") != "ENABLED":
            print(f"  ⏭️  Skipping disabled action group: {ag['actionGroupName']}")
            continue

        # Skip built-in action groups (UserInput, CodeInterpreter)
        if ag.get("parentActionSignature"):
            print(f"  ⏭️  Skipping built-in: {ag.get('parentActionSignature')}")
            continue

        executor = ag.get("actionGroupExecutor", {})
        lambda_arn = executor.get("lambda")
        if not lambda_arn:
            print(f"  ⚠️  No Lambda for '{ag['actionGroupName']}' — skipping (RETURN_CONTROL type?)")
            continue

        tools = extract_tools_from_action_group(ag)
        if not tools:
            print(f"  ⚠️  No tools extracted from '{ag['actionGroupName']}' — check schema")
            continue

        print(f"  🔧 Creating target: {ag['actionGroupName']} → {lambda_arn} ({len(tools)} tools)")

        target = agentcore.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=ag["actionGroupName"].replace(" ", "-"),
            description=ag.get("description", f"Migrated from action group: {ag['actionGroupName']}"),
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": lambda_arn,
                        "toolSchema": {"inlinePayload": tools}
                    }
                }
            },
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ]
        )
        targets.append({"action_group": ag["actionGroupName"], "target_id": target["targetId"], "tools": tools})
        print(f"    ✅ Target created: {target['targetId']}")

    return targets


# ---------------------------------------------------------------------------
# 3. Generate AgentCore Runtime agent code (Strands SDK)
# ---------------------------------------------------------------------------

def generate_agent_code(agent, gateway_id, gateway_url, kb_list, output_dir="agentcore_agent"):
    """Generate a deployable Strands agent that connects to the migrated Gateway."""
    os.makedirs(output_dir, exist_ok=True)

    model_id = agent.get("foundationModel", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
    system_prompt = agent.get("instruction", "You are a helpful assistant.")

    # --- agent.py ---
    agent_code = textwrap.dedent(f'''\
        #!/usr/bin/env python3
        """Auto-generated AgentCore agent — migrated from Bedrock Agent: {agent["agentName"]}"""
        import json
        import boto3
        from strands import Agent
        from strands.models import BedrockModel
        from strands.tools.mcp import MCPClient

        GATEWAY_URL = "{gateway_url}"
        MODEL_ID = "{model_id}"
        SYSTEM_PROMPT = """{system_prompt}"""
    ''')

    # Add KB tool if knowledge bases exist
    if kb_list:
        kb_ids = [kb["knowledgeBaseId"] for kb in kb_list]
        agent_code += textwrap.dedent(f'''\

        # --- Knowledge Base tools (migrated from Bedrock Agent KB integration) ---
        from strands import tool

        KB_IDS = {json.dumps(kb_ids)}

        @tool
        def search_knowledge_base(query: str, kb_index: int = 0) -> str:
            """Search the knowledge base for relevant information.
            Args:
                query: The search query
                kb_index: Index of knowledge base to search (default: 0)
            """
            kb_client = boto3.client("bedrock-agent-runtime")
            kb_id = KB_IDS[min(kb_index, len(KB_IDS) - 1)]
            resp = kb_client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={{"text": query}},
                retrievalConfiguration={{"vectorSearchConfiguration": {{"numberOfResults": 5}}}}
            )
            results = []
            for r in resp.get("retrievalResults", []):
                results.append(r.get("content", {{}}).get("text", ""))
            return "\\n---\\n".join(results) if results else "No results found."
    ''')

    agent_code += textwrap.dedent(f'''\

        def create_agent():
            model = BedrockModel(model_id=MODEL_ID)
            mcp = MCPClient(gateway_url=GATEWAY_URL)
            gateway_tools = mcp.list_tools()
            all_tools = list(gateway_tools)
    ''')

    if kb_list:
        agent_code += '        all_tools.append(search_knowledge_base)\n'

    agent_code += textwrap.dedent('''\
            return Agent(model=model, tools=all_tools, system_prompt=SYSTEM_PROMPT)

        # --- AgentCore Runtime entrypoint ---
        try:
            from bedrock_agentcore.runtime import BedrockAgentCoreApp
            app = BedrockAgentCoreApp()

            @app.entrypoint
            def handle(request):
                agent = create_agent()
                return agent(request.input_text)
        except ImportError:
            pass  # Running locally without Runtime

        if __name__ == "__main__":
            agent = create_agent()
            while True:
                user_input = input("\\nYou: ")
                if user_input.lower() in ("quit", "exit"):
                    break
                response = agent(user_input)
                print(f"Agent: {response}")
    ''')

    with open(os.path.join(output_dir, "agent.py"), "w") as f:
        f.write(agent_code)

    # --- requirements.txt ---
    with open(os.path.join(output_dir, "requirements.txt"), "w") as f:
        f.write("strands-agents>=0.1.0\nstrands-agents-tools-mcp>=0.1.0\nboto3>=1.35.0\nbedrock-agentcore-runtime>=0.1.0\n")

    # --- Dockerfile ---
    dockerfile = textwrap.dedent('''\
        FROM public.ecr.aws/lambda/python:3.12
        COPY requirements.txt .
        RUN pip install -r requirements.txt
        COPY agent.py .
        EXPOSE 8080
        CMD ["python", "agent.py"]
    ''')
    with open(os.path.join(output_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile)

    print(f"✅ Agent code generated in ./{output_dir}/")
    return output_dir


# ---------------------------------------------------------------------------
# 4. Generate Lambda adapter wrapper
# ---------------------------------------------------------------------------

def generate_lambda_adapter(action_groups, output_dir="lambda_adapters"):
    """Generate adapter Lambdas that translate AgentCore Gateway format → existing Lambda logic."""
    os.makedirs(output_dir, exist_ok=True)

    adapter_code = textwrap.dedent('''\
        """
        Lambda adapter: translates AgentCore Gateway flat input format
        to your existing Bedrock Agent action group Lambda logic.

        Deploy this as a Lambda layer or wrap your existing handlers.
        """
        import json

        def adapt_gateway_to_bedrock_format(event, context):
            """Convert AgentCore Gateway event → Bedrock Agent action group event format."""
            custom = {}
            if hasattr(context, 'client_context') and context.client_context:
                custom = getattr(context.client_context, 'custom', {}) or {}

            tool_name_raw = custom.get('bedrockAgentCoreToolName', '')
            delimiter = '___'
            if delimiter in tool_name_raw:
                tool_name = tool_name_raw[tool_name_raw.index(delimiter) + len(delimiter):]
            else:
                tool_name = tool_name_raw

            # Reconstruct Bedrock Agent-style parameters array
            parameters = [
                {"name": k, "type": type(v).__name__, "value": str(v)}
                for k, v in event.items()
            ]

            return {
                "messageVersion": "1.0",
                "agent": {"name": "migrated", "id": "migrated", "alias": "migrated", "version": "1"},
                "inputText": "",
                "sessionId": custom.get('bedrockAgentCoreAwsRequestId', 'unknown'),
                "actionGroup": custom.get('bedrockAgentCoreTargetId', 'unknown'),
                "function": tool_name,
                "parameters": parameters,
                "sessionAttributes": {},
                "promptSessionAttributes": {}
            }


        def adapt_bedrock_response_to_gateway(bedrock_response):
            """Convert Bedrock Agent Lambda response → AgentCore Gateway response (plain JSON)."""
            try:
                body = bedrock_response.get("response", {})
                func_resp = body.get("functionResponse", {})
                resp_body = func_resp.get("responseBody", body.get("responseBody", {}))
                json_body = resp_body.get("application/json", resp_body.get("TEXT", {}))
                content = json_body.get("body", json.dumps(json_body))
                return content if isinstance(content, str) else json.dumps(content)
            except Exception:
                return json.dumps(bedrock_response)
    ''')

    with open(os.path.join(output_dir, "gateway_adapter.py"), "w") as f:
        f.write(adapter_code)

    print(f"✅ Lambda adapter generated in ./{output_dir}/gateway_adapter.py")
    print("   Option A: Update existing Lambdas to accept flat input (recommended)")
    print("   Option B: Use this adapter to wrap existing handlers without code changes")
    return output_dir


# ---------------------------------------------------------------------------
# 5. Generate migration report
# ---------------------------------------------------------------------------

def generate_report(agent, action_groups, kb_list, gateway, targets, output_file="migration_report.md"):
    """Generate a markdown migration report."""
    lines = [
        f"# Migration Report: {agent['agentName']} → AgentCore",
        f"\n**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Source Agent:** {agent['agentId']} ({agent['agentName']})",
        f"**Model:** {agent.get('foundationModel', 'N/A')}",
        f"\n## Gateway",
        f"- **ID:** {gateway['gatewayId']}",
        f"- **URL:** {gateway.get('gatewayUrl', 'N/A')}",
        f"\n## Migrated Action Groups → Gateway Targets\n",
        "| Action Group | Lambda ARN | Target ID | Tools |",
        "|---|---|---|---|"
    ]
    for t in targets:
        tool_names = ", ".join([tool["name"] for tool in t["tools"]])
        ag = next((a for a in action_groups if a["actionGroupName"] == t["action_group"]), {})
        lambda_arn = ag.get("actionGroupExecutor", {}).get("lambda", "N/A")
        lines.append(f"| {t['action_group']} | `{lambda_arn}` | `{t['target_id']}` | {tool_names} |")

    if kb_list:
        lines.append("\n## Knowledge Bases (wrapped as tools)\n")
        for kb in kb_list:
            lines.append(f"- `{kb['knowledgeBaseId']}` → `search_knowledge_base()` tool in agent code")

    skipped = [ag for ag in action_groups if ag.get("parentActionSignature") or ag.get("actionGroupState") != "ENABLED"]
    if skipped:
        lines.append("\n## Skipped Action Groups\n")
        for ag in skipped:
            reason = ag.get("parentActionSignature", "DISABLED")
            lines.append(f"- {ag['actionGroupName']} — {reason}")

    lines.extend([
        "\n## ⚠️ Manual Steps Required\n",
        "1. **Update Lambda input format** — existing Lambdas expect Bedrock Agent event format.",
        "   Either refactor to accept flat input OR use the generated `gateway_adapter.py` wrapper.",
        "2. **IAM permissions** — Gateway role needs `lambda:InvokeFunction` on all target Lambdas.",
        "3. **Test each tool** via Gateway MCP endpoint before deploying Runtime agent.",
        "4. **Guardrails** — If using Bedrock Guardrails, add AgentCore Policy (Cedar) for tool-level",
        "   controls and keep Bedrock Guardrails at the model inference layer for content safety.",
        "5. **Deploy to Runtime** — Build container from generated Dockerfile and deploy.",
    ])

    report = "\n".join(lines)
    with open(output_file, "w") as f:
        f.write(report)
    print(f"✅ Migration report: {output_file}")
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Migrate Bedrock Agent → AgentCore")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--agent-version", default="DRAFT")
    parser.add_argument("--gateway-role-arn", required=True)
    parser.add_argument("--runtime-role-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dry-run", action="store_true", help="Extract and generate code only, don't create AWS resources")
    parser.add_argument("--output-dir", default="migration_output")
    args = parser.parse_args()

    bedrock_agent = boto3.client("bedrock-agent", region_name=args.region)

    print("=" * 60)
    print("🚀 Bedrock Agent → AgentCore Migration")
    print("=" * 60)

    # Step 1: Extract
    print("\n📋 Step 1: Extracting Bedrock Agent configuration...")
    agent, action_groups, kb_list = extract_agent_config(bedrock_agent, args.agent_id, args.agent_version)

    # Save extracted config
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "extracted_config.json"), "w") as f:
        json.dump({
            "agent": {k: str(v) for k, v in agent.items()},
            "action_groups": [{k: str(v) for k, v in ag.items()} for ag in action_groups],
            "knowledge_bases": kb_list
        }, f, indent=2, default=str)

    if args.dry_run:
        print("\n🔍 DRY RUN — generating code only, no AWS resources created")
        gateway = {"gatewayId": "DRY-RUN", "gatewayUrl": "https://gateway-PLACEHOLDER.bedrock-agentcore.amazonaws.com"}
        targets = [{"action_group": ag["actionGroupName"], "target_id": "DRY-RUN",
                     "tools": extract_tools_from_action_group(ag)} for ag in action_groups
                    if ag.get("actionGroupState") == "ENABLED" and not ag.get("parentActionSignature")]
    else:
        # Step 2: Create Gateway + Targets
        agentcore = boto3.client("bedrock-agentcore-control", region_name=args.region)

        print("\n🌐 Step 2: Creating AgentCore Gateway...")
        gateway = create_gateway(agentcore, agent["agentName"], args.gateway_role_arn)

        print("\n🔧 Step 3: Migrating Action Groups → Gateway Targets...")
        targets = create_gateway_targets(agentcore, gateway["gatewayId"], action_groups)

    # Step 4: Generate agent code
    print("\n💻 Step 4: Generating AgentCore Runtime agent code...")
    generate_agent_code(agent, gateway["gatewayId"],
                        gateway.get("gatewayUrl", "PLACEHOLDER"),
                        kb_list, os.path.join(args.output_dir, "agent"))

    # Step 5: Generate Lambda adapter
    print("\n🔄 Step 5: Generating Lambda adapter...")
    generate_lambda_adapter(action_groups, os.path.join(args.output_dir, "lambda_adapters"))

    # Step 6: Report
    print("\n📊 Step 6: Generating migration report...")
    generate_report(agent, action_groups, kb_list, gateway, targets,
                    os.path.join(args.output_dir, "migration_report.md"))

    print("\n" + "=" * 60)
    print("✅ Migration complete!")
    print(f"   Output: ./{args.output_dir}/")
    print(f"   ├── extracted_config.json    (source agent config)")
    print(f"   ├── agent/agent.py           (Strands agent code)")
    print(f"   ├── agent/requirements.txt")
    print(f"   ├── agent/Dockerfile")
    print(f"   ├── lambda_adapters/         (input format adapter)")
    print(f"   └── migration_report.md      (full report)")
    print("=" * 60)


if __name__ == "__main__":
    main()

