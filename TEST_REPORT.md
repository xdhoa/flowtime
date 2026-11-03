# Kiểm tra Flowtime 3.0 (Python/Flask)

Ngày: 03/11/2026. Máy: Windows 11, Python 3.14.7 (Vercel dùng 3.12 theo `.python-version`).

## Kết quả tự động

- `python -m pytest -q`: **67/67 đạt** (gồm 16 test cho luồng gửi yêu cầu không cần đăng nhập).
- `node --test "tests/frontend/*.test.mjs"` (tùy chọn, kiểm tra module giao diện): **10/10 đạt**.
- Kiểm tra trực tiếp trên Chrome (chế độ demo): trang chủ là biểu mẫu gửi yêu cầu; gửi không cần đăng nhập → nhận đường dẫn theo dõi → trang theo dõi hiển thị đúng → dashboard quản lý demo thấy yêu cầu; không có lỗi console.
- Smoke test HTTP với `python app.py`: `/` trả `text/html`; `/app.js`, `/planner.mjs` trả `text/javascript`; `/api/index?route=config` trả JSON `configured:false`; `/.env` trả 404.

| Nhóm | Phạm vi |
|---|---|
| Phân quyền API | Người giao việc không đọc được việc của người khác (404), không dùng được plan/timer/status/handoff/settings/AI phân tích (403); role giả trong metadata bị bỏ qua; người giao việc không nhận plans/sessions |
| Hợp đồng API | Giữ nguyên `/api/index?route=…` và `/api/cron`; tạo việc gắn danh tính từ máy chủ; trường riêng tư bị bỏ qua; định dạng ngày ISO giống bản Node |
| Bí mật và input | Không trả khóa trong config; chặn URL `javascript:`, ngày sai, lịch đảo ngược, múi giờ sai, JSON sai/không phải object, body quá lớn; chặn POST khác origin; không phục vụ `.env`, `app.py`, mã nguồn |
| Tính lịch (Python) | Cùng bộ test với `planner.mjs`: trừ thời gian thực tế, nghỉ trưa/cuối tuần/múi giờ, lịch bận giữa slot, thứ tự đang làm → ưu tiên → deadline, cảnh báo rủi ro/hết 90 ngày |
| AI | Thiếu khóa báo lỗi rõ; refusal và số phút sai không thành ước tính |
| Cron | Từ chối khi thiếu hoặc sai `CRON_SECRET` |

## Giới hạn xác minh

Test API dùng mock thay cho Supabase/OpenAI/Resend. Chưa chạy trên Supabase, OpenAI, Resend hay Vercel thật (cần tài khoản/khóa của chủ app). Chưa kiểm tra giao diện trong trình duyệt ở bản này; mã giao diện `public/` không thay đổi so với bản 2.0.

Trước khi dùng thật, hoàn thành checklist staging trong `GO_LIVE_VI.md`, đặc biệt luồng hai tài khoản, hai máy và hai timer đồng thời.
