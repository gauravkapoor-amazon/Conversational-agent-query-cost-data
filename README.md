# SWIM Agentic Project — Bedrock Agent to AgentCore Migration

End-to-end notebook for migrating an existing Amazon Bedrock Agent to Amazon Bedrock AgentCore. Covers agent preparation, invocation testing, and automated migration with Gateway + Runtime code generation.

## What's in the Notebook

### 1. Setup & Dependencies
Installs the required packages: `strands-agents`, `bedrock-agentcore`, `bedrock-agentcore-starter-toolkit`, `agentcore`, and `boto3`.

### 2. Prepare Bedrock Agent
Uses `BedrockAgentManager` to check agent status and prepare (build) a DRAFT version of the existing Bedrock Agent (`ConversationalQueryAgent` — a CUR billing query agent).

### 3. Invoke & Test Bedrock Agent
`BedrockAgentInvoker` demonstrates three invocation patterns against the source agent:
- Single prompt (top 5 services by cost)
- Conversational flow (same session for follow-up questions)
- Streaming response (real-time chunked output)

Also includes an `interactive_chat()` function for ad-hoc testing.

### 4. Migration: Bedrock Agent → AgentCore

#### 4a. Initial Migration Attempt (`BedrockToAgentCoreMigrator`)
A class-based migrator that:
1. Extracts agent details and action groups from Bedrock
2. Creates an AgentCore Gateway with IAM auth
3. Migrates action groups as Gateway targets (Lambda-backed)
4. Generates Strands SDK agent code
5. Creates a deployment package (zip with Dockerfile)
6. Sets up IAM roles
7. Deploys to AgentCore Runtime

> Note: This initial attempt hit a `ParamValidationError` due to API parameter mismatches — resolved in the refined script below.

#### 4b. Refined Migration Script (`migrate_bedrock_to_agentcore.py`)
A production-ready CLI tool that performs the full migration:

```bash
python migrate_bedrock_to_agentcore.py \
    --agent-id AGENT_ID \
    --agent-version DRAFT \
    --gateway-role-arn arn:aws:iam::ACCOUNT:role/GatewayRole \
    --runtime-role-arn arn:aws:iam::ACCOUNT:role/RuntimeRole \
    --region us-east-1 \
    [--dry-run]
```

Features:
- Extracts agent config, action groups, and knowledge bases
- Creates AgentCore Gateway (MCP protocol, IAM auth)
- Converts action group schemas (function schema + OpenAPI) to Gateway tool definitions
- Generates a deployable Strands agent with MCP Gateway tools + KB search tools
- Produces a Lambda adapter for translating Gateway input format to Bedrock Agent event format
- Outputs a markdown migration report with manual steps checklist
- Supports `--dry-run` for code generation without creating AWS resources

### 5. IAM Role Setup Scripts
- `create_gateway_role.py` — Creates `AgentCoreGatewayExecutionRole` with permissions for gateway invocation, Lambda invoke, CloudWatch, X-Ray, and Secrets Manager
- `create_runtime_role.py` — Creates `AgentCoreRuntimeExecutionRole` with permissions for Bedrock model invocation, knowledge base access, gateway access, memory sessions, and logging

## Output Structure

After running the migration:

```
migration_output/
├── extracted_config.json        # Source agent configuration
├── agent/
│   ├── agent.py                 # Strands SDK agent (AgentCore Runtime)
│   ├── requirements.txt
│   └── Dockerfile
├── lambda_adapters/
│   └── gateway_adapter.py       # Input format translator
└── migration_report.md          # Full migration report
```

## Prerequisites

- Python 3.12+
- AWS credentials with access to Bedrock, AgentCore, Lambda, and IAM
- An existing Bedrock Agent to migrate

## Key Technologies

- [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-core.html) — Runtime + Gateway
- [Strands Agents SDK](https://github.com/strands-agents/strands-agents) — Agent framework
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) — Tool communication protocol
- Amazon Athena — CUR query execution (source agent use case)
