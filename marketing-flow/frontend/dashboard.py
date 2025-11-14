import streamlit as st
import requests
import time
import os
import json
import pandas as pd

# URL backend FastAPI của bạn
API_URL = "http://localhost:8080"

# --- GIAO DIỆN CHÍNH ---
st.set_page_config(
    layout="wide",
    page_title="Video Dashboard",
    page_icon="🎬"
)

# === SỬA LỖI: ĐỊNH NGHĨA CSS TỶ LỆ 16:9 (DÙNG CHUNG) ===
# Định nghĩa style 1 lần ở đây để cả Tab 2 và Tab 3 đều dùng được
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
# === KẾT THÚC SỬA LỖI ===


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
def handle_tick(row_gspread, col_gspread, key, column_name, video_title):
    """
    Gửi yêu cầu cập nhật đến API /export/sheet/update-cell
    VÀ TỰ ĐỘNG TẢI LẠI DỮ LIỆU SAU KHI THÀNH CÔNG
    VÀ GỌI WEBHOOK NẾU LÀ NÚT 'READY'
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
                        st.toast("🚀 Webhook đã kích hoạt thành công!", icon="🎉")
                    else:
                        st.warning(f"Webhook response: {wh_res.status_code} - {wh_res.text}")
                
                except Exception as wh_e:
                    st.error(f"Lỗi khi gọi Webhook: {wh_e}")
            # --- KẾT THÚC GỌI WEBHOOK ---

            st.toast("Đang tải lại dữ liệu sheet để cập nhật links...")
            refresh_sheet_data("MVP_Content_Plan", "sheet_data")
            
        else:
            st.error(f"Lỗi cập nhật Sheet: {res.text}")
            st.session_state[key] = not new_value 
            
    except Exception as e:
        st.error(f"Lỗi kết nối API: {e}")
        st.session_state[key] = not new_value

# --- TẠO 5 TABS ---
tab_mvp, tab_tiktok, tab_subtitle, tab_uploader, tab_dashboard = st.tabs([
    "1. Phân tích URL (MVP)", 
    "2. Phân tích TikTok", 
    "3. Tạo Phụ đề Tự động",
    "4. Đăng tải Đa nền tảng",
    "5. Báo cáo Hiệu suất" 
])

# ==========================================================
# ===== TÍNH NĂNG 1: PHÂN TÍCH URL (MVP) =====
# ==========================================================
with tab_mvp:
    # --- Helper Function for rendering ---
    def render_structured_data(data_obj, title_map):
        """
        Hàm này nhận một dictionary (data_obj) và một map (title_map)
        để render dữ liệu một cách thân thiện.
        """
        if not isinstance(data_obj, dict):
            st.write(data_obj) 
            return

        for key, items in data_obj.items():
            title = title_map.get(key, key.replace('_', ' ').capitalize())
            st.markdown(f"**{title}**") 

            if isinstance(items, list) and items:
                for item in items:
                    st.markdown(f"- {item}")
            elif isinstance(items, str) and items:
                st.write(items)
            elif not items:
                st.caption(f"Không có dữ liệu")
            
            st.write("") 
    # --- End Helper Function ---

    # === CĂN GIỮA TOÀN BỘ TAB 1 ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    
    with main_col:
        st.header("Phân tích URL & Keyword")

        url = st.text_input("Dán URL bài viết", key="mvp_url")
        keyword = st.text_input("Nhập Keyword chính", key="mvp_kw")

        if st.button("Chạy phân tích MVP"):
            if not url or not keyword:
                st.warning("Vui lòng nhập cả URL và Keyword")
            else:
                try:
                    with st.spinner("Đang phân tích..."):
                        payload = {"url": url, "keyword": keyword}
                        res = requests.post(f"{API_URL}/mvp/run", json=payload)

                        if res.status_code == 200:
                            data = res.json()

                            # --- Draft ---
                            st.subheader("📝 Bản Nháp")
                            st.text_area("Draft", data.get("draft", ""), height=220)
                            
                            # ---------------- INSIGHTS (Layout 2 cột) ----------------
                            with st.container(border=True):
                                st.subheader("🔍 Thông Tin Chi Tiết (Insights)")
                                
                                insights_data = data.get("insights")
                                insights_map = {
                                    "strengths": "Điểm Mạnh",
                                    "weaknesses": "Điểm Yếu",
                                    "formula": "Công thức/Cấu trúc",
                                    "improvements": "Đề xuất Cải thiện",
                                    "title_suggestion": "Tiêu đề gợi ý",
                                    "keywords": "Keywords liên quan"
                                }
                                
                                if isinstance(insights_data, dict):
                                    # Tạo 2 cột bên trong container
                                    col1, col2 = st.columns(2)

                                    # Phân chia dữ liệu
                                    col1_keys = ["strengths", "weaknesses", "formula"]
                                    col2_keys = ["improvements", "title_suggestion", "keywords"]
                                    
                                    col1_data = {k: insights_data.get(k) for k in col1_keys if insights_data.get(k)}
                                    col2_data = {k: insights_data.get(k) for k in col2_keys if insights_data.get(k)}
                                    
                                    with col1:
                                        render_structured_data(col1_data, insights_map)
                                    with col2:
                                        render_structured_data(col2_data, insights_map)
                                else:
                                    # Fallback nếu 'insights' không phải là dict
                                    render_structured_data(insights_data, insights_map)

                            # --- RAW JSON ---
                            with st.expander("📦 Xem dữ liệu gốc (Raw JSON)"):
                                st.json(data)

                        else:
                            st.error(f"Lỗi từ API: {res.text}")
                
                except Exception as e:
                    st.error(f"Lỗi kết nối: {e}")

# ==========================================================
# ===== TÍNH NĂNG 2: PHÂN TÍCH TIKTOK (ĐÃ CẬP NHẬT) =====
# ==========================================================
# [THAY THẾ TOÀN BỘ 'with tab_tiktok:' TRONG dashboard.py]

# ==========================================================
# ===== TÍNH NĂNG 2: PHÂN TÍCH TIKTOK (ĐÃ CẬP NHẬT) =====
# ==========================================================
with tab_tiktok:
    # === CĂN GIỮA TOÀN BỘ TAB 2 ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        st.header("Phân tích Video TikTok")
        tt_url = st.text_input("Dán URL video TikTok", key="tt_url")
        
        # Thêm tùy chọn Ngôn ngữ
        language = st.selectbox(
            "Chọn ngôn ngữ của video",
            options=["vi", "en", "auto"],
            index=0,
            format_func=lambda x: "Tiếng Việt" if x == "vi" else ("Tiếng Anh" if x == "en" else "Tự động phát hiện"),
            key="tt_lang"
        )
        
        if st.button("Phân tích TikTok"):
            with st.spinner("Đang tải, tạo phụ đề và phân tích AI... (Việc này có thể mất 1-2 phút)"):
                try:
                    params = {"url": tt_url, "language": language}
                    res = requests.post(f"{API_URL}/video/viral-analyze", params=params, timeout=300) # Tăng timeout
                    
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state['tt_analysis_result'] = data # Lưu kết quả
                    
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
            audio_url = data.get('audio_url')
            
            if video_url:
                video_url_full = f"{API_URL}{video_url}"
                video_html = f"""
                <div class="video-wrapper-16_9">
                    <video controls autoplay playsinline>
                        <source src="{video_url_full}" type="video/mp4">
                        Trình duyệt của bạn không hỗ trợ video này.
                    </video>
                </div>
                """
                st.markdown(video_html, unsafe_allow_html=True)

            if audio_url:
                st.audio(f"{API_URL}{audio_url}")

            st.divider() 
            
            # --- TẠO 2 CỘT CHO DỮ LIỆU (STATS VÀ CTA) ---
            data_col1, data_col2 = st.columns(2)
            
            with data_col1:
                # [SỬA] Hiển thị stats của TOÀN BỘ phụ đề
                stats_all = data.get('all_segments_stats', {})
                if stats_all:
                    st.subheader("📊 Thống kê (Toàn bộ Phụ đề)")
                    st.metric("Tổng số Phân đoạn (Sub)", f"{int(stats_all.get('count', 0))}")
                    st.metric("TB (giây)", f"{stats_all.get('mean', 0):.2f}s")
                    st.metric("Ngắn nhất", f"{stats_all.get('shortest', 0):.2f}s")
                    st.metric("Dài nhất", f"{stats_all.get('longest', 0):.2f}s")

            with data_col2:
                ctas = data.get('content_deliverables', {}).get('cta_comments', [])
                if ctas:
                    st.subheader("💬 Gợi ý CTA")
                    for cta in ctas:
                        st.markdown(f"- {cta}")

            
            # --- [CẬP NHẬT] HIỂN THỊ THEO YÊU CẦU MỚI ---
            st.divider()

            # 1. Bảng Toàn bộ Phụ đề (LUÔN HIỂN THỊ)
            st.subheader("🎬 Toàn bộ Phụ đề của Video")
            all_segments_data = data.get('all_segments', [])
            
            if not all_segments_data:
                st.info("Không có dữ liệu phân đoạn (phụ đề) nào được tìm thấy.")
            else:
                st.dataframe(all_segments_data, height=300, use_container_width=True)

            # 2. Highlights do AI chọn (Hiển thị BÊN DƯỚI bảng)
            st.subheader("🤖 Highlights do AI chọn")
            ai_highlights_data = data.get('ai_highlights', [])

            if not ai_highlights_data:
                st.info("AI không tìm thấy highlights nào đáng chú ý.")
            else:
                st.caption(f"AI đã phân tích và chọn ra {len(ai_highlights_data)} đoạn hay nhất.")
                
                for i, scene in enumerate(ai_highlights_data):
                    start_time = scene.get('start_sec', 0.0)
                    end_time = scene.get('end_sec', 0.0)
                    reason = scene.get('reason', 'Không có lý do')
                    text = scene.get('text', 'Không có nội dung')
                    
                    start_m, start_s = divmod(start_time, 60)
                    end_m, end_s = divmod(end_time, 60)
                    timestamp = f"[{int(start_m):02d}:{start_s:04.1f} -> {int(end_m):02d}:{end_s:04.1f}]"

                    expander_title = f"**{i+1}. {reason}** ({timestamp})"
                    
                    with st.expander(expander_title):
                        st.markdown(f"**Nội dung:**")
                        st.write(text)

            # --- Hiển thị Ảnh Carousel (Giữ nguyên) ---
            images = data.get('content_deliverables', {}).get('carousel_images', [])
            if images:
                st.subheader("🖼️ Ảnh Carousel")
                num_images_to_show = 5
                cols = st.columns(num_images_to_show)
                
                for i, img_url in enumerate(images[:num_images_to_show]):
                    if i < len(cols): 
                        cols[i].image(f"{API_URL}{img_url}", use_container_width=True)

# ==========================================================
# ===== TÍNH NĂNG 3: TẠO PHỤ ĐỀ (POLLING) =====
# ==========================================================
with tab_subtitle:
    # === CĂN GIỮA TOÀN BỘ TAB 3 ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        st.header("Tạo Phụ đề Tự động & Thêm nhạc nền")

        vid_file = st.file_uploader("1. Tải lên video", type=["mp4", "mov", "avi", "mkv"])
        bgm_file = st.file_uploader("2. (Tùy chọn) Tải lên nhạc nền (BGM)", type=["mp3", "wav", "m4a"])
        
        bgm_mode = "mix" 
        remove_original_audio = False # Mặc định
        
        if bgm_file:
            bgm_mode_option = st.selectbox(
                "Chế độ nhạc nền", 
                options=["mix", "replace"],
                format_func=lambda x: "Trộn (Giữ giọng nói)" if x == "mix" else "Thay thế (Xóa âm thanh gốc)"
            )
            remove_original_audio = (bgm_mode_option == "replace")

        col1, col2 = st.columns(2)
        with col1:
            burn_in = st.checkbox("Ghi đè phụ đề (Hard sub)", value=True)
        with col2:
            flip_video = st.checkbox("Lật video (Flip)", value=False)
        
        if st.button("Tạo video"):
            if not vid_file:
                st.warning("Bạn phải tải lên một video")
            else:
                status_placeholder = st.empty()
                status_placeholder.info("Đang tải file lên và bắt đầu xử lý...")

                try:
                    files = {'video': (vid_file.name, vid_file, vid_file.type)}
                    form_data = {
                        'burn_in': str(burn_in),
                        'flip': str(flip_video),
                        'language': '' # Ngôn ngữ (nếu cần, có thể thêm UI)
                    }
                    
                    if bgm_file:
                        files['bgm'] = (bgm_file.name, bgm_file, bgm_file.type)
                        # SỬA LỖI: Gửi 'remove_original_audio' qua form
                        form_data['remove_original_audio'] = str(remove_original_audio)

                    start_res = requests.post(
                        f"{API_URL}/process", 
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
                            status_placeholder.info(f"Đang xử lý... (Job ID: {job_id[:8]})")
                            
                            download_url = None
                            while True:
                                status_res = requests.get(f"{API_URL}/process/status/{job_id}")
                                if status_res.status_code != 200:
                                    st.error("Lỗi khi kiểm tra trạng thái job.")
                                    break
                                
                                status_data = status_res.json()
                                
                                if status_data.get('status') == 'complete':
                                    status_placeholder.success("Xử lý hoàn tất!")
                                    download_url = status_data.get('download_url')
                                    break
                                elif status_data.get('status') == 'failed':
                                    st.error(f"Job thất bại: {status_data.get('error')}")
                                    break
                                
                                time.sleep(5) 
                            
                            if download_url:
                                final_url = f"{API_URL}{download_url}"
                                
                                # === DÙNG HTML/CSS ĐỂ KHÓA TỶ LỆ 16:9 ===
                                video_html = f"""
                                <div class="video-wrapper-16_9">
                                    <video controls autoplay playsinline>
                                        <source src="{final_url}" type="video/mp4">
                                        Trình duyệt của bạn không hỗ trợ video này.
                                    </video>
                                </div>
                                """
                                st.markdown(video_html, unsafe_allow_html=True)
                                # === KẾT THÚC SỬA LỖI ===

                                st.link_button("Tải video về", final_url)
                                
                except Exception as e:
                    st.error(f"Lỗi nghiêm trọng: {e}")

# ==========================================================
# ===== TÍNH NĂNG 4: ĐĂNG TẢI (SHEET) =====
# ==========================================================
with tab_uploader:
    # === CĂN GIỮA TOÀN BỘ TAB 4 ===
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
            else:
                header_row_index = -1
                headers = []
                
                LOOKUP_COL_1 = "link video gốc"
                LOOKUP_COL_2 = "title (nội dung chính)" 

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

                # --- Tạo map ánh xạ ---
                cleaned_header_map = {str(h).strip().lower(): idx for idx, h in enumerate(headers)}

                try:
                    IDX_TITLE = cleaned_header_map[LOOKUP_COL_2]
                    IDX_FB_CHECK = cleaned_header_map["facebook"]
                    IDX_IG_CHECK = cleaned_header_map["ig"]
                    IDX_READY_CHECK = cleaned_header_map["ready"]
                    IDX_ERROR_CHECK = cleaned_header_map["error"]
                    IDX_FB_LINK = cleaned_header_map.get("link facebook", -1) # Dùng .get() để tránh lỗi
                    IDX_IG_LINK = cleaned_header_map.get("link instagram", -1) # Dùng .get() để tránh lỗi
                except KeyError as e:
                    st.error(f"Lỗi cấu trúc Sheet. Không tìm thấy cột cần thiết: {e}.")
                    st.stop()
                
                # --- Hiển thị Header ---
                header_cols = st.columns([4, 0.7, 0.7, 0.7, 0.7, 2])
                header_cols[0].markdown(f"**{headers[IDX_TITLE]}**")
                header_cols[1].markdown(f"**{headers[IDX_FB_CHECK]}**")
                header_cols[2].markdown(f"**{headers[IDX_IG_CHECK]}**")
                header_cols[3].markdown(f"**{headers[IDX_READY_CHECK]}**")
                header_cols[4].markdown(f"**{headers[IDX_ERROR_CHECK]}**")
                header_cols[5].markdown(f"**Links**")
                st.divider()
                
                # --- Vòng lặp data ---
                for i, row_data in enumerate(all_data):
                    if i <= header_row_index:
                        continue 
                    
                    row_index_gspread = i + 1 
                    
                    try:
                        video_title = row_data[IDX_TITLE]
                        if not video_title:
                            continue 
                        
                        val_fb = str(row_data[IDX_FB_CHECK]).upper() == 'TRUE'
                        val_ig = str(row_data[IDX_IG_CHECK]).upper() == 'TRUE'
                        val_ready = str(row_data[IDX_READY_CHECK]).upper() == 'TRUE'
                        val_error = str(row_data[IDX_ERROR_CHECK]).upper() == 'TRUE'
                        
                        link_fb = row_data[IDX_FB_LINK] if IDX_FB_LINK != -1 else ""
                        link_ig = row_data[IDX_IG_LINK] if IDX_IG_LINK != -1 else ""
                    
                    except IndexError:
                        continue 

                    COL_FB_CHECK_GSPREAD = IDX_FB_CHECK + 1
                    COL_IG_CHECK_GSPREAD = IDX_IG_CHECK + 1
                    COL_READY_CHECK_GSPREAD = IDX_READY_CHECK + 1
                    COL_ERROR_CHECK_GSPREAD = IDX_ERROR_CHECK + 1

                    key_fb = f"check_{row_index_gspread}_{COL_FB_CHECK_GSPREAD}"
                    key_ig = f"check_{row_index_gspread}_{COL_IG_CHECK_GSPREAD}"
                    key_ready = f"check_{row_index_gspread}_{COL_READY_CHECK_GSPREAD}"
                    key_error = f"check_{row_index_gspread}_{COL_ERROR_CHECK_GSPREAD}"

                    row_cols = st.columns([4, 0.7, 0.7, 0.7, 0.7, 2])
                    row_cols[0].write(video_title)
                    
                    row_cols[1].checkbox("FB", value=val_fb, key=key_fb, on_change=handle_tick, args=(row_index_gspread, COL_FB_CHECK_GSPREAD, key_fb, "facebook", video_title), label_visibility="collapsed")
                    row_cols[2].checkbox("IG", value=val_ig, key=key_ig, on_change=handle_tick, args=(row_index_gspread, COL_IG_CHECK_GSPREAD, key_ig, "ig", video_title), label_visibility="collapsed")
                    row_cols[3].checkbox("Ready", value=val_ready, key=key_ready, on_change=handle_tick, args=(row_index_gspread, COL_READY_CHECK_GSPREAD, key_ready, "ready", video_title), label_visibility="collapsed")
                    row_cols[4].checkbox("Error", value=val_error, key=key_error, on_change=handle_tick, args=(row_index_gspread, COL_ERROR_CHECK_GSPREAD, key_error, "error", video_title), label_visibility="collapsed")

                    # Hiển thị links
                    with row_cols[5]:
                        links_md = []
                        if link_fb and "http" in str(link_fb):
                            links_md.append(f"[Facebook]({link_fb})")
                        if link_ig and "http" in str(link_ig):
                            links_md.append(f"[Instagram]({link_ig})")
                        
                        if links_md:
                            st.markdown(" | ".join(links_md), unsafe_allow_html=True)
                        else:
                            st.caption("Chưa có link")

# ==========================================================
# ===== TÍNH NĂNG 5: BÁO CÁO (PURE STREAMLIT) =====
# ==========================================================
with tab_dashboard:
    # === CĂN GIỮA TOÀN BỘ TAB 5 ===
    _, main_col, _ = st.columns([0.5, 3, 0.5])
    with main_col:
        st.header("🎬 Báo cáo Hiệu suất Video")
        
        report_sheet_name = "Engagement"
        st.caption(f"Dữ liệu từ sheet: **{report_sheet_name}**")
        
        if st.button("Làm mới dữ liệu", key="refresh_tab_5_button"):
            refresh_sheet_data(report_sheet_name, "sheet_data_report")

        if 'sheet_data_report' not in st.session_state:
            st.info("Vui lòng bấm 'Làm mới' để tải dữ liệu.")
        else:
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
                            video_options[f"{title_text} (Hàng {i+1})"] = i
                    except IndexError:
                        continue
                
                if not video_options:
                    st.warning("Không tìm thấy video nào có Title.")
                    st.stop()
                        
                selected_key = st.selectbox("📌 Chọn video để xem báo cáo", options=video_options.keys())
                
                if selected_key:
                    selected_row_index = video_options[selected_key]
                    selected_row_data = all_data[selected_row_index]
                    
                    # Hàm lấy data an toàn
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
                    
                    # --- A. KPI Metrics ---
                    st.subheader("⚡ Chỉ số chính")
                    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                    kpi1.metric("Total Views", f"{int(total_views):,}")
                    kpi2.metric("Avg Watch Time", f"{avg_time}s")
                    kpi3.metric("Watch Ratio", f"{avg_ratio}%")
                    kpi4.metric("Engagement Rate", f"{eng_rate}%")
                    
                    # --- B. Charts Layout ---
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

                    # --- C. Social Actions ---
                    st.subheader("👍 Hành động xã hội (Social Actions)")
                    if social_data and any(social_data.values()):
                        df_social = pd.DataFrame(list(social_data.items()), columns=['Action', 'Count'])
                        df_social = df_social.set_index('Action')
                        df_social = df_social.sort_values(by='Count', ascending=True)
                        st.bar_chart(df_social, horizontal=True)
                    else:
                        st.caption("Không có dữ liệu Social Action.")