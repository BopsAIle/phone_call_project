#!/usr/bin/env python3
"""Cắt một file ghi âm cuộc gọi thành các đoạn cho bộ đo STT.

    .venv/bin/python scripts/split_call.py audio/recordings/20260918-101500-abc123.wav

Đọc file .wav cùng file .jsonl bên cạnh (do audio/recorder.py ghi), cắt mỗi lượt khách
nói thành một đoạn trong audio/eval/, kèm sẵn bản ghi mà STT nghe được lúc đó.

Bản ghi kèm sẵn được đặt tên **.txt.auto**, KHÔNG phải .txt. scripts/stt_eval.py bỏ qua
đoạn nào không có .txt, nên một đoạn chỉ vào bộ đo sau khi có người nghe lại và sửa rồi
đổi tên. Lấy kết quả của chính hệ thống làm đáp án đúng thì đo ra 100% và không nói lên
điều gì.

Chỉ dùng thư viện chuẩn.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BYTES_PER_SECOND = 24000 * 2
PAD_BYTES = int(BYTES_PER_SECOND * 0.2)  # ~200 ms đệm hai đầu, tránh cụt phụ âm đầu
MIN_CLIP_BYTES = int(BYTES_PER_SECOND * 0.3)


def read_marks(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    marks: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            marks.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return marks


def turns(marks: list[dict], total_bytes: int) -> list[tuple[int, int, str]]:
    """Mỗi lượt là khoảng từ speech_started tới transcript ngay sau nó."""
    out: list[tuple[int, int, str]] = []
    started: int | None = None
    for mark in marks:
        event = mark.get("event")
        offset = int(mark.get("offset") or 0)
        if event == "speech_started":
            started = offset
        elif event == "transcript":
            begin = started if started is not None else max(0, offset - BYTES_PER_SECOND * 5)
            started = None
            text = str(mark.get("text") or "").strip()
            start = max(0, begin - PAD_BYTES)
            end = min(total_bytes, offset + PAD_BYTES)
            if end - start >= MIN_CLIP_BYTES:
                out.append((start, end, text))
    return out


def write_clip(pcm: bytes, path: pathlib.Path) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(pcm)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", help="file .wav do bộ ghi âm tạo ra")
    parser.add_argument("--out", default="audio/eval", help="thư mục chứa các đoạn cắt ra")
    args = parser.parse_args()

    source = pathlib.Path(args.recording)
    if not source.exists():
        raise SystemExit(f"Không thấy file {source}")

    with wave.open(str(source), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise SystemExit("Cần PCM16 mono. File này không phải.")
        if reader.getframerate() != 24000:
            print(f"Cảnh báo: {reader.getframerate()} Hz, không phải 24000 — đoạn cắt sẽ lệch.")
        pcm = reader.readframes(reader.getnframes())

    marks = read_marks(source.with_suffix(".jsonl"))
    if not marks:
        raise SystemExit(
            f"Không thấy {source.with_suffix('.jsonl')}. Không có mốc thì không cắt được theo lượt."
        )

    spans = turns(marks, len(pcm))
    if not spans:
        raise SystemExit("Không có lượt nào trong file mốc.")

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem

    written = 0
    for index, (start, end, text) in enumerate(spans, 1):
        clip_path = out_dir / f"{stem}-{index:03d}.wav"
        write_clip(pcm[start:end], clip_path)
        if text:
            clip_path.with_suffix(".txt.auto").write_text(text + "\n", encoding="utf-8")
        written += 1
        seconds = (end - start) / BYTES_PER_SECOND
        print(f"  {clip_path.name}  {seconds:4.1f}s  {text[:60]!r}")

    print(f"\nĐã cắt {written} đoạn vào {out_dir}/")
    print("Bước tiếp: nghe lại, sửa file .txt.auto cho đúng, rồi đổi đuôi thành .txt.")
    print("Chỉ đoạn có .txt mới vào bộ đo — đáp án phải do người xác nhận.")


if __name__ == "__main__":
    main()
