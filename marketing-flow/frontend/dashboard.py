import streamlit as st
import requests
import time
import os
import json
import pandas as pd
import re # Thêm re để xử lý text

# URL backend FastAPI của bạn
API_URL = "http://localhost:8080"

# --- GIAO DIỆN CHÍNH ---
st.set_page_config(
    layout="wide",
    page_title="Video Dashboard",
    page_icon="🎬"
)

# === ĐỊNH NGHĨA CSS TỶ LỆ 16:9 (DÙNG CHUNG) ===
video_style_16_9 = """
<style>
/* Định nghĩa khung bọc 16:9 cho video ngang */
.video-wrapper-16_9 {
    position: relative;
    padding-bottom: 56.25%; /* 16:9 Aspect Ratio (9 / 16 = 0.5625) */
    height: 0;
    overflow: hidden;
    max-width: 100%; /* Dãn hết chiều rộng của cột main_col */
    margin: 10px auto; /* Căn giữa và thêm margin */
    border-radius: 10px; /* Bo góc */
    background: #000; /* Nền đen phòng khi video load chậm */
}
.video-wrapper-16_9 video {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
}
</style>
"""
st.markdown(video_style_16_9, unsafe_allow_html=True)
# === KẾT THÚC CSS ===


# --- HÀM TẢI LẠI DỮ LIỆU SHEET (DÙNG CHUNG) ---
def refresh_sheet_data(sheet_name, state_key):
    """
    Hàm chung để gọi API và tải lại dữ liệu cho một sheet cụ thể vào session_state.
    """
    try:
        with st.spinner(f"Đang tải dữ liệu từ sheet '{sheet_name}'..."):
            res = requests.get(f"{API_URL}/export/sheet/read", params={"sheet_name": sheet_name})
            if res.status_code == 200:
                st.session_state[state_key] = res.json().get('data', [])
                st.toast(f"Tải lại dữ liệu sheet '{sheet_name}' thành công!", icon="✅")
            else:
                st.error(f"Lỗi đọc Sheet '{sheet_name}': {res.text}")
    except Exception as e:
        st.error(f"Lỗi kết nối API: {e}")

# --- TÍNH NĂNG (TICK GOOGLE SHEET) ---
# (Phiên bản đơn giản, không polling, đã sửa lỗi `rerun`)
def handle_tick(row_gspread, col_gspread, key, column_name, video_title):
    """
    Gửi yêu cầu cập nhật đến API /export/sheet/update-cell
    VÀ GỌI WEBHOOK NẾU LÀ NÚT 'READY'
    VÀ TẢI LẠI DỮ LIỆU 1 LẦN
    """
    new_value = st.session_state[key]
    
    st.toast(f"Đang cập nhật Hàng {row_gspread}, Cột {col_gspread} ({column_name}) thành {new_value}...")
    
    try:
        payload = {"row": row_gspread, "col": col_gspread, "value": new_value}
        res = requests.post(f"{API_URL}/export/sheet/update-cell", json=payload)
        
        if res.status_code == 200:
            st.toast("✅ Cập nhật Google Sheet thành công!", icon="✅")
            
            # --- GỌI WEBHOOK KHI TICK 'READY' ---
            if column_name == "ready" and new_value is True:
                st.toast("Đang kích hoạt Webhook...")
                try:
                    # LƯU Ý: ĐÂY LÀ WEBHOOK CỦA BẠN, GIỮ NGUYÊN
                    WEBHOOK_URL = "https://partible-terese-homocercal.ngrok-free.dev/webhook/e59036d3-dd92-45b6-9b14-cc2e4db45b05"
                    webhook_payload = {
                        "row_index": row_gspread,
                        "title": video_title,
                        "event": "ready_for_processing"
                    }
                    wh_res = requests.post(WEBHOOK_URL, json=webhook_payload, timeout=5)
                    
                    if wh_res.status_code == 200:
                        st.toast("🚀 Webhook đã kích hoạt! n8n đang xử lý...", icon="🎉")
                    else:
                        st.warning(f"Webhook response: {wh_res.status_code} - {wh_res.text}")
                
                except Exception as wh_e:
                    st.error(f"Lỗi khi gọi Webhook: {wh_e}")
            # --- KẾT THÚC GỌI WEBHOOK ---

            # Tải lại sheet NGAY LẬP TỨC để lưu checkbox
            # (Người dùng sẽ phải bấm "Làm mới" sau để lấy link)
            refresh_sheet_data("MVP_Content_Plan", "sheet_data")
            
        else:
            st.error(f"Lỗi cập nhật Sheet: {res.text}")
            st.session_state[key] = not new_value 
            
    except Exception as e:
        st.error(f"Lỗi kết nối API: {e}")
        st.session_state[key] = not new_value

# --- [CẢI TIẾN] CÁC HÀM HELPER ĐỂ HIỂN THỊ N8N ---
def _find_key_in_dict(data_dict, potential_keys):
    """
    Hàm helper tìm key trong dict, không phân biệt chữ hoa/thường/dấu cách/gạch dưới.
    """
    if not isinstance(data_dict, dict):
        return None
        
    for key in data_dict:
        normalized_key = str(key).lower().replace(" ", "").replace("_", "")
        if normalized_key in potential_keys:
            return data_dict[key]
    return None

