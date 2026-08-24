from datetime import date, time

from apps.voice_agent.extractor import HeuristicExtractor
from shared.models import CallSession


def test_extractor_core_slots():
    extractor = HeuristicExtractor(today=date(2026, 8, 20))
    delta = extractor.extract(
        "4 nguoi ngay mai 7 gio toi Quan 1 ten Nguyen An sdt 0901234567 sinh nhat",
        CallSession(id="s1"),
    )
    assert delta.guest_count == 4
    assert delta.date == date(2026, 8, 21)
    assert delta.time == time(19, 0)
    assert delta.branch == "quan-1"
    assert delta.customer_name == "Nguyen An"
    assert delta.phone == "0901234567"
    assert delta.notes and "sinh nhat" in delta.notes
