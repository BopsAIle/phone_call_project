"""Collect details, confirm them, file the request.

The write is guarded by `require_confirmed_details` in `tools/base.py`, not by
the prompt. An LLM alone does not authorise a side effect.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import ValidationError

from tools.base import Tool, ToolContext, ToolResult
from tools.slots import BookingSlots, DeliverySlots, RequestDraft, date_problem
from tools.store_api import StoreApi, StoreApiUncertain, StoreApiValidationError

logger = logging.getLogger(__name__)

CALLBACK_NOTE = (
    "Request filed. Tell the caller a member of staff will call them back shortly "
    "to confirm. Do NOT say it is booked, reserved, or confirmed."
)
UNCERTAIN_NOTE = (
    "This may or may not have reached the restaurant. Do NOT tell the caller it "
    "went through, and do NOT tell them it failed. Ask them to call the restaurant "
    "directly to be sure."
)

BOOKING_FIELDS = {
    "date": {"type": "string", "description": "Reservation date as YYYY-MM-DD, resolved to the restaurant's timezone."},
    "time": {"type": "string", "description": "Reservation time as 24-hour HH:MM."},
    "party_size": {"type": "integer", "description": "How many people are coming."},
    "name": {"type": "string", "description": "Name the reservation is under."},
    "phone": {"type": "string", "description": "Phone number for the staff call-back. Read it back digit by digit first."},
}
DELIVERY_FIELDS = {
    "address": {"type": "string", "description": "Full delivery address."},
    "items": {"type": "string", "description": "What the caller wants to order, in their own words."},
    "name": {"type": "string", "description": "Name for the order."},
    "phone": {"type": "string", "description": "Phone number for the staff call-back. Read it back digit by digit first."},
}


def _readable(exc: ValidationError) -> list[str]:
    """Validation errors phrased so the model can ask the caller for a fix."""
    out: list[str] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error.get("loc", ())) or "value"
        message = error.get("msg", "is invalid")
        out.append(f"{field}: {message.removeprefix('Value error, ')}")
    return out


class SetDetails(Tool):
    """Merge what the caller just said into the draft.

    Never touches the confirmation fingerprint: because confirmation is recorded
    against the slot values, changing a field invalidates it automatically.
    """

    slow = False
    safe_to_retry = True

    def __init__(self, name: str, draft_attr: str, fields: dict[str, Any], noun: str) -> None:
        self.name = name
        self.draft_attr = draft_attr
        self.description = (
            f"Record or update {noun} details as the caller gives them. "
            "Call this as soon as you learn a value; you do not need them all at once."
        )
        self.parameters = {"type": "object", "properties": dict(fields)}

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        draft: RequestDraft = getattr(ctx.session, self.draft_attr)
        try:
            updated = draft.apply(args)
        except ValidationError as exc:
            return ToolResult.failure("invalid_details", problems=_readable(exc))
        chosen_date = getattr(updated, "date", None)
        if chosen_date:
            problem = date_problem(chosen_date, getattr(ctx.session, "timezone", "UTC"))
            if problem:
                return ToolResult.failure("invalid_details", problems=[problem])
        setattr(ctx.session, self.draft_attr, updated)
        return ToolResult(
            ok=True,
            data={
                "recorded": updated.model_dump(exclude_none=True),
                "still_missing": updated.missing(),
                "confirmed": updated.fingerprint() == ctx.session.details_fingerprint,
            },
        )


class ConfirmDetails(Tool):
    """Record that the caller verified the read-back."""

    slow = False
    safe_to_retry = True

    def __init__(self, name: str, draft_attr: str, noun: str) -> None:
        self.name = name
        self.draft_attr = draft_attr
        self.description = (
            f"Call this ONLY after you have read the full {noun} back to the caller "
            "and they have said it is correct. If they change anything afterwards, "
            "read it back and confirm again."
        )
        self.parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        draft: RequestDraft = getattr(ctx.session, self.draft_attr)
        missing = draft.missing()
        if missing:
            return ToolResult.failure("incomplete", still_missing=missing)
        ctx.session.details_fingerprint = draft.fingerprint()
        return ToolResult(ok=True, data={"confirmed": True, "details": draft.to_request()})


class SubmitRequest(Tool):
    """File the request with the restaurant. The only tool here with a side effect."""

    slow = True
    safe_to_retry = False  # HttpStoreApi owns its own single retry
    requires_confirmation = True

    def __init__(self, name: str, draft_attr: str, kind: str, api: StoreApi, noun: str) -> None:
        self.name = name
        self.draft_attr = draft_attr
        self.kind = kind
        self.api = api
        self.description = (
            f"Send the confirmed {noun} to the restaurant so staff can call the caller "
            "back. This does NOT reserve anything. Only call it after "
            f"confirm_{kind}_details has succeeded."
        )
        self.parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        draft: RequestDraft = getattr(ctx.session, self.draft_attr)
        fingerprint = draft.fingerprint()
        payload = draft.to_request()
        key = f"{ctx.session.call_id or 'nocall'}:{fingerprint}"
        # Shielded: if the caller hangs up now, the request they just confirmed
        # still reaches the restaurant. Dropping it would strand them.
        dispatched = asyncio.ensure_future(
            self.api.submit_request(
                self.kind, payload, idempotency_key=key, call_id=ctx.session.call_id
            )
        )
        if ctx.register_write is not None:
            ctx.register_write(dispatched)
        try:
            response = await asyncio.shield(dispatched)
        except asyncio.CancelledError:
            logger.warning(
                "Call ended mid-write; letting the %s request finish %s", self.kind, ctx.session.tag
            )
            raise
        except StoreApiValidationError as exc:
            logger.error("Store API rejected the %s request %s (%s)", self.kind, ctx.session.tag, exc)
            return ToolResult.failure("rejected", problems=[str(exc)])
        except StoreApiUncertain as exc:
            logger.error("Store API outcome unknown for %s %s (%s)", self.kind, ctx.session.tag, exc)
            return ToolResult.failure("uncertain", guidance=UNCERTAIN_NOTE)

        ctx.session.consumed_fingerprints.add(fingerprint)
        logger.info("Filed %s request %s key=%s", self.kind, ctx.session.tag, key)
        return ToolResult(
            ok=True,
            data={"filed": True, "reference": response.get("request_id"), "next": CALLBACK_NOTE},
        )


def booking_tools(api: StoreApi) -> list[Tool]:
    return [
        SetDetails("set_booking_details", "booking", BOOKING_FIELDS, "reservation"),
        ConfirmDetails("confirm_booking_details", "booking", "reservation"),
        SubmitRequest("submit_booking_request", "booking", "booking", api, "reservation request"),
    ]


def delivery_tools(api: StoreApi) -> list[Tool]:
    return [
        SetDetails("set_delivery_details", "delivery", DELIVERY_FIELDS, "delivery order"),
        ConfirmDetails("confirm_delivery_details", "delivery", "delivery order"),
        SubmitRequest("submit_delivery_request", "delivery", "delivery", api, "delivery request"),
    ]


__all__ = [
    "BookingSlots",
    "ConfirmDetails",
    "DeliverySlots",
    "SetDetails",
    "SubmitRequest",
    "booking_tools",
    "delivery_tools",
]
