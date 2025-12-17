# A2A Workflow using Microsoft Agent Framework

Python sandbox for building agents with **Microsoft Agent Framework**.

## Prereqs

- Python **3.12.3** (this repo targets `>=3.12.3,<3.13`) OR a Dev Container
- [`uv`](https://github.com/astral-sh/uv) installed (only needed if not using the Dev Container)

> Note: Agent Framework is currently published as a **pre-release** on PyPI.
> This repo expects you to sync with pre-releases enabled.

## Setup

### Option A: Dev Container (recommended)

Open the repo in VS Code and choose **“Dev Containers: Reopen in Container”**.

On first container creation, dependencies are automatically installed with:

```bash
uv sync --prerelease=allow
```

Notes:

- `uv.lock` remains the lockfile for reproducible installs.

### Option B: Local (no container)

Create a local virtual environment in `.venv`:

```bash
uv venv
```

Install/sync dependencies (including pre-releases):

```bash
uv sync --prerelease=allow
```

That will create/update:

- `.venv/` (virtual environment)
- `uv.lock` (resolved dependency lockfile)

## Run a quick sanity check

```bash
uv run --prerelease=allow python -c "import agent_framework; print('agent_framework import ok')"
```

## Common dev commands

Run tests:

```bash
uv run --prerelease=allow pytest
```

Run lints:

```bash
uv run --prerelease=allow ruff check .
```

## Run the agents locally

Both services require Azure AI Foundry project settings:

```bash
export AZURE_AI_PROJECT_ENDPOINT="https://<aiservices-id>.services.ai.azure.com/api/projects/<project-name>"
export AZURE_AI_MODEL_DEPLOYMENT_NAME="<your-model-deployment-name>"
```

Optional telemetry to Application Insights:

```bash
export APPLICATIONINSIGHTS_CONNECTION_STRING="<connection-string>"
```

Start the writer service (defaults to port 8000 unless you override):

Note: for A2A clients, make sure the agent card advertises the correct host/port by setting `A2A_PUBLIC_URL` (e.g. `http://localhost:8000`).

```bash
PYTHONPATH=src uv run --prerelease=allow uvicorn agents.writer.main:app --host 0.0.0.0 --port 8000
```

Invoke the writer:

```bash
curl -sS -X POST http://localhost:8000/invoke \
  -H 'content-type: application/json' \
  -d '{"topic":"Azure Container Apps"}'

### A2A endpoints (Agent-to-Agent protocol)

Each service also exposes A2A REST endpoints under `/a2a` (in addition to `/invoke`).

- Agent card: `GET /a2a/.well-known/agent-card.json`
- Send (non-streaming): `POST /a2a/v1/message:send`
- Send (streaming via SSE): `POST /a2a/v1/message:stream`

Writer example (streaming):

```bash
curl -N -sS -X POST http://localhost:8000/a2a/v1/message:stream \
  -H 'content-type: application/json' \
  -d '{
    "message": {
      "kind": "message",
      "role": "user",
      "parts": [{"kind": "text", "text": "Azure Container Apps", "metadata": {}}],
      "messageId": null,
      "contextId": "local"
    }
  }'
```

Start the reviewer service:

Note: for A2A clients, set `A2A_PUBLIC_URL` (e.g. `http://localhost:8001`) so the agent card contains the correct port.

```bash
PYTHONPATH=src uv run --prerelease=allow uvicorn agents.reviewer.main:app --host 0.0.0.0 --port 8001
```

Invoke the reviewer:

```bash
curl -sS -X POST http://localhost:8001/invoke \
  -H 'content-type: application/json' \
  -d '{"topic":"Azure Container Apps","draft":"<paste writer output here>"}'

Reviewer example (streaming):

The reviewer expects the message text to include both a topic and a draft. Supported formats:

- `Topic: ...` then `Draft: ...`
- First line is topic, remaining lines are draft

```bash
curl -N -sS -X POST http://localhost:8001/a2a/v1/message:stream \
  -H 'content-type: application/json' \
  -d '{
    "message": {
      "kind": "message",
      "role": "user",
      "parts": [{
        "kind": "text",
        "text": "Topic: Azure Container Apps\n\nDraft: <paste writer output here>",
        "metadata": {}
      }],
      "messageId": null,
      "contextId": "local"
    }
  }'
```

## Adding dependencies

Add a runtime dependency:

```bash
uv add <package>
```

Add a dev dependency:

```bash
uv add --group dev <package>
```
