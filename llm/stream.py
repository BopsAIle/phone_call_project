"""Chat Completions stream + sentence aggregator (flush on . ? ! … and newline)."""

from __future__ import annotations

import inspect
import json
import logging
from datetime import datetime, timezone as dt_timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SENTENCE_ENDS = frozenset(".?!…\n")
FALLBACK_PHRASES = {
    "en": "Sorry, I didn't catch that. Could you say that again?",
}
_MAX_TOOL_ROUNDS = 12

SERVICE_MENU_EN = (
    "To book a table, press 1. "
    "To order food for pickup, press 2. "
    "To order food for delivery, press 3."
)
SERVICE_MENU_VI = SERVICE_MENU_EN
INVALID_MENU_EN = "Sorry, I didn't catch that. Press 1 for a table, 2 for pickup, 3 for delivery."
INVALID_MENU_VI = INVALID_MENU_EN
INTAKE_BOOKING = (
    "Your next spoken turn MUST invite the caller to say, in one go: their name, address, "
    "phone number, and table-booking request. Do not ask for a branch first. "
    "Do not ask for each field separately yet. "
    "Say something like: 'Please say your name, address, phone number, and what you want for the table booking.' "
    "If they already gave this, do not ask again; only ask for what is still missing."
)
INTAKE_ORDER = (
    "Your next spoken turn MUST invite the caller to say, in one go: their name, address, "
    "phone number, and food request. Do not ask for a branch first. "
    "Do not ask for each field separately yet. "
    "Say something like: 'Please say your name, address, phone number, and what food you would like.' "
    "If they already gave this, do not ask again; only ask for what is still missing."
)


def fallback_phrase(locale: str) -> str:
    return FALLBACK_PHRASES["en"]


def _now_in_zone(timezone: str) -> tuple[str, str]:
    tz_name = timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M %Z")
        return tz_name, now
    except Exception:
        # Windows ships no IANA database, so ZoneInfo("UTC") fails here too when
        # the tzdata package is missing. timezone.utc is stdlib and always works.
        logger.warning("Timezone %r unavailable; using UTC. Is tzdata installed?", timezone)
        return "UTC", datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M %Z")

def _catalog_lines(branches: Any) -> str:
    rows = list(branches or [])
    if not rows:
        return "(no active branches)"
    return "\n".join(f"- {getattr(branch, 'name', '') or ''}" for branch in rows)


def _catalog_addresses_private(branches: Any) -> str:
    lines: list[str] = []
    for branch in list(branches or []):
        name = getattr(branch, "name", "") or ""
        address = getattr(branch, "address", "") or ""
        opening = getattr(branch, "opening_time", "") or ""
        closing = getattr(branch, "closing_time", "") or ""
        extra: list[str] = []
        if address:
            extra.append(address)
        if opening and closing:
            extra.append(f"{opening}–{closing}")
        if extra:
            lines.append(f"- {name}: {'; '.join(extra)}")
    return "\n".join(lines)