def _format_text_as_markdown_list(text_content):
    """
    Hàm helper để chuyển một chuỗi văn bản (string)
    có chứa dấu '•' thành một danh sách Markdown (list)
    được định dạng đẹp.
    """
    if not text_content:
        return ""
    
    # Tách chuỗi dựa trên ký tự bullet '•'
    parts = re.split(r'•', text_content)
    
    markdown_list = []
    for part in parts:
        part_trimmed = part.strip()
        if part_trimmed: # Bỏ qua các chuỗi rỗng
            # Thêm dấu * và một dấu cách
            markdown_list.append(f"* {part_trimmed}")
            
    return "\n".join(markdown_list)

# --- [CẢI TIẾN] HÀM HIỂN THỊ N8N (TAB 1) ---
def render_n8n_analysis(analysis_data):
    """
    Hiển thị kết quả phân tích AI (dưới dạng một chuỗi lớn) từ n8n.
    [CẢI TIẾN 3.0] Tự động format '•' thành Markdown list.
    """
    if not isinstance(analysis_data, dict):
        st.caption("Không có dữ liệu phân tích AI (n8n).")
        return

    analysis_content = _find_key_in_dict(
        analysis_data, 
        ["phântíchvideo", "analysis"]
    )

    with st.container(border=True):
        st.subheader("🤖 Phân tích AI")
        
        if analysis_content and isinstance(analysis_content, str):
            
            # [CẢI TIẾN UI/UX]
            parts = re.split(
                r'((?:❌|X)\s*ĐIỂM YẾU:|(?:💡)\s*GỢI Ý CẢI THIỆN:)', 
                analysis_content, 
                flags=re.IGNORECASE
            )
            
            # --- Xử lý ĐIỂM MẠNH (Luôn là phần tử đầu tiên) ---
            part_strong = re.sub(
                r'^(?:✅|✔️)\s*ĐIỂM MẠNH:', '', 
                parts[0], flags=re.IGNORECASE
            ).strip()
            
            if part_strong:
                with st.container(border=True):
                    st.success("✅ ĐIỂM MẠNH")
                    formatted_strong = _format_text_as_markdown_list(part_strong)
                    st.markdown(formatted_strong)

            # --- Xử lý ĐIỂM YẾU VÀ GỢI Ý (Nếu có) ---
            if len(parts) > 1:
                content_map = {}
                current_key = None

                for part in parts[1:]:
                    if re.match(r'(?:❌|X|💡)', part.strip()):
                        if "ĐIỂM YẾU" in part.upper():
                            current_key = "WEAK"
                        elif "GỢI Ý" in part.upper():
                            current_key = "SUGGEST"
                    
                    elif current_key and part.strip():
                        content_map[current_key] = part.strip()
                        current_key = None

                # Hiển thị
                if "WEAK" in content_map:
                    with st.container(border=True):
                        st.error("❌ ĐIỂM YẾU")
                        formatted_weak = _format_text_as_markdown_list(content_map["WEAK"])
                        st.markdown(formatted_weak)
                
                if "SUGGEST" in content_map:
                    with st.container(border=True):
                        st.info("💡 GỢI Ý CẢI THIỆN")
                        formatted_suggest = _format_text_as_markdown_list(content_map["SUGGEST"])
                        st.markdown(formatted_suggest)

        else:
            st.caption("Webhook n8n đã chạy nhưng không trả về dữ liệu phân tích hợp lệ.")
            with st.expander("Xem dữ liệu thô từ n8n (để gỡ lỗi)"):
                st.json(analysis_data)


# --- [CẢI TIẾN] HÀM HIỂN THỊ N8N (TAB 2) ---
def render_n8n_captions(analysis_data):
    """Hiển thị Title và Captions (Tool 2) từ n8n."""
    if not isinstance(analysis_data, dict):
        st.caption("Không có dữ liệu phân tích AI.")
        return

    title = _find_key_in_dict(analysis_data, ["title", "tiêuđề"])
    caption_fb = _find_key_in_dict(analysis_data, ["captionfacebook", "caption_facebook", "captionfb"])
    caption_ig = _find_key_in_dict(analysis_data, ["captioninstagram", "caption_instagram", "captionig"])
    
    has_valid_data = (title or caption_fb or caption_ig)

    with st.container(border=True):
        st.subheader("Gợi ý Nội dung")
        
        if not has_valid_data:
            st.caption("Webhook n8n đã chạy nhưng không trả về dữ liệu Title/Caption.")
        else:
            
            if title:
                with st.container(border=True):
                    st.markdown("##### Tiêu đề (Title)")
                    st.markdown(title)
            
            if caption_fb:
                with st.container(border=True):
                    st.markdown("##### Caption Facebook")
                    st.markdown(caption_fb)
            
            if caption_ig:
                with st.container(border=True):
                    st.markdown("##### Caption Instagram")
                    st.markdown(caption_ig)


