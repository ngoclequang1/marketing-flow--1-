# app/routers/mvp.py
import os
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
import google.generativeai as genai
from google.generativeai import types
from gspread_asyncio import AsyncioGspreadClient

from app.services.crawl import smart_fields
from app.services.nlp import analyze_competitor
from app.services.sheets import export_rows
from app.dependencies import get_sheet_client # <-- Sửa 1: Import dependency

router = APIRouter()

# Sửa 2: Dùng model name đúng (giống nlp.py)
MODEL = "gemini-2.5-flash" 
SPREADSHEET_ID = "1hcFoYNhmJdizx5s2id8gl_iPz_74fp5cZYz0I1bAJH8"
SHEET_TITLE = "MVP_Content_Plan" # Hoặc "MVP_Content_Plan" tùy bạn

# Sửa 3: Khởi tạo model theo cách của nlp.py (cách gọi đúng)
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(MODEL)
except Exception as e:
    print(f"LỖI KHỞI TẠO GEMINI (MVP): {e}")
    gemini_model = None

class MVPReq(BaseModel):
    url: HttpUrl
    keyword: str
    platform: str = "page"  # "page" or "blog"
    geo: str = "VN"


def _fallback_draft(keyword: str, platform: str) -> str:
    # (Giữ nguyên code fallback của bạn)
    if platform == "page":
        return (
            f"[FALLBACK – không dùng LLM]\n"
            f"Hook: {keyword} đang HOT? Xem ngay!\n"
            f"Body: Điểm nổi bật • Lợi ích nhanh • Cam kết rõ ràng • Bằng chứng ngắn\n"
            f"CTA: Bình luận \"TÔI MUỐN\" để nhận ưu đãi."
        )
    return (
        f"[FALLBACK – không dùng LLM]\n"
        f"Outline SEO cho từ khóa: {keyword}\n"
        f"H2 1. Tổng quan & lợi ích chính\n"
        f"H2 2. So sánh & lựa chọn phù hợp\n"
        f"H2 3. Hướng dẫn sử dụng/ứng dụng\n"
        f"H2 4. Câu hỏi thường gặp (FAQ)\n"
        f"Meta ≤60/≤155, chèn từ khóa & biến thể dài."
    )


@router.post("/run")
# Sửa 4: Chuyển sang 'async def' và tiêm 'gc'
async def mvp_run(
    req: MVPReq,
    gc: AsyncioGspreadClient = Depends(get_sheet_client)
):
    # 1) URL → crawl + insights
    fields = smart_fields(str(req.url))
    insights = analyze_competitor(fields)  # Hàm này đã đúng


    # 3) Draft (Gemini or fallback)
    if os.getenv("MFA_LLM_OFF") == "1" or gemini_model is None:
        draft = _fallback_draft(req.keyword, req.platform)
    else:
        template = (
            "Generate  1 video caption tailored for me with these requirements:\n"
                "1. Focus on storytelling, emotional hook, and shareability. Include a clear CTA.\n"
                "2. Keep it short, aesthetic, and trendy. Use bullet points for value and include 5-10 relevant hashtags.\n"
                "3. Conversational, punchy, and authentic (text-first vibe). Focus on sparking a discussion or debate.\n"
                
            if req.platform == "page"
            else "SEO blog outline with H2/H3, meta title (<=60 chars), meta description (<=155 chars)"
        )
        prompt = (
            f"Keyword: {req.keyword}\n"
            f"Template: {template}\n"
            f"Write in Vietnamese. Keep it practical and high-converting."
        )
        try:
            # Sửa 5: Gọi 'gemini_model.generate_content_async'
            # (Dùng _async để không block server)
            resp = await gemini_model.generate_content_async(
                contents=prompt,
                generation_config=types.GenerationConfig(
                    temperature=0.3,
                ),
            )
            draft = resp.text
        except Exception as e:
            draft = _fallback_draft(req.keyword, req.platform) + f"\n\n(Note: Fallback due to error: {e})"

    # 4) Build result
    result = {
        "source": str(req.url),
        "keyword": req.keyword,
        "fields": fields,
        "insights": insights,
        "draft": draft,
    }

    # 5) Auto-export to Google Sheet
    try:
        title_str = result.get("fields", {}).get("title", "")
        strengths_str = "\n".join(result.get("insights", {}).get("strengths", []))
        cap_fb = result.get("draft", "")
        cap_ig = result.get("draft", "")

        header: List[str] = [
            "Keyword", "Link Video Gốc", "Title (Nội dung chính)", "Điểm mạnh",
            "Caption FB", "Caption IG", 
            "Facebook","IG", "Ready", "Error"
        ]
        checkboxes: List[str] = ["Facebook","IG", "Ready", "Error"]
        data_row: List[str] = [
            result.get("keyword", ""),
            result.get("source", ""),
            title_str,
            strengths_str,
            cap_fb,
            cap_ig,
            "FALSE", "FALSE", "FALSE", "FALSE"
        ]
        
        await export_rows(gc,
            spreadsheet_id=SPREADSHEET_ID,
            title=SHEET_TITLE,
            rows=[data_row],
            header_row=header,
            checkbox_columns=checkboxes
        )

    except Exception as e:
        print(f"--- SHEET EXPORT ERROR ---")
        print(str(e))
        print("----------------------------")
        result["sheet_export_error"] = f"Lỗi Google Sheet: {e}"

    return result