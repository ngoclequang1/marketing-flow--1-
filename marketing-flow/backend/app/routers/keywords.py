import os
from fastapi import APIRouter
from pydantic import BaseModel
from google import genai
from google.genai import types
from app.services.trends import keyword_snapshot

router = APIRouter()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash"

class KwReq(BaseModel):
    keyword: str
    platform: str = "page"  # "page" or "blog"
    geo: str = "VN"

def _fallback_draft(keyword: str, platform: str):
    if platform == "page":
        return f"""[FALLBACK – không dùng LLM]
Hook: {keyword} đang HOT? Xem ngay!
Body: Điểm nổi bật • Lợi ích nhanh • Cam kết rõ ràng • Bằng chứng ngắn
CTA: Bình luận "TÔI MUỐN" để nhận ưu đãi.
Hashtags: #{keyword.replace(" ", "")} #deal #hot"""
    return f"""[FALLBACK – không dùng LLM]
Outline SEO cho từ khóa: {keyword}
H2 1. Tổng quan & lợi ích chính
H2 2. So sánh & lựa chọn phù hợp
H2 3. Hướng dẫn sử dụng/ứng dụng
H2 4. Câu hỏi thường gặp (FAQ)
Meta title ≤60, description ≤155, chèn từ khóa và biến thể dài."""

@router.post("")
def keyword_report(req: KwReq):
    snap = keyword_snapshot(req.keyword, geo=req.geo)

    if os.getenv("MFA_LLM_OFF") == "1":
        return {"keyword": req.keyword, "trends": snap, "draft": _fallback_draft(req.keyword, req.platform)}

    template = "AIDA-style Facebook Page caption with hook, body, CTA" if req.platform == "page" \
        else "SEO blog outline with H2/H3, meta title (<=60 chars), meta description (<=155 chars)"
    prompt = (
        f"Keyword: {req.keyword}\n"
        f"Template: {template}\n"
        f"Trends (last 12m + related queries): {snap}\n"
        f"Write in Vietnamese. Keep it practical and high-converting."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="You write high-performing marketing content in Vietnamese.",
                temperature=0.3,
            ),
        )
        draft = resp.text
    except Exception as e:
        draft = _fallback_draft(req.keyword, req.platform) + f"\n\n(Note: Fallback due to error: {e})"

    return {"keyword": req.keyword, "trends": snap, "draft": draft}
