# Đưa Flowtime lên từ GitHub — hướng dẫn từng bước

## 1. Chạy thử trên máy (Windows)

Từ bản 3.0, máy chủ viết bằng **Python + Flask**. Không cần Node.js để chạy app.

1. Cài **Python 3.12 trở lên** tại https://www.python.org/downloads/. Trong trình cài đặt, đánh dấu **“Add python.exe to PATH”**.
2. Trong VS Code, chọn **File → Open Folder** và mở thư mục `flowtime-github` (thư mục có `app.py`).
3. Chọn **Terminal → New Terminal**, chạy **một lần**:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Nếu PowerShell báo không cho chạy script: chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, trả lời `Y`, rồi chạy lại dòng `Activate.ps1`.

4. Chạy app:

```powershell
python app.py
```

5. Mở http://localhost:3000 → **Mở demo tương tác**. Bấm `Ctrl+C` trong Terminal để dừng.
6. Thử đổi vai, gửi yêu cầu mới, quay về quản lý, tiếp nhận, bắt đầu/tạm dừng và bàn giao.

Những lần sau chỉ cần: `.\.venv\Scripts\Activate.ps1` rồi `python app.py`. Muốn dùng thật trên máy: sao chép `.env.example` thành `.env` và điền giá trị; `app.py` tự đọc file `.env`.

Demo dùng được ngay. AI/email thật và nhiều người ở các máy khác nhau cần làm các bước tiếp theo.

## 2. Tạo cơ sở dữ liệu Supabase

1. Đăng nhập https://supabase.com, tạo một project dành riêng cho Flowtime.
2. Mở **SQL Editor → New query**.
3. Mở file `supabase/schema.sql` trong VS Code, sao chép toàn bộ, chạy **một lần** trong SQL Editor. Script tạo bảng mới; không chạy lặp lại trên dữ liệu đang dùng.
3b. Sau đó chạy lần lượt các file trong `supabase/migrations/` (New query → dán → Run):
   - `001_public_requests.sql`: cho phép **gửi yêu cầu không cần đăng nhập**.
   - `002_decline_status.sql`: cho phép quản lý **từ chối** yêu cầu (kèm lý do) và mở lại.
   - `003_multi_manager.sql`: **nhiều người quản lý**, mỗi người có link nhận việc riêng.

   Nếu bạn đã có cơ sở dữ liệu đang dùng, chỉ cần chạy các file này: chúng chỉ bổ sung, không xóa hay đổi dữ liệu cũ, và chạy lại nhiều lần vẫn an toàn.
4. Trong phần API Keys/Project Settings, ghi lại:
   - Project URL → `SUPABASE_URL`.
   - Khóa anon/publishable → `SUPABASE_ANON_KEY`.
   - Khóa **service_role** bí mật → `SUPABASE_SERVICE_ROLE_KEY`. Không để khóa này vào `public/`, ảnh chụp hay repo.
5. Trong **Authentication → Providers → Email**, bật email/password và **bật xác nhận email** (Confirm email). Người quản lý mới phải xác nhận email trước khi dùng được app.
6. Không cần tạo tài khoản trong Supabase: **mỗi người quản lý tự tạo tài khoản trong app** (trang đăng nhập → **Tạo tài khoản quản lý**). Sau khi xác nhận email và đăng nhập, dashboard hiện **link nhận yêu cầu riêng** để gửi cho người giao việc.
7. Cấu hình SMTP cho email xác nhận/đặt lại mật khẩu khi chia sẻ cho người dùng thật (email mặc định của Supabase chỉ gửi được vài email mỗi giờ). Dịch vụ email Auth này tách biệt với email bàn giao qua Resend.
8. Nếu sau này muốn **khóa đăng ký mới**: Authentication → Sign In / Providers → tắt **Allow new users to sign up**. Người quản lý đã có tài khoản vẫn dùng bình thường.

Các bảng đã bật RLS và không cấp quyền truy cập trực tiếp cho anon/authenticated. Mọi thao tác dữ liệu đi qua API máy chủ, xác minh token người dùng với Supabase Auth trước. Không thêm policy công khai để “sửa” lỗi quyền.

## 3. Tạo GitHub repo

Bạn có thể dùng nút **Upload files**, nhưng Git thường giữ cấu trúc và file cấu hình đầy đủ hơn.

