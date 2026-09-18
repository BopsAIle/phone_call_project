# Cải thiện độ chính xác và tốc độ của pipeline AI

## Bối cảnh

Pipeline hiện tại đã chạy được: nghe → hiểu → gọi tool → nói. Nhưng khi đọc kỹ toàn bộ đường đi của một
cuộc gọi, tôi tìm thấy **sáu lỗi thật sự làm hệ thống trả kết quả sai hoặc chết giữa chừng**, và **năm chỗ
mất thời gian không cần thiết**. Chưa có chỗ nào đo được thời gian, nên hiện tại không ai biết một lượt nói
mất bao nhiêu giây, và sửa xong có nhanh lên thật không.

Tài liệu này liệt kê từng vấn đề theo ba nhóm bạn nêu: **nghe đúng (đầu vào)**, **làm đúng (đầu ra)**,
**nhanh hơn**. Mỗi mục viết theo cùng một khuôn: *hiện tại xảy ra chuyện gì → tại sao sai → sửa thế nào →
khách hàng thấy khác gì*.

Ràng buộc đã chốt với bạn:
- Chỉ sửa trong thư mục `AI/`. Không đụng BE (NestJS) đợt này.
- Ưu tiên sửa lỗi sai trước, tốc độ sau.
- Được phép ghi âm cuộc gọi vào máy local để xây bộ dữ liệu kiểm tra.
- Mốc chờ im lặng 800ms **giữ nguyên mặc định**, chỉ đưa ra biến môi trường để thử nghiệm.

Khi triển khai, tài liệu này cũng được chép vào `AI/documents/` để team đọc.

---

## Phần A — Sáu lỗi làm hệ thống sai (đợt 1)

### A1. Gọi trùng một món hai lần rồi sửa số lượng → tool báo lỗi vô nghĩa

**Hiện tại:** khách gọi "cho tôi phở bò", rồi "thêm một phở bò nữa nhưng ít cay". Giỏ hàng có hai dòng cùng
món. Khách nói tiếp "cho thành ba tô". AI gọi tool `update_cart`, tool **văng lỗi kỹ thuật** và trả về
`tool_failed`. Model không hiểu gì, nói bừa.

