from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apps.voice_agent.extractor import fold_vi
from shared.config import REPO_ROOT
from shared.models import AvailabilityResponse, BookingSlots, SlotDelta
from shared.slots import branch_label

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_VI_WEEKDAYS = (
    "Thứ Hai",
    "Thứ Ba",
    "Thứ Tư",
    "Thứ Năm",
    "Thứ Sáu",
    "Thứ Bảy",
    "Chủ Nhật",
)


def call_context_note(now: datetime | None = None) -> str:
    """Real-time date anchor so the LLM can resolve relative dates/times.

    Without this the model has no idea what "ngày mai" or "thứ 7" mean and
    either leaves the date empty or guesses a past date the backend rejects.
    """
    now = now or datetime.now(VN_TZ)
    today = now.date()
    weekday = _VI_WEEKDAYS[today.weekday()]
    tomorrow = today + timedelta(days=1)
    return (
        "Bối cảnh thời gian thực của cuộc gọi (múi giờ Việt Nam):\n"
        f"- Hôm nay là {weekday}, ngày {today:%d/%m/%Y} (ISO {today.isoformat()}).\n"
        f"- Bây giờ khoảng {now:%H:%M}.\n"
        f"- 'Ngày mai' là {tomorrow.isoformat()}.\n"
        "Khi khách nói ngày/giờ tương đối (hôm nay, ngày mai, ngày kia, tối nay, "
        "thứ 2..thứ 7, chủ nhật, cuối tuần, mùng mấy...), hãy tự quy đổi sang ngày "
        "dương lịch tuyệt đối theo hôm nay rồi mới gọi update_slots. "
        "Trường date luôn ở dạng YYYY-MM-DD, trường time ở dạng HH:MM 24 giờ "
        "(ví dụ: 7 giờ tối = 19:00, 8 giờ rưỡi tối = 20:30). "
        "Không đặt ngày vào quá khứ; nếu khách nói một thứ trong tuần đã qua, hiểu là tuần kế tiếp."
    )


def load_system_prompt() -> str:
    path = REPO_ROOT / "prompts" / "system_vi.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return (
        "You are a Vietnamese restaurant booking phone agent. "
        "Ask one missing field per turn. Never invent table availability."
    )


TRANSFER_LINE = (
    "Dạ em xin phép chuyển máy cho nhân viên lễ tân ạ, "
    "anh chị giữ máy giúp em một chút."
)
REPEAT_LINE = "Dạ xin lỗi, em nghe chưa rõ ạ. Anh chị nói lại giúp em được không ạ?"


def question_for(
    field: str,
    *,
    slots: BookingSlots | None = None,
    delta: SlotDelta | None = None,
    last_user_text: str | None = None,
) -> str:
    """Ask the next booking field in a way that fits what we already know."""
    slots = slots or BookingSlots()
    if field == "customer_name":
        return _ask_name(slots)
    if field == "phone":
        return _ask_phone(slots)
    if field == "guest_count":
        return _ask_guest_count(slots)
    if field == "date":
        return _ask_date(slots)
    if field == "time":
        return _ask_time(slots, last_user_text=last_user_text)
    if field == "branch":
        return _ask_branch(slots)
    return "Anh chị cho em thêm thông tin đặt bàn ạ?"


def opening_line(slots: BookingSlots | None = None) -> str:
    slots = slots or BookingSlots()
    return (
        "Dạ nhà hàng xin nghe ạ. Em rất vui được hỗ trợ anh chị đặt bàn. "
        + question_for("customer_name", slots=slots)
    )


def speak_guidance(
    slots: BookingSlots,
    missing: list[str],
    *,
    delta: SlotDelta | None = None,
    available: bool | None = None,
) -> dict[str, object]:
    """Hints for the LLM: what to ask next, not a scripted sentence."""
    next_field = missing[0] if missing else None
    return {
        "next_field": next_field,
        "ready_to_confirm": not missing and available is not False,
        "known": known_facts(slots),
        "just_saved": _delta_fields(delta),
        "available": available,
        "instruction": (
            "Tự soạn lời thoại mới. Nếu next_field có giá trị, chỉ hỏi đúng trường đó, "
            "gắn với known và điều khách vừa nói, gọi khách bằng tên nếu đã có. "
            "Không dùng câu hỏi khuôn, không lặp câu trong lịch sử. "
            "Nếu ready_to_confirm, đọc lại đặt bàn rồi hỏi chốt."
        ),
    }


