#!/usr/bin/env python
"""Compare STT models on recorded calls. Run before and after changing STT settings.

    .venv/bin/python scripts/stt_eval.py

Reads audio/eval/NNN.wav (PCM16 mono 24 kHz) with a matching NNN.txt holding the
true transcript, and transcribes each one with every model, with and without the
catalog keywords. Prints a per-clip comparison plus word error rate and keyword
recall, which is the number that actually decides whether an order goes through.

Record the clips through the real path (browser or phone), not a studio mic — the
codec and the room are part of what you are measuring.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import pathlib
import re
import sys
import wave
from difflib import SequenceMatcher

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI  # noqa: E402

from stt.realtime import NEW_MODELS, build_transcription_session  # noqa: E402

DEFAULT_MODELS = ("gpt-4o-mini-transcribe", "gpt-4o-transcribe", "gpt-live-transcribe")
# Replace with real catalog names, or pass --keywords "A,B,C".
DEFAULT_KEYWORDS = ("Chicken Zinger Combo", "Zinger", "Mushroom Risotto", "Caesar Salad")
CHUNK_BYTES = 9600  # ~200 ms at 24 kHz PCM16
IDLE_SECONDS = 2.0  # hết đoạn khi socket im chừng này


def _words(text: str) -> list[str]:
    """Tách từ, GIỮ chữ có dấu.

    Bản cũ dùng [^a-z0-9 ] nên xoá sạch mọi ký tự có dấu ở cả đáp án lẫn kết quả:
    "Phở bò" thành "ph b" hai bên như nhau, nên nghe sai đúng những từ quan trọng
    nhất lại được chấm là đúng.
    """
    return re.sub(r"[^\w]+", " ", (text or "").casefold(), flags=re.UNICODE).split()


def word_error_rate(hypothesis: str, reference: str) -> float:
    """Khoảng cách Levenshtein trên từ, chia cho độ dài đáp án.

    Bản cũ đếm khối khớp của SequenceMatcher nên KHÔNG phạt chữ thừa: STT nghe ra dài
    gấp đôi mà chứa đủ chữ đúng vẫn được 0% lỗi. Không chặn trên 1.0 — WER > 1 là có
    thật và đáng nhìn thấy.
    """
    ref, hyp = _words(reference), _words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        cur = [i]
        for j, hyp_word in enumerate(hyp, 1):
            cur.append(
                min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ref_word != hyp_word))
            )
        prev = cur
    return prev[-1] / len(ref)


def keyword_hit(hypothesis: str, reference: str, keywords: tuple[str, ...]) -> bool | None:
    """True/False when the truth contains a keyword, None when the clip has none."""
    hay, truth = (hypothesis or "").lower(), (reference or "").lower()
    expected = [kw for kw in keywords if kw.lower() in truth]
    if not expected:
        return None
    return all(kw.lower() in hay for kw in expected)


def read_pcm(path: pathlib.Path) -> bytes:
    with wave.open(str(path)) as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise SystemExit(f"{path.name}: expected mono PCM16")
        if handle.getframerate() != 24000:
            print(f"  ! {path.name} is {handle.getframerate()} Hz, not 24000")
        return handle.readframes(handle.getnframes())


async def transcribe(
    client: AsyncOpenAI,
    model: str,
    pcm: bytes,
    keywords: tuple[str, ...],
    languages: tuple[str, ...],
    prompt: str = "",
    silence_duration_ms: int = 0,
) -> str:
    # Cùng một hàm dựng cấu hình với runtime, nếu không thì đang đo một hệ khác.
    session = build_transcription_session(
        model,
        languages,
        prompt=prompt,
        keywords=keywords,
        silence_duration_ms=silence_duration_ms,
    )
    parts: list[str] = []
    async with client.realtime.connect(extra_query={"intent": "transcription"}) as conn:
        await conn.session.update(session=session)
        for start in range(0, len(pcm), CHUNK_BYTES):
            chunk = pcm[start : start + CHUNK_BYTES]
            await conn.input_audio_buffer.append(audio=base64.b64encode(chunk).decode())
        await conn.input_audio_buffer.commit()
        # Gom hết các đoạn, không dừng ở đoạn đầu: với turn_detection bật, một clip
        # nhiều câu sẽ ra nhiều đoạn, và bản cũ vứt hết phần sau — làm WER của clip
        # dài xấu đi một cách giả tạo, trông như lỗi thiếu chữ.
        while True:
            try:
                event = await asyncio.wait_for(conn.__anext__(), timeout=IDLE_SECONDS)
            except (asyncio.TimeoutError, StopAsyncIteration):
                break
            event_type = str(getattr(event, "type", "") or "")
            if "transcription.completed" in event_type:
                parts.append(str(getattr(event, "transcript", "") or ""))
            elif event_type == "error":
                return f"<error: {getattr(event, 'error', '')}>"
    return " ".join(part for part in parts if part).strip()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="audio/eval", help="folder of NNN.wav + NNN.txt")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    parser.add_argument("--languages", default="en")
    parser.add_argument(
        "--prompt",
        default="",
        help="Prompt ngữ cảnh — kênh mớm tên món DUY NHẤT trên gpt-4o-transcribe. "
        "Dùng stt.context.build_prompt để dựng đúng như production.",
    )
    parser.add_argument(
        "--silence-ms",
        type=int,
        default=0,
        help="Ghi đè silence_duration_ms để A/B (0 = giữ mặc định 800).",
    )
    args = parser.parse_args()

    models = tuple(m.strip() for m in args.models.split(",") if m.strip())
    keywords = tuple(k.strip() for k in args.keywords.split(",") if k.strip())
    languages = tuple(l.strip() for l in args.languages.split(",") if l.strip()) or ("en",)

    clips = sorted(pathlib.Path(args.dir).glob("*.wav"))
    if not clips:
        raise SystemExit(f"No .wav files in {args.dir}. See section 7.2 of the playbook.")

    client = AsyncOpenAI()
    totals: dict[tuple[str, bool], list[float]] = {}
    recalls: dict[tuple[str, bool], list[bool]] = {}

    for clip in clips:
        truth_path = clip.with_suffix(".txt")
        if not truth_path.exists():
            print(f"{clip.name}: no .txt alongside it, skipping")
            continue
        truth = truth_path.read_text(encoding="utf-8").strip()
        pcm = read_pcm(clip)
        print(f"\n{clip.name}  truth: {truth!r}")
        for model in models:
            for use_keywords in (False, True):
                if use_keywords and model not in NEW_MODELS:
                    continue  # older models have no `keywords` field
                text = await transcribe(
                    client,
                    model,
                    pcm,
                    keywords if use_keywords else (),
                    languages,
                    prompt=args.prompt,
                    silence_duration_ms=args.silence_ms,
                )
                wer = word_error_rate(text, truth)
                hit = keyword_hit(text, truth, keywords)
                totals.setdefault((model, use_keywords), []).append(wer)
                if hit is not None:
                    recalls.setdefault((model, use_keywords), []).append(hit)
                tag = "kw" if use_keywords else "  "
                mark = "" if hit is None else ("  keyword OK" if hit else "  KEYWORD MISS")
                print(f"  {model:26} {tag}  wer {wer:5.2f}  {text!r}{mark}")

    print("\n== summary ==")
    for (model, use_keywords), scores in sorted(totals.items()):
        hits = recalls.get((model, use_keywords), [])
        recall = f"{100 * sum(hits) / len(hits):5.1f}%" if hits else "   n/a"
        print(
            f"  {model:26} {'kw' if use_keywords else '  '}  "
            f"mean wer {sum(scores) / len(scores):5.2f}   keyword recall {recall}"
        )


if __name__ == "__main__":
    asyncio.run(main())
