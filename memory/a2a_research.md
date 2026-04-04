---
name: A2A Protocol Research
description: Google A2A protocol details — Agent Cards, skills, tasks, SDKs, and how they map to AI Playground
type: reference
---

## A2A Protocol (Agent2Agent)
- Open standard under Linux Foundation, contributed by Google (April 2025)
- 150+ supporting organizations (Atlassian, Salesforce, SAP, LangChain, etc.)
- Built on HTTP + SSE + JSON-RPC — plays well with FastAPI
- Current version: 0.3 (adds gRPC, security card signing)

## Agent Card (discovery document)
- Published at `/.well-known/agent.json`
- Fields: name, description, url, provider, version, capabilities, skills[], authentication
- Skills have: id, name, description, tags[], examples[]
- `extensions` field is the official extension mechanism — our `playground/persona` namespace goes here

## Task Lifecycle
- States: submitted → working → input-required → completed / failed / canceled
- Streaming via SSE (Server-Sent Events)
- Artifacts returned as task results (text, files, structured data)

## Python SDKs
- Official: `a2a-python` (github.com/a2aproject/a2a-python)
- Community: `python-a2a` by themanojdesai (has MCP integration)
- Google ADK has native A2A support

## Key URLs
- Spec: https://a2a-protocol.org/latest/specification/
- GitHub: https://github.com/a2aproject/A2A
- Python SDK: https://github.com/a2aproject/a2a-python
- Samples: https://github.com/a2aproject/a2a-samples
- Tutorials: https://a2a-protocol.org/latest/tutorials/python/1-introduction/
