from fastapi import APIRouter
from pydantic import BaseModel
from app.services.sheets import export_rows

router = APIRouter()

SPREADSHEET_ID = "1hcFoYNhmJdizx5s2id8gl_iPz_74fp5cZYz0I1bAJH8"
SHEET_TITLE = "data"  # Change this if you want a different tab

class ExportReq(BaseModel):
    rows: list[list[str]]

@router.post("/sheet/export")
def export_sheet(req: ExportReq):
    return export_rows(SPREADSHEET_ID, SHEET_TITLE, req.rows)