def known_facts(slots: BookingSlots) -> dict[str, str]:
    facts: dict[str, str] = {}
    if slots.customer_name:
        facts["customer_name"] = slots.customer_name
    if slots.phone:
        facts["phone"] = slots.phone
    if slots.guest_count:
        facts["guest_count"] = str(slots.guest_count)
    if slots.date:
        facts["date"] = _date_phrase(slots.date)
    if slots.time:
        facts["time"] = slots.time.strftime("%H:%M")
    if slots.branch:
        facts["branch"] = branch_label(slots.branch)
    if slots.notes:
        facts["notes"] = slots.notes
    return facts


def confirm_summary(slots: BookingSlots) -> str:
    name = slots.customer_name or "anh chị"
    bits = []
    if slots.guest_count:
        bits.append(f"bàn cho {slots.guest_count} vị")
    if slots.date:
        bits.append(f"ngày {slots.date.strftime('%d/%m/%Y')}")
    if slots.time:
        bits.append(f"lúc {slots.time.strftime('%H:%M')}")
    if slots.branch:
        bits.append(f"chi nhánh {branch_label(slots.branch)}")
    if slots.phone:
        bits.append(f"số liên hệ {slots.phone}")
    if slots.notes:
        bits.append(f"ghi chú {slots.notes}")
    detail = ", ".join(bits)
    return (
        f"Dạ em xin phép đọc lại giúp {name}: {detail}. "
        f"Anh chị xem đã vừa ý để em giữ bàn ạ?"
    )


def booked_line(booking_id: str) -> str:
    return (
        f"Dạ em đã giữ bàn thành công, mã đặt {booking_id}. "
        f"Rất hân hạnh được đón anh chị ạ."
    )


def alternatives_line(availability: AvailabilityResponse) -> str:
    if not availability.alternatives:
        return (
            "Dạ khung giờ đó bên em vừa hết chỗ rồi ạ. "
            "Anh chị đổi ngày khác, hoặc em chuyển máy cho nhân viên hỗ trợ thêm ạ?"
        )
    parts = []
    for alt in availability.alternatives:
        parts.append(
            f"{alt.time.strftime('%H:%M')} ngày {alt.date.strftime('%d/%m')} "
            f"chi nhánh {branch_label(alt.branch)}"
        )
    return (
        "Dạ khung giờ đó vừa hết chỗ rồi ạ, bên em vẫn còn "
        + "; ".join(parts)
        + ". Anh chị chọn giúp em khung nào vừa ý hơn ạ?"
    )


def validation_line(errors: list[str]) -> str:
    return " ".join(errors) + " Anh chị cung cấp lại giúp em ạ?"


def faq_then_question(
    faq_text: str,
    next_field: str | None,
    *,
    slots: BookingSlots | None = None,
    delta: SlotDelta | None = None,
    last_user_text: str | None = None,
) -> str:
    text = faq_text.strip()
    if next_field:
        return (
            f"{text} "
            + question_for(
                next_field,
                slots=slots,
                delta=delta,
                last_user_text=last_user_text,
            )
        )
    return f"{text} Anh chị còn muốn em hỗ trợ đặt bàn không ạ?"


def _ask_name(slots: BookingSlots) -> str:
    ack = _ack_known(slots, skip={"customer_name", "phone"})
    if ack:
        return f"{ack} Cho em xin được biết tên mình để em giữ bàn ạ?"
    if slots.phone:
        return (
            "Dạ em đã có số máy này rồi ạ. "
            "Cho em xin được biết anh chị tên gì để em xưng hô cho phải ạ?"
        )
    return "Dạ em xin được biết anh chị tên gì ạ?"


def _ask_phone(slots: BookingSlots) -> str:
    ack = _ack_known(slots, skip={"phone", "customer_name"})
    name = slots.customer_name
    ask = "Anh chị cho em xin số điện thoại liên hệ để em giữ bàn ạ?"
    if ack and name:
        return f"{ack} Cảm ơn {name} ạ. {ask}"
    if ack:
        return f"{ack} {ask}"
    if name:
        return f"Dạ cảm ơn {name} ạ. {ask}"
    return ask


