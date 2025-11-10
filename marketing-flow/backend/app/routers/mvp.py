import os
from fastapi import APIRouter
from pydantic import BaseModel, HttpUrl
from google import genai
from google.genai import types
import json
from app.services.crawl import smart_fields   # <-- platform-aware fetcher
from app.services.nlp import analyze_competitor
from app.services.trends import keyword_snapshot
from app.services.sheets import export_rows   # <-- import Sheets service

router = APIRouter()

MODEL = "gemini-2.5-flash"
SPREADSHEET_ID = "1hcFoYNhmJdizx5s2id8gl_iPz_74fp5cZYz0I1bAJH8"
SHEET_TITLE = "Sheet1"


def _get_gemini_client():
    """Create Gemini client only when needed to avoid import-time crashes."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


class MVPReq(BaseModel):
    url: HttpUrl
    keyword: str
    platform: str = "page"  # "page" or "blog"
    geo: str = "VN"


def _fallback_draft(keyword: str, platform: str) -> str:
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
def mvp_run(req: MVPReq):
    # 1) URL → crawl + insights (smart handling for TikTok/Facebook/normal pages)
    fields = smart_fields(str(req.url))
    insights = analyze_competitor(fields)  # Gemini (structured) or heuristic fallback

    # 2) Keyword → trends
    snap = keyword_snapshot(req.keyword, geo=req.geo)

    # 3) Draft (Gemini or fallback)
    if os.getenv("MFA_LLM_OFF") == "1":
        draft = _fallback_draft(req.keyword, req.platform)
    else:
        template = (
            "AIDA-style Facebook Page caption with hook, body, CTA"
            if req.platform == "page"
            else "SEO blog outline with H2/H3, meta title (<=60 chars), meta description (<=155 chars)"
        )
        prompt = (
            f"Keyword: {req.keyword}\n"
            f"Template: {template}\n"
            f"Trends (last 12m + related queries): {snap}\n"
            f"Write in Vietnamese. Keep it practical and high-converting."
        )
        try:
            client = _get_gemini_client()
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

    # 4) Build result
    result = {
        "source": str(req.url),
        "keyword": req.keyword,
        "fields": fields,
        "insights": insights,
        "trends": snap,
        "draft": draft,
    }

      # 5) Auto-export to Google Sheet (safe serialization + normalization)
    try:
        # Serialize complex structures to single JSON strings
        fields_str = json.dumps(result.get("fields", {}), ensure_ascii=False)
        insights_str = json.dumps(result.get("insights", {}), ensure_ascii=False)
        trends_str = json.dumps(result.get("trends", {}), ensure_ascii=False)

        # Build the row exactly with no leading empty cells
        row = [
            result.get("keyword", ""),
            result.get("source", ""),
            fields_str,
            insights_str,
            trends_str,
            result.get("draft", ""),
        ]

        # Call export; export_rows will normalize/pad as needed
        export_rows(SPREADSHEET_ID, SHEET_TITLE, [row])

    except Exception as e:
        # don't break the main response if export fails
        result["sheet_export_error"] = str(e)

    return result