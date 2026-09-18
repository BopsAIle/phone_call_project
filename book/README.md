# Sổ tay dự án `phone_call_project`

Tài liệu này giải thích **toàn bộ dự án cho người mới bắt đầu**: bạn chưa biết gì về
repo này, có thể chưa từng làm hệ thống thoại, và muốn hiểu dần từ "nó làm gì" đến
"code nằm ở đâu, chạy ra sao".

Mỗi chương là một file nhỏ, đọc được trong 5–15 phút. Đọc theo thứ tự nếu bạn mới vào;
nhảy cóc nếu bạn đã quen.

## Dự án này là gì trong một câu

Một **lễ tân nhà hàng bằng AI trả lời điện thoại**: khách gọi vào số hotline, AI nghe,
hiểu, nói chuyện lại bằng giọng tổng hợp, rồi **đặt bàn** hoặc **đặt món** thật vào cơ sở
dữ liệu của nhà hàng. Nhân viên xem lại mọi thứ trên một dashboard web.

## Mục lục

### Phần A — Hiểu bức tranh lớn
| Chương | Nội dung |
| --- | --- |
| [01 — Tổng quan](01-tong-quan.md) | Hệ thống giải quyết vấn đề gì, một cuộc gọi diễn ra thế nào |
| [02 — Kiến trúc & cổng](02-kien-truc.md) | Ba dịch vụ, ai gọi ai, sơ đồ luồng dữ liệu |
| [03 — Chạy thử lần đầu](03-chay-thu-lan-dau.md) | Cài đặt, biến môi trường, kiểm tra từng service |
| [04 — Bản đồ thư mục](04-ban-do-thu-muc.md) | File nào làm gì, đọc code bắt đầu từ đâu |

### Phần B — Lõi AI (thư mục `AI/`)
| Chương | Nội dung |
| --- | --- |
| [05 — AI Bridge khởi động](05-ai-bridge-khoi-dong.md) | `app.py` → `create_app()` → WebSocket |
| [06 — Vòng đời một cuộc gọi](06-vong-doi-cuoc-goi.md) | Máy trạng thái Init → Greeting → Listening → … |
| [07 — Nghe: STT](07-nghe-stt.md) | Realtime transcription, VAD, từ khóa thực đơn, khớp phiên âm |
| [08 — Nghĩ: LLM](08-nghi-llm.md) | System prompt, stream theo câu, gọi tool, sửa lịch sử hội thoại |
| [09 — Nói: TTS](09-noi-tts.md) | `TurnPlayer`, `OutboundGate`, định dạng âm thanh |
| [10 — Barge-in: khách cắt lời](10-barge-in.md) | Vì sao khó, giải pháp `generation_id` |

### Phần C — Nghiệp vụ & tích hợp
| Chương | Nội dung |
| --- | --- |
| [11 — Tool đặt bàn](11-tool-dat-ban.md) | `resolve_branch`, `confirm_branch`, `create_booking` |
| [12 — Tool đặt món](12-tool-dat-mon.md) | Thực đơn, giỏ hàng, pickup/delivery, `create_order` |
| [13 — Telnyx: cuộc gọi thật](13-telnyx.md) | Webhook, media stream, codec L16, ngrok |
| [14 — Cache Redis & đồng bộ](14-cache-va-sync.md) | Generation, snapshot catalog, poller nền |

### Phần D — Backend, Frontend, vận hành
| Chương | Nội dung |
| --- | --- |
| [15 — Backend NestJS](15-backend-nestjs.md) | Module, entity, bảng dữ liệu, API |
| [16 — Frontend dashboard](16-frontend-dashboard.md) | React + Vite + Ant Design |
| [17 — Log, đo lường, ghi âm](17-log-do-luong-ghi-am.md) | Transcript, `TurnTimer`, `scripts/` |
| [18 — Kiểm thử](18-kiem-thu.md) | 30 file test, cách chạy, cách viết thêm |
| [19 — Sự cố thường gặp](19-su-co-thuong-gap.md) | Không có tiếng, 401, STT nghe sai… |
| [20 — Thuật ngữ](20-thuat-ngu.md) | STT, TTS, VAD, DTMF, barge-in, PCM… là gì |

## Đọc thế nào cho nhanh

- **Chỉ cần chạy được dự án:** đọc 01 → 02 → 03, rồi dừng.
- **Sắp sửa code phần AI:** đọc thêm 04 → 05 → 06 → 07 → 08 → 09 → 10.
- **Sắp sửa code phần nghiệp vụ (bàn/món/API):** đọc 04 → 11 → 12 → 15.
- **Sắp đụng vào cuộc gọi thật:** đọc 13 kỹ, kèm 19.

> Tài liệu này mô tả code tại thời điểm viết. Khi code đổi, nó có thể lệch — file nguồn
> luôn là chân lý. Mọi chương đều dẫn đường tới file thật để bạn tự kiểm chứng.
