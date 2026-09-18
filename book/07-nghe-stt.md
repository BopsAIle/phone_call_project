# 07 — Nghe: STT (Speech to Text)

Files: `AI/stt/realtime.py`, `AI/stt/context.py`, `AI/stt/phonetic.py`.

## Ý tưởng

AI Bridge mở **một WebSocket tới OpenAI Realtime** cho mỗi cuộc gọi, đẩy PCM 24 kHz vào,
và nhận về các sự kiện: khách bắt đầu nói, khách ngừng nói, văn bản từng phần, văn bản
hoàn chỉnh.

Model **không nói** — session được mở với `intent=transcription`, nó chỉ phiên âm.

## Kết nối

```python
self._manager = client.realtime.connect(extra_query={"intent": "transcription"})
self._connection = await self._manager.enter()
await self._connection.session.update(session=self._session_payload())
```

`_session_payload()` khai báo:

```python
{
  "type": "transcription",
  "audio": {"input": {
      "format": {"type": "audio/pcm", "rate": 24000},
      "transcription": {"model": "gpt-4o-transcribe", "language": "en", "prompt": "..."},
      "turn_detection": vad_config(...),
      "noise_reduction": {"type": "near_field"},
  }}
}
```

## VAD — máy dò tiếng nói, thứ quyết định nhịp hội thoại

```python
VAD = {
    "type": "server_vad",
    "threshold": 0.45,
    "prefix_padding_ms": 400,
    "silence_duration_ms": 800,     # chỉnh qua STT_SILENCE_DURATION_MS
}
```

`silence_duration_ms` = "khách im bao lâu thì coi như đã nói xong". Đây là **chặng chờ cố
định lớn nhất mỗi lượt**, nên rất hấp dẫn để hạ xuống cho nhanh. Đừng hạ tùy tiện:
comment trong code ghi rõ mốc cũ 450 ms **cắt vụn câu** của người nói tiếng Anh không phải
bản ngữ (họ ngập ngừng giữa câu), khiến STT nghe sai nhiều hơn. Biến môi trường tồn tại để
bạn A/B **có số đo** — chạy `AI/scripts/turn_stats.py` trước và sau khi đổi.

VAD cũng là thứ sinh ra sự kiện `speech_started`, mà `speech_started` chính là tín hiệu
kích hoạt barge-in. Không có VAD ⇒ không có cắt lời, và cũng **không có transcript nào**
vì không gì chốt buffer đầu vào.

### Vì sao KHÔNG dùng `gpt-live-transcribe`

Comment trong `AI/config.py` và `_warn_if_vad_unsupported()` ghi lại kết quả đo thật:
model đó trả lời *"Turn detection is not supported for this transcription model"*.
Không VAD ⇒ pipeline này không hoạt động. Dùng `gpt-4o-transcribe`.

## Xử lý sự kiện

| Sự kiện OpenAI | Xử lý |
| --- | --- |
| `input_audio_buffer.speech_started` | → `on_speech_started()` → có thể barge-in |
| `input_audio_buffer.speech_stopped` | → ghi mốc thời gian để đo độ trễ |
| `...transcription.delta` | → cộng dồn văn bản tạm, log ra *"Người gọi (đang nói): …"* |
| `...transcription.completed` | → `on_transcript_completed(text)` → bắt đầu một lượt |
| `...transcription.failed` | → xử lý như transcript rỗng |
| `error` | → thử bỏ trường không hỗ trợ, hoặc cảnh báo VAD |

Có chống trùng bằng `item_id`: cùng một transcript đến hai lần (qua `conversation.item.done`
và `...completed`) chỉ được xử lý một lần.

## Tự hạ cấp khi server từ chối một trường

```python
OPTIONAL_FIELDS = ("delay", "keywords", "prompt", "languages")
```

