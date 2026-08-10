# Source Notes

Nguồn corpus là các trang công khai chính thức của Green SM. Trang hỗ trợ gộp nhiều mục FAQ trong một tài liệu web; hệ thống snapshot theo section/FAQ selector và cấp `source_id` riêng để citation/evaluation ổn định.

Pass B (2026-08-09): live HTML được materialize từ `__NEXT_DATA__` trước khi chạy selector DSL (`section:` / `faq:` / `page:`). `Quy chế hoạt động` trên site là chuỗi ảnh quét (`quychehoatdong-1.jpg` … `-56.jpg`); unit `GSM-TERMS-OPERATING` lưu provenance URL ảnh (OCR chưa làm).

Nguồn kỹ thuật Gemini:

- Models: https://ai.google.dev/gemini-api/docs/models
- Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Embeddings: https://ai.google.dev/gemini-api/docs/embeddings

Normalized snapshot JSON được commit dưới `data/corpus/snapshots/by_source/`. `raw_cache/` tiếp tục gitignore.
