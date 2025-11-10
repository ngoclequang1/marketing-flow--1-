import os, json, re
from collections import Counter
from typing import Dict, List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

# --- Gemini client (uses GEMINI_API_KEY) ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash"  # fast, budget model for text tasks

SYSTEM = (
    "You are a concise marketing analyst. Given a webpage's extracted content, "
    "return a compact JSON with keys: strengths (3-5 bullets), weaknesses (3-5 bullets), "
    "formula (describe hook/structure/CTA if detectable), improvements (3-5 specific actions), "
    "seo (title_suggestion, 3-5 keywords). Keep answers short and actionable. "
    "Respond in Vietnamese when the content is Vietnamese."
)

# ---- Structured output schema (reliable JSON) ----
class SEO(BaseModel):
    title_suggestion: Optional[str] = None
    keywords: List[str] = []

class Insights(BaseModel):
    strengths: List[str]
    weaknesses: List[str]
    formula: Optional[str] = None
    improvements: List[str]
    seo: SEO

# ---- Lightweight heuristics for offline/fallback mode ----
STOPWORDS = {
    "the","a","an","and","or","of","to","in","on","for","is","are","be","with","as","by","at","that",
    "this","it","from","we","you","our","your","their","they","i","he","she","was","were","will","can",
    "about","more","most","less","very","so","if","but","not","no","yes","do","does","did","have","has",
    "had","than","then","when","what","which","who","whom","also","into","out","over","under"
}
def _simple_keywords(text: str, k: int = 5):
    words = re.findall(r"[a-zA-ZÀ-ỹ0-9]+", (text or "").lower())
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]
    common = [w for w, _ in Counter(words).most_common(50)]
    return common[:k] or ["content","marketing","seo"]

def _heuristic_insights(content: Dict) -> Dict:
    title = content.get("title") or ""
    h1 = content.get("h1") or []
    h2 = content.get("h2") or []
    metas = content.get("metas") or {}
    text = content.get("text") or ""
    wc = len(text.split())
    kws = _simple_keywords(text, 5)
    strengths, weaknesses = [], []
    if h1: strengths.append("Có H1 rõ ràng (tiêu đề chính hiện diện).")
    if len(h2) >= 3: strengths.append("Bố cục có nhiều H2 giúp dễ đọc.")
    if metas.get("description"): strengths.append("Có thẻ meta description.")
    if wc >= 600: strengths.append("Nội dung đủ dài cho SEO cơ bản.")
    if not metas.get("description"): weaknesses.append("Thiếu hoặc yếu thẻ meta description.")
    if wc < 600: weaknesses.append("Nội dung ngắn, khó xếp hạng từ khóa cạnh tranh.")
    if "mua" not in text.lower() and "liên hệ" not in text.lower():
        weaknesses.append("Thiếu CTA rõ ràng dẫn dắt hành động.")
    if len(h2) < 2: weaknesses.append("Ít đề mục con (H2), cấu trúc chưa rõ ràng.")
    return {
        "strengths": strengths or ["Có cấu trúc cơ bản."],
        "weaknesses": weaknesses or ["Cần tối ưu thêm cho SEO/CTA."],
        "formula": "Mở bài → H2 nội dung → Kết luận/CTA.",
        "improvements": [
            "Thêm CTA sau mỗi 2–3 đoạn (mua ngay/đăng ký/nhận tư vấn).",
            "Viết lại meta title/description bám keyword & lợi ích.",
            "Bổ sung 2–3 H2/H3 để chia nhỏ nội dung, thêm bullet.",
            "Chèn 1–2 ảnh có alt chứa keyword.",
            "Thêm FAQ 3–4 câu hỏi từ khóa dài."
        ],
        "seo": {"title_suggestion": (title[:45] + "…") if title and len(title) > 48 else (title or "Gợi ý tiêu đề tối ưu"),
                "keywords": kws}
    }

def analyze_competitor(content: Dict) -> Dict:
    # Fallback mode if you set MFA_LLM_OFF=1
    if os.getenv("MFA_LLM_OFF") == "1":
        return _heuristic_insights(content)

    user = f"""Title: {content.get('title','')}
H1: {content.get('h1','')}
H2: {content.get('h2','')}
Meta: {content.get('metas',{})}

Body:
{content.get('text','')[:8000]}
"""
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=Insights,  # enforce JSON shape
                temperature=0.2,
            ),
        )
        # If structured output parsed is available, use it; else parse text
        return resp.parsed.model_dump() if hasattr(resp, "parsed") and resp.parsed else json.loads(resp.text)
    except Exception as e:
        # fall back gracefully on any SDK/API error
        data = _heuristic_insights(content)
        data["_note"] = f"Fallback used due to error: {e}"
        return data
