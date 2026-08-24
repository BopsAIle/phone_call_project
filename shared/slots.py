from __future__ import annotations

from shared.models import BookingSlots, SlotDelta

REQUIRED_CORE = ("customer_name", "phone", "guest_count", "date", "time")
AVAILABILITY_KEYS = ("guest_count", "date", "time", "branch")

BRANCH_ALIASES = {
    "quan-1": "quan-1",
    "quan 1": "quan-1",
    "quận 1": "quan-1",
    "q1": "quan-1",
    "q.1": "quan-1",
    "dong khoi": "quan-1",
    "đồng khởi": "quan-1",
    "thao-dien": "thao-dien",
    "thao dien": "thao-dien",
    "thảo điền": "thao-dien",
    "thảo dien": "thao-dien",
    "q2": "thao-dien",
    "quận 2": "thao-dien",
    "quan 2": "thao-dien",
}

BRANCH_LABELS = {
    "quan-1": "Quận 1",
    "thao-dien": "Thảo Điền",
}


def normalize_branch(value: str | None) -> str | None:
    if not value:
        return None
    key = " ".join(value.strip().lower().replace("_", " ").split())
    if key in BRANCH_ALIASES:
        return BRANCH_ALIASES[key]
    for alias, code in BRANCH_ALIASES.items():
        if alias in key or key in alias:
            return code
    return key.replace(" ", "-")


def missing_fields(slots: BookingSlots, multi_branch: bool) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_CORE:
        if getattr(slots, field) in (None, ""):
            missing.append(field)
    if multi_branch and not slots.branch:
        # Name and phone first, then guests/date/time/branch like a receptionist.
        if "time" in missing:
            missing.insert(missing.index("time") + 1, "branch")
        elif "date" in missing:
            missing.insert(missing.index("date") + 1, "branch")
        else:
            missing.append("branch")
    return missing


def has_availability_keys(slots: BookingSlots, multi_branch: bool) -> bool:
    if slots.guest_count is None or slots.date is None or slots.time is None:
        return False
    if multi_branch and not slots.branch:
        return False
    return True


def touches_availability_keys(delta: SlotDelta) -> bool:
    return any(
        getattr(delta, key) is not None
        for key in ("guest_count", "date", "time", "branch")
    )


def apply_delta(slots: BookingSlots, delta: SlotDelta) -> BookingSlots:
    data = slots.model_dump()
    patch = delta.model_dump(exclude_none=True)
    if "branch" in patch:
        patch["branch"] = normalize_branch(patch["branch"])
    data.update(patch)
    data["source"] = slots.source
    return BookingSlots.model_validate(data)


def branch_label(code: str | None) -> str:
    if not code:
        return ""
    return BRANCH_LABELS.get(code, code)
