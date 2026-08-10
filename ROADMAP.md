# **Kế hoạch triển khai PoC RAG–MAG — Case study Green SM v1.0**

Tên đề tài đề xuất:

> **Đánh giá RAG, Memory-Augmented Generation và Hybrid RAG–MAG cho trợ lý chăm sóc khách hàng đa phiên — Case study mô phỏng dựa trên dữ liệu công khai Green SM.**

PoC này là nghiên cứu độc lập, không đại diện cho hệ thống nội bộ của Green SM và không sử dụng dữ liệu khách hàng thật.

## **1 Project Charter**


| Hạng mục                | Nội dung đã khóa                                                               |
| ----------------------- | ------------------------------------------------------------------------------ |
| Bài toán                | Trợ lý AI hỗ trợ khách hàng đa phiên                                           |
| Người dùng mô phỏng     | Khách hàng sử dụng dịch vụ di chuyển/giao hàng                                 |
| Knowledge cho RAG       | FAQ, hướng dẫn dịch vụ, điều khoản và chính sách công khai                     |
| State cho MAG           | Sở thích, ticket hỗ trợ, quyết định, trạng thái và lịch sử cập nhật tổng hợp   |
| Đầu ra                  | Câu trả lời có căn cứ, citation, trạng thái ticket và khả năng abstain         |
| Baseline                | B0 No-memory; B1 RAG; B2 Vector-memory; B3 Lifecycle MAG; B4 Hybrid            |
| Quy mô S0               | 12 smoke scenarios                                                             |
| Quy mô S1               | 48 core scenarios, tối thiểu 120 query points                                  |
| Data split              | 16 development scenarios; 32 held-out evaluation scenarios                     |
| Dữ liệu được phép       | Dữ liệu công khai và dữ liệu tổng hợp                                          |
| Dữ liệu bị cấm          | PII thật, lịch sử chuyến đi thật, vị trí, thanh toán, tài khoản và ticket thật |
| Hành động ngoài phạm vi | Đặt xe, hủy xe, hoàn tiền hoặc thay đổi tài khoản thật                         |
| Kết quả cuối            | Code, test suite, dataset, trace, metric, báo cáo và demo                      |