Mức hỗ trợ các trường này khác nhau tùy model và tùy tài khoản, và tài liệu OpenAI có chỗ
không khớp SDK. Khi server báo lỗi nhắc tới một trường, `_maybe_drop_unsupported()`
**bỏ trường đó rồi gửi lại session** thay vì để cả cuộc gọi chết. Mất một gợi ý còn hơn
mất phiên âm cả cuộc gọi.

## Làm STT nghe đúng tên món — `stt/context.py`

Đây là phần thú vị nhất.

Catalog đã biết chính xác nhà hàng này bán món gì. Chừng nào chưa đưa danh sách đó cho
model, nó phải **đoán từ âm thanh thuần túy** — và một người nói tiếng Anh không chuẩn
đọc "Chicken Zinger Combo" thì model gần như không có manh mối.

`build_keywords()` và `build_prompt()` dựng danh sách gợi ý từ: tên nhà hàng + tên chi
nhánh + tên món. Có lọc:

- Bỏ từ quá phổ biến (`chicken`, `rice`, `combo`, `salad`…) — chúng chỉ chiếm chỗ của
  những từ hiếm mới thật sự cần gợi ý.
- Từ dưới 6 ký tự hiếm khi là từ bị nghe nhầm.
- Trần an toàn: tối đa 80 keyword, mỗi cái ≤ 40 ký tự, prompt ≤ 800 ký tự. Không phải
  giới hạn của OpenAI — là trần tự đặt, vì một `session.update` bị từ chối làm mất **toàn
  bộ** ngữ cảnh.

`update_context()` gọi được **nhiều lần** trong cuộc gọi: catalog về sau khi socket đã mở,
thực đơn về muộn hơn nữa. `CallPipeline._push_stt_context()` có kiểm tra chữ ký
(`_stt_context_sig`) để không gửi lại khi không có gì đổi.

## Khớp phiên âm — `stt/phonetic.py`

Mạng an toàn cuối cùng, chạy **trước** khi tốn một lượt gọi LLM.

STT trả về cái khách **nghe giống**, không phải cái khách **muốn nói**:
"chicken singer combo" ← "Chicken Zinger Combo", "sesar salat" ← "Caesar Salad".
Khoảng cách văn bản thuần (Levenshtein) không bắc được cầu đó, vì nguyên âm chính là thứ
người nói không chuẩn sai nhiều nhất.

Giải pháp: **bỏ hết nguyên âm, gộp phụ âm thành nhóm** (p/b, s/z, l/r, k/g, f/v/w…), rồi
so phần còn lại.

```python
ACCEPT_SCORE  = 0.75   # điểm tối thiểu
ACCEPT_MARGIN = 0.20   # phải hơn ứng viên thứ hai chừng này
```

Hai ngưỡng đo được từ bộ eval trong `AI/documents/stt-accuracy-playbook.md`: mọi trường
hợp đúng đều ≥ 0.82, mọi câu không phải tên món đều ≤ 0.67. Chỉ dùng thư viện chuẩn,
vài micro giây mỗi lần gọi, kết quả tất định.

## Đo chất lượng STT

`AI/scripts/stt_eval.py` so sánh các model STT trên file ghi âm thật:

```bash
cd AI && .venv/bin/python scripts/stt_eval.py
```

Đọc `audio/eval/NNN.wav` (PCM16 mono 24 kHz) kèm `NNN.txt` là transcript đúng, rồi chấm
mỗi model, có và không có keyword. In ra WER (word error rate) và **keyword recall** —
con số thật sự quyết định đơn hàng có lọt hay không.

Ghi clip **qua đường thật** (trình duyệt hoặc điện thoại), không phải micro phòng thu:
codec và tiếng ồn phòng là một phần của thứ bạn đang đo. Bật ghi âm bằng `CALL_RECORD_DIR`
(xem [chương 17](17-log-do-luong-ghi-am.md)).

## Tiếp theo

→ [08 — Nghĩ: LLM](08-nghi-llm.md)