# --- [SỬA LỖI] THAY THẾ st.tabs BẰNG st.radio ĐỂ GIỮ TRẠNG THÁI ---
tab_options = [
    "1. Phân tích Video Tiktok", 
    "2. Chỉnh sửa Video",
    "3. Đăng tải Đa nền tảng",
    "4. Báo cáo Hiệu suất"
]

# === [CẢI TIẾN] CĂN GIỮA NAVBAR ===
_, nav_col, _ = st.columns([0.5, 3, 0.5])

with nav_col:
    active_tab_key = st.radio(
        "Điều hướng:", 
        options=tab_options, 
        horizontal=True, 
        label_visibility="collapsed",
        key="active_tab" # Đây là chìa khóa để lưu trạng thái
    )
# === KẾT THÚC SỬA LỖI ===


# ==========================================================
# ===== TÍNH NĂNG 1: PHÂN TÍCH TIKTOK  =====
# ==========================================================
if active_tab_key == "1. Phân tích Video Tiktok":
    # === CĂN GIỮA TOÀN BỘ TAB ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        st.header("Phân tích Video TikTok")
        
        tt_url = st.text_input("Dán URL video TikTok", key="tt_url")
        tt_keyword = st.text_input("Nhập Keyword", key="tt_keyword")
        
        language = st.selectbox(
            "Chọn ngôn ngữ của video",
            options=["vi", "en", "auto"],
            index=0,
            format_func=lambda x: "Tiếng Việt" if x == "vi" else ("Tiếng Anh" if x == "en" else "Tự động phát hiện"),
            key="tt_lang"
        )
        
        if st.button("Phân tích Video"):
            
            if not tt_url or not tt_keyword:
                st.warning("Vui lòng nhập cả URL TikTok và Keyword.")
            else:
                with st.spinner("Đang tải..."):
                    try:
                        params = {
                            "url": tt_url, 
                            "language": language,
                            "keyword": tt_keyword,
                            "target_sheet": "Source Phân tích Video",
                            "n8n_webhook_url": "https://partible-terese-homocercal.ngrok-free.dev/webhook/a7b4c66d-f180-4439-a36d-96bce1e27bd0"
                        }
                        res = requests.post(f"{API_URL}/video/viral-analyze", params=params, timeout=300)
                        
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state['tt_analysis_result'] = data # Lưu kết quả
                            st.success("Phân tích thành công! Dữ liệu đã được lưu vào Google Sheet.")
                        
                        else:
                            st.error(f"Lỗi API: {res.text}")
                            st.session_state.pop('tt_analysis_result', None)

                    except requests.exceptions.ReadTimeout:
                        st.error("Lỗi: Yêu cầu hết thời gian (Timeout). Tác vụ phân tích này tốn nhiều thời gian hơn dự kiến. Vui lòng thử lại với video ngắn hơn.")
                    except Exception as e:
                        st.error(f"Lỗi kết nối: {e}")
                        st.session_state.pop('tt_analysis_result', None)

        # --- Hiển thị kết quả (nếu có) từ session_state ---
        if 'tt_analysis_result' in st.session_state:
            data = st.session_state['tt_analysis_result']
            
            st.subheader("Kết quả phân tích")
            
            source_url = data.get('source_url')
            if source_url:
                st.caption(f"Nguồn: {source_url}")
            
            video_url = data.get('video_url')
            
            if video_url:
                video_url_full = f"{API_URL}{video_url}"
                video_html = f"""
                <div class="video-wrapper-16_9">
                    <video controls>
                        <source src="{video_url_full}" type="video/mp4">
                        Trình duyệt của bạn không hỗ trợ video này.
                    </video>
                </div>
                """
                st.markdown(video_html, unsafe_allow_html=True)
            
            ai_analysis = data.get('ai_analysis')
            if ai_analysis:
                render_n8n_analysis(ai_analysis) # Gọi hàm render mới

            st.divider()
            