1. Tạo repository mới trên https://github.com (có thể để Private).
2. Không thêm README/.gitignore mặc định vì bộ code đã có.
3. Cài Git nếu máy chưa có. Trong terminal tại thư mục `flowtime-github`, chạy:

```bash
git init
git add .
git commit -m "Build Flowtime task management app"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/flowtime.git
git push -u origin main
```

Thay `YOUR_USERNAME/flowtime` bằng repo của bạn. Đăng nhập GitHub khi Git yêu cầu. **Không nhập access token trong câu lệnh hoặc commit nó.**

Nếu dùng giao diện upload: upload **nội dung bên trong** `flowtime-github` vào root repo; `app.py`, `requirements.txt`, `vercel.json`, `flowtime/`, `public/`, `supabase/` phải cùng cấp. Đảm bảo `.gitignore` và `.python-version` cũng được đưa lên. File `.env` và thư mục `.venv` luôn giữ ngoài repo.

## 4. Deploy bằng Vercel

1. Đăng nhập https://vercel.com bằng tài khoản của bạn.
2. Chọn **Add New → Project → Import Git Repository**, chọn repo Flowtime.
3. Framework Preset: **Flask** (Vercel thường tự nhận ra nhờ `app.py` + `requirements.txt`).
4. Root Directory: thư mục chứa `app.py` (root nếu upload đúng).
5. Build Command và Output Directory: **để trống, không ghi đè**. Vercel tự cài `requirements.txt` và phục vụ thư mục `public/` qua CDN.
6. Phiên bản Python lấy từ file `.python-version` (3.12).
7. **Nếu bạn đã có dự án Vercel từ bản Node 2.x:** vào Project → Settings → Build & Deployment, đổi Framework Preset sang **Flask**, tắt ghi đè Build Command (`npm run build`) và Output Directory (`public`), rồi Redeploy. Biến môi trường giữ nguyên.
8. Thêm Environment Variables:

| Tên | Giá trị |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_ANON_KEY` | Khóa anon/publishable |
| `SUPABASE_SERVICE_ROLE_KEY` | Khóa service_role bí mật |
| `APP_URL` | URL Vercel dự kiến của dự án, sau đó sửa đúng URL được cấp |
| `OPENAI_API_KEY` | Khóa OpenAI API của bạn |
| `OPENAI_MODEL` | `gpt-4.1-mini`, hoặc model tương thích trong tài khoản |
| `AI_DAILY_LIMIT` | Tổng số lượt AI mỗi ngày cho **tất cả** người quản lý, ví dụ `300` (bảo vệ chi phí OpenAI) |

9. Bấm **Deploy**. Nếu chưa biết chính xác URL trước lần deploy đầu, cập nhật `APP_URL` ngay sau đó và **Redeploy** trước khi cho người khác đăng nhập.
10. URL mặc định dạng `https://ten-du-an.vercel.app`, không có chữ chatgpt. Tên thực tế phụ thuộc tính khả dụng và tài khoản của bạn.

Vercel chạy toàn bộ ứng dụng Flask (`app.py`) như một hàm máy chủ. Không chuyển riêng `public/` sang GitHub Pages rồi mong API vẫn chạy.

**Phương án thay thế: Render.** Repo có sẵn `render.yaml` (chạy bằng gunicorn). Trên https://render.com chọn **New → Blueprint**, chọn repo, nhập các biến môi trường như bảng trên. Render không chạy cron trong cấu hình này; để có email nhắc hạn, dùng GitHub Actions (xem mục 7).

## 5. Hoàn thiện cấu hình đăng nhập

Trong Supabase **Authentication → URL Configuration**:

- Site URL: URL production của bạn, ví dụ `https://ten-du-an.vercel.app`.
- Redirect URLs: thêm URL production hợp lệ và `http://localhost:3000` nếu cần thử local.
- Khi đổi tên miền, cập nhật Site URL, Redirect URLs và `APP_URL`, sau đó redeploy.

Thử:

