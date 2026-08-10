# Implementation Specification v0.1.0

## Kiến trúc tối giản

- Python 3.11+ trên Windows, không Docker.
- SQLite cho Ticket Store, Memory Store và Audit Event Store.
- NumPy cosine search cho corpus/memory nhỏ.
- Gemini API cho generation và embedding.
- CLI là acceptance surface; không xây UI trong core scope.

## Thứ tự triển khai

### Day 1 — Contract freeze

Hoàn thiện source snapshots, schema và review 12 development scenarios. Không gọi API.

### Day 2 — Common foundation + B0

Xây database migrations, Ticket Service, state policy, structured action, trace logger, dry-run và cost guard. B0 dùng Gemini + Ticket Service, không RAG/MAG.

### Day 3 — B1 + B3

B1 thêm offline indexing và online retrieval/citation. B3 thêm memory write/read path, owner/lifecycle filter và reconciliation.

### Day 4 — B4 + S0

Kết hợp hai context planes; chạy 12 S0; sửa critical/major; đóng băng prompt/config/model; tạo dự toán chi phí và xin Gate G3.

### Day 5 — Held-out

Chạy 12 S1 cho B0/B1/B3/B4, review mẫu phân tầng 25%, tổng hợp metric, error taxonomy và kết luận.

## Model và budget snapshot

`gemini-3.5-flash-lite` và `gemini-embedding-001` được xác minh ngày 09/08/2026. Giá standard được ghi trong `config/experiment.yaml` chỉ phục vụ dự toán; runner phải kiểm tra lại trước paid run. Hard cap 15 USD là bất biến.

## Stop conditions

Dừng run nếu có cross-user leakage, lifecycle reuse, unauthorized write, policy bypass, memory ghi đè Ticket Store, auto-select ticket mơ hồ hoặc dự toán vượt hard cap.
