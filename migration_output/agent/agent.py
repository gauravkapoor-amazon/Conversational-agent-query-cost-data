#!/usr/bin/env python3
"""AgentCore agent — CUR Query Agent with SigV4 gateway auth"""
import sys
import traceback
import httpx
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from bedrock_agentcore.runtime import BedrockAgentCoreApp

GATEWAY_URL = "https://conversationalqueryagent-gateway-yjs5fhepiw.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
MODEL_ID = "amazon.nova-lite-v1:0"
SYSTEM_PROMPT = """# CUR Query Agent Instructions

You are an AI agent designed to create and execute CUR (Cost and Usage Report) queries on the "conv_query_cur2"."data" table in Athena.

## Date Handling
- Call ClockandCalendarActionGroup tool for any date calculation first
- Use TIMESTAMP for date formatting: TIMESTAMP '2024-03-01 00:00:00.000'
- Full AWS service names: 'Amazon Elastic Compute Cloud - Compute' for EC2, 'Amazon Simple Storage Service' for S3, 'Amazon Relational Database Service' for RDS

## Query Construction
- Use exact column names from the list below
- Include bill_payer_account_id and line_item_usage_account_id in all queries
- Always use COALESCE: SUM(COALESCE(line_item_unblended_cost, 0))
- ROUND costs to 2 decimals: ROUND(SUM(COALESCE(line_item_unblended_cost, 0)), 2)
- GROUP BY must include all non-aggregated columns, repeat full expression not alias
- For service queries use product['product_name']
- Use unblended_cost by default

## Key Columns
- bill_payer_account_id, line_item_usage_account_id, line_item_usage_account_name
- line_item_unblended_cost, line_item_blended_cost, line_item_usage_amount
- line_item_usage_start_date, line_item_usage_end_date, line_item_usage_type
- line_item_product_code, line_item_operation, line_item_resource_id
- line_item_line_item_type, line_item_availability_zone
- product (nested: product['product_name'], product['servicecode'], product['region'], product['instance_type'])
- discount_total_discount, pricing_term, pricing_unit, billing_period
- reservation_effective_cost, savings_plan_savings_plan_effective_cost

## Sample Query
```sql
SELECT product['product_name'] AS service, ROUND(SUM(COALESCE(line_item_unblended_cost, 0)), 2) AS total_cost, bill_payer_account_id, line_item_usage_account_id
FROM "conv_query_cur2"."data"
WHERE line_item_usage_start_date >= TIMESTAMP '2024-03-01 00:00:00.000'
GROUP BY product['product_name'], bill_payer_account_id, line_item_usage_account_id
ORDER BY total_cost DESC LIMIT 5
```

## Response Format
Always include: Date Range, Cost ($XX.XX), SQL Query executed, Details (bullet list with emojis).
"""


class SigV4Auth(httpx.Auth):
    """SigV4 auth for httpx requests to AgentCore gateway."""
    def __init__(self):
        session = boto3.Session()
        self.credentials = session.get_credentials().get_frozen_credentials()
        self.signer = __import__('botocore.auth', fromlist=['SigV4Auth']).SigV4Auth(
            session.get_credentials(), 'bedrock-agentcore', 'us-east-1'
        )

    def auth_flow(self, request):
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
            data=request.content,
        )
        self.signer.add_auth(aws_request)
        request.headers.update(dict(aws_request.headers))
        yield request


app = BedrockAgentCoreApp()

@app.entrypoint(prompt_key="prompt")
def handle(payload):
    try:
        from strands import Agent
        from strands.models import BedrockModel
        from strands.tools.mcp import MCPClient
        from mcp.client.streamable_http import streamablehttp_client

        model = BedrockModel(model_id=MODEL_ID)
        auth = SigV4Auth()
        mcp = MCPClient(lambda: streamablehttp_client(GATEWAY_URL, auth=auth))
        mcp.start()
        tools = list(mcp.list_tools_sync())
        agent = Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)

        prompt = payload if isinstance(payload, str) else payload.get("prompt", str(payload))
        result = agent(prompt)
        return str(result)
    except Exception as e:
        return f"Error: {e}\n{traceback.format_exc()}"

if __name__ == "__main__":
    handle.run(port=8080)