**Tại sao:** trong [order/tools.py:348-353](AI/order/tools.py#L348) có một dòng lệnh nằm sau lệnh `return`
nên **không bao giờ chạy được**:

```python
    if not matches:
        return -1
        return -2          # <- dòng này chết, không bao giờ tới
```

Khi tìm thấy hai dòng trùng, hàm rơi xuống cuối và trả về rỗng. Đoạn dùng nó rồi đem rỗng đi so sánh với
số → lỗi Python. Điều buồn cười là mã lỗi `ambiguous_line` (nhiều dòng trùng) **đã được viết sẵn** ở
[order/tools.py:824-825](AI/order/tools.py#L824), chỉ là không bao giờ chạm tới được.

**Sửa:** bỏ dòng chết, trả về đúng mã `-2`. Đồng thời làm cho câu trả lời **dùng được**: kèm danh sách các
dòng đang trùng và gợi ý cho model hỏi lại khách muốn sửa dòng nào.

**Khách thấy gì:** thay vì AI nói lảm nhảm, AI hỏi "Dạ anh muốn sửa tô ít cay hay tô thường ạ?"

> Ghi chú: toàn bộ nhóm hàm giỏ hàng (`update_cart`, `remove_from_cart`) **hiện không có một bài test nào**.
> Đó là lý do một dòng lệnh chết nằm đó mà không ai biết.

---

### A2. Khách nói chen vào đúng lúc đang tạo đơn → cả phần còn lại của cuộc gọi hỏng

Đây là lỗi nặng nhất trong danh sách.

**Hiện tại:** AI nói "Dạ em đang lên đơn cho mình", rồi gọi lệnh tạo đơn gửi lên BE. Đúng lúc đó khách nói
chen vào. Hệ thống ngắt lời AI (đúng), nhưng trong lúc ngắt nó **ghi câu AI vừa nói vào sổ hội thoại**, chèn
vào giữa hai thứ vốn phải dính liền nhau: lệnh gọi tool và kết quả của tool đó.

Kết quả sổ hội thoại thành:

```
[AI gọi tool tạo đơn]  →  [AI nói: "Dạ em đang lên đơn"]  →  [kết quả tool]
                            ↑ kẻ chen ngang
```

OpenAI **bắt buộc** kết quả tool phải nằm ngay sau lệnh gọi tool. Có kẻ chen giữa là nó từ chối nguyên cả
request.

**Tại sao đau:** sổ hội thoại không bao giờ được sửa lại. Nên **từ lượt đó trở đi, mọi lượt nói đều lỗi**.
Mỗi lần lỗi, AI lại nói câu "Sorry, I didn't catch that. Could you say that again?" — khách tưởng AI không
nghe được, nói lại, lại lỗi, lặp vô tận cho đến khi khách bỏ cuộc.

**Tại sao xảy ra:** [turn/barge_in.py:114](AI/turn/barge_in.py#L114) ghi câu nói vào sổ, trong khi
[llm/stream.py:576](AI/llm/stream.py#L576) và [llm/stream.py:594](AI/llm/stream.py#L594) ghi lệnh tool và
kết quả tool vào **cùng một cuốn sổ đó**, ở hai thời điểm cách nhau (vì phải chờ BE trả lời). Ai chen vào
khoảng giữa cũng phá được.

**Sửa — ba lớp, không phải một:**

1. **Ghi tool thành một cụm liền, không thể chen.** Gom lệnh gọi tool + tất cả kết quả vào một danh sách
   riêng, rồi ghi vào sổ **một lần duy nhất** bằng một lệnh không có chỗ nghỉ. Trong Python chạy một luồng,
   một lệnh ghi liền như vậy thì không gì chen vào giữa được. Kể cả khi bị hủy giữa chừng, vẫn ghi đủ cụm
   (những tool chưa chạy xong thì điền "bị ngắt").

2. **Trả quyền sổ hội thoại về cho `bridge/session.py`.** Hiện `llm/stream.py` đang sửa trực tiếp cuốn sổ
   của người khác. Đổi thành: nó làm việc trên bản sao, xong thì "nộp" cụm kết quả về cho session ghi. Đây
   mới là chỗ sửa gốc — lớp 1 chỉ vá đúng một đường đi, lớp 2 làm cho cả **loại lỗi** này không tái diễn khi
   sau này có người thêm code mới.

3. **Thêm bước tự chữa.** Một hàm kiểm tra sổ hội thoại đầu mỗi lượt: nếu phát hiện kết quả tool bị lạc chỗ
   thì kéo về đúng vị trí, thiếu thì bù vào, thừa thì bỏ. Nếu sổ đang lành thì không đụng gì. Cần lớp này
   vì lớp 1 và 2 chỉ chặn lỗi **mới** — cuộc gọi nào đã hỏng rồi thì vẫn hỏng.

**Bonus:** dời việc ghi câu nói ra **sau** khi tool chạy xong, để sổ ghi đúng thứ tự "AI gọi tool → tool trả
kết quả → AI nói". Đọc lại transcript sẽ khớp với những gì thật sự diễn ra.

**Khách thấy gì:** cuộc gọi không còn chết giữa chừng vì khách nói chen vào lúc xác nhận đơn.

---

### A3. Đọc số tiền bị cắt làm hai câu

**Hiện tại:** AI đọc "Tổng cộng là 19.000 đồng." Hệ thống cắt thành **hai câu**: `"Tổng cộng là 19."` và
`"000 đồng."` Mỗi câu là một lần gọi TTS riêng, nên khách nghe: *"Tổng cộng là mười chín."* — ngắt — *"không
không không đồng."*

Các trường hợp khác cùng lỗi:
- `"Mr. Smith"` → `"Mr."` + `"Smith"`
- `"Wait... okay"` → `"Wait."` + `".. okay"`
- `"1.5 kg"` → `"1."` + `"5 kg"`

**Tại sao:** bộ cắt câu ở [llm/stream.py:427-435](AI/llm/stream.py#L427) chỉ cần thấy dấu chấm rồi tới một
ký tự không phải khoảng trắng là cắt ngay. Nó không phân biệt được dấu chấm cuối câu với dấu chấm trong số.

Trớ trêu là tài liệu `documents/new_pipeline.md` viết rõ cơ chế "nhìn trước một ký tự" tồn tại chính là **để
chống trường hợp 19.000 bị vỡ** — nhưng cách viết hiện tại không làm được điều đó.

**Sửa:** tách phần "đây có phải hết câu không" thành một hàm riêng, kiểm tra thêm bốn điều kiện đơn giản:
chấm giữa hai chữ số thì không cắt; chấm sau các từ viết tắt (Mr, Mrs, Dr…) thì không cắt; nhiều dấu chấm
liên tiếp (`...`) thì không cắt; chấm sau một chữ cái hoa đơn lẻ (A. Nguyễn) thì không cắt. Còn lại cắt bình
thường.

Cần lưu ý: `"bấm 1. Để đặt bàn"` **vẫn phải cắt** (vì có khoảng trắng sau dấu chấm) — đây là câu menu DTMF,
không được gộp. Tôi đã kiểm tra: cả 4 bài test hiện có vẫn pass.

**Khách thấy gì:** số tiền và tên riêng đọc liền mạch. Bớt được một lần gọi TTS nên cũng nhanh hơn chút.

---

### A4. Tạo đơn bỏ qua kết quả kiểm tra dữ liệu

**Hiện tại:** khi tạo đơn, hệ thống có chạy kiểm tra dữ liệu khách cung cấp (số điện thoại, ngày) — nhưng
**vứt kết quả kiểm tra đi**. [order/tools.py:925](AI/order/tools.py#L925):

```python
        _apply_order_details(session, args)   # hàm này trả về danh sách lỗi — bị bỏ luôn
```

Nên nếu model đưa số điện thoại sai ở bước tạo đơn, hệ thống lặng lẽ bỏ qua, dùng số cũ đã lưu từ trước, và
đơn được gửi lên BE với **số điện thoại cũ trong khi model tưởng nó vừa cập nhật số mới**.

Hàm `save_order_details` ngay bên cạnh thì làm đúng — nó báo lỗi ra ngoài. Chỉ đường tạo đơn là quên.

**Sửa:** nhận kết quả kiểm tra, nếu có lỗi thì trả về `{"ok": false, "error": "invalid_fields", ...}` kèm
danh sách trường sai và **không gửi lên BE**. Đặt ngay trước các bước kiểm tra khác.

**Một trường hợp cần cẩn thận:** nếu khách đồng ý dùng số đang gọi tới mà hệ thống lại không lấy được số từ
nhà mạng, thì trước đây nó âm thầm dùng số cũ, giờ sẽ báo lỗi cứng. Rủi ro thấp (system prompt chỉ bật luật
"dùng số đang gọi" khi có số thật), nhưng sẽ theo dõi log sau khi triển khai.

**Khách thấy gì:** đơn không bị gửi đi với số điện thoại sai. Đổi lại mất thêm một lượt hỏi — đó chính là ý đồ.

---

### A5. Có lúc AI im lặng hoàn toàn, không nói gì cả

**Hiện tại:** có **hai** đường đi khiến một lượt kết thúc mà không phát ra tiếng nào:

1. Model gọi tool liên tục 12 vòng không dừng → [llm/stream.py:615](AI/llm/stream.py#L615) ghi log cảnh báo
   rồi thoát, không nói gì.
2. **Đường phổ biến hơn:** model trả về rỗng — không chữ, không tool (hoặc tool bị hỏng tên) →
   [llm/stream.py:561](AI/llm/stream.py#L561) `return` luôn.

Đường thứ hai đáng lo hơn vì nó xảy ra thường xuyên hơn. Và cơ chế cứu hộ ở
[bridge/session.py:925](AI/bridge/session.py#L925) **chỉ chạy khi có lỗi ném ra** — còn đây là "chạy thành
công nhưng rỗng", nên không ai đỡ.

Chính hợp đồng của dự án (`documents/backend_contract/ai-bridge-contract.md` §9) đã viết: *"Gửi cái gì đó —
kể cả câu lỗi nói thành tiếng còn hơn im lặng."*

**Sửa:** đặt một nguyên tắc duy nhất — **một lượt không bao giờ được kết thúc mà chưa nói gì**. Đánh dấu đã
nói hay chưa, và ở cả hai điểm thoát, nếu chưa nói câu nào thì nói một câu xin lỗi.

Quan trọng: **không** áp dụng khi lượt bị khách ngắt lời — lúc đó im lặng mới đúng.

**Khách thấy gì:** không còn cảnh gọi điện mà đầu dây bên kia im bặt không rõ lý do.

---

### A6. Số điện thoại không kiểm tra độ dài

**Hiện tại:** [booking/tools.py:223](AI/booking/tools.py#L223) chỉ lọc lấy chữ số, không kiểm tra dài ngắn.
Tôi đã chạy thử:

```
normalize_customer_phone('5')                 -> '5'                # được chấp nhận, gửi lên BE
normalize_customer_phone('0912')              -> '0912'             # được chấp nhận
normalize_customer_phone('84123456789012')    -> '84123456789012'   # 14 số, được chấp nhận
```

Hai hàm tạo đơn / đặt bàn chỉ kiểm tra "có rỗng không". Một từ nghe nhầm thành số là thành số điện thoại hợp
lệ trong database.

**Sửa:** giới hạn 8–15 chữ số (15 là giới hạn chuẩn quốc tế E.164). Ngoài khoảng đó trả về rỗng.

**Thêm một điều quan trọng:** phân biệt "khách chưa cho số" với "khách cho số nhưng nghe không ra". Hiện
cả hai đều báo `missing_fields`, khiến model hỏi lại từ đầu như chưa từng hỏi. Cần mã lỗi riêng
`invalid_phone` để model nói "Dạ em nghe chưa rõ, anh đọc lại từng số giúp em" thay vì "Cho em xin số điện
thoại ạ".

**Khách thấy gì:** không bị nhà hàng gọi lại vào số sai. Và khi nghe nhầm thì AI xin đọc lại, không hỏi lại
như người mất trí nhớ.

> Nhóm hàm này cũng **không có test nào** — `normalize_customer_phone` không xuất hiện trong bất kỳ file
> test nào. Toàn bộ tính năng "dùng số đang gọi tới" cũng vậy.

---

## Phần B — Năm chỗ làm chậm (đợt 2)

### B1. Khoảng lặng khi tạo đơn — cho AI nói trong lúc đang làm

**Hiện tại:** khách xác nhận đơn xong, AI gọi lệnh tạo đơn lên BE. Trong lúc BE xử lý và ghi database, **AI
không nói gì**. Khách nghe im lặng, tưởng rớt máy, nói "alo?" — và tiếng "alo" đó kích hoạt cơ chế ngắt lời,
phá luôn lượt nói.

Lưu ý đây là chỗ duy nhất trong hệ thống còn gọi ra ngoài mạng thật. Tra cứu món ăn đã đọc từ RAM nên gần
như tức thì; chỉ tạo đơn / đặt bàn là bắt buộc phải gửi lên BE.

**Sửa:** thêm một ô bắt buộc tên `customer_response` vào hai tool chậm nhất (`create_order`,
`create_booking`). Model tự viết sẵn một câu ngắn — *"Dạ em đang lên đơn cho mình nhé"* — nằm ngay trong
lệnh gọi tool. Hệ thống nói câu đó ra **trước** khi gửi lên BE.

Điểm hay: không tốn thêm một lần gọi OpenAI nào (câu này đi kèm trong dữ liệu model vốn đã phải sinh ra), và
kiến trúc hiện tại đã cho sẵn tính song song — [`TurnPlayer.speak_sentence`](AI/bridge/session.py#L296) tạo
việc rồi trả về ngay, không đợi tổng hợp giọng xong. Nên chỉ cần phát câu đó ra đúng chỗ là TTS và HTTP tự
chạy cùng lúc.

**Ba chỗ dễ sai:**
1. Phải **bóc** `customer_response` ra khỏi dữ liệu trước khi đưa xuống tool, nếu không tool nhận một trường
   lạ.
2. Chỉ gắn cho tool chậm. Tra cứu món chạy dưới 1 mili-giây — nói câu chờ cho việc đó nghe rất thừa.
3. **Rủi ro chính:** model có thể tưởng câu chờ đó là câu xác nhận luôn, rồi sau khi tool xong thì không nói
   gì nữa. Khách nghe "Dạ em đang lên đơn" rồi im. Chặn bằng cách ghi rõ trong mô tả *"không được nói là đã
   xong — lúc này chưa biết kết quả"*, và thêm một dòng vào system prompt: *"câu đó chỉ là câu giữ nhịp, sau
   khi tool trả kết quả vẫn phải báo kết quả thật bằng một câu riêng."*

**Khách thấy gì:** khoảng lặng lúc chốt đơn giảm từ ~1–2 giây xuống còn ~0,3 giây.

---

### B2. Bỏ đồng hồ khỏi system prompt để dùng được bộ nhớ đệm của OpenAI

**Hiện tại:** system prompt dài khoảng **3.700 chữ** (tính cả mô tả 11 tool), được gửi lại **nguyên vẹn
trong mỗi vòng của mỗi lượt nói**. OpenAI có cơ chế giảm giá và giảm độ trễ nếu phần đầu request không đổi
giữa các lần gọi.

Nhưng [llm/stream.py:172](AI/llm/stream.py#L172) nhét **giờ phút hiện tại** vào prompt:

```python
        f"The current local time is {now}.",     # "2026-09-18 14:23 +07"
```

Mỗi phút trôi qua là prompt đổi → bộ nhớ đệm không bao giờ trúng. Tệ hơn: `refresh_system_prompt` được gọi
lại nhiều lần **ngay trong cùng một lượt** (mỗi tool đặt món gọi nó hai lần), nên prompt còn đổi giữa các
vòng của cùng một lượt.

**Sửa, hai bước:**

**Bước 1 (rủi ro thấp, làm ngay):** bỏ phút, chỉ giữ ngày. Việc hiểu "ngày mai", "tối nay" **đã được code xử
lý sẵn** ở [booking/tools.py:149-197](AI/booking/tools.py#L149) — prompt không cần biết chính xác đến phút.
Nếu vẫn muốn model biết giờ để nói "giờ này quán đóng cửa rồi", làm tròn theo giờ là đủ.

**Bước 2 (rủi ro cao hơn, làm cuối cùng):** tách prompt làm hai phần. Phần **quy tắc** (cách nói chuyện,
luật dùng tool, danh sách chi nhánh) đứng yên ở đầu, gần như không đổi cả cuộc gọi. Phần **tình trạng hiện
tại** (giỏ hàng, còn thiếu thông tin gì, đã chọn chi nhánh nào) tách ra một tin nhắn riêng, đặt ngay trước
câu khách vừa nói. Như vậy toàn bộ phần đầu là cố định và dùng được bộ nhớ đệm.

Bước 2 còn một lợi ích phụ: thông tin mới nhất nằm **gần câu khách vừa nói** thay vì bị đẩy lên tận đầu — mô
hình thường chú ý kém với thứ nằm giữa đoạn dài.

**Rủi ro của bước 2:** mô hình coi trọng tin nhắn hệ thống ở đầu khác với ở giữa. Có thể nó bắt đầu hỏi lại
chi nhánh hoặc lặp câu hỏi thu thập thông tin. Vì vậy phải làm **sau cùng**, và chỉ sau khi đã có số đo
(mục B4) để biết có cải thiện thật không.

**Cách kiểm chứng:** OpenAI trả về số token được dùng lại từ bộ nhớ đệm. Ghi nó vào log. Nếu vẫn bằng 0 thì
việc tách chưa xong.

---

### B3. Bỏ một lần gọi AI thừa ở mỗi câu khách nói

**Hiện tại:** [bridge/session.py:883-899](AI/bridge/session.py#L883) — khi nhà hàng có nhiều chi nhánh và
khách chưa chọn, **mọi câu khách nói** đều bị đem đi hỏi AI xem có phải đang nói tên chi nhánh không. Kể cả
khi khách nói "vâng", "hai người", "bảy giờ tối".

Mà hàm đó ([booking/matcher.py:382](AI/booking/matcher.py#L382)) là **một lần gọi OpenAI đầy đủ**, chạy
xong mới tới lượt gọi OpenAI chính. Tức mỗi câu nói phải chờ hai lần gọi nối tiếp nhau.

**Sửa:** thêm một bộ lọc rẻ chạy trước, không gọi mạng: câu này có khả năng nhắc tên chi nhánh không? Tận
dụng đồ đã có sẵn trong `booking/matcher.py` — so khớp tên theo âm, tên riêng Sài Gòn/HCM, các từ khóa như
"chi nhánh", "quận", "gần", "đường". Không khớp gì thì bỏ qua, đi thẳng vào lượt nói chính.

**Một điểm agent phản biện bắt được mà tôi bỏ sót:** phải lọc cả theo **địa chỉ**, không chỉ tên. Việc quan
trọng nhất của bộ so khớp chi nhánh là ánh xạ "106 Hoàng Quốc Việt" vào đúng chi nhánh — nếu chỉ lọc theo
tên thì mất luôn khả năng đó.

**Tại sao an toàn:** tool `resolve_branch` vẫn còn nguyên, và system prompt vẫn dạy model gọi nó khi khách
nhắc địa điểm. Bộ lọc bỏ sót thì chỉ tốn thêm một vòng — mà chỉ tốn đúng ở những câu khách thật sự nhắc chi
nhánh, vài câu mỗi cuộc gọi. Thiệt hại có giới hạn rõ ràng.

**Khách thấy gì:** với nhà hàng nhiều chi nhánh, mỗi câu nói bình thường nhanh hơn khoảng 300–600 mili-giây.

---

### B4. Chưa có gì đo thời gian — gắn đồng hồ vào

**Hiện tại:** trong toàn bộ code chỉ có 3 chỗ đo thời gian, và **không chỗ nào đo độ trễ pipeline** (một chỗ
để ước lượng còn bao nhiêu audio chưa phát, một chỗ giới hạn tần suất ghi log, một chỗ chống bấm phím trùng).

Nghĩa là hiện tại không ai trả lời được: *một lượt nói mất bao lâu? OpenAI chậm hay TTS chậm? Sửa xong có
nhanh lên không?*

**Sửa:** mỗi lượt nói ghi **một dòng log duy nhất**, dạng dễ đọc và dễ bóc bằng script:

```
TURN call=abc123 gen=7 stt_ms=812 llm_ttft_ms=430 llm_ttfs_ms=512 tts_ttfb_ms=190
     first_audio_ms=1104 llm_rounds=2 tool_ms=640 tools=search_menu,add_to_cart
     cached_tokens=3584 prompt_tokens=4102
```

Đo sáu mốc: khách ngừng nói → có chữ; gọi OpenAI → chữ đầu tiên; → câu đầu tiên; gọi TTS → byte tiếng đầu
tiên; tool mất bao lâu; và **con số quan trọng nhất**: khách ngừng nói → byte tiếng đầu tiên ra dây.

Kèm một script nhỏ `scripts/turn_stats.py` đọc file log và in ra trung vị / p90 / p95 cho từng chỉ số.

**Điểm kỹ thuật cần lưu ý:** đặt ở package riêng `obs/` không phụ thuộc gì, vì `bridge` đã gọi `llm` rồi —
nếu `llm` gọi ngược lại `bridge` sẽ thành vòng tròn. Truyền qua `contextvars` để không phải sửa chữ ký hàm
khắp nơi (giá trị tự động theo sang các task con, đúng cái ta cần cho các task TTS).

**Đây là việc phải làm trước B1/B2/B3**, nếu không thì sửa xong cũng chỉ là cảm giác.

---

### B5. Đưa mốc chờ im lặng 800ms ra biến môi trường

**Giữ nguyên 800ms mặc định** như bạn đã chốt. Chỉ thêm biến `STT_SILENCE_DURATION_MS` để bạn tự thử
600/700/900 và so bằng số đo ở mục B4.

Đây là chặng chờ cố định lớn nhất trong mỗi lượt (800ms trước khi AI bắt đầu nghĩ), nhưng nó được đặt cao
**có chủ đích** — tài liệu `stt-accuracy-playbook.md` ghi rõ mốc cũ 450ms cắt vụn câu của người nói tiếng
Anh không phải bản ngữ, khiến AI nghe sai nhiều hơn. Đừng hạ nếu chưa có số.

---

## Phần C — Nghe đúng hơn (đợt 3)

Phần này khác hai phần trên: nó **không phải sửa lỗi, mà là xây khả năng đo**. Hiện tại không ai biết STT
nghe đúng bao nhiêu phần trăm.

### C1. Ghi âm cuộc gọi vào máy

`scripts/stt_eval.py` là một công cụ đo **hoàn chỉnh và chạy được**, nhưng nó thoát ngay khi chạy vì thư
mục `audio/eval/` rỗng — chưa ai từng ghi âm cuộc gọi thật. Tài liệu playbook liệt kê đây là việc còn dở số
1, và mọi việc tinh chỉnh STT đều chờ nó.

**Làm:** thêm bộ ghi âm **mặc định tắt**, bật bằng biến `CALL_RECORD_DIR`. Ghi audio **đúng chỗ STT nghe**
([bridge/session.py:496](AI/bridge/session.py#L496)) chứ không phải chỗ Telnyx gửi vào — vì thứ đáng đo là
thứ STT thật sự nhận, và cách này bao luôn cả đường `/v1/bridge` lẫn demo trình duyệt.

Kèm một file `.jsonl` bên cạnh ghi lại mốc byte của từng sự kiện (khách bắt đầu nói, câu STT nghe ra, câu AI
đáp). Đây là thứ biến một file ghi âm dài thành một bộ dữ liệu kiểm tra — có script
`scripts/split_call.py` cắt ra từng đoạn kèm sẵn bản ghi.

**Hai điều bắt buộc không được quên:**

1. **`.gitignore` hiện không có `audio/`.** Tôi đã kiểm tra cả `.gitignore` gốc và `AI/.gitignore` — không
   có. Nếu không thêm, file ghi âm cuộc gọi khách hàng sẽ bị commit lên git.

2. **Thông báo cho người gọi.** BE không được đụng đợt này, nhưng
   [`ensure_intent_greeting`](AI/bridge/session.py#L76) nằm trong `AI/` và đang tự thêm menu bấm phím vào
   câu chào. Khi bật ghi âm thì thêm một câu thông báo ở đó. Một dòng, và nó giữ cho việc này hợp lệ.

Bản ghi tự động được đặt tên `.txt.auto` chứ không phải `.txt` — vì `stt_eval.py` bỏ qua đoạn nào không có
`.txt`, nên đoạn nào chưa có người đọc lại và sửa thì chưa vào bộ đo. Lấy kết quả của chính hệ thống làm
đáp án đúng thì đo ra 100% và không nói lên điều gì.

### C2. Sửa ba lỗi trong chính công cụ đo

Công cụ đo hiện có ba chỗ khiến kết quả không đáng tin:

1. **Không đo đúng cấu hình đang chạy thật.** Nó không gửi `prompt` và `noise_reduction`. Mà `prompt` là
   **kênh duy nhất** để mớm tên món cho model `gpt-4o-transcribe` đang dùng. Tức là đang đo một cấu hình
   khác với cấu hình production, đúng ở chiều đang muốn tinh chỉnh. Sửa bằng cách tách phần dựng cấu hình ra
   một hàm chung cho cả hai bên dùng — như vậy về sau không thể lệch nữa.

2. **Công thức tính sai không phạt chữ thừa.** [scripts/stt_eval.py:42](AI/scripts/stt_eval.py#L42) dùng
   `SequenceMatcher` nên nếu STT nghe ra dài gấp đôi mà chứa đủ chữ đúng thì vẫn được 0% lỗi. Thay bằng
   công thức khoảng cách sửa chuỗi tiêu chuẩn.

3. **Nó xóa sạch tiếng Việt.** Dòng [scripts/stt_eval.py:39](AI/scripts/stt_eval.py#L39):

   ```python
   re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
   ```

   Regex này bỏ mọi ký tự có dấu. `"Phở bò"` thành `"ph b"` ở **cả** đáp án lẫn kết quả — nên nghe sai đúng
   những từ quan trọng nhất lại được chấm là đúng. Đây là lỗi nghiêm trọng nhất trong ba lỗi.

Agent phản biện còn phát hiện thêm: công cụ chỉ lấy **đoạn đầu tiên** rồi dừng, nên đoạn ghi âm dài nhiều
câu bị mất phần sau, làm kết quả xấu đi một cách giả tạo.

---

## Thứ tự thực hiện

```
Đợt 1 — sửa lỗi sai
  1. A1  giỏ hàng trùng món            nhỏ, độc lập, làm trước cho ấm máy
  2. A6  kiểm tra số điện thoại        phải làm trước A4 (A4 dùng kết quả của nó)
  3. A4  tạo đơn nhận kết quả kiểm tra
  4. C1  bộ ghi âm                     >>> ship sớm, để bắt đầu gom dữ liệu ngay
  5. A3  bộ cắt câu                    hàm thuần, độc lập
  6. tests/fakes.py: FakeChatCompletions   <<< không có cái này thì 4 lỗi dưới không test được
  7. A2  sổ hội thoại (3 lớp)          lỗi nặng nhất, cần nhiều test nhất
  8. A5  không bao giờ im lặng         cùng file với A2, làm liền mạch

Đợt 2 — nhanh hơn
  9.  B4  gắn đồng hồ đo               >>> phải trước mọi việc tối ưu
  10. B5  biến môi trường VAD          nhỏ, gộp chung
  11. B3  bỏ lần gọi AI thừa           lợi ích chắc chắn nhất
  12. B1  câu nói lấp khoảng lặng      phải sau A2 (cùng vòng lặp)
  13. B2  bước 1: bỏ phút khỏi prompt  rủi ro thấp
  14. B2  bước 2: tách prompt          rủi ro cao nhất, làm cuối, có số đo mới làm

Đợt 3 — nghe đúng hơn
  15. C2  sửa công cụ đo
  16. chạy đo trên dữ liệu thật, rồi mới bàn tới chỉnh VAD / noise_reduction / delay
```

**Hai điều đáng chú ý về thứ tự:**

- **Bộ ghi âm phải ship sớm** dù nó thuộc nhóm "đo lường". Mọi việc khác mất vài ngày, mà bộ dữ liệu cần
  những cuộc gọi diễn ra **trong lúc đang làm**. Ship muộn là mất luôn từng ấy cuộc gọi.

- **`FakeChatCompletions` là điều kiện tiên quyết.** File `llm/stream.py` **hiện không có một bài test trực
  tiếp nào** — mà bốn trong sáu lỗi ở Phần A nằm trong đúng file đó. Đó chính là lý do chúng lọt được vào.
  Phải dựng công cụ test giả lập cho nó trước, nếu không việc sửa chỉ là hy vọng.

---

## Các file chính bị sửa

| File | Việc |
|---|---|
| [llm/stream.py](AI/llm/stream.py) | A2, A3, A5, B1, B2, B4 — file nặng nhất |
| [bridge/session.py](AI/bridge/session.py) | A2 (quyền sở hữu sổ + tự chữa), B3, B4, C1 |
| [order/tools.py](AI/order/tools.py) | A1, A4, B1 (mô tả tool) |
| [booking/tools.py](AI/booking/tools.py) | A6, B1 (mô tả tool) |
| [booking/matcher.py](AI/booking/matcher.py) | B3 (bộ lọc rẻ) |
| [turn/barge_in.py](AI/turn/barge_in.py) | A2 (dời chỗ ghi câu nói) |
| [stt/realtime.py](AI/stt/realtime.py) | B5, C2 (tách hàm dựng cấu hình) |
| [scripts/stt_eval.py](AI/scripts/stt_eval.py) | C2 |
| [tests/fakes.py](AI/tests/fakes.py) | `FakeChatCompletions` — nền cho mọi test mới |
| File mới | `audio/recorder.py`, `obs/timing.py`, `scripts/turn_stats.py`, `scripts/split_call.py` |

**File test mới:** `test_llm_stream.py`, `test_history_repair.py`, `test_timing.py`, `test_recorder.py`,
`test_stt_eval.py`. Bổ sung cho: `test_order_tools.py`, `test_booking_tools.py`, `test_aggregator.py`,
`test_barge_in.py`, `test_booking_matcher.py`, `test_booking_session.py`, `test_stt_realtime.py`.

---

## Cách kiểm chứng

**Sau mỗi mục:**
```bash
cd AI && .venv/bin/python -m pytest        # 251 test hiện có phải còn xanh
```

**Đợt 1 — kiểm bằng kịch bản gọi thật:**
- A1: gọi một món hai lần với ghi chú khác nhau, rồi xin đổi số lượng → AI phải hỏi lại rõ ràng, không lảm nhảm
- A2: đúng lúc AI nói "đang lên đơn", nói chen vào → các lượt sau vẫn bình thường, không lặp câu xin lỗi
- A3: để AI đọc tổng tiền có nghìn → nghe liền mạch, không ngắt giữa số
- A4: cố tình đọc số điện thoại sai ở bước chốt đơn → AI phải hỏi lại, và BE **không** nhận đơn
- A5: bắt model rơi vào vòng tool (hoặc dùng test) → phải nghe được câu xin lỗi, không im lặng

**Đợt 2 — kiểm bằng số:**
```bash
cd AI && .venv/bin/python scripts/turn_stats.py app.log
```
So `first_audio_ms` trước/sau. Với B2, xem `cached_tokens` — nếu vẫn 0 thì việc tách chưa xong.

**Đợt 3:**
```bash
CALL_RECORD_DIR=audio/recordings .venv/bin/python app.py   # gọi vài cuộc
.venv/bin/python scripts/split_call.py audio/recordings/<tên>
# sửa tay các file .txt.auto thành .txt, rồi:
.venv/bin/python scripts/stt_eval.py
```
Theo playbook §7.4: **ưu tiên chỉ số "nghe đúng tên món" hơn tỉ lệ lỗi chữ tổng thể**. Và luôn xem kèm tỉ lệ
nhận nhầm — nhận nhiều hơn mà nhầm nhiều hơn là tệ hơn.

---

## Những gì KHÔNG làm đợt này

Ghi rõ để khỏi bàn lại:

- **Không đụng BE** — theo bạn chốt. Hệ quả: chống tạo đơn trùng khi lỗi mạng chỉ chặn được **một nửa**. Khi
  gửi đơn bị timeout, BE **có thể đã ghi đơn rồi** mà phía AI không biết. Chặn triệt để cần BE nhận `callId`
  làm khóa chống trùng. Tài liệu `new_pipeline.md:1415` đã ghi *"chưa có idempotency key thì đừng retry"* —
  đợt này giữ nguyên nguyên tắc không thử lại.
- **Không hạ mốc 800ms** — chỉ đưa ra biến môi trường.
- **Không đổi model STT** — playbook đã đo và loại `gpt-live-transcribe` (nó không hỗ trợ nhận biết lượt
  nói, mất luôn khả năng ngắt lời).
- **Không chuyển sang speech-to-speech** — ba tài liệu đã chốt giữ kiến trúc nối tầng.
- **Không lưu lịch sử cuộc gọi vào database** — cần BE. Nhưng đây là lỗ hổng vận hành thật: khách khiếu nại
  đơn thì hiện không có gì đối chiếu. Nên xếp lịch cho đợt sau.
- **Không đụng cắt câu theo độ dài tối thiểu** — sửa A3 làm câu dài hơn, đủ rồi; thêm nữa sẽ làm việc ghi
  nhận "khách đã nghe được đến đâu" kém chính xác đi.
