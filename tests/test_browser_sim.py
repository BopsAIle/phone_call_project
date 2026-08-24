from datetime import time

from shared.config import Settings

from apps.browser_sim.sim import (
    BROWSER_LLM_TOOLS,
    BrowserChatStore,
    browser_page_url,
    browser_voice_webhook_url,
    execute_browser_tool,
    new_browser_call_sid,
)
from apps.voice_agent.nlg import GREETING


def test_browser_webhook_urls():
    settings = Settings(browser_sim_base_url="http://127.0.0.1:8002")
    assert browser_voice_webhook_url(settings) == "http://127.0.0.1:8002/browser/voice"
    assert browser_page_url(settings) == "http://127.0.0.1:8002/browser"


def test_browser_call_sid_prefix():
    assert new_browser_call_sid().startswith("CA-browser-")


def test_browser_tools_match_voice_agent():
    names = {item["function"]["name"] for item in BROWSER_LLM_TOOLS}
    assert names == {"update_slots", "search_knowledge", "confirm_booking", "transfer_to_staff"}


def test_browser_chat_store_starts_with_greeting():
    store = BrowserChatStore()
    history = store.start("sess-1")
    assert history[0]["role"] == "system"
    assert history[1]["role"] == "system"
    assert "hôm nay" in history[1]["content"].lower()
    assert history[2] == {"role": "assistant", "content": GREETING}
    assert store.get("sess-1") is history
    store.drop("sess-1")
    assert store.get("sess-1") is None


async def test_browser_update_slots_tool_hits_backend(engine, tomorrow):
    start = await engine.start(call_sid="CA-browser-tool")
    result = await execute_browser_tool(
        engine,
        start.session.id,
        "update_slots",
        {
            "guest_count": 4,
            "date": tomorrow.isoformat(),
            "time": "19:00",
            "branch": "quan-1",
            "customer_name": "Lan",
        },
    )
    session = result["session"]
    assert session["slots"]["guest_count"] == 4
    assert session["slots"]["time"] == "19:00:00" or session["slots"]["time"] == time(19, 0).isoformat()
    assert "phone" in result["missing_fields"]
    assert result["speak"]["next_field"] == "phone"
    assert result["speak"]["known"]["customer_name"] == "Lan"


async def test_browser_search_knowledge_tool(engine):
    result = await execute_browser_tool(
        engine,
        "unused",
        "search_knowledge",
        {"query": "Nha hang mo cua luc may gio?"},
    )
    assert result["chunks"]
    assert "available" not in result
    assert "Do not claim table availability" in result["note"]


async def test_browser_transfer_tool(engine):
    start = await engine.start(call_sid="CA-browser-xfer")
    result = await execute_browser_tool(
        engine,
        start.session.id,
        "transfer_to_staff",
        {"reason": "guest_requested_human"},
    )
    assert result["transferred"] is True
    session = await engine.backend.get_session(start.session.id)
    assert session.status == "transferred"
    assert session.transfer_reason == "guest_requested_human"


async def test_typed_utterance_skips_tts(monkeypatch, engine):
    from apps.browser_sim.sim import BrowserTurnResult, handle_browser_utterance

    chats = BrowserChatStore()
    session = await engine.backend.create_session(call_sid="CA-typed-tts")
    chats.start(session.id)

    async def fake_llm(*_args, **_kwargs):
        return BrowserTurnResult(assistant_text="Cho em xin so dien thoai a?")

    async def boom_tts(*_args, **_kwargs):
        raise AssertionError("typed turns should skip TTS")

    monkeypatch.setattr("apps.browser_sim.sim.run_browser_llm_turn", fake_llm)
    monkeypatch.setattr("apps.browser_sim.sim.synthesize_speech", boom_tts)

    result = await handle_browser_utterance(
        engine=engine,
        chats=chats,
        settings=Settings(openai_api_key=""),
        session_id=session.id,
        text="ten Lan 4 nguoi",
    )
    assert result.audio_b64 is None
    assert result.user_text == "ten Lan 4 nguoi"
    assert "so dien thoai" in result.assistant_text


async def test_voice_utterance_still_requests_tts(monkeypatch, engine):
    from apps.browser_sim.sim import BrowserTurnResult, handle_browser_utterance

    chats = BrowserChatStore()
    session = await engine.backend.create_session(call_sid="CA-voice-tts")
    chats.start(session.id)

    async def fake_stt(*_args, **_kwargs):
        return "ten Lan"

    async def fake_llm(*_args, **_kwargs):
        return BrowserTurnResult(assistant_text="Cho em xin so a?")

    async def fake_tts(*_args, **_kwargs):
        return "YQ=="

    monkeypatch.setattr("apps.browser_sim.sim.transcribe_audio", fake_stt)
    monkeypatch.setattr("apps.browser_sim.sim.run_browser_llm_turn", fake_llm)
    monkeypatch.setattr("apps.browser_sim.sim.synthesize_speech", fake_tts)

    result = await handle_browser_utterance(
        engine=engine,
        chats=chats,
        settings=Settings(openai_api_key="x"),
        session_id=session.id,
        audio_b64="AAAA",
    )
    assert result.audio_b64 == "YQ=="
    assert result.user_text == "ten Lan"
