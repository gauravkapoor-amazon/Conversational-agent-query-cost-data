# CUR Query Agent

An AI agent built on [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-core.html) that queries AWS Cost and Usage Reports (CUR) via natural language. It uses the Strands Agents framework with an MCP-based gateway tool and SigV4 authentication.

## How It Works

1. Receives a natural language prompt (e.g., "What were my top 5 services by cost last month?")
2. Connects to an AgentCore MCP gateway for CUR/Athena query execution
3. Uses Amazon Nova Lite to translate the prompt into SQL against the CUR Athena table
4. Returns formatted cost breakdowns with the SQL query used

## Prerequisites

- Python 3.12+
- AWS credentials configured with access to Bedrock and the AgentCore gateway
- Docker (optional, for containerized deployment)

## Quick Start

### Local

```bash
pip install -r requirements.txt
python agent.py
```

The agent starts on port `8080`.

### Docker

```bash
docker build -t cur-query-agent .
docker run -p 8080:8080 cur-query-agent
```

## Project Structure

| File | Description |
|---|---|
| `agent.py` | Main agent — handles prompts, SigV4 auth, MCP tool connection, and CUR query logic |
| `Dockerfile` | Container image definition |
| `requirements.txt` | Python dependencies |

## Key Dependencies

- `strands-agents` — Agent framework
- `bedrock-agentcore` — AgentCore runtime
- `boto3` — AWS SDK (SigV4 signing)