# ==========================================================
# ===== TÍNH NĂNG 2: CHỈNH SỬA VIDEO  =====
# ==========================================================
elif active_tab_key == "2. Chỉnh sửa Video":
    # === CĂN GIỮA TOÀN BỘ TAB ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        st.header("Công cụ chỉnh sửa Video")

        # --- BƯỚC 1: PHÂN TÍCH (Giống Tool 2) ---
        st.subheader("Bước 1: Tải Video")
        
        if 'tt_analysis_done' not in st.session_state:
            st.session_state.tt_analysis_done = False
        if 'tt_analysis_results' not in st.session_state:
            st.session_state.tt_analysis_results = {}

        tt_url = st.text_input("Dán URL video TikTok", key="remix_url")
        tt_keyword = st.text_input("Nhập Keyword (Bắt buộc)", key="remix_keyword")
        language = st.selectbox(
            "Chọn ngôn ngữ của video",
            options=["vi", "en", "auto"],
            index=0,
            format_func=lambda x: "Tiếng Việt" if x == "vi" else ("Tiếng Anh" if x == "en" else "Tự động phát hiện"),
            key="remix_lang"
        )
        
        if st.button("Tải Video"):
            st.session_state.tt_analysis_done = False
            st.session_state.tt_analysis_results = {}
            
            if not tt_url or not tt_keyword:
                st.warning("Vui lòng nhập cả URL TikTok và Keyword.")
            else:
                with st.spinner("Đang tải..."):
                    try:
                        params = {
                            "url": tt_url, 
                            "language": language,
                            "keyword": tt_keyword,
                            "target_sheet": "Source Chỉnh sửa Video",
                            "n8n_webhook_url": "https://partible-terese-homocercal.ngrok-free.dev/webhook/ac438374-32a4-4f72-9043-a9971d21fe8c"
                        }
                        res = requests.post(f"{API_URL}/video/viral-analyze", params=params, timeout=300)
                        
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state.tt_analysis_results = data
                            st.session_state.tt_analysis_done = True
                            st.success("Phân tích thành công! Dữ liệu đã được lưu vào 'Source Phân tích Video'.")
                        else:
                            st.error(f"Lỗi API: {res.text}")

                    except requests.exceptions.ReadTimeout:
                        st.error("Lỗi: Yêu cầu hết thời gian (Timeout).")
                    except Exception as e:
                        st.error(f"Lỗi kết nối: {e}")

        # --- BƯỚC 2: HIỂN THỊ KẾT QUẢ PHÂN TÍCH (NẾU CÓ) ---
        if st.session_state.tt_analysis_done:
            data = st.session_state.tt_analysis_results
            
            source_url = data.get('source_url')
            if source_url:
                st.caption(f"Nguồn: {source_url}")
            
            video_url = data.get('video_url')
            if video_url:
                video_url_full = f"{API_URL}{video_url}"
                video_html = f"""
                <div class="video-wrapper-16_9">
                    <video controls key="{data.get('video_path')}">
                        <source src="{video_url_full}" type="video/mp4">
                    </video>
                </div>
                """
                st.markdown(video_html, unsafe_allow_html=True)

            ai_analysis = data.get('ai_analysis')
            if ai_analysis:
                render_n8n_captions(ai_analysis) # Gọi hàm render mới
            
            st.divider()

            # [SỬA UI/UX] Đổi tiêu đề và bỏ cột 'reason'
            st.subheader("🎬 Phụ đề của Video ") 
            all_segments_data = data.get('all_segments', [])
            
            if not all_segments_data:
                st.info("Không có dữ liệu phụ đề.")
            else:
                # Chuyển sang DataFrame để dễ dàng bỏ cột 'reason'
                df_segments = pd.DataFrame(all_segments_data)
                
                # Kiểm tra xem cột 'reason' có tồn tại không trước khi xóa
                if 'reason' in df_segments.columns:
                    df_segments = df_segments.drop(columns=['reason'])
                
                st.dataframe(df_segments, height=200, use_container_width=True)

            st.subheader("🤖 Highlights do AI chọn")
            ai_highlights_data = data.get('ai_highlights', [])
            if not ai_highlights_data:
                st.info("AI không tìm thấy highlights nào.")
            else:
                st.caption(f"AI đã chọn ra {len(ai_highlights_data)} đoạn hay nhất.")
                for i, scene in enumerate(ai_highlights_data):
                    start_time = scene.get('start_sec', 0.0)
                    end_time = scene.get('end_sec', 0.0)
                    reason = scene.get('reason', 'N/A')
                    text = scene.get('text', 'N/A')
                    start_m, start_s = divmod(start_time, 60)
                    end_m, end_s = divmod(end_time, 60)
                    timestamp = f"[{int(start_m):02d}:{start_s:04.1f} -> {int(end_m):02d}:{end_s:04.1f}]"
                    with st.expander(f"**{i+1}. {reason}** ({timestamp})"):
                        st.markdown(f"> {text}") # Thêm blockquote
            
            # --- BƯỚC 3: TÙY CHỌN CHỈNH SỬA & TẠO VIDEO ---
            st.divider()
            st.subheader("Bước 2: Tùy chọn Chỉnh sửa & Tạo Video")
            
            # Lấy thông tin cần thiết từ kết quả phân tích
            source_video_path = data.get('video_path')
            highlights_json_string = json.dumps(data.get('ai_highlights', []))
            
            # [SỬA LỖI] Lấy phụ đề đã sửa (cho Bước 3)
            corrected_segments_data = data.get('all_segments', [])
            segments_json_string = json.dumps(corrected_segments_data, ensure_ascii=False)

            do_remix = st.checkbox("Remix video (chỉ giữ lại các highlights do AI chọn)", value=False, key="remix_do_remix")
            
            if do_remix and not ai_highlights_data:
                st.warning("AI không tìm thấy highlights nào. Tính năng Remix sẽ bị bỏ qua và video gốc sẽ được sử dụng.")
                do_remix = False # Tự động tắt nếu không có highlight

            remix_bgm_file = st.file_uploader("2. (Tùy chọn) Tải lên nhạc nền (BGM)", type=["mp3", "wav", "m4a"], key="remix_bgm")
            
            # [SỬA LỖI] Khởi tạo biến Ở ĐÂY (bên ngoài if)
            remix_remove_original_audio = False
            
            if remix_bgm_file:
                remix_bgm_mode_option = st.selectbox(
                    "Chế độ nhạc nền", 
                    options=["mix", "replace"],
                    format_func=lambda x: "Trộn (Giữ giọng nói)" if x == "mix" else "Thay thế (Xóa âm thanh gốc)",
                    key="remix_bgm_mode"
                )
                remix_remove_original_audio = (remix_bgm_mode_option == "replace")

            col1, col2 = st.columns(2)
            with col1:
                remix_burn_in = st.checkbox("Ghi đè phụ đề (Hard sub)", value=True, key="remix_burn_in")
            with col2:
                remix_flip_video = st.checkbox("Lật video (Chỉ dùng cho video không có chữ)", value=False, key="remix_flip")
            
            if st.button("Tạo video cuối cùng"):
                if not source_video_path:
                    st.error("Lỗi: Không tìm thấy 'video_path' từ kết quả phân tích.")
                else:
                    status_placeholder = st.empty()
                    status_placeholder.info("Đang gửi yêu cầu xử lý video...")

                    try:
                        # Chuẩn bị Form Data
                        form_data = {
                            'source_video_path': source_video_path,
                            'source_url': tt_url, # Lấy từ input Bước 1
                            'keyword': tt_keyword, # Lấy từ input Bước 1
                            'do_remix': str(do_remix),
                            'highlights_json': highlights_json_string,
                            
                            'segments_json': segments_json_string, # Dùng phụ đề đã sửa
                            
                            'remove_original_audio': str(remix_remove_original_audio), 
                            'burn_in': str(remix_burn_in),
                            'flip_video': str(remix_flip_video)
                        }
                        
                        # Chuẩn bị File (chỉ BGM)
                        files = {}
                        if remix_bgm_file:
                            files['bgm'] = (remix_bgm_file.name, remix_bgm_file, remix_bgm_file.type)

                        # Gọi Endpoint MỚI
                        start_res = requests.post(
                            f"{API_URL}/process-remix", 
                            files=files, 
                            data=form_data
                        )
                        
                        if start_res.status_code != 200:
                            st.error(f"Lỗi khi bắt đầu job: {start_res.text}")
                        else:
                            start_data = start_res.json()
                            job_id = start_data.get('job_id')
                            
                            if not job_id:
                                st.error("API không trả về job_id")
                            else:
                                status_placeholder.info(f"Đang xử lý... ")
                                
                                download_url = None
                                while True:
                                    status_res = requests.get(f"{API_URL}/process/status/{job_id}")
                                    if status_res.status_code != 200:
                                        st.error("Lỗi khi kiểm tra trạng thái job.")
                                        break
                                    
                                    status_data = status_res.json()
                                    
                                    if status_data.get('status') == 'complete':
                                        status_placeholder.success("Xử lý hoàn tất! Video đã được upload lên Dropbox và Google Sheet.")
                                        download_url = status_data.get('download_url')
                                        break
                                    elif status_data.get('status') == 'failed':
                                        st.error(f"Job thất bại: {status_data.get('error')}")
                                        break
                                    
                                    time.sleep(5) 
                                
                                if download_url:
                                    final_url = f"{API_URL}{download_url}"
                                    
                                    final_video_html = f"""
                                    <div class="video-wrapper-16_9">
                                        <video controls >
                                            <source src="{final_url}" type="video/mp4">
                                        </video>
                                    </div>
                                    """
                                    st.markdown(final_video_html, unsafe_allow_html=True)
                                    st.link_button("Tải video về", final_url)
                                    
                    except Exception as e:
                        st.error(f"Lỗi nghiêm trọng: {e}")
                        
