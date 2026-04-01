# Migration Report: ConversationalQueryAgent → AgentCore

**Date:** 2026-03-20 19:15:49
**Source Agent:** PMGQINV3MX (ConversationalQueryAgent)
**Model:** amazon.nova-lite-v1:0

## Gateway
- **ID:** conversationalqueryagent-gateway-yjs5fhepiw
- **URL:** https://conversationalqueryagent-gateway-yjs5fhepiw.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp

## Migrated Action Groups → Gateway Targets

| Action Group | Lambda ARN | Target ID | Tools |
|---|---|---|---|
| BuildandRunAthenaQueryActionGroup | `arn:aws:lambda:us-east-1:381491969808:function:BuildandRunAthenaQuery` | `BVLFN5M4RW` | executeAthenaQuery |
| ClockandCalendarActionGroup | `arn:aws:lambda:us-east-1:381491969808:function:ClockandCalendar` | `4RY3NSCHFX` | GetDateAndTime |

## ⚠️ Manual Steps Required

1. **Update Lambda input format** — existing Lambdas expect Bedrock Agent event format.
   Either refactor to accept flat input OR use the generated `gateway_adapter.py` wrapper.
2. **IAM permissions** — Gateway role needs `lambda:InvokeFunction` on all target Lambdas.
3. **Test each tool** via Gateway MCP endpoint before deploying Runtime agent.
4. **Guardrails** — If using Bedrock Guardrails, add AgentCore Policy (Cedar) for tool-level
   controls and keep Bedrock Guardrails at the model inference layer for content safety.
5. **Deploy to Runtime** — Build container from generated Dockerfile and deploy.