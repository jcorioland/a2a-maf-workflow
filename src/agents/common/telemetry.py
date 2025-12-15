import os
from typing import Any


_telemetry_configured = False


def setup_telemetry(*, service_name: str) -> None:
    """Configure OpenTelemetry export to Application Insights (Azure Monitor).

    Controlled via `APPLICATIONINSIGHTS_CONNECTION_STRING`.
    Safe to call multiple times.
    """

    global _telemetry_configured
    if _telemetry_configured:
        return

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        return

    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})

    configure_azure_monitor(
        connection_string=connection_string,
        resource=resource,
    )

    # Optional: enable framework/client instrumentations.
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass

    _telemetry_configured = True


def instrument_fastapi(app: Any) -> None:
    """Instrument a FastAPI app for tracing (no-op if unavailable)."""

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        return