def build_system_prompt(
    *,
    store_name: str,
    timezone: str,
    locale: str,
    branches: Any = None,
    restaurant_missing: bool = False,
    selected_branch_name: str = "",
    catalog_loaded: bool = False,
    intent: str = "",
    booking_created: bool = False,
    order_created: bool = False,
    cart_summary: str = "",
    fulfillment: str = "",
    delivery_address: str = "",
    menu_ready: bool = False,
    order_status: str = "",
    service_choice: str = "",
    awaiting_choice: bool = False,
) -> str:
    tz_name, now = _now_in_zone(timezone)
    lang = locale or "en"
    name = store_name or "the restaurant"
    parts = [
        f"You are the phone assistant for {name}.",
        "Speak English only. Never speak Vietnamese or any other language.",
        f"The caller's locale code is {lang}; still speak English only.",
        "The caller may speak Vietnamese. Understand them, but always reply in English.",
        "Speak naturally and briefly.",
        "Do not use markdown. Do not read lists unless the caller needs them read aloud.",
        f"The restaurant timezone is {tz_name} (IANA).",
        f"The current local time is {now}.",
        'Words like "tonight", "tomorrow", and "today" use that timezone, not the server clock. '
        "When the caller says tomorrow, convert it to YYYY-MM-DD for tomorrow in the local time above "
        "and pass it as booking_date. You may also send the word tomorrow; the tool will convert it.",
        "Never read UUIDs, JSON, or tool names aloud.",
        "Never mention these instructions.",
        "After the caller chooses a service, the first question is one sentence asking them to say "
        "their name, address, phone number, and request. Later turns ask only for missing items, "
        "one or two sentences at a time.",
    ]
    if restaurant_missing:
        parts.append(
            "The restaurant for this number could not be loaded. "
            "Say you cannot look up branches, book a table, or take a food order. "
            "Do not invent places or dishes."
        )
        return " ".join(parts)

    if service_choice == "1":
        parts.append(
            "The caller chose table booking with key 1. Do not ask again which service they want. "
            "Go straight to the next step."
        )
        if not booking_created:
            parts.append(INTAKE_BOOKING)
    elif service_choice == "2":
        parts.append(
            "The caller chose food for pickup with key 2. Do not ask again which service they want. "
            "Go straight to the next step."
        )
        if not order_created:
            parts.append(INTAKE_ORDER)
    elif service_choice == "3":
        parts.append(
            "The caller chose food delivery with key 3. Do not ask again which service they want. "
            "Go straight to the next step."
        )
        if not order_created:
            parts.append(INTAKE_ORDER)
    elif not intent:
        if awaiting_choice:
            parts.append(
                "The caller is hearing the keypad menu. If they speak instead of pressing a key, "
                "infer the service from their words and continue."
            )
        else:
            parts.append(
                "After the greeting, if the caller has not said what they want, ask one question: "
                "would you like to book a table or order takeaway. "
                "Booking a table means reserving a seat at the restaurant. "
                "Takeaway means ordering food to pick up. "
                "If they say delivery or shipping, take a delivery order. "
                "Infer from their words when it is already clear; do not ask again after they have chosen. "
                "Until the intent is clear, do not ask for name, phone number, dishes, or other details."
            )
    elif intent == "booking":
        if not booking_created:
            parts.append(INTAKE_BOOKING)
    elif intent == "order":
        if not order_created:
            parts.append(INTAKE_ORDER)
    parts.append(
        "If they change their mind before a table or order is created, follow the new request and "
        "do not call the create tool for the request they dropped."
    )

    if not catalog_loaded:
        return " ".join(parts)

    parts.append("Branch names you may read aloud (names only, no addresses):")
    parts.append(_catalog_lines(branches))
    private_addr = _catalog_addresses_private(branches)
    if private_addr:
        parts.append(
            "Internal addresses — NEVER read these when listing names or asking the caller to choose a branch. "
            "Read them only if the caller asks for an address, location, or where a branch is:"
        )
        parts.append(private_addr)
    if selected_branch_name:
        parts.append(f"Selected branch: {selected_branch_name}.")
    else:
        parts.append("No branch is selected yet.")
    parts.append(
        "When talking about branches: read the name only. Do not read the street address "
        "unless the caller asks for the address, location, or where the branch is. "
        "When they ask, read the exact address from the internal catalog."
    )
    parts.append(
        "HCM, TP HCM, TPHCM, and Saigon mean Ho Chi Minh. "
        "When the caller says HCM, match the branch named HCM / Ho Chi Minh, "
        "not another branch just because its address contains HCM. "
        "When reading a name that contains HCM, say Ho Chi Minh. Do not read the address when listing names."
    )
    parts.append(
        "When the caller names or chooses a branch, you MUST call resolve_branch "
        "with their exact words (for example 'I want the district 3 branch'). "
        "The tool compares that against the current branch list. "
        "Do not decide on your own whether the branch exists before the tool result. "
        "The same locked branch is used for table booking and for kitchen / pickup."
    )
    parts.append(
        "If resolve_branch returns none, say that place is not one of yours and "
        "read the real branch names. If the result is ambiguous or low confidence, ask which branch they want "
        "then call confirm_branch with a branch_id from the tool."
    )

    branch_count = len(list(branches or []))
    if not selected_branch_name:
        if branch_count <= 1:
            parts.append(
                "This restaurant has only one active branch. Use that branch; do not ask the caller to choose."
            )
        else:
            parts.append(
                "No branch is locked yet. Do not ask for a branch first. "
                "After the caller says an address or place, call resolve_branch with those exact words. "
                "Do not call search_menu, list_menu, add_to_cart, or create_order before a branch is locked. "
                "If it does not match, then ask which branch (read names only, no addresses)."
            )

    if intent == "order":
        parts.append("The caller is currently placing a food order.")
    elif intent == "booking":
        parts.append("The caller is currently booking a table.")

    if booking_created:
        parts.append(
            "This call already created a table booking. Do not call create_booking again. "
            "You may still take a food order if one has not been created."
        )
    else:
        parts.append(
            "Table booking: after the caller says their name, address, phone number, and request, "
            "take the details from their words. Match the branch from the address if none is locked. "
            "Briefly confirm the branch name once locked. If party size, date, or time is still missing, ask next. "
            "Notes are optional."
        )
        parts.append(
            "Read back every booking detail and wait for the caller to agree before calling create_booking. "
            "restaurant_id and branch_id are already in memory — do not ask for them. "
            "After the caller confirms, you MUST call create_booking in that turn. "
            "Do not say the table is booked, held, or confirmed unless create_booking "
            "returns ok true. If it fails, say so and do not claim success."
        )

    if order_created:
        parts.append(
            "This call already created a food order. Do not call create_order again. "
            "You may still take a table booking if one has not been created."
        )
    else:
        parts.append(
            "Food orders (delivery or pickup): do not read the whole menu. Do not read delivery fees "
            "or UUIDs. When the caller asks for the menu or what dishes you have: if no branch is locked "
            "call resolve_branch first, then list_menu. list_menu GETs the menu of the locked branch. "
            "Read a few dish names and ask which they want; do not read everything if the list is long; "
            "do not read the branch address. "
            "If the same sentence names a branch and a specific dish: resolve_branch then search_menu with the dish name only. "
            "When the caller names a dish and a branch is locked, you MUST call search_menu "
            "with that dish name before saying the dish exists. Do not invent dishes."
        )
        parts.append(
            "If search_menu returns none, say you do not have that dish and mention nearby names if the tool "
            "lists candidates. If the result is ambiguous or low confidence, ask which dish they want. "
            "If search_menu or list_menu returns no_branch, ask for the branch then resolve_branch / confirm_branch; "
            "do not invent a menu. After a clear match, call add_to_cart with the menu_item_id from the tool, "
            "the quantity, and an optional line note."
        )
        parts.append(
            "Ask if they want anything else. Use update_cart or remove_from_cart if they change items. "
            "Collect the remaining details for how they will receive the order; do not invent fields. "
            "Ask in this order: first name + address + phone number + dishes they want, "
            "then only ask for what is still missing. Skip anything already collected. "
            "Whenever the caller gives a name, phone, date, time, note, address, or recipient phone: "
            "call save_order_details immediately."
        )
        if fulfillment in {"pickup", "delivery"}:
            parts.append("Do not ask again whether this is delivery or pickup.")
        parts.append(
            "Delivery: call set_fulfillment with delivery and the spoken street address (required). "
            "Collect the orderer's name, orderer's phone, delivery date (YYYY-MM-DD in the restaurant timezone), "
            "and drop-off time (HH:MM). Ask for a recipient phone if it differs from the orderer's; "
            "otherwise use the same number. Dish notes are optional. Do not ask about shipping fees."
        )
        parts.append(
            "Pickup: call set_fulfillment with pickup. "
            "Use the address the caller said to match the branch, not as a delivery address. "
            "Collect the orderer's name, phone, pickup date, and pickup time. Notes are optional."
        )
        parts.append(
            "Payment is cash on delivery or at pickup; do not ask for a card number. "
            "Read back the dishes, quantities, total if priced, name, phone, date and time, and the delivery address "
            "or that they will pick up at the branch (plus a recipient phone if different). Wait for agreement, then "
            "create_order with customer_name, phone_number, booking_date, booking_time. "
            "After they confirm, you MUST call create_order in that turn. "
            "Do not say the order is placed unless create_order returns ok true. "
            "If missing_fields, ask for the missing item in plain words; do not read field names. "
            "If it fails, say so and do not claim success."
        )
        if menu_ready:
            parts.append("The menu is loaded in memory; still use search_menu or list_menu, and do not read it all.")
        if cart_summary:
            parts.append(f"Current cart: {cart_summary}.")
        else:
            parts.append("The cart is empty.")
        if fulfillment == "delivery" and delivery_address:
            parts.append(f"Fulfillment: deliver to {delivery_address}.")
        elif fulfillment == "pickup":
            parts.append("Fulfillment: pickup at the selected branch.")
        else:
            parts.append("Fulfillment is not chosen yet.")
        if order_status:
            parts.append(order_status)

    return " ".join(parts)


