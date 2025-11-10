Marketing Flow Automation

Dự án này là một hệ thống backend (sử dụng FastAPI) và frontend (sử dụng React) được thiết kế để tự động hóa các tác vụ marketing. Nó kết hợp phân tích đối thủ, nghiên cứu từ khóa, phân tích video viral, và một studio xử lý video mạnh mẽ sử dụng AI để tạo phụ đề và tùy chỉnh âm thanh.

Các tính năng chính

Phân tích MVP (All-in-One):

Input: Một URL (trang web, TikTok) và một Từ khóa chính.

Output: Một báo cáo đầy đủ bao gồm:

Phân tích SEO/nội dung của URL (sử dụng Gemini).

Dữ liệu Google Trends cho từ khóa (sử dụng pytrends).

Một bản nháp nội dung (bài đăng, outline blog) do Gemini tạo ra.

Studio Xử lý Video (Thông qua Job Polling):

Phiên âm (Transcription): Tự động tạo phụ đề cho video bằng faster-whisper.

Đốt phụ đề (Hardsub): Ghi đè phụ đề trực tiếp lên video (tùy chọn).

Xử lý âm thanh (BGM):

Thay thế: Xóa âm thanh gốc và thay bằng nhạc nền (BGM) mới.

Trộn (Audio Ducking): Giữ lại giọng nói và tự động giảm âm lượng BGM khi có người nói (sử dụng sidechaincompress).

Lật Video (Flip): Lật video theo chiều ngang (trái sang phải).

Hệ thống Job (Job System): Xử lý các video dài (ví dụ: 5 phút) một cách đáng tin cậy bằng cách sử dụng BackgroundTasks và cơ chế polling (hỏi thăm) từ frontend, tránh bị timeout.

Phân tích Video Viral (TikTok):

Tải video từ link TikTok (sử dụng yt-dlp).

Tách file âm thanh gốc (MP3/WAV).

Phân tích video và chia thành các "cảnh" (scene) với dấu thời gian (timestamp).

Tích hợp Google Sheets:

Tự động xuất kết quả phân tích MVP sang một Google Sheet được chỉ định.

Công nghệ sử dụng

Backend:

FastAPI: Framework API Python.

Uvicorn: Server ASGI.

Frontend:

React.js

AI & Media Processing:

google-generativeai: Dành cho phân tích và sáng tạo nội dung (Gemini).

faster-whisper: Dành cho phiên âm (transcription) đa ngôn ngữ, tốc độ cao.

ffmpeg: Công cụ cốt lõi cho mọi tác vụ xử lý video và âm thanh (lật, trộn, đốt phụ đề).

opencv-python: Dành cho phân tích cảnh (scene analysis).

Data & APIs:

yt-dlp: Tải video từ TikTok và các nền tảng khác.

playwright: Crawl các trang web nặng về JavaScript.

beautifulsoup4: Phân tích (parse) HTML.

pytrends: Lấy dữ liệu Google Trends.

gspread-asyncio: Tương tác bất đồng bộ với Google Sheets.

Cài đặt và Chạy

Dự án được chia thành hai phần: backend và frontend.

1. Backend (FastAPI)

Clone dự án:

git clone [URL_REPOSITORY_CUA_BAN]
cd [TEN_THU_MUC_DU_AN]/backend


Tạo môi trường ảo (virtual environment):

python -m venv .venv
source .venv/bin/activate  # Trên macOS/Linux
.\.venv\Scripts\activate   # Trên Windows (PowerShell)


Cài đặt các thư viện Python:
(Sử dụng file requirements.txt đã được cung cấp)

pip install -r requirements.txt


Cài đặt trình duyệt Playwright (Bắt buộc):
Thư viện playwright cần tải về các trình duyệt.

playwright install


Cài đặt FFmpeg (Bắt buộc cho video):
Hệ thống này yêu cầu ffmpeg và ffprobe để xử lý mọi tác vụ video (tạo phụ đề, lật video, trộn âm thanh).

Trên Windows:

Truy cập ffmpeg.org/download.html và tải về bản build cho Windows (thường được khuyên dùng là từ gyan.dev).

Tải bản "essentials" build (ví dụ: ffmpeg-7.0.1-essentials_build.zip).

Giải nén file zip vào một thư mục cố định (ví dụ: E:\tools\ffmpeg\).

Đường dẫn bạn cần sẽ trỏ vào thư mục bin bên trong, ví dụ: E:\tools\ffmpeg\bin\ffmpeg.exe và E:\tools\ffmpeg\bin\ffprobe.exe.

Trên macOS (sử dụng Homebrew):

brew install ffmpeg


Trên Linux (sử dụng apt):

sudo apt update && sudo apt install ffmpeg


Nếu bạn cài đặt trên macOS hoặc Linux, ffmpeg thường sẽ tự động được thêm vào PATH hệ thống, bạn có thể không cần cấu hình FFMPEG_BIN trong bước tiếp theo.

Cấu hình Môi trường (.env):
Tạo một file tên là .env trong thư mục backend và điền các giá trị:

# API Keys
GEMINI_API_KEY="AIza..."

# Đường dẫn đến file service account JSON của Google
# (Bắt buộc cho Google Sheets)
GOOGLE_APPLICATION_CREDENTIALS="duong/dan/den/file-credentials.json"

# Đường dẫn tuyệt đối đến file ffmpeg.exe và ffprobe.exe
# (Rất quan trọng cho việc xử lý video, đặc biệt trên Windows)
FFMPEG_BIN="E:\tools\ffmpeg\bin\ffmpeg.exe"
FFPROBE_BIN="E:\tools\ffmpeg\bin\ffprobe.exe"

# Tùy chọn (Tắt các tính năng để debug)
# MFA_LLM_OFF="1"         # Tắt các cuộc gọi đến Gemini
# MFA_TRENDS_OFF="1"      # Tắt các cuộc gọi đến Google Trends
# MFA_TIKTOK_RENDER="1"   # Bật Playwright để crawl TikTok (chậm hơn)


Chạy server backend:

uvicorn app.main:app --reload --port 8080


Server sẽ chạy tại http://localhost:8080.

2. Frontend (React)

Mở một terminal mới và đi đến thư mục frontend:

cd ../frontend


Cài đặt các gói Node.js:

npm install


Cấu hình Môi trường (.env.local):
Tạo một file .env.local trong thư mục frontend để nó biết địa chỉ backend:

NEXT_PUBLIC_API="http://localhost:8080"


Chạy server frontend:

npm run dev


Ứng dụng sẽ chạy tại http://localhost:3000.

Tổng quan API Endpoints

Đây là các endpoint chính được định nghĩa trong app/main.py:

POST /mvp/run: Chạy phân tích MVP (URL + Keyword) đầy đủ.

POST /video/viral-analyze: Phân tích một link TikTok.

POST /process: Endpoint chính (Job). Bắt đầu một tác vụ xử lý video (sub, BGM, lật). Trả về một job_id.

GET /process/status/{job_id}: Endpoint Polling. Frontend dùng để kiểm tra trạng thái của job xử lý.

GET /keywords: Chỉ lấy dữ liệu từ khóa.

POST /analyze/url: Chỉ phân tích một URL.

POST /export/sheet: Chỉ xuất dữ liệu sang Google Sheets.

GET /health: Kiểm tra xem server có đang chạy không.

GET /debug/ffmpeg: Kiểm tra xem ffmpeg đã được cấu hình đúng chưa.