1. Vào `/#login` → **Tạo tài khoản quản lý** → mở email xác nhận → đăng nhập → dashboard hiện ô **Link nhận yêu cầu của bạn**.
2. Bấm **Sao chép link**, mở link đó ở tab ẩn danh (không đăng nhập) → trang ghi “Gửi yêu cầu cho <tên bạn>” → gửi một yêu cầu → nhận **đường dẫn theo dõi**.
3. Bạn tải lại dashboard → phải thấy việc vừa gửi.
4. Tạo **tài khoản quản lý thứ hai** (email khác) → dashboard của tài khoản này **không** thấy việc của bạn.
5. Mở đường dẫn theo dõi ở tab ẩn danh → thấy trạng thái và trao đổi, **không** thấy thời lượng, ghi chú riêng hay việc khác.
6. Đổi một ký tự trong đường dẫn theo dõi → phải báo đường dẫn không hợp lệ.
7. Thử Quên mật khẩu → email → đặt mật khẩu mới.

**Gửi link cho người giao việc:** mỗi người quản lý gửi **link riêng** của mình (dạng `https://ten-du-an.vercel.app/#request/ma-cua-ban`). Người giao việc không cần tài khoản. Nếu họ chỉ mở địa chỉ app, trang sẽ hỏi **mã người quản lý** (phần cuối link). Có thể đổi mã trong dashboard (**Đổi mã**); link cũ sẽ ngừng hoạt động.

App tự kiểm tra phiên khoảng mỗi phút khi người dùng không đang nhập form hoặc mở hộp thoại. Có nút ↻ để tải lại ngay.

## 6. Kết nối AI

1. Tạo khóa ở https://platform.openai.com/api-keys bằng tài khoản của bạn; cấu hình billing/hạn mức theo tài khoản.
2. Nhập `OPENAI_API_KEY` ở Vercel Environment Variables (server only), không dán vào giao diện app.
3. Redeploy.
4. Trong giao diện người giao việc, thử một yêu cầu nhỏ qua chat. Kiểm tra bản nháp rồi mới gửi.
5. Trong quản lý, mở việc → **AI ước tính** → xem khoảng/giả định → **Dùng mức giữa khoảng AI đề xuất** → **Lưu kế hoạch**.
6. Trong **Trợ lý & báo cáo**, bấm **Phân tích & đề xuất**.

Kết quả AI không tự áp dụng. Trong giai đoạn đầu, lịch sử ít nên bạn cần hiệu chỉnh ước tính. Chỉ bấm phân tích khi đồng ý gửi nội dung liên quan tới dịch vụ AI. Giới hạn lượt theo tài khoản đã được thực thi trong DB, nhưng vẫn nên đặt ngân sách dịch vụ.

## 7. Email bàn giao và nhắc hạn

Nếu chưa cần email tự động, có thể bỏ bước này và dùng sao chép/mở ứng dụng email.

1. Tạo tài khoản https://resend.com.
2. Thêm và xác minh tên miền gửi bằng DNS theo hướng dẫn của Resend.
3. Thêm vào Vercel:
   - `RESEND_API_KEY`.
   - `EMAIL_FROM`, ví dụ `Flowtime <notifications@yourdomain.com>`.
   - `CRON_SECRET`: chuỗi ngẫu nhiên dài ít nhất 32 ký tự.

   Email nhắc hạn được gửi tới **email tài khoản của từng người quản lý**, mỗi người chỉ nhận việc của mình.
4. Tạo secret trong terminal nếu cần:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

5. Redeploy.
6. Hoàn thành một việc, nhập kết quả, chuyển **Chờ duyệt** → **Soạn email bàn giao** → xem trước → **Xác nhận gửi email**.
7. Kiểm tra mục Cron Jobs của dự án Vercel và log lần chạy.

`vercel.json` đặt lịch `0 0 * * *`: **00:00 UTC hằng ngày, tương ứng 07:00 tại Việt Nam**. Thời điểm thực thi cụ thể có thể phụ thuộc gói nền tảng. Email tổng hợp việc quá hạn và đến hạn trong 24 giờ; **không phải** nhắc chính xác 15 phút trước từng deadline.

Muốn nhắc dày hơn, kiểm tra gói Vercel hỗ trợ rồi điều chỉnh cron.

