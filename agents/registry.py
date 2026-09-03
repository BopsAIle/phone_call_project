"""Agent lookup, and the tool registry that carries their handoff tools."""

from __future__ import annotations

import logging
from typing import Optional

from agents.base import Agent, HandoffTool
from agents.booking import BOOKING
from agents.concierge import CONCIERGE
from agents.delivery import DELIVERY
from tools.builtin import GetCurrentTime
from tools.registry import ToolRegistry
from tools.request_tools import booking_tools, delivery_tools
from tools.store_api import StoreApi, StubStoreApi

logger = logging.getLogger(__name__)

DEFAULT_AGENT = CONCIERGE.name

AGENTS: dict[str, Agent] = {agent.name: agent for agent in (CONCIERGE, BOOKING, DELIVERY)}


def resolve_agent(name: str) -> Agent:
    """Never fail a live call over an unknown agent name; fall back to concierge."""
    agent = AGENTS.get(name)
    if agent is None:
        logger.error("Unknown agent %r; falling back to %s", name, DEFAULT_AGENT)
        return AGENTS[DEFAULT_AGENT]
    return agent


def build_registry(api: Optional[StoreApi] = None) -> ToolRegistry:
    """Built-in tools, one handoff tool per agent, and the request workflow.

    Falls back to the in-memory stub so a bridge with no STORE_API_URL still
    runs the whole conversation — it just files nowhere.
    """
    api = api if api is not None else StubStoreApi()
    registry = ToolRegistry([GetCurrentTime()])
    for agent in AGENTS.values():
        registry.add(HandoffTool(agent))
    for tool in (*booking_tools(api), *delivery_tools(api)):
        registry.add(tool)
    return registry
