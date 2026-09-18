from __future__ import annotations

import asyncio
import json

from llm.history import is_well_formed
from llm.stream import GIVE_UP_PHRASE, OpenAiLlm
from tests.fakes import FakeChatCompletions, LlmRound

_TOOLS = [{"type": "function", "function": {"name": "create_order", "parameters": {}}}]


def _base_history() -> list[dict]:
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "cho tôi hai tô phở"},
    ]


async def _drain(llm, history, *, abort=lambda: False, **kwargs) -> list[str]:
    return [s async for s in llm.stream_sentences(history, abort, **kwargs)]


# --- A2: cụm tool phải ghi nguyên khối vào lịch sử ---


async def test_tool_round_lands_contiguously_in_history() -> None:
    client = FakeChatCompletions(
        [
            LlmRound(tools=[("call_1", "create_order", '{"customer_name": "A"}')]),
            LlmRound(text="Đơn của mình đã xong."),
        ]
    )
    history = _base_history()
    committed: list[list[dict]] = []

    async def execute(name: str, args: str) -> str:
        return json.dumps({"ok": True})

    sentences = await _drain(
        OpenAiLlm(client, "m"),
        history,
        tools=_TOOLS,
        execute_tool=execute,
        on_tool_round=lambda group: (committed.append(group), history.extend(group))[0],
    )

    assert sentences == ["Đơn của mình đã xong."]
    assert [m["role"] for m in history] == ["system", "user", "assistant", "tool"]
    assert history[2]["tool_calls"][0]["id"] == "call_1"
    assert history[3]["tool_call_id"] == "call_1"
    assert is_well_formed(history)
    # Một lần commit duy nhất, gồm cả lệnh gọi lẫn kết quả
    assert len(committed) == 1
    assert [m["role"] for m in committed[0]] == ["assistant", "tool"]


async def test_streamer_does_not_mutate_the_caller_list_itself() -> None:
    """Quyền sở hữu lịch sử thuộc về session; streamer chỉ nộp cụm qua callback."""
    client = FakeChatCompletions(
        [LlmRound(tools=[("call_1", "create_order", "{}")]), LlmRound(text="Xong ạ.")]
    )
    history = _base_history()

    async def execute(name: str, args: str) -> str:
        return "{}"

    await _drain(OpenAiLlm(client, "m"), history, tools=_TOOLS, execute_tool=execute)
    assert [m["role"] for m in history] == ["system", "user"]


async def test_second_round_sees_the_tool_result() -> None:
    client = FakeChatCompletions(
        [LlmRound(tools=[("call_1", "create_order", "{}")]), LlmRound(text="Xong ạ.")]
    )

    async def execute(name: str, args: str) -> str:
        return json.dumps({"ok": True, "order_id": "ord-9"})

    await _drain(OpenAiLlm(client, "m"), _base_history(), tools=_TOOLS, execute_tool=execute)
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assert "ord-9" in second[3]["content"]


