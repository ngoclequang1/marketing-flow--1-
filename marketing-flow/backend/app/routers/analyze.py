from fastapi import APIRouter
from pydantic import BaseModel, HttpUrl
from app.services.crawl import smart_fields
from app.services.nlp import analyze_competitor

router = APIRouter()

class AnalyzeRequest(BaseModel):
    url: HttpUrl

@router.post("/url")
def analyze_url(payload: AnalyzeRequest):
    fields = smart_fields(str(payload.url))
    insights = analyze_competitor(fields)
    return {"source": str(payload.url), "fields": fields, "insights": insights}