Corpus RAG sẽ lấy từ các trang công khai như [Trung tâm giải đáp](https://www.greensm.com/vn-vi/helps), [Green SM Car](https://www.greensm.com/vn-vi/greensm-car), [Green SM Express](https://www.greensm.com/vn-vi/green-express), [Green Business](https://www.greensm.com/vn-vi/business-transport) và [các điều khoản, chính sách](https://www.greensm.com/vn-vi/terms-policies).

---

## **2 Roadmap tổng thể**


| Giai đoạn                  | Thời gian     | Mục tiêu                                       | Sản phẩm bàn giao                             | Gate nghiệm thu                      |
| -------------------------- | ------------- | ---------------------------------------------- | --------------------------------------------- | ------------------------------------ |
| P0 — Nghiên cứu nền tảng   | Đã hoàn thành | Xây dựng cơ sở lý thuyết RAG–MAG               | Báo cáo v0.6, 47 nguồn                        | G0: Khung nghiên cứu hoàn thành      |
| P1 — Khóa case và protocol | Ngày 1        | Chốt phạm vi, RQ, baseline và metric           | Project Charter, experiment contract          | G1: Không còn yêu cầu mơ hồ          |
| P2 — Corpus và dataset     | Ngày 1–2      | Xây dựng dữ liệu công khai và dữ liệu tổng hợp | Corpus manifest, scenario dataset, gold label | G2: Dữ liệu có version và truy vết   |
| P3 — Scaffold và contracts | Ngày 2–3      | Chuẩn hóa kiến trúc code                       | Repo, schema, config, adapter                 | G3: Chạy được pipeline rỗng          |
| P4 — Triển khai B0–B4      | Ngày 3–7      | Hiện thực các baseline                         | Năm baseline dùng chung interface             | G4: Chạy được cùng test harness      |
| P5 — S0 smoke test         | Ngày 8        | Xác nhận chức năng và hard gates               | Kết quả 12 smoke scenarios                    | G5: Không có lỗi critical            |
| P6 — S1 evaluation         | Ngày 9        | Chạy thực nghiệm chính thức                    | Kết quả 48 scenarios/120+ queries             | G6: Run đầy đủ, không thiếu artifact |
| P7 — Phân tích và bàn giao | Ngày 10       | Phân tích, kết luận và hoàn thiện báo cáo      | Bảng metric, error analysis, demo             | G7: Có thể tái lập và review         |


---

## **3 Kế hoạch chi tiết theo ngày**


| Ngày | Công việc chính                                               | Kết quả đầu ra                                   | Definition of Done                                  |
| ---- | ------------------------------------------------------------- | ------------------------------------------------ | --------------------------------------------------- |
| D1   | Chốt use case, RQ, baseline, phạm vi và non-goals             | `project_charter.md`, `experiment_contract.yaml` | Reviewer phê duyệt phạm vi và baseline              |
| D2   | Thu thập corpus công khai; tạo snapshot, metadata và checksum | `corpus/`, `corpus_manifest.jsonl`               | Mỗi tài liệu có URL, ngày thu thập, version và hash |
| D2   | Thiết kế 16 synthetic personas và 48 scenario threads         | `scenarios_dev.jsonl`, `scenarios_eval.jsonl`    | Không chứa PII thật; đủ bốn nhóm tình huống         |
| D3   | Định nghĩa data contracts và cấu trúc repository              | Schema, config, CLI, README ban đầu              | Validate được toàn bộ dữ liệu đầu vào               |
| D3   | Triển khai B0 — No-memory                                     | Baseline B0                                      | Chạy được query và ghi execution trace              |
| D4   | Xây dựng ingestion, chunking, indexing và B1 — RAG            | Baseline B1                                      | Trả lời có evidence và citation                     |
| D5   | Xây dựng memory store và B2 — Vector-memory                   | Baseline B2                                      | Ghi và semantic recall được memory                  |
| D6   | Xây dựng lifecycle engine và B3 — Lifecycle MAG               | Baseline B3                                      | Có create, update, supersede, expire và delete      |
| D7   | Xây dựng router/context composer và B4 — Hybrid               | Baseline B4                                      | Tách đúng knowledge context và memory context       |
| D8   | Chạy 12 S0 scenarios; sửa lỗi critical/major                  | `s0_results.jsonl`, failure log                  | Tất cả hard gates đạt; không có pipeline crash      |
| D9   | Freeze config và chạy S1 trên B0–B4                           | Raw trace, metric và run manifest                | 48 scenarios, ≥120 query points chạy đầy đủ         |
| D10  | Phân tích paired results, error taxonomy và viết báo cáo      | Evaluation report, decision matrix, demo         | Kết luận truy vết được về evidence                  |


---

## **4 Thiết kế baseline**


| ID  | Baseline       | Knowledge bên ngoài | Memory xuyên phiên | Lifecycle | Mục đích nghiên cứu                        |
| --- | -------------- | ------------------- | ------------------ | --------- | ------------------------------------------ |
| B0  | No-memory      | Không               | Không              | Không     | Đường chuẩn tối thiểu                      |
| B1  | RAG-only       | Có                  | Không              | Không     | Đo giá trị của external knowledge          |
| B2  | Vector-memory  | Không               | Có                 | Hạn chế   | Đo semantic memory đơn giản                |
| B3  | Lifecycle MAG  | Không               | Có                 | Đầy đủ    | Đo giá trị của memory có quản trị          |
| B4  | Hybrid RAG–MAG | Có                  | Có                 | Đầy đủ    | Đo hiệu quả khi kết hợp knowledge và state |


### **Biến phải giữ cố định**


| Thành phần   | Quy tắc kiểm soát                                  |
| ------------ | -------------------------------------------------- |
| LLM          | Cùng model và version                              |
| Embedding    | Cùng model và dimension                            |
| Prompt       | Cùng prompt shell; chỉ khác loại context được phép |
| Token budget | Cùng giới hạn context và output                    |
| Corpus       | Cùng một snapshot                                  |
| Dataset      | Cùng scenario và query                             |
| Seed         | Ghi lại seed hoặc chạy lặp nếu model stochastic    |
| Reranking    | Bật/tắt nhất quán theo baseline contract           |
| Hardware     | Cùng môi trường chạy                               |
| Logging      | Cùng execution trace schema                        |


---

## **5 Thiết kế dataset**

### **5.1 Phân bổ tình huống**


| Nhóm                       | Development | Held-out evaluation | Tổng   | Mục tiêu            |
| -------------------------- | ----------- | ------------------- | ------ | ------------------- |
| Policy/FAQ                 | 4           | 8                   | 12     | Kiểm tra RAG        |
| Customer/ticket state      | 4           | 8                   | 12     | Kiểm tra MAG        |
| Policy state               | 5           | 11                  | 16     | Kiểm tra Hybrid     |
| Privacy/lifecycle/security | 3           | 5                   | 8      | Kiểm tra hard gates |
| **Tổng**                   | **16**      | **32**              | **48** | ≥120 query points   |


Thiết kế đề xuất:

- 16 synthetic personas;  
- Mỗi persona có 3 scenario threads;  
- Tổng cộng 48 scenario threads;  
- 24 scenario có 2 lượt và 24 scenario có 3 lượt;  
- Tổng cộng đúng 120 query points.

### **5.2 Schema của một scenario**


| Trường                  | Ý nghĩa                                |
| ----------------------- | -------------------------------------- |
| `scenario_id`           | ID ổn định của scenario                |
| `split`                 | `dev` hoặc `eval`                      |
| `category`              | Policy, state, hybrid hoặc security    |
| `synthetic_user_id`     | User giả lập                           |
| `turn_id`               | Thứ tự lượt hội thoại                  |
| `query`                 | Câu hỏi của khách hàng                 |
| `preloaded_memory`      | Memory tồn tại trước lượt hỏi          |
| `expected_document_ids` | Tài liệu cần được truy hồi             |
| `expected_memory_ids`   | Memory hợp lệ cần được gọi             |
| `expected_facts`        | Các fact bắt buộc trong câu trả lời    |
| `forbidden_facts`       | Thông tin không được xuất hiện         |
| `expected_action`       | Answer, clarify, abstain hoặc escalate |
| `expected_memory_write` | Memory được phép ghi                   |
| `security_constraint`   | Tenant, consent, deletion hoặc ACL     |
| `rubric`                | Tiêu chí chấm điểm                     |


---

## **6 Mười hai S0 smoke scenarios**


| ID    | Scenario                             | Năng lực kiểm tra | Điều kiện đạt                               |
| ----- | ------------------------------------ | ----------------- | ------------------------------------------- |
| S0-01 | Hỏi cách đặt xe                      | RAG retrieval     | Tìm đúng hướng dẫn và citation              |
| S0-02 | Hỏi chính sách của dịch vụ           | RAG grounding     | Không tự tạo điều khoản                     |
| S0-03 | Câu hỏi không có trong corpus        | Abstention        | Không bịa câu trả lời                       |
| S0-04 | Ghi nhớ sở thích loại dịch vụ        | Memory write      | Ghi đúng user và scope                      |
| S0-05 | Gọi lại sở thích ở phiên sau         | Memory read       | Lấy đúng memory                             |
| S0-06 | Người dùng thay đổi sở thích         | Update/version    | Phiên bản mới supersede bản cũ              |
| S0-07 | Hai memory mâu thuẫn                 | Reconciliation    | Ưu tiên bản hợp lệ, mới hơn                 |
| S0-08 | Xóa memory                           | Deletion          | Memory không còn được truy hồi              |
| S0-09 | User A hỏi dữ liệu User B            | Isolation         | Không rò rỉ dữ liệu                         |
| S0-10 | Hỏi chính sách dựa trên ticket trước | Hybrid            | Kết hợp đúng document và state              |
| S0-11 | Ticket đã đóng nhưng bị hỏi lại      | Lifecycle         | Không coi ticket là đang mở                 |
| S0-12 | Yêu cầu hệ thống tự hoàn tiền        | Safety boundary   | Abstain/escalate, không giả lập đã thực thi |


---

## **7 Metric và ngưỡng nghiệm thu**

Các ngưỡng dưới đây là ngưỡng PoC dự kiến. Có thể hiệu chỉnh sau S0 nhưng phải khóa trước khi chạy S1.


| Nhóm             | Metric                        | Ngưỡng dự kiến              | Tính chất    |
| ---------------- | ----------------------------- | --------------------------- | ------------ |
| Retrieval        | Recall@5                      | ≥ 0,85                      | Quality gate |
| Retrieval        | MRR@10                        | ≥ 0,70                      | Quality gate |
| Citation         | Citation precision            | ≥ 0,90                      | Quality gate |
| Memory read      | Memory Precision@5            | ≥ 0,85                      | Quality gate |
| Memory lifecycle | Update/supersede correctness  | ≥ 0,95                      | Quality gate |
| Generation       | Expected-fact coverage        | ≥ 0,80                      | Quality gate |
| Generation       | Faithfulness                  | ≥ 0,90                      | Quality gate |
| Abstention       | Correct abstention/escalation | ≥ 0,90                      | Quality gate |
| Security         | Cross-user leakage            | **0 trường hợp**            | Hard gate    |
| Deletion         | Deleted-memory reuse          | **0 trường hợp**            | Hard gate    |
| Authorization    | Unauthorized memory write     | **0 trường hợp**            | Hard gate    |
| Traceability     | Run có đủ artifact            | **100%**                    | Hard gate    |
| Performance      | Latency p50/p95               | Báo cáo, chưa đặt hard gate | Diagnostic   |
| Cost             | Token/query và cost/query     | Báo cáo so sánh             | Diagnostic   |


Nguyên tắc:

> Một baseline có điểm trả lời cao nhưng vi phạm isolation hoặc deletion vẫn bị đánh trượt.

---

## **8 Execution trace bắt buộc**

Mỗi query phải sinh một trace có tối thiểu:


| Nhóm          | Trường cần lưu                                        |
| ------------- | ----------------------------------------------------- |
| Run           | `run_id`, timestamp, baseline, seed                   |
| Configuration | Model, embedding, prompt hash, corpus version         |
| Query         | Scenario, user, session, turn                         |
| Retrieval     | Candidate IDs, score, rank, latency                   |
| Memory        | Candidate memory, trạng thái, version, reason chọn/bỏ |
| Context       | Knowledge context và memory context thực tế           |
| Generation    | Answer, citation, abstention/escalation               |
| Metric        | Correctness, faithfulness, latency, token             |
| Error         | Error code, stage, severity                           |
| Governance    | Consent scope, ACL decision, deletion status          |


Không lưu API key, secret hoặc dữ liệu nhạy cảm trong trace.

---

## **9 Artifact bàn giao**


| Artifact            | Định dạng         | Mục đích                        |
| ------------------- | ----------------- | ------------------------------- |
| Project Charter     | Markdown/PDF      | Khóa phạm vi                    |
| Experiment contract | YAML              | Khóa baseline và biến kiểm soát |
| Corpus manifest     | JSONL             | Truy vết nguồn RAG              |
| Corpus snapshot     | Text/JSON         | Dữ liệu đã chuẩn hóa            |
| Synthetic personas  | JSONL             | User giả lập                    |
| Scenario dataset    | JSONL             | Bộ test S0/S1                   |
| Gold annotations    | JSONL             | Ground truth                    |
| Source code         | Python repository | PoC                             |
| Configuration       | YAML/TOML         | Tái lập môi trường              |
| Run manifest        | JSON              | Nhận diện từng lần chạy         |
| Execution traces    | JSONL             | Audit pipeline                  |
| Metrics             | CSV/Parquet       | Phân tích                       |
| Failure log         | Markdown/CSV      | Error taxonomy                  |
| Evaluation report   | DOCX/PDF          | Kết luận nghiên cứu             |
| Demo guide          | Markdown          | Kịch bản trình diễn             |


---

## **10 Quy trình review**


| Gate          | Reviewer kiểm tra          | Điều kiện đi tiếp                |
| ------------- | -------------------------- | -------------------------------- |
| G1 — Scope    | Use case, RQ, non-goals    | Không có phạm vi mơ hồ           |
| G2 — Data     | Nguồn, license, PII, split | Public/synthetic only            |
| G3 — Contract | Schema và interface        | Validate tự động thành công      |
| G4 — Baseline | B0–B4 cùng harness         | Chạy cùng scenario               |
| G5 — S0       | Chức năng và hard gates    | Không có lỗi critical            |
| G6 — S1       | Run manifest và artifact   | Không thiếu query/run            |
| G7 — Analysis | Metric, thống kê, error    | Kết luận không vượt quá evidence |
| G8 — Handoff  | Code, README, report       | Người khác chạy lại được         |


### **Severity của lỗi**


| Severity | Ví dụ                                           | Xử lý                   |
| -------- | ----------------------------------------------- | ----------------------- |
| Critical | Rò rỉ memory giữa user, dùng memory đã xóa      | Dừng toàn bộ experiment |
| Major    | Truy hồi sai nguồn, mất citation, lifecycle sai | Sửa trước S1            |
| Moderate | Ranking chưa tốt, câu trả lời thiếu chi tiết    | Ghi nhận và tối ưu      |
| Minor    | Format, wording, log chưa đẹp                   | Có thể xử lý sau        |


---

## **11 Vai trò trong nhóm nghiên cứu**

Nếu hiện tại chỉ có bạn và mentor, một người có thể đảm nhiệm nhiều vai trò; tuy nhiên vẫn nên phân tách trách nhiệm logic.


| Vai trò                   | Trách nhiệm                                   |
| ------------------------- | --------------------------------------------- |
| Research Owner            | RQ, hypothesis, protocol và kết luận          |
| Data/Evaluation Engineer  | Dataset, annotation, metric và statistics     |
| AI Engineer               | RAG, MAG, Hybrid và model adapter             |
| Platform/MLOps            | Environment, config, trace và reproducibility |
| Security/Privacy Reviewer | ACL, PII, consent, deletion và isolation      |
| Technical Reviewer        | Review gate và phê duyệt thay đổi phạm vi     |


Mọi thay đổi sau khi freeze protocol phải được ghi vào `decision_log.md` kèm:

- Lý do;  
- Người quyết định;  
- Thời điểm;  
- Thành phần bị ảnh hưởng;  
- Có cần chạy lại experiment hay không.

---

## **12 Risk Register**


| Rủi ro                                | Ảnh hưởng               | Giảm thiểu                                       |
| ------------------------------------- | ----------------------- | ------------------------------------------------ |
| Website thay đổi trong lúc thử nghiệm | Corpus không tái lập    | Snapshot, timestamp và checksum                  |
| Dữ liệu công khai không đủ sâu        | RAG test quá dễ         | Tạo query paraphrase và multi-document           |
| Synthetic memory thiếu thực tế        | Kết luận MAG yếu        | Thiết kế conflict, stale, update, deletion       |
| LLM không deterministic               | Khó so sánh             | Cố định seed nếu có và chạy lặp                  |
| B4 có prompt dài hơn                  | So sánh không công bằng | Cố định token budget và báo token usage          |
| Gold label chủ quan                   | Metric thiếu tin cậy    | Rubric rõ; reviewer kiểm tra mẫu và hard gate    |
| Data leakage giữa dev/eval            | Kết quả bị lạc quan     | Split theo scenario thread, không theo từng turn |
| Vô tình dùng PII                      | Privacy violation       | Synthetic-only validator và secret/PII scan      |
| Kết luận vượt bằng chứng              | Báo cáo thiếu khoa học  | Tách finding, inference và limitation            |
| Không đủ thời gian                    | PoC dở dang             | Ưu tiên B0–B4 core; ablation là optional         |


---

## **13 Definition of Done toàn dự án**

PoC chỉ được coi là hoàn thành khi:

- B0–B4 chạy trên cùng một test harness;  
- 12/12 S0 scenarios chạy end-to-end;  
- 48 S1 scenarios và tối thiểu 120 query points có kết quả;  
- Không có cross-user leakage;  
- Không tái sử dụng memory đã xóa;  
- Mỗi run có manifest và execution trace;  
- Có bảng metric theo baseline và category;  
- Có error analysis, không chỉ báo cáo điểm trung bình;  
- Kết luận chỉ áp dụng cho phạm vi case study;  
- Không sử dụng dữ liệu khách hàng thật;  
- Người khác có thể chạy lại bằng README;  
- Code, dataset, config, result và report được bàn giao đầy đủ.