**Nếu không dùng Vercel (ví dụ Render):** dùng workflow có sẵn `.github/workflows/deadline-digest.yml`. Trong GitHub repo → Settings → Secrets and variables → Actions: thêm Variable `FLOWTIME_URL` (ví dụ `https://flowtime.onrender.com`, không có dấu `/` cuối) và Secret `CRON_SECRET` (giống giá trị trên máy chủ). Khi chưa đặt `FLOWTIME_URL`, workflow không làm gì. Email nhắc có khóa chống gửi lặp theo ngày. Endpoint chỉ chấp nhận header `Authorization: Bearer <CRON_SECRET>`; không đưa secret vào query string hay frontend.

## 8. Tên miền riêng

1. Mua tên miền bạn muốn từ nhà đăng ký phù hợp.
2. Trong Vercel → Project → Settings → Domains, thêm tên miền.
3. Tạo DNS records đúng giá trị Vercel trả về; không dùng một IP mẫu cố định trong tài liệu này.
4. Khi xác minh xong, cập nhật `APP_URL` và Supabase Auth URLs sang tên miền mới, redeploy.

Mua tên miền không bắt buộc. Bạn có thể dùng địa chỉ `vercel.app` trước.

## 9. Checklist staging trước khi mời người dùng

- [ ] `python -m pytest -q` đạt.
- [ ] SQL schema chạy thành công, không mở quyền bảng công khai.
- [ ] Tài khoản của bạn có dashboard quản lý, tài khoản khác không có.
- [ ] Hai người gửi ở hai trình duyệt khác nhau chỉ thấy yêu cầu của riêng mình.
- [ ] Tiếp nhận, đổi deadline, trao đổi và duyệt kết quả đồng bộ giữa hai máy.
- [ ] Bắt đầu cùng lúc từ hai tab: chỉ một session đang chạy trong bảng `sessions`.
- [ ] Chuyển sang Chờ phối hợp/Chờ duyệt sẽ dừng timer.
- [ ] Roadmap tránh một lịch bận nằm giữa 15 phút và tránh nghỉ trưa/cuối tuần.
- [ ] AI parse/estimate/advice hoạt động thật; khóa không xuất hiện trong DevTools response/config hoặc repo.
- [ ] Email Auth, quên mật khẩu, bàn giao và cron đến đúng địa chỉ.
- [ ] Mở điện thoại: nhập yêu cầu, xem chi tiết và đăng xuất hoạt động.
- [ ] Sao lưu cơ sở dữ liệu và cấu hình giới hạn chi phí trên các nhà cung cấp.

## Khắc phục thường gặp

| Triệu chứng | Cách kiểm tra |
|---|---|
| Chỉ thấy demo, nút đăng nhập bị khóa | Kiểm tra bốn biến Supabase/Manager UUID, redeploy |
| Đăng nhập được nhưng không phải quản lý | UUID phải trùng Auth User ID, không dùng email |
| Không thấy email xác nhận | Supabase SMTP, spam, Site URL, giới hạn gửi Auth |
| Lỗi đọc/lưu dữ liệu | Schema đã chạy chưa, khóa service_role đúng dự án chưa |
| AI báo chưa kết nối | OPENAI_API_KEY, billing, OPENAI_MODEL tương thích, redeploy |
| `/api/index?route=config` trả HTML hoặc 404 | Deploy nguyên repo; Framework Preset là Flask; không ghi đè Build/Output Directory; xem log build có cài `requirements.txt` |
| `python` không được nhận ra trên Windows | Cài lại Python và đánh dấu “Add python.exe to PATH”, mở lại VS Code |
| Lỗi `ModuleNotFoundError: flask` | Chưa kích hoạt `.venv` hoặc chưa chạy `pip install -r requirements-dev.txt` |
| Không gửi được bàn giao | Tên miền Resend đã xác minh, EMAIL_FROM đúng, khóa hợp lệ |
| Không có nhắc khi đóng app | Cron production đã bật, CRON_SECRET/RESEND_API_KEY/EMAIL_FROM đã đặt, log cron |
| Người giao việc báo “Không tìm thấy người quản lý” | Kiểm tra mã trong link khớp với mã ở dashboard; nếu vừa đổi mã, gửi lại link mới |

Bộ mã chưa tự tạo tài khoản dịch vụ, chưa đẩy vào GitHub của bạn và chưa deploy Vercel. Bạn có toàn bộ source để triển khai theo tài khoản/tên miền của mình.
