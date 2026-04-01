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