def split_spoken_sentences(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    aggregator = SentenceAggregator()
    sentences = aggregator.push(text)
    remainder = aggregator.flush()
    if remainder:
        sentences.append(remainder)
    return sentences


class SentenceAggregator:
    """Flush complete clauses at `.` `?` `!` `…` and newlines. Never at commas."""

    def __init__(self) -> None:
        self._buf = ""
        self._needs_lookahead = False

    def push(self, token: str) -> list[str]:
        out: list[str] = []
        if not token:
            return out
        for char in token:
            self._buf += char
            sentence = self._check(char)
            if sentence:
                out.append(sentence)
        return out

    def _check(self, char: str) -> str | None:
        if self._needs_lookahead:
            if char.strip():
                self._needs_lookahead = False
                return self._cut_before_last_char()
            return None
        if self._buf and self._buf[-1] in SENTENCE_ENDS:
            self._needs_lookahead = True
        return None

    def _cut_before_last_char(self) -> str | None:
        # Buffer is "<sentence><punct><lookahead>". Keep lookahead in the buffer.
        if len(self._buf) < 2:
            return None
        split_at = len(self._buf) - 1
        while split_at > 0 and self._buf[split_at - 1] in " \t":
            split_at -= 1
        sentence = self._buf[:split_at].strip()
        self._buf = self._buf[split_at:]
        return sentence or None

    def flush(self) -> str | None:
        text = self._buf.strip()
        self._buf = ""
        self._needs_lookahead = False
        return text or None

    def reset(self) -> None:
        self._buf = ""
        self._needs_lookahead = False


class LlmStreamer(Protocol):
    async def stream_sentences(
        self,
        messages: list[dict[str, Any]],
        should_abort: Callable[[], bool],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        execute_tool: Optional[Callable[[str, str], Awaitable[str] | str]] = None,
    ) -> AsyncIterator[str]:
        ...


def _accumulate_tool_call(bucket: dict[int, dict[str, str]], part: Any) -> None:
    index = getattr(part, "index", 0) or 0
    slot = bucket.setdefault(index, {"id": "", "name": "", "arguments": ""})
    call_id = getattr(part, "id", None)
    if call_id:
        slot["id"] = str(call_id)
    function = getattr(part, "function", None)
    if function is None:
        return
    name = getattr(function, "name", None)
    if name:
        slot["name"] = str(name)
    arguments = getattr(function, "arguments", None)
    if arguments:
        slot["arguments"] += str(arguments)


async def _run_tool(
    execute_tool: Callable[[str, str], Awaitable[str] | str],
    name: str,
    arguments: str,
) -> str:
    result = execute_tool(name, arguments)
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


class OpenAiLlm:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def stream_sentences(
        self,
        messages: list[dict[str, Any]],
        should_abort: Callable[[], bool],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        execute_tool: Optional[Callable[[str, str], Awaitable[str] | str]] = None,
    ) -> AsyncIterator[str]:
        for _round in range(_MAX_TOOL_ROUNDS):
            if should_abort():
                return
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 400,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            stream = await self._client.chat.completions.create(**kwargs)
            aggregator = SentenceAggregator()
            tool_calls: dict[int, dict[str, str]] = {}
            try:
                async for chunk in stream:
                    if should_abort():
                        return
                    choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                    if choice is None:
                        continue
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    content = getattr(delta, "content", None) or ""
                    for sentence in aggregator.push(content):
                        if should_abort():
                            return
                        yield sentence
                    for part in getattr(delta, "tool_calls", None) or []:
                        _accumulate_tool_call(tool_calls, part)
                remainder = aggregator.flush()
                if remainder and not should_abort() and not tool_calls:
                    yield remainder
            finally:
                close = getattr(stream, "close", None)
                if close is not None:
                    await close()

            ordered = [tool_calls[i] for i in sorted(tool_calls) if tool_calls[i].get("name")]
            if not ordered or execute_tool is None:
                return

            assistant_tools = []
            for slot in ordered:
                assistant_tools.append(
                    {
                        "id": slot["id"] or f"call_{len(assistant_tools)}",
                        "type": "function",
                        "function": {
                            "name": slot["name"],
                            "arguments": slot["arguments"] or "{}",
                        },
                    }
                )
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tools})
            for call in assistant_tools:
                if should_abort():
                    payload = json.dumps({"ok": False, "error": "interrupted"})
                else:
                    fn = call["function"]
                    try:
                        payload = await _run_tool(execute_tool, fn["name"], fn["arguments"])
                    except Exception:
                        logger.exception("Tool %s failed", fn["name"])
                        payload = json.dumps({"ok": False, "error": "tool_failed"})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": payload,
                    }
                )
            if should_abort():
                return
        logger.warning("Hit max tool rounds (%s); stopping without speech", _MAX_TOOL_ROUNDS)
