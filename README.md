# 🤖 Project: Marketing Flow Automation (MFA)

Đây là một dự án full-stack (FastAPI + Streamlit) được thiết kế để tự động hóa các quy trình marketing phức tạp, từ phân tích nội dung, chỉnh sửa video, đến quản lý đăng tải và báo cáo hiệu suất.

Hệ thống này sử dụng Google Sheets làm cơ sở dữ liệu chính và tích hợp mạnh mẽ với **n8n** để xử lý các tác vụ nền.

## 🏛️ Kiến trúc tổng quan

Dự án này bao gồm hai phần chính:

* **`backend` (FastAPI):** Một máy chủ API mạnh mẽ xử lý tất cả các tác vụ nặng:
    * Tải video (`yt-dlp`).
    * Phiên âm (Transcription) bằng `faster-whisper`.
    * Phân tích và sửa lỗi AI (`google-gemini`).
    * Xử lý video (cắt, nối, hardsub) bằng `ffmpeg`.
    * Giao tiếp với Google Sheets và Dropbox.
    * Quản lý hàng đợi (job queue) cho các tác vụ nền.

* **`frontend` (Streamlit):** Một dashboard tương tác cho phép người dùng:
    * Kích hoạt các quy trình.
    * Xem và chỉnh sửa phụ đề.
    * Tạo video remix.
    * Quản lý lịch đăng.
    * Xem báo cáo.

* **Các dịch vụ bên ngoài:**
    * **Google Sheets:** Đóng vai trò là cơ sở dữ liệu (lưu trữ phụ đề, highlights, trạng thái đăng bài, dữ liệu báo cáo).
    * **n8n:** Xử lý các quy trình tự động (auto-posting lên Facebook/Instagram, thu thập dữ liệu báo cáo).
    * **Dropbox:** Lưu trữ các file video đã chỉnh sửa.



[Image of full-stack application architecture diagram]


## ✨ Tính năng chính

Dashboard được chia thành 4 công cụ (tabs) chính:

### 1. Phân tích Video Tiktok

* **Mô tả:** Người dùng cung cấp URL TikTok và Keyword.
* **Hành động:** Hệ thống tải video, chạy phiên âm (Whisper), gửi bản thô cho AI (Gemini) sửa lỗi, và lưu bản đã sửa vào Google Sheet (Tab `Source Phân tích Video`).
* **Webhook:** Kích hoạt n8n để chạy phân tích AI (ví dụ: tạo "Điểm mạnh", "Điểm yếu").

### 2. Chỉnh sửa Video

* **Mô tả:** Một quy trình 2 bước để tạo video remix.
* **Bước 1 (Phân tích):** Giống như Tool 1, nhưng lưu vào tab `Source Chỉnh sửa Video` và AI (Gemini) sẽ tìm các "Highlights" (đoạn hay).
* **Bước 2 (Tạo video):** Người dùng chọn các tùy chọn (Remix từ highlights, thêm nhạc nền, hardsub, lật video). Hệ thống sẽ dùng `ffmpeg` để tạo video cuối cùng, tải lên Dropbox, và cập nhật link vào Google Sheet.

### 3. Đăng tải Đa nền tảng

* **Mô tả:** Giao diện đọc Google Sheet (Tab `MVP_Content_Plan`) và hiển thị 3 danh sách: "Chờ xử lý", "Đã đăng", "Bị lỗi".
* **Hành động:** Khi người dùng tick vào "Ready", giao diện sẽ gọi backend. Backend sẽ kích hoạt webhook n8n (Tool 3) để bắt đầu quy trình đăng bài.
* **Polling:** Giao diện sẽ tự động poll (kiểm tra) backend mỗi 10 giây để xem n8n đã hoàn thành chưa. Khi hoàn tất, nó sẽ tự động làm mới để hiển thị link (nếu có).

### 4. Báo cáo Hiệu suất

* **Mô tả:** Một dashboard chỉ đọc (read-only) để trực quan hóa dữ liệu từ tab "Engagement" trên Google Sheet.
* **Hành động:** Người dùng bấm "Kích hoạt n8n" để yêu cầu n8n thu thập dữ liệu mới. n8n chạy nền (mất vài phút) và cập nhật vào "Engagement".
* **Polling:** Giao diện poll backend để biết khi nào n8n làm xong, sau đó tự động tải dữ liệu mới về và vẽ biểu đồ (KPIs, Lượt xem, Tương tác, Tỷ lệ giữ chân).

## 🚀 Cài đặt và Cấu hình

### Điều kiện tiên quyết

* Python 3.10+
* `ffmpeg` (phải được cài đặt trên hệ thống và thêm vào biến môi trường PATH)
* Tài khoản Google Cloud (với file JSON credentials cho Google Sheets & Gemini API).
* Tài khoản Dropbox (với Access Token).
* Một hệ thống n8n đang chạy (để nhận webhook).

### Hướng dẫn tải ffmpeg

Cài đặt FFmpeg (Bắt buộc cho video):
Hệ thống này yêu cầu ffmpeg và ffprobe để xử lý mọi tác vụ video (tạo phụ đề, lật video, trộn âm thanh).

Truy cập ffmpeg.org/download.html và tải về bản build cho Windows (thường được khuyên dùng là từ gyan.dev).

Tải bản "essentials" build (ví dụ: ffmpeg-7.0.1-essentials_build.zip).

Giải nén file zip vào một thư mục cố định (ví dụ: E:\tools\ffmpeg\).

Đường dẫn bạn cần sẽ trỏ vào thư mục bin bên trong, ví dụ: E:\tools\ffmpeg\bin\ffmpeg.exe và E:\tools\ffmpeg\bin\ffprobe.exe.

### 1. Backend (FastAPI)

1.  Di chuyển vào thư mục `backend`:
    ```bash
    cd backend
    ```

2.  Tạo và kích hoạt môi trường ảo:
    ```bash
    # Windows
    python -m venv .venv
    .\.venv\Scripts\activate
    
    # macOS / Linux
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  Cài đặt các thư viện trong `backend`:
    ```
    chạy:
    ```bash
    pip install -r requirements.txt
    ```

4.  Tạo tệp `.env` trong thư mục `backend` và điền các biến môi trường:
    ```ini
    # API Key của Google Gemini
    GEMINI_API_KEY="AIz..."
    
    # (Lựa chọn 1) Đường dẫn đến file service account .json của Google
    GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your-google-credentials.json"
    
    # (Lựa chọn 2) Thay thế token cứng trong media.py bằng biến này
    DROPBOX_ACCESS_TOKEN="sl.u.A..."
    
    # (Tùy chọn) Nếu ffmpeg không nằm trong PATH
    FFMPEG_BIN="C:\ffmpeg\bin\ffmpeg.exe"
    ```

### 2. Frontend (Streamlit)

1.  Mở một cửa sổ dòng lệnh (terminal) **mới**.

2.  Di chuyển vào thư mục `frontend`:
    ```bash
    cd frontend
    ```

3.  Cài đặt các thư viện trong `frontend`:
    chạy:
    ```bash
    pip install -r requirements-frontend.txt
    ```

## 🏃 Cách chạy

Bạn cần chạy 2 máy chủ song song trên 2 cửa sổ terminal riêng biệt.

### Terminal 1: Chạy Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8080
```
### Terminal 2: Chạy Frontend
```bash
cd frontend
streamlit run dashboard.py
```
