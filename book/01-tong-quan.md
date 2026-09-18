# 01 — Tổng quan

## Vấn đề

Một nhà hàng nhận điện thoại cả ngày. Phần lớn cuộc gọi lặp đi lặp lại: đặt bàn, hỏi
thực đơn, đặt món mang về, đặt giao hàng. Nhân viên phải bỏ việc đang làm để nghe máy,
ghi tay, rồi nhập lại vào hệ thống — chậm và dễ sai.

## Giải pháp của dự án

Một **tổng đài AI** thay người nghe máy:

1. Khách gọi vào số hotline của nhà hàng.
2. AI chào, đọc menu dịch vụ: *bấm 1 đặt bàn, bấm 2 lấy tại quán, bấm 3 giao hàng*.
3. Khách nói chuyện bình thường. AI nghe (STT), hiểu (LLM), trả lời bằng giọng nói (TTS).
4. AI tự tra cứu chi nhánh, thực đơn, giá — từ chính cơ sở dữ liệu của nhà hàng.
5. Khi khách xác nhận, AI **ghi đơn thật** vào database.
6. Cuộc gọi kết thúc; toàn bộ transcript được lưu lại để tra soát.
7. Nhân viên mở dashboard web xem đơn mới.

Toàn bộ hội thoại hiện tại chạy **bằng tiếng Anh** (xem `build_system_prompt` trong
`AI/llm/stream.py`: *"Speak English only"*), dù người dùng gõ tiếng Việt trong code và
tài liệu.

## Một cuộc gọi trông như thế nào

```
AI   : Hello, you have reached our automated assistant.
       To book a table, press 1. To order food for pickup, press 2.
       To order food for delivery, press 3.
Khách: *bấm phím 2*
AI   : Please say your name, address, and what food you would like.
       Is the number you are calling from, 0 9 1 2 3 4 5 6 7 8, the right one for the order?
Khách: Yes. My name is Minh, I want two Caesar salads.
AI   : (gọi tool search_menu → add_to_cart)
       Two Caesar Salads, that's 190,000 dong. Anything else?
Khách: No, that's it. Pickup at six.
AI   : (gọi tool save_order_details → create_order)
       Your order is placed. See you at six, Minh.
*máy tự cúp sau khi phát hết câu cuối*
```

## Ba khối phần mềm

Dự án là một **monorepo** với ba phần chạy độc lập:

| Khối | Thư mục | Ngôn ngữ | Nhiệm vụ |
| --- | --- | --- | --- |
| **AI Bridge** | `AI/` | Python + FastAPI | Xử lý cuộc gọi: nghe, nghĩ, nói, gọi tool |
| **BE** | `BE/` | TypeScript + NestJS | Nghiệp vụ nhà hàng, cơ sở dữ liệu, REST API |
| **FE** | `FE/` | TypeScript + React | Dashboard cho nhân viên |

AI Bridge **không có database riêng**. Mọi thứ nó biết về nhà hàng đều đến từ BE qua HTTP.
Đó là lý do BE phải chạy trước AI.

## Những điều làm dự án này khó hơn "gọi API OpenAI"

Đây là phần đáng chú ý nhất với người mới. Một chatbot văn bản chỉ cần gửi câu hỏi và
nhận câu trả lời. Một tổng đài thoại phải xử lý thêm:

- **Độ trễ là tất cả.** Khách im lặng 2 giây là thấy "máy bị đơ". Toàn bộ pipeline được
  thiết kế để phát ra tiếng sớm nhất có thể: LLM stream **từng câu**, câu đầu tiên được
  đưa đi tổng hợp giọng ngay khi vừa đủ một câu, không đợi hết câu trả lời.
  → [Chương 09](09-noi-tts.md)
- **Khách cắt lời (barge-in).** Khi khách nói đè lên lúc AI đang nói, phải im ngay lập tức
  và vứt bỏ phần còn lại — nhưng **không được vứt** cái POST đang tạo đơn hàng dở dang.
  → [Chương 10](10-barge-in.md)
- **STT nghe sai tên món.** "Chicken Zinger Combo" thành "chicken singer combo". Dự án
  đẩy tên món của đúng nhà hàng đó vào STT làm gợi ý, và có một bộ khớp phiên âm chạy
  trước cả LLM. → [Chương 07](07-nghe-stt.md)
- **Không được nói dối.** AI chỉ được xác nhận "đã đặt bàn" khi tool `create_booking`
  trả về `ok: true`. Prompt nói rõ điều này nhiều lần. → [Chương 11](11-tool-dat-ban.md)
- **Âm thanh phải đúng từng byte.** Sai endianness của PCM là tiếng rè trắng, và **không
  có lỗi nào được báo**. → [Chương 13](13-telnyx.md)

## Tiếp theo

→ [02 — Kiến trúc & cổng](02-kien-truc.md)
