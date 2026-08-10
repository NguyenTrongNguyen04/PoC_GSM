# Data Contract v0.1.0

## 1. Mục tiêu

Data contract bảo đảm mọi baseline được so sánh trên cùng dữ liệu, cùng Ticket Store và cùng ground truth. Mọi thay đổi sau config freeze phải tăng phiên bản và ghi lý do.

## 2. Corpus

Website Green SM hiện tập trung nhiều FAQ trong một trang `/helps`. Vì vậy, D14 được triển khai thành **18 retrieval units** theo từng mục FAQ/chính sách, tương ứng 5 URL chính thức. Đơn vị retrieval được xem như tài liệu độc lập khi chunk/index và có `source_id` ổn định.

Trước indexing, mỗi row trong `corpus_manifest.csv` phải chuyển từ `pending` sang `snapshotted` và có:

- `fetched_at` theo ISO-8601;
- SHA-256 của nội dung chuẩn hóa;
- selector/section dùng để trích nội dung;
- phiên bản parser và chunker trong experiment manifest.

## 3. Persona và split isolation

Có 8 persona tổng hợp, mỗi persona sở hữu đúng 3 scenarios. Development và held-out dùng `user_id` khác nhau hoàn toàn. Không sao chép tình huống, ticket ID hay memory ID qua hai split.

## 4. Scenario

Mỗi scenario có 2–3 turn và một initial state độc lập. Ground truth của từng query gồm:

- `expected_doc_ids`;
- `expected_memory_ids` và `expected_write_memory_ids`;
- `expected_facts` ở mức fact ID;
- `expected_action` gồm type, policy decision và required fields;
- `forbidden_facts`;
- `required_behaviors`.

Reference answer chỉ hỗ trợ human review, không dùng exact string match.

## 5. Ticket Store

Ticket Store là system of record dùng chung cho mọi baseline. Trạng thái: `OPEN`, `WAITING_CUSTOMER`, `IN_REVIEW`, `RESOLVED`, `CLOSED`. LLM chỉ đề xuất action; policy engine kiểm tra và Ticket Service thực thi.

## 6. MAG Memory

Allowlist: `TICKET_REFERENCE`, `SUPPORT_SUMMARY`, `SUPPORT_PREFERENCE`. Memory có owner, status, version, validity và expiry. Ticket memory hết hạn sau `CLOSED + 7 ngày`; preference có TTL 90 ngày. Nội dung đã xóa không được lưu trong vector/cache/audit tombstone.

## 7. Trace

Một trace record tương ứng một query point. Trace phải chứa baseline, scenario/query ID, trusted user, retrieved IDs, ticket calls, policy decision, answer/action, token, latency, estimated cost và error.

## 8. Change control

Held-out dataset không được chỉnh sau G3 trừ lỗi contract khách quan. Mọi chỉnh sửa phải lưu version cũ, nêu impact đến comparability và chạy lại toàn bộ baseline bị ảnh hưởng.