# ==========================================================
# ===== TÍNH NĂNG 3: ĐĂNG TẢI =====
# ==========================================================
elif active_tab_key == "3. Đăng tải Đa nền tảng":
    # === CĂN GIỮA TOÀN BỘ TAB ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        st.header("Công cụ Đăng tải Đa nền tảng")
        st.write("Giúp bạn chọn video mà bạn muốn đăng cùng với nền tảng.")
        
        if st.button("Làm mới dữ liệu", key="refresh_tab_4_button"):
            refresh_sheet_data("MVP_Content_Plan", "sheet_data")

        if 'sheet_data' not in st.session_state:
            # Tải dữ liệu lần đầu
            refresh_sheet_data("MVP_Content_Plan", "sheet_data")

        if 'sheet_data' in st.session_state:
            all_data = st.session_state['sheet_data']
            
            if not all_data or len(all_data) < 2:
                st.warning(f"Không tìm thấy dữ liệu trong sheet hoặc sheet trống.")
                st.stop()

            # --- 1. Xử lý Header (Giữ nguyên) ---
            header_row_index = -1
            headers = []
            
            LOOKUP_COL_1 = "keyword"
            LOOKUP_COL_2 = "link video gốc" 

            for i, row in enumerate(all_data):
                if not row: continue
                cleaned_row = [str(cell).strip().lower() for cell in row]
                
                if LOOKUP_COL_1 in cleaned_row and LOOKUP_COL_2 in cleaned_row:
                    header_row_index = i
                    headers = all_data[header_row_index] 
                    break 
            
            if header_row_index == -1:
                st.error(f"Không tìm thấy hàng tiêu đề. Cần tìm thấy CỘT '{LOOKUP_COL_1}' VÀ '{LOOKUP_COL_2}'.")
                st.stop()

            cleaned_header_map = {str(h).strip().lower(): idx for idx, h in enumerate(headers)}

            try:
                IDX_TITLE = cleaned_header_map[LOOKUP_COL_1]
                IDX_FB_CHECK = cleaned_header_map["facebook"]
                IDX_IG_CHECK = cleaned_header_map["ig"]
                IDX_READY_CHECK = cleaned_header_map["ready"]
                IDX_ERROR_CHECK = cleaned_header_map["error"]
                IDX_FB_LINK = cleaned_header_map.get("link facebook", -1)
                IDX_IG_LINK = cleaned_header_map.get("link instagram", -1)
            except KeyError as e:
                st.error(f"Lỗi cấu trúc Sheet. Không tìm thấy cột cần thiết: {e}.")
                st.stop()
            
            # --- 2. Phân loại dữ liệu (Giữ nguyên) ---
            pending_rows = []
            published_rows = []
            error_rows = []

            for i, row_data in enumerate(all_data):
                if i <= header_row_index:
                    continue 

                try:
                    video_title = str(row_data[IDX_TITLE]).strip()
                    if not video_title:
                        continue 

                    val_error = str(row_data[IDX_ERROR_CHECK]).upper() == 'TRUE'
                    link_fb = row_data[IDX_FB_LINK] if IDX_FB_LINK != -1 else ""
                    link_ig = row_data[IDX_IG_LINK] if IDX_IG_LINK != -1 else ""
                    
                    has_link = (link_fb and "http" in str(link_fb)) or \
                               (link_ig and "http" in str(link_ig))
                    
                    row_info = {
                        "row_data": row_data,
                        "gspread_index": i + 1, 
                        "title": video_title,
                        "link_fb": link_fb,
                        "link_ig": link_ig
                    }

                    if val_error:
                        error_rows.append(row_info)
                    elif has_link:
                        published_rows.append(row_info)
                    else:
                        pending_rows.append(row_info)

                except IndexError:
                    continue 

            # --- 3. Hiển thị bằng st.tabs (Giữ nguyên) ---
            
            tab_pending, tab_published, tab_error = st.tabs(
                [
                    f"⌛ Chờ xử lý ({len(pending_rows)})",
                    f"✅ Đã đăng ({len(published_rows)})",
                    f"❌ Bị lỗi ({len(error_rows)})"
                ]
            )

            # === TAB 1: CHỜ XỬ LÝ ===
            with tab_pending:
                st.subheader("Danh sách video chờ đăng")
                
                # --- [SỬA LỖI CĂN LỀ] ---
                # Bỏ HTML và dùng st.markdown đơn giản.
                # Nó sẽ tự động căn lề trái, khớp với checkbox bên dưới.
                header_cols = st.columns([4, 1, 1, 1])
                header_cols[0].markdown(f"**{headers[IDX_TITLE]}**")
                header_cols[1].markdown(f"**{headers[IDX_FB_CHECK]}**")
                header_cols[2].markdown(f"**{headers[IDX_IG_CHECK]}**")
                header_cols[3].markdown(f"**{headers[IDX_READY_CHECK]}**")
                # --- KẾT THÚC SỬA LỖI ---

                if not pending_rows:
                    st.info("Không có video nào đang chờ xử lý.")

                # Dùng container cho mỗi item (Giữ nguyên)
                for item in pending_rows:
                    with st.container(border=True): 
                        row_data = item["row_data"]
                        row_index_gspread = item["gspread_index"]
                        video_title = item["title"]

                        val_fb = str(row_data[IDX_FB_CHECK]).upper() == 'TRUE'
                        val_ig = str(row_data[IDX_IG_CHECK]).upper() == 'TRUE'
                        val_ready = str(row_data[IDX_READY_CHECK]).upper() == 'TRUE'
                        
                        COL_FB_CHECK_GSPREAD = IDX_FB_CHECK + 1
                        COL_IG_CHECK_GSPREAD = IDX_IG_CHECK + 1
                        COL_READY_CHECK_GSPREAD = IDX_READY_CHECK + 1

                        key_fb = f"check_{row_index_gspread}_{COL_FB_CHECK_GSPREAD}"
                        key_ig = f"check_{row_index_gspread}_{COL_IG_CHECK_GSPREAD}"
                        key_ready = f"check_{row_index_gspread}_{COL_READY_CHECK_GSPREAD}"

                        row_cols = st.columns([4, 1, 1, 1])
                        row_cols[0].write(video_title)
                        
                        # Code checkbox giữ nguyên (vì nó đã căn lề trái)
                        row_cols[1].checkbox("FB", value=val_fb, key=key_fb, on_change=handle_tick, args=(row_index_gspread, COL_FB_CHECK_GSPREAD, key_fb, "facebook", video_title), label_visibility="collapsed")
                        row_cols[2].checkbox("IG", value=val_ig, key=key_ig, on_change=handle_tick, args=(row_index_gspread, COL_IG_CHECK_GSPREAD, key_ig, "ig", video_title), label_visibility="collapsed")
                        row_cols[3].checkbox("Ready", value=val_ready, key=key_ready, on_change=handle_tick, args=(row_index_gspread, COL_READY_CHECK_GSPREAD, key_ready, "ready", video_title), label_visibility="collapsed")


            # === TAB 2: ĐÃ ĐĂNG ===
            with tab_published:
                # (Tab này code đã đúng, không cần sửa)
                st.subheader("Danh sách video đã đăng tải")
                
                header_cols = st.columns([4, 3])
                header_cols[0].markdown(f"**{headers[IDX_TITLE]}**")
                header_cols[1].markdown(f"**Links**")
                st.divider()

                if not published_rows:
                    st.info("Chưa có video nào được đăng tải.")

                for item in published_rows:
                    with st.container(border=True): 
                        video_title = item["title"]
                        link_fb = item["link_fb"]
                        link_ig = item["link_ig"]

                        row_cols = st.columns([4, 3])
                        row_cols[0].write(video_title)
                        
                        with row_cols[1]:
                            links_md = []
                            if link_fb and "http" in str(link_fb):
                                links_md.append(f"[Facebook]({link_fb})")
                            if link_ig and "http" in str(link_ig):
                                links_md.append(f"[Instagram]({link_ig})")
                            
                            if links_md:
                                st.markdown(" | ".join(links_md), unsafe_allow_html=True)
                            else:
                                st.caption("Không có link")
            
            # === TAB 3: BỊ LỖI ===
            with tab_error:
                st.subheader("Danh sách video bị lỗi")
                st.caption("Các video này đã được đánh dấu 'Error' trong Sheet. Bạn có thể bỏ tick 'Error' ở đây để 'reset' và gửi lại video vào hàng chờ.")

                # --- [SỬA LỖI CĂN LỀ] ---
                # Bỏ HTML và dùng st.markdown đơn giản
                header_cols = st.columns([4, 2])
                header_cols[0].markdown(f"**{headers[IDX_TITLE]}**")
                header_cols[1].markdown(f"**{headers[IDX_ERROR_CHECK]} (Bỏ tick để reset)**")
                # --- KẾT THÚC SỬA LỖI ---
                
                st.divider()

                if not error_rows:
                    st.info("Không có video nào bị lỗi.")

                for item in error_rows:
                    with st.container(border=True): 
                        row_index_gspread = item["gspread_index"]
                        video_title = item["title"]

                        COL_ERROR_CHECK_GSPREAD = IDX_ERROR_CHECK + 1
                        key_error = f"check_{row_index_gspread}_{COL_ERROR_CHECK_GSPREAD}"

                        row_cols = st.columns([4, 2])
                        row_cols[0].write(video_title)
                        
                        # Code checkbox giữ nguyên (nó sẽ căn lề trái)
                        row_cols[1].checkbox(
                            "Error", 
                            value=True, 
                            key=key_error, 
                            on_change=handle_tick, 
                            args=(row_index_gspread, COL_ERROR_CHECK_GSPREAD, key_error, "error", video_title), 
                            label_visibility="collapsed"
                        )
