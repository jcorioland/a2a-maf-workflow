from typing import Any

from agent_framework.observability import setup_observability
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

_telemetry_configured = False


async def enable_observability(*, ai_project_endpoint: str) -> None:
    """Configure OpenTelemetry export to AI Foundry / Application Insights."""

    global _telemetry_configured
    if _telemetry_configured:
        return

    async with AIProjectClient(
        endpoint=ai_project_endpoint,
        credential=AsyncDefaultAzureCredential(),
    ) as client:
        connection_string = await client.telemetry.get_application_insights_connection_string()

        if not connection_string:
            return
        
        # Enable Microsoft Agent Framework observability
        setup_observability(
            enable_sensitive_data=True,
            applicationinsights_connection_string=connection_string
        )

        _telemetry_configured = True


def instrument_fastapi(app: Any) -> None:
    """Instrument a FastAPI app for tracing (no-op if unavailable)."""

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        return