def _ask_guest_count(slots: BookingSlots) -> str:
    if slots.customer_name and _is_birthday(slots):
        return f"Dạ {slots.customer_name} ạ, nhân dịp này anh chị đi mấy người ạ?"
    if slots.customer_name:
        return f"Dạ cảm ơn {slots.customer_name} ạ. Anh chị đặt bàn cho mấy người ạ?"
    if _is_birthday(slots):
        return "Dạ nhân dịp này anh chị đặt bàn cho mấy người ạ?"
    return "Dạ anh chị đặt bàn cho mấy người ạ?"


def _ask_date(slots: BookingSlots) -> str:
    if slots.customer_name and slots.guest_count:
        return (
            f"Dạ {slots.customer_name} đặt bàn {slots.guest_count} vị, "
            "anh chị muốn ghé nhà hàng ngày nào ạ?"
        )
    if slots.guest_count:
        return f"Dạ bàn {slots.guest_count} vị, anh chị muốn ghé nhà hàng ngày nào ạ?"
    return "Anh chị muốn ghé nhà hàng ngày nào ạ?"


def _ask_time(slots: BookingSlots, *, last_user_text: str | None = None) -> str:
    when = _date_phrase(slots.date) if slots.date else ""
    folded = fold_vi(last_user_text or "")
    evening = any(token in folded for token in ("toi", "chieu", "dem"))
    if when and evening and slots.guest_count:
        return (
            f"Dạ bàn {slots.guest_count} vị {when} buổi tối, "
            "anh chị muốn khoảng mấy giờ ạ?"
        )
    if when and slots.guest_count:
        return (
            f"Dạ bàn {slots.guest_count} vị {when}, "
            "anh chị muốn dùng bữa lúc mấy giờ ạ?"
        )
    if when:
        return f"Dạ {when} anh chị muốn dùng bữa lúc mấy giờ ạ?"
    return "Anh chị muốn dùng bữa khoảng mấy giờ ạ?"


def _ask_branch(slots: BookingSlots) -> str:
    when = _date_phrase(slots.date) if slots.date else ""
    clock = slots.time.strftime("%H:%M") if slots.time else ""
    if when and clock:
        return (
            f"Dạ {when} lúc {clock}, anh chị muốn dùng bữa ở "
            "chi nhánh Quận 1 hay Thảo Điền ạ?"
        )
    if slots.guest_count:
        return (
            f"Dạ bàn {slots.guest_count} vị, anh chị muốn dùng bữa ở "
            "chi nhánh Quận 1 hay Thảo Điền ạ?"
        )
    return "Anh chị muốn dùng bữa ở chi nhánh Quận 1 hay Thảo Điền ạ?"


def _ack_known(slots: BookingSlots, skip: set[str] | None = None) -> str:
    skip = skip or set()
    bits: list[str] = []
    if slots.guest_count and "guest_count" not in skip:
        bits.append(f"bàn {slots.guest_count} vị")
    if slots.date and "date" not in skip:
        bits.append(_date_phrase(slots.date))
    if slots.time and "time" not in skip:
        bits.append(f"lúc {slots.time.strftime('%H:%M')}")
    if slots.branch and "branch" not in skip:
        bits.append(f"chi nhánh {branch_label(slots.branch)}")
    if slots.notes and "notes" not in skip:
        bits.append(slots.notes)
    if not bits:
        return ""
    return "Dạ em ghi nhận " + ", ".join(bits) + " ạ."


def _date_phrase(day: date) -> str:
    today = datetime.now(VN_TZ).date()
    if day == today:
        return "hôm nay"
    if day == today + timedelta(days=1):
        return "ngày mai"
    if day == today + timedelta(days=2):
        return "ngày kia"
    return f"ngày {day.strftime('%d/%m')}"


def _is_birthday(slots: BookingSlots) -> bool:
    return "sinh nhat" in fold_vi(slots.notes or "")


def _delta_fields(delta: SlotDelta | None) -> list[str]:
    if delta is None:
        return []
    names = (
        "guest_count",
        "date",
        "time",
        "branch",
        "customer_name",
        "phone",
        "notes",
    )
    return [name for name in names if getattr(delta, name) is not None]


GREETING = opening_line()
