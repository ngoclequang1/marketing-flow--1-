import os
from fastapi import APIRouter
from pydantic import BaseModel
import google.generativeai as genai
from google.generativeai import types
from typing import Optional
from app.services.trends import keyword_snapshot
from fastapi.concurrency import run_in_threadpool

router = APIRouter()

MODEL = "gemini-1.5-flash-latest"

# --- Cấu hình API Key ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("CẢNH BÁO (Keywords Router): GEMINI_API_KEY chưa được set. Các hàm AI sẽ thất bại.")

gemini_model = genai.GenerativeModel(
    MODEL,
    system_instruction="You write high-performing marketing content in Vietnamese."
)

class KwReq(BaseModel):
    keyword: str
    platform: str = "page"
    geo: str = "VN"

def _fallback_draft(keyword: str, platform: str):
    if platform == "page":
        return f"""Hook: {keyword} đang HOT? Xem ngay!
Body: Điểm nổi bật • Lợi ích nhanh • Cam kết rõ ràng • Bằng chứng ngắn
CTA: Bình luận "TÔI MUỐN" để nhận ưu đãi.
Hashtags: #{keyword.replace(" ", "")} #deal #hot"""
    return f"""Outline SEO cho từ khóa: {keyword}
H2 1. Tổng quan & lợi ích chính
H2 2. So sánh & lựa chọn phù hợp
H2 3. Hướng dẫn sử dụng/ứng dụng
H2 4. Câu hỏi thường gặp (FAQ)
Meta title ≤60, description ≤155, chèn từ khóa và biến thể dài."""

@router.post("")
async def keyword_report(req: KwReq):
    
    draft_error_note: Optional[str] = None
    
    snap = await run_in_threadpool(keyword_snapshot, req.keyword, geo=req.geo)

    # --- ĐÃ SỬA LỖI ---
    # Thay 'genai.API_KEY' bằng biến 'GEMINI_API_KEY'
    if os.getenv("MFA_LLM_OFF") == "1" or not GEMINI_API_KEY:
        draft = _fallback_draft(req.keyword, req.platform)
        draft_error_note = "Tạo bản nháp AI đã bị tắt hoặc thiếu API key."
    else:
        template = "AIDA-style Facebook Page caption..." if req.platform == "page" \
            else "SEO blog outline with H2/H3..."
        prompt = (
            f"Keyword: {req.keyword}\n"
            f"Template: {template}\n"
            f"Trends (last 12m + related queries): {snap}\n"
            f"Write in Vietnamese. Keep it practical and high-converting."
        )
        try:
            generation_config = types.GenerationConfig(temperature=0.3)
            
            resp = await run_in_threadpool(
                gemini_model.generate_content,
                contents=prompt,
                generation_config=generation_config
            )
            draft = resp.text
        except Exception as e:
            draft = _fallback_draft(req.keyword, req.platform)
            draft_error_note = f"Không thể tạo bản nháp AI (lỗi: {e}). Đã sử dụng mẫu cơ bản."

    return {
        "keyword": req.keyword, 
        "trends": snap, 
        "draft": draft, 
        "draft_error_note": draft_error_note
    }