async def test_cancelled_mid_tool_still_commits_a_complete_round() -> None:
    """Barge-in huỷ task giữa lúc tool đang chạy — cụm vẫn phải đủ, không nửa vời."""
    client = FakeChatCompletions(
        [
            LlmRound(tools=[("call_1", "search_menu", "{}"), ("call_2", "search_menu", "{}")]),
            LlmRound(text="Xong ạ."),
        ]
    )
    committed: list[list[dict]] = []
    entered = asyncio.Event()

    async def execute(name: str, args: str) -> str:
        entered.set()
        await asyncio.sleep(3600)  # treo cho tới khi bị huỷ
        return "{}"

    async def consume() -> None:
        async for _ in OpenAiLlm(client, "m").stream_sentences(
            _base_history(),
            lambda: False,
            tools=_TOOLS,
            execute_tool=execute,
            on_tool_round=committed.append,
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(committed) == 1
    group = committed[0]
    assert [m["role"] for m in group] == ["assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in group[1:]] == ["call_1", "call_2"]
    for message in group[1:]:
        assert json.loads(message["content"]) == {"ok": False, "error": "interrupted"}
    assert is_well_formed(_base_history() + group)


async def test_failing_tool_answers_its_call_instead_of_raising() -> None:
    client = FakeChatCompletions(
        [LlmRound(tools=[("call_1", "create_order", "{}")]), LlmRound(text="Em xin lỗi ạ.")]
    )
    committed: list[list[dict]] = []

    async def execute(name: str, args: str) -> str:
        raise RuntimeError("backend down")

    sentences = await _drain(
        OpenAiLlm(client, "m"),
        _base_history(),
        tools=_TOOLS,
        execute_tool=execute,
        on_tool_round=committed.append,
    )
    assert sentences == ["Em xin lỗi ạ."]
    assert json.loads(committed[0][1]["content"]) == {"ok": False, "error": "tool_failed"}


# --- A5: một lượt không bao giờ được kết thúc mà chưa nói gì ---


async def test_empty_completion_speaks_a_fallback() -> None:
    client = FakeChatCompletions([LlmRound()])
    sentences = await _drain(OpenAiLlm(client, "m"), _base_history(), tools=_TOOLS)
    assert sentences == [GIVE_UP_PHRASE]


async def test_tool_delta_without_a_name_speaks_a_fallback() -> None:
    """Tool call hỏng (thiếu tên) — trước đây rơi thẳng vào im lặng."""
    client = FakeChatCompletions([LlmRound(tools=[("call_1", "", "{}")])])

    async def execute(name: str, args: str) -> str:
        return "{}"

    sentences = await _drain(
        OpenAiLlm(client, "m"), _base_history(), tools=_TOOLS, execute_tool=execute
    )
    assert sentences == [GIVE_UP_PHRASE]


async def test_endless_tool_loop_speaks_once_after_the_round_ceiling() -> None:
    client = FakeChatCompletions([LlmRound(tools=[("call_1", "search_menu", "{}")])])

    async def execute(name: str, args: str) -> str:
        return "{}"

    sentences = await _drain(
        OpenAiLlm(client, "m"), _base_history(), tools=_TOOLS, execute_tool=execute
    )
    assert sentences == [GIVE_UP_PHRASE]
    assert client.call_count == 12  # _MAX_TOOL_ROUNDS


async def test_no_fallback_when_the_model_already_spoke() -> None:
    client = FakeChatCompletions([LlmRound(text="Dạ em nghe ạ.")])
    sentences = await _drain(OpenAiLlm(client, "m"), _base_history(), tools=_TOOLS)
    assert sentences == ["Dạ em nghe ạ."]


async def test_no_fallback_when_the_caller_interrupted() -> None:
    """Khách đang nói — im lặng mới là đúng."""
    client = FakeChatCompletions([LlmRound()])
    sentences = await _drain(
        OpenAiLlm(client, "m"), _base_history(), abort=lambda: True, tools=_TOOLS
    )
    assert sentences == []


# --- A3 ở tầng stream: số tiền về theo nhiều token vẫn phải liền câu ---


async def test_price_readback_is_not_split_across_tokens() -> None:
    client = FakeChatCompletions([LlmRound(text="Tổng cộng là 19.000 đồng. Cảm ơn anh.", token_size=3)])
    sentences = await _drain(OpenAiLlm(client, "m"), _base_history())
    assert sentences == ["Tổng cộng là 19.000 đồng.", "Cảm ơn anh."]


# --- B1: câu chờ phát ra trước, song song với việc gửi lên backend ---


def test_pop_customer_response_strips_the_field() -> None:
    from llm.stream import pop_customer_response

    spoken, rest = pop_customer_response('{"customer_response": "Em đang lên đơn.", "quantity": 2}')
    assert spoken == "Em đang lên đơn."
    assert json.loads(rest) == {"quantity": 2}


def test_pop_customer_response_leaves_other_payloads_alone() -> None:
    from llm.stream import pop_customer_response

    assert pop_customer_response('{"quantity": 2}') == ("", '{"quantity": 2}')
    assert pop_customer_response("{oops") == ("", "{oops")
    assert pop_customer_response("") == ("", "")


async def test_filler_is_spoken_before_the_tool_runs() -> None:
    """Đây là toàn bộ điểm của tính năng: khách nghe tiếng trong lúc BE đang xử lý."""
    client = FakeChatCompletions(
        [
            LlmRound(
                tools=[
                    (
                        "call_1",
                        "create_order",
                        json.dumps({"customer_response": "Dạ em đang lên đơn.", "customer_name": "A"}),
                    )
                ]
            ),
            LlmRound(text="Đơn của mình đã xong."),
        ]
    )
    spoken_before_tool: list[str] = []
    seen_args: list[str] = []
    said = asyncio.Event()

    async def execute(name: str, args: str) -> str:
        seen_args.append(args)
        # Khi tool chạy, câu chờ phải đã ra khỏi generator rồi
        assert said.is_set(), "tool chạy trước khi nói — mất tác dụng"
        return json.dumps({"ok": True})

    out: list[str] = []
    async for sentence in OpenAiLlm(client, "m").stream_sentences(
        _base_history(), lambda: False, tools=_TOOLS, execute_tool=execute
    ):
        out.append(sentence)
        if not said.is_set():
            spoken_before_tool.append(sentence)
            said.set()

    assert out[0] == "Dạ em đang lên đơn."
    assert out[-1] == "Đơn của mình đã xong."
    # Tool không được nhận trường lạ
    assert json.loads(seen_args[0]) == {"customer_name": "A"}


async def test_history_records_the_arguments_that_actually_ran() -> None:
    client = FakeChatCompletions(
        [
            LlmRound(
                tools=[
                    ("call_1", "create_booking", json.dumps({"customer_response": "Chờ em chút.", "party_size": 2}))
                ]
            ),
            LlmRound(text="Xong ạ."),
        ]
    )
    committed: list[list[dict]] = []

    async def execute(name: str, args: str) -> str:
        return "{}"

    await _drain(
        OpenAiLlm(client, "m"),
        _base_history(),
        tools=_TOOLS,
        execute_tool=execute,
        on_tool_round=committed.append,
    )
    recorded = json.loads(committed[0][0]["tool_calls"][0]["function"]["arguments"])
    assert recorded == {"party_size": 2}


async def test_fast_tools_get_no_filler() -> None:
    """search_menu đọc từ RAM dưới 1 ms — nói câu chờ cho nó là thừa."""
    client = FakeChatCompletions(
        [
            LlmRound(
                tools=[("call_1", "search_menu", json.dumps({"customer_response": "Chờ em.", "spoken_name": "phở"}))]
            ),
            LlmRound(text="Dạ có ạ."),
        ]
    )
    seen: list[str] = []

    async def execute(name: str, args: str) -> str:
        seen.append(args)
        return "{}"

    out = await _drain(OpenAiLlm(client, "m"), _base_history(), tools=_TOOLS, execute_tool=execute)
    assert out == ["Dạ có ạ."]
    # Không bóc, không nói — trường thừa đi thẳng xuống tool, đúng như trước
    assert "customer_response" in json.loads(seen[0])


async def test_filler_is_skipped_when_the_caller_interrupted() -> None:
    client = FakeChatCompletions(
        [LlmRound(tools=[("call_1", "create_order", json.dumps({"customer_response": "Chờ em."}))])]
    )

    async def execute(name: str, args: str) -> str:
        return "{}"

    out = await _drain(
        OpenAiLlm(client, "m"),
        _base_history(),
        abort=lambda: True,
        tools=_TOOLS,
        execute_tool=execute,
    )
    assert out == []
