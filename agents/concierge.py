"""Entry agent: greets, answers general questions, routes."""

from __future__ import annotations

from agents.base import Agent

CONCIERGE = Agent(
    name="concierge",
    handoff_description=(
        "Hand back to the general assistant when the caller no longer wants a "
        "reservation or a delivery order, or asks something unrelated."
    ),
    tool_names=("get_current_time",),
    handoffs=("booking", "delivery"),
    prompt_fragment=(
        "You are the first point of contact on this call. Answer general questions "
        "about the restaurant briefly.\n"
        "As soon as the caller's need is clear, hand off: a table reservation goes to "
        "the booking agent, a food delivery order goes to the delivery agent. Say one "
        "short natural line as you hand off, so the caller is not left in silence.\n"
        "Do not collect reservation or order details yourself — the specialist agent "
        "does that.\n"
        "If the caller has only greeted you or is unclear, ask one short question to "
        "find out what they need."
    ),
)