# ==========================================================
# ===== TÍNH NĂNG 4: BÁO CÁO =====
# ==========================================================
elif active_tab_key == "4. Báo cáo Hiệu suất":
    # === CĂN GIỮA TOÀN BỘ TAB ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        
        # --- [SỬA ĐỔI] CHUYỂN SANG LOGIC "THỦ CÔNG" (MANUAL) ---
        
        st.header("🎬 Báo cáo Hiệu suất Video")
        
        report_sheet_name = "Engagement"
        st.caption(f"Dữ liệu từ sheet: **{report_sheet_name}**")
        
        # [SỬA ĐỔI] Tách thành 2 nút
        col_btn_1, col_btn_2 = st.columns(2)
        
        with col_btn_1:
            if st.button("Lấy dữ liệu mới", key="refresh_tab_5_n8n_button", use_container_width=True):
                with st.spinner("Đang thu thập dữ liệu mới..."):
                    try:
                        N8N_REPORT_WEBHOOK = "https://partible-terese-homocercal.ngrok-free.dev/webhook/b6f588e5-46c5-4e2d-9375-f80971ad4d84"
                        
                        # Dùng timeout ngắn (fire-and-forget)
                        res = requests.post(N8N_REPORT_WEBHOOK, json={"event": "report_refresh_requested"}, timeout=5)
                        
                        if res.status_code == 200:
                            st.success("Đã kích hoạt n8n thành công!")
                            st.info("Dữ liệu đang được xử lý. Vui lòng bấm 'Tải lại dữ liệu' sau vài phút.")
                        else:
                            st.error(f"Kích hoạt n8n thất bại: {res.text}")
                    
                    except requests.exceptions.ReadTimeout:
                         # Đây là điều MONG ĐỢI (fire-and-forget)
                         st.success("Đã kích hoạt n8n thành công!")
                         st.info("Dữ liệu đang được xử lý. Vui lòng bấm 'Tải lại dữ liệu' sau vài phút.")
                    
                    except Exception as e:
                        st.error(f"Lỗi khi kích hoạt n8n: {e}")
        
        with col_btn_2:
            if st.button("Tải lại dữ liệu (Xem kết quả)", key="refresh_tab_5_button", use_container_width=True):
                refresh_sheet_data(report_sheet_name, "sheet_data_report")
        
        
        # Logic hiển thị data
        if 'sheet_data_report' not in st.session_state:
            st.info("Vui lòng bấm 'Tải lại dữ liệu' để xem báo cáo (hoặc 'Lấy dữ liệu mới' nếu muốn lấy dữ liệu mới nhất).")
        
        if 'sheet_data_report' in st.session_state:
            all_data = st.session_state['sheet_data_report']
            
            if not all_data or len(all_data) < 2:
                st.warning("Sheet trống.")
            else:
                # --- 1. Xử lý Header ---
                header_row_index = -1
                header_map = {}
                REQUIRED_KEY_COLUMN = "title" 

                for i, row in enumerate(all_data):
                    if not row: continue
                    processed_row = [str(cell).strip().lower() for cell in row]
                    if REQUIRED_KEY_COLUMN in processed_row:
                        header_row_index = i
                        headers = [str(cell).strip().lower() for cell in all_data[header_row_index]]
                        header_map = {name.replace(" ", ""): i for i, name in enumerate(headers)}
                        break
                
                if header_row_index == -1:
                    st.error(f"Không tìm thấy cột '{REQUIRED_KEY_COLUMN}'.")
                    st.stop()

                # --- 2. Dropdown chọn Video ---
                video_options = {} 
                try:
                    title_col_index = header_map[REQUIRED_KEY_COLUMN]
                except KeyError:
                    st.error(f"Lỗi code: Không tìm thấy '{REQUIRED_KEY_COLUMN}' trong header_map.")
                    st.stop()
                
                for i, row in enumerate(all_data):
                    if i <= header_row_index: continue
                    try:
                        title_text = row[title_col_index]
                        if title_text:
                            video_options[f"{title_text}"] = i
                    except IndexError:
                        continue
                
                if not video_options:
                    st.warning("Không tìm thấy video nào có Title.")
                    st.stop()
                        
                selected_key = st.selectbox("📌 Chọn video để xem báo cáo", options=video_options.keys())
                
                if selected_key:
                    selected_row_index = video_options[selected_key]
                    selected_row_data = all_data[selected_row_index]
                    
                    def get_val(key, is_json=False):
                        try:
                            col_idx = header_map[key.lower().replace(" ", "")]
                            raw = selected_row_data[col_idx]
                            if not raw: return 0
                            if is_json: return json.loads(raw.replace("'", '"'))
                            return float(str(raw).replace(',', ''))
                        except Exception:
                            return [] if is_json else 0

                    # --- Lấy dữ liệu ---
                    total_views = get_val('totalviews')
                    avg_time = get_val('avgwatchtimesec')
                    avg_ratio = get_val('avgwatchratio')
                    eng_rate = get_val('engagementrate')
                    replay_count = get_val('replaycount')
                    total_eng = get_val('totalengagements')
                    retention_data = get_val('retentiongraph', is_json=True)
                    social_data = get_val('socialgained', is_json=True)

                    st.markdown("---")
                    
                    st.subheader("⚡ Chỉ số chính")
                    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                    kpi1.metric("Total Views", f"{int(total_views):,}")
                    kpi2.metric("Avg Watch Time", f"{avg_time}s")
                    kpi3.metric("Watch Ratio", f"{avg_ratio}%")
                    kpi4.metric("Engagement Rate", f"{eng_rate}%")
                    
                    col_chart_1, col_chart_2 = st.columns(2)
                    
                    with col_chart_1:
                        st.subheader("📊 Tương tác (Interactions)")
                        df_interact = pd.DataFrame({
                            "Metric": ["Total Views", "Replays", "Engagements"],
                            "Count": [total_views, replay_count, total_eng]
                        }).set_index("Metric")
                        st.bar_chart(df_interact, color="#FF4B4B")

                    with col_chart_2:
                        st.subheader("📉 Giữ chân người xem (Retention)")
                        if retention_data:
                            retention_pct = [x * 100 for x in retention_data]
                            st.area_chart(retention_pct, color="#29B5E8")
                        else:
                            st.info("Chưa có dữ liệu Retention.")

                    st.subheader("👍 Hành động xã hội (Social Actions)")
                    if social_data and any(social_data.values()):
                        df_social = pd.DataFrame(list(social_data.items()), columns=['Action', 'Count'])
                        df_social = df_social.set_index('Action')
                        df_social = df_social.sort_values(by='Count', ascending=True)
                        st.bar_chart(df_social, horizontal=True)
                    else:
                        st.caption("Không có dữliệu Social Action.")