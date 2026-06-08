# MCP Multi-Agent Server

A **multi-domain multi-agent system** served over **MCP (Model Context Protocol)** with **FastMCP**. A set of specialized domain agents (email, CRM, calendar, customer support, helpdesk, reporting) are exposed as MCP tools and coordinated to automate business workflows, with a bilingual **Streamlit dashboard** for observability.

> Part of the **SunnyLab** build series. Sanitized public showcase — credentials and infrastructure identifiers removed; configure your own `.env`.

## What it demonstrates
- **Multi-agent architecture over MCP / FastMCP** — domain agents as composable, policy-routed tools
- **Enterprise integrations** — Gmail, Salesforce, and other services behind a service layer
- **Streamlit dashboard** (Korean / English) for runs and observability
- **Cloud-native delivery** — Docker, docker-compose, Cloud Build, GitHub Actions (project/VM values are placeholders)

## Architecture
```
MCP client (Claude Desktop / Cursor / custom)
        │  MCP
        ▼
FastMCP server ── routes ──► domain agents
   ├─ email      ├─ crm        ├─ calendar
   ├─ cs         ├─ helpdesk   └─ report
        │
        ▼
 service layer (Gmail / Salesforce / …)   →   Streamlit dashboard (KR/EN)
```
See [`mcp_server/`](mcp_server/) for agents, tools, and services.

## Tech stack
Python · MCP / FastMCP · Salesforce & Gmail integrations · Streamlit · Docker / docker-compose · Google Cloud Build · GitHub Actions

## Project structure
```
mcp_server/      # agents, tools, services (MCP/FastMCP)
dashboard.py     # Streamlit dashboard (KR)
dashboard_en.py  # Streamlit dashboard (EN)
tests/           # unit tests
cloudbuild.yaml  # Cloud Build (placeholders)
docker-compose.yml · Dockerfile
.env.example     # required env vars (no real keys)
```

## Setup
```bash
cp .env.example .env      # fill in your own keys (OPENAI/Google/Salesforce …)
pip install -r requirements.txt
# run the MCP server (see mcp_server/) and the dashboard:
streamlit run dashboard.py
```

## Note
Public **portfolio showcase**. Credential files, tokens, and infra identifiers (GCP project, VM IP) were removed before publishing; CI/deploy files use placeholders and require your own configuration.

---
**SunnyLab** — building agentic AI in public · Medium [@sunnylabtv](https://medium.com/@sunnylabtv) · YouTube [@sunnylabtv](https://www.youtube.com/@sunnylabtv)
