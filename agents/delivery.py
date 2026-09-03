"""Food delivery agent.

Assumed symmetric with booking: the endpoint files an order *request* that staff
confirm by calling back. If delivery ever commits a real order, its write tool
needs `safe_to_retry = False` and the strict never-retry policy.
"""

from __future__ import annotations

from agents.base import Agent

DELIVERY = Agent(
    name="delivery",
    handoff_description=(
        "Hand off to the delivery agent when the caller wants food delivered or "
        "wants to place a takeaway order."
    ),
    tool_names=(
        "get_current_time",
        "set_delivery_details",
        "confirm_delivery_details",
        "submit_delivery_request",
    ),
    handoffs=("concierge", "booking"),
    prompt_fragment=(
        "You are taking a food delivery REQUEST.\n"
        "You cannot see the kitchen queue or the delivery area, and you must never "
        "guess whether an address is deliverable or how long it will take. If asked, "
        "say you cannot check from here and offer to pass the request on.\n"
        "Collect, one or two at a time so it stays conversational: the delivery "
        "address, what the caller would like to order, the caller's name, and a phone "
        "number to reach them on.\n"
        "The phone number is essential — without it nobody can call the caller back. "
        "Read it back digit by digit and have the caller confirm it.\n"
        "Record each detail with set_delivery_details the moment you hear it; you do "
        "not need them all at once.\n"
        "When nothing is missing, read the whole order back and ask the caller to "
        "confirm it is correct. Only once they say yes, call confirm_delivery_details "
        "and then submit_delivery_request. If the caller changes anything afterwards, "
        "read it back and confirm again before submitting.\n"
        "NEVER say the order is placed, accepted, or confirmed. It is not. What you "
        "promise is a call back: a member of staff will ring the caller shortly to "
        "confirm the order and the delivery time. Say that plainly before the call ends."
    ),
)
