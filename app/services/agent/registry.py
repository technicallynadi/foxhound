"""Tool registry with @tool decorator.

Tools are auto-discovered from app/services/agent/tools/ modules.
Each tool declares metadata (permissions, side effects, cost, confirmation).
The registry collects them and provides definitions for the Claude API
and a dispatch method for execution.
"""

from __future__ import annotations

import functools
import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Type for tool handler functions
ToolHandler = Callable[[AsyncSession, str, dict], Coroutine[Any, Any, dict]]


@dataclass
class ToolSpec:
    """Metadata for a registered tool."""

    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    permissions: list[str] = field(default_factory=lambda: ["read"])
    side_effects: bool = False
    requires_confirmation: bool = False
    cost_estimate: str = "low"  # "free" | "low" | "medium" | "high"


# Global registry
_registry: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    input_schema: dict,
    permissions: list[str] | None = None,
    side_effects: bool = False,
    requires_confirmation: bool = False,
    cost_estimate: str = "low",
):
    """Decorator to register a function as an agent tool.

    Usage:
        @tool(
            name="search_jobs",
            description="Search for jobs matching a query...",
            input_schema={"type": "object", "properties": {...}},
            permissions=["read"],
        )
        async def search_jobs(db, user_id, params):
            ...
    """

    def decorator(func: ToolHandler) -> ToolHandler:
        spec = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=func,
            permissions=permissions or ["read"],
            side_effects=side_effects,
            requires_confirmation=requires_confirmation,
            cost_estimate=cost_estimate,
        )
        _registry[name] = spec

        @functools.wraps(func)
        async def wrapper(db: AsyncSession, user_id: str, params: dict) -> dict:
            return await func(db, user_id, params)

        return wrapper

    return decorator


def get_tool_definitions() -> list[dict]:
    """Get Claude API tool definitions for all registered tools."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
        }
        for spec in _registry.values()
    ]


def get_tool_spec(name: str) -> ToolSpec | None:
    """Get the full spec for a tool by name."""
    return _registry.get(name)


async def execute_tool(
    db: AsyncSession, user_id: str, tool_name: str, params: dict
) -> dict:
    """Execute a tool by name. Returns the tool result dict."""
    spec = _registry.get(tool_name)
    if not spec:
        return {"error": "unknown_tool", "message": f"Unknown tool: {tool_name}"}
    try:
        return await spec.handler(db, user_id, params)
    except Exception as e:
        logger.exception("Tool %s failed for user %s", tool_name, user_id)
        return {"error": "tool_error", "message": str(e)}


def discover_tools() -> None:
    """Import all tool modules to trigger @tool decorator registration."""
    import app.services.agent.tools as tools_pkg

    for importer, modname, ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname.startswith("_"):
            continue
        importlib.import_module(f"app.services.agent.tools.{modname}")

    logger.info("Discovered %d agent tools: %s", len(_registry), list(_registry.keys()))
