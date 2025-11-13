import streamlit as st
import requests
import time
import os

# URL backend FastAPI của bạn
API_URL = "http://localhost:8080"

# Dùng tabs để tổ chức 3 tính năng của bạn
tab_mvp, tab_tiktok, tab_subtitle = st.tabs([
    "1. Phân tích URL (MVP)", 
    "2. Phân tích TikTok", 
    "3. Tạo Phụ đề Tự động"
])

# ----- TÍNH NĂNG 1: PHÂN TÍCH URL (MVP) -----
with tab_mvp:
    st.header("Phân tích URL và Keyword")
    
    # Tương đương với: const [url, setUrl] = useState("");
    url = st.text_input("Dán URL bài viết", key="mvp_url")
    
    # Tương đương với: const [keyword, setKeyword] = useState("");
    keyword = st.text_input("Nhập Keyword chính", key="mvp_kw")
    
    # Tương đương với: <button onClick={runMVP}>
    if st.button("Chạy phân tích MVP"):
        if not url or not keyword:
            st.warning("Vui lòng nhập cả URL và Keyword")
        else:
            # Tương đương với: setLoading(true)
            with st.spinner("Đang phân tích..."):
                try:
                    # Tương đương với: fetch(`${API}/mvp/run`, ...)
                    payload = {"url": url, "keyword": keyword}
                    res = requests.post(f"{API_URL}/mvp/run", json=payload)
                    
                    if res.status_code == 200:
                        data = res.json()
                        # Tương đương với: setResult(data)
                        st.subheader("Bản nháp (Draft)")
                        st.text_area("Draft", data.get('draft', ''), height=250)
                        
                        st.subheader("Insights")
                        st.json(data.get('insights', {}))
                        
                        st.subheader("Trends")
                        st.json(data.get('trends', {}))
                        
                        st.subheader("Raw JSON")
                        st.json(data)
                    else:
                        st.error(f"Lỗi từ API: {res.text}")
                except Exception as e:
                    # Tương đương với: setError(e.message)
                    st.error(f"Lỗi kết nối: {e}")

# ----- TÍNH NĂNG 2: TẠO PHỤ ĐỀ (POLLING) -----
with tab_subtitle:
    st.header("Tạo Phụ đề Tự động & Thêm nhạc nền")

    # Tương đương với: const [vidFile, setVidFile] = useState(null);
    vid_file = st.file_uploader("1. Tải lên video", type=["mp4", "mov", "avi", "mkv"])
    
    # Tương đương với: const [bgmFile, setBgmFile] = useState(null);
    bgm_file = st.file_uploader("2. (Tùy chọn) Tải lên nhạc nền (BGM)", type=["mp3", "wav", "m4a"])
    
    col1, col2 = st.columns(2)
    with col1:
        # Tương đương với: const [burnIn, setBurnIn] = useState(true);
        burn_in = st.checkbox("Ghi đè phụ đề (Hard sub)", value=True)
    with col2:
        # Tương đương với: const [flipVideo, setFlipVideo] = useState(false);
        flip_video = st.checkbox("Lật video (Flip)", value=False)
    
    # Tương đương với: <button onClick={handleProcess}>
    if st.button("Tạo video"):
        if not vid_file:
            st.warning("Bạn phải tải lên một video")
        else:
            # Tương đương với: setProcLoading(true)
            status_placeholder = st.empty() # Tạo một "khung" để cập nhật trạng thái
            status_placeholder.info("Đang tải file lên và bắt đầu xử lý...")

            try:
                # 1. Tải file lên backend (giống hệt logic React)
                files = {'video': (vid_file.name, vid_file, vid_file.type)}
                if bgm_file:
                    files['bgm'] = (bgm_file.name, bgm_file, bgm_file.type)
                
                form_data = {
                    'burn_in': str(burn_in),
                    'flip': str(flip_video),
                    'language': '' # Bạn có thể thêm ô nhập cho 'langHint'
                }

                # Tương đương với: fetch(`${API}/process`, ...)
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
                        # Tương đương với: setCurrentJobId(job_id)
                        status_placeholder.info(f"Đang xử lý... (Job ID: {job_id[:8]})")
                        
                        # 2. Bắt đầu Polling (logic giống hệt React)
                        download_url = None
                        while True:
                            # Tương đương với: fetch(`${API}/process/status/${job_id}`)
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
                            
                            # Chờ 5 giây rồi kiểm tra lại
                            time.sleep(5) 
                        
                        # 3. Hiển thị kết quả
                        if download_url:
                            # Tương đương với: setProcBlobUrl(...)
                            final_url = f"{API_URL}{download_url}"
                            st.video(final_url)
                            st.link_button("Tải video về", final_url)
                            
            except Exception as e:
                # Tương đương với: setProcError(e.message)
                st.error(f"Lỗi nghiêm trọng: {e}")

# ----- TÍNH NĂNG 3: PHÂN TÍCH TIKTOK -----
with tab_tiktok:
    st.header("Phân tích Video TikTok")
    tt_url = st.text_input("Dán URL video TikTok", key="tt_url")
    
    if st.button("Phân tích TikTok"):
        with st.spinner("Đang tải và phân tích..."):
            try:
                # Logic gọi /video/viral-analyze
                params = {"url": tt_url}
                res = requests.post(f"{API_URL}/video/viral-analyze", params=params)
                
                if res.status_code == 200:
                    data = res.json()
                    st.subheader("Kết quả phân tích")
                    
                    # Lấy link audio
                    audio_url = data.get('audio_url')
                    if audio_url:
                        st.audio(f"{API_URL}{audio_url}")
                    
                    # Hiển thị bảng các cảnh
                    st.subheader("Phân đoạn (Scenes)")
                    st.dataframe(data.get('scenes', []))
                    
                    # Hiển thị ảnh carousel
                    st.subheader("Carousel Images")
                    images = data.get('content_deliverables', {}).get('carousel_images', [])
                    if images:
                        # Hiển thị 3 ảnh trên 1 hàng
                        cols = st.columns(3) 
                        for i, img_url in enumerate(images):
                            cols[i % 3].image(f"{API_URL}{img_url}")
                    
                    st.json(data) # Hiển thị JSON đầy đủ
                else:
                    st.error(f"Lỗi API: {res.text}")
            except Exception as e:
                st.error(f"Lỗi kết nối: {e}")