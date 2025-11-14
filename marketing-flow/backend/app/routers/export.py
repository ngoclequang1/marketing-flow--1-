# app/routers/export.py
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from gspread_asyncio import AsyncioGspreadClient

# Import các hàm gốc từ service
from app.services.sheets import export_rows, update_sheet_cell, read_sheet_data
# Import dependency mới
from app.dependencies import get_sheet_client

router = APIRouter()

SPREADSHEET_ID = "1hcFoYNhmJdizx5s2id8gl_iPz_74fp5cZYz0I1bAJH8"
SHEET_TITLE = "MVP_Content_Plan" 

class ExportReq(BaseModel):
    rows: list[list[str]]

@router.post("/sheet/export")
async def export_sheet(
    req: ExportReq,
    gc: AsyncioGspreadClient = Depends(get_sheet_client) # <-- Sửa: Tiêm client
):
    try:
        # Sửa: Dùng await và truyền 'gc'
        return await export_rows(gc, SPREADSHEET_ID, SHEET_TITLE, req.rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class UpdateCellReq(BaseModel):
    row: int
    col: int
    value: bool

@router.post("/sheet/update-cell")
async def update_cell(
    req: UpdateCellReq,
    gc: AsyncioGspreadClient = Depends(get_sheet_client) # <-- Sửa: Tiêm client
):
    """
    Nhận yêu cầu từ frontend để tick/untick một ô.
    """
    try:
        # Sửa: Dùng await và truyền 'gc'
        result = await update_sheet_cell(
            gc,
            SPREADSHEET_ID, 
            SHEET_TITLE, 
            req.row, 
            req.col, 
            req.value
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/sheet/read")
async def read_sheet(
    sheet_name: str = Query(..., alias="sheet_name"),
    gc: AsyncioGspreadClient = Depends(get_sheet_client) # <-- Sửa: Tiêm client
):
    """
    Đọc và trả về tất cả dữ liệu từ Google Sheet (dựa theo tên).
    """
    try:
        # Sửa: Dùng await và truyền 'gc'
        data = await read_sheet_data(gc, SPREADSHEET_ID, sheet_name) 
        return {"ok": True, "data": data}
    except Exception as e:
        # Trả về lỗi 404 nếu không tìm thấy sheet
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found in spreadsheet.")
        raise HTTPException(status_code=500, detail=str(e))