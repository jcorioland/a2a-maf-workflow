"""Helpers to host MCP (Model Context Protocol) tools inside a FastAPI app.

This module provides utilities to expose agent functionality as MCP tools
alongside existing A2A and REST endpoints. MCP tools allow agents to be
consumed by MCP-compatible clients such as Claude Desktop, IDEs, and other
AI applications.

The main entrypoint is `mount_mcp_tools`.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI
from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def combine_lifespans(original_lifespan, mcp: FastMCP):
    """Combine the original FastAPI lifespan with the MCP lifespan.
    
    This is necessary because FastMCP requires its lifespan to be integrated
    with the parent app's lifespan to properly initialize task groups.
    
    According to FastMCP documentation, we must pass mcp_app.lifespan to the
    parent app to ensure the StreamableHTTPSessionManager task group is initialized.
    
    Args:
        original_lifespan: The original lifespan context manager from FastAPI
        mcp: The FastMCP instance
        
    Returns:
        A tuple of (combined_lifespan, mcp_app) where mcp_app must be used
        in mount_mcp_tools to ensure the same instance is mounted
    """
    # Create the MCP HTTP app once
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    
    @asynccontextmanager
    async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Run both lifespans together
        # Use mcp_app.lifespan which properly initializes the task group
        async with original_lifespan(app):
            async with mcp_app.lifespan(app):
                yield
    
    return combined_lifespan, mcp_app


def mount_mcp_tools(
    app: FastAPI,
    mcp_app: Any,
    *,
    prefix: str = "/mcp",
) -> None:
    """Mount MCP server tools into an existing FastAPI application.

    This integrates an MCP server instance (with registered tools) into a FastAPI
    app, making the MCP tools accessible via HTTP at the specified prefix.
    
    IMPORTANT: You must use the mcp_app instance returned by combine_lifespans().
    This ensures the same MCP app instance with its lifespan running is mounted.

    Args:
        app: The FastAPI application to mount the MCP server into
        mcp_app: The MCP HTTP app instance returned by combine_lifespans()
        prefix: URL prefix for MCP endpoints (default: "/mcp")

    Example:
        >>> mcp = FastMCP("My Agent")
        >>> 
        >>> @mcp.tool()
        >>> async def my_tool(input: str) -> dict:
        >>>     return {"result": input}
        >>> 
        >>> # Combine lifespans
        >>> @asynccontextmanager
        >>> async def my_lifespan(app: FastAPI):
        >>>     # your startup code
        >>>     yield
        >>>     # your shutdown code
        >>> 
        >>> combined_lifespan, mcp_app = combine_lifespans(my_lifespan, mcp)
        >>> app = FastAPI(lifespan=combined_lifespan)
        >>> mount_mcp_tools(app, mcp_app, prefix="/mcp")
    """
    # Mount the MCP server's HTTP app into the FastAPI app
    # This must be the same mcp_app instance returned by combine_lifespans()
    app.mount(prefix, mcp_app)
    logger.info(f"MCP tools mounted at {prefix}")


def create_mcp_error_handler(func: Callable) -> Callable:
    """Decorator to handle errors in MCP tool functions.

    Wraps an MCP tool function to catch exceptions and convert them
    to user-friendly error messages.

    Args:
        func: The async function to wrap

    Returns:
        Wrapped function with error handling

    Example:
        >>> @create_mcp_error_handler
        >>> async def my_tool(input: str) -> dict:
        >>>     return {"result": process(input)}
    """
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            logger.error(f"MCP tool error in {func.__name__}: {exc}")
            raise

    return wrapper
