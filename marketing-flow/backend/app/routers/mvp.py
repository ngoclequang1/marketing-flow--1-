import os
from fastapi import APIRouter
from pydantic import BaseModel, HttpUrl
import google.generativeai as genai
from google.generativeai import types
import json
from typing import Optional, List

# --- Import các service ---
from app.services.crawl import smart_fields
from app.services.nlp import analyze_competitor
from app.services.trends import keyword_snapshot
from app.services.sheets import export_rows
from fastapi.concurrency import run_in_threadpool

router = APIRouter()

MODEL = "gemini-2.5-flash"
SPREADSHEET_ID = "1hcFoYNhmJdizx5s2id8gl_iPz_74fp5cZYz0I1bAJH8"
SHEET_TITLE = "MVP_Content_Plan"

# --- Cấu hình API Key ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("CẢNH BÁO (MVP Router): GEMINI_API_KEY chưa được set. Các hàm AI sẽ thất bại.")

gemini_model = genai.GenerativeModel(
    MODEL,
    system_instruction="Từ tiêu đề này tạo cho tôi một video description có độ dài 300 từ, dễ đọc chuẩn seo, 2 đến 3 dòng là viết 1 đoạn mới , mỗi đầu dòng có emoji gây chú ý , phong cách viết chuyên sâu giữ chân người và gợi ý cho tôi một số hastag để sử dụng cho video đấy"
)

class MVPReq(BaseModel):
    url: HttpUrl
    keyword: str
    platform: str = "page"
    geo: str = "VN"

def _fallback_draft(keyword: str, platform: str) -> str:
    if platform == "page":
        return (
            f"Hook: {keyword} đang HOT? Xem ngay!\n"
            f"Body: Điểm nổi bật • Lợi ích nhanh • Cam kết rõ ràng • Bằng chứng ngắn\n"
            f"CTA: Bình luận \"TÔI MUỐN\" để nhận ưu đãi."
        )
    return (
        f"Outline SEO cho từ khóa: {keyword}\n"
        f"H2 1. Tổng quan & lợi ích chính\n"
        f"H2 2. So sánh & lựa chọn phù hợp\n"
        f"H2 3. Hướng dẫn sử dụng/ứng dụng\n"
        f"H2 4. Câu hỏi thường gặp (FAQ)\n"
        f"Meta ≤60/≤155, chèn từ khóa & biến thể dài."
    )


@router.post("/run")
async def mvp_run(req: MVPReq):
    
    draft_error_note: Optional[str] = None
    
    fields = await run_in_threadpool(smart_fields, str(req.url))
    insights = await run_in_threadpool(analyze_competitor, fields)
    snap = await run_in_threadpool(keyword_snapshot, req.keyword, geo=req.geo)

    # 3) Draft (Gemini or fallback)
    
    # --- ĐÃ SỬA LỖI ---
    # Thay 'genai.API_KEY' bằng biến 'GEMINI_API_KEY'
    if os.getenv("MFA_LLM_OFF") == "1" or not GEMINI_API_KEY:
        draft = _fallback_draft(req.keyword, req.platform)
        draft_error_note = "Tạo bản nháp AI đã bị tắt hoặc thiếu API key."
    else:
        template = (
            "AIDA-style Facebook Page caption..."
            if req.platform == "page"
            else "SEO blog outline with H2/H3..."
        )
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

    # 4) Build result
    result = {
        "source": str(req.url),
        "keyword": req.keyword,
        "fields": fields,
        "insights": insights,
        "trends": snap,
        "draft": draft,
        "draft_error_note": draft_error_note
    }

    # 5) Auto-export to Google Sheet
    try:
        title_str = result.get("fields", {}).get("title", "")
        strengths_str = "\n".join(result.get("insights", {}).get("strengths", []))
        cap_fb = result.get("draft", "")
        cap_ig = result.get("draft", "")
        cap_tt = result.get("draft", "")

        header: List[str] = [
            "Keyword", "Link Video Gốc", "Title (Nội dung chính)", "Điểm mạnh",
            "Caption FB", "Caption IG", "Caption TikTok",
            "Facebook", "IG", "Thread", "Ready", "Error"
        ]
        checkboxes: List[str] = ["Facebook", "IG", "Thread", "Ready", "Error"]
        data_row: List[str] = [
            result.get("keyword", ""),
            result.get("source", ""),
            title_str,
            strengths_str,
            cap_fb,
            cap_ig,
            cap_tt,
            "FALSE", "FALSE", "FALSE", "FALSE", "FALSE"
        ]
        
        await export_rows(
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