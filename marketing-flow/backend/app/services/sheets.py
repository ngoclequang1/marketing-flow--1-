import os
import gspread
import gspread_asyncio
from google.oauth2.service_account import Credentials
from gspread import Cell
# Thêm import cho type hint của client
from gspread_asyncio import AsyncioGspreadClient
from typing import List, Optional, Sequence
from itertools import islice
import asyncio

# =============================
# CONFIG
# =============================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# =============================
# AUTH FUNCTIONS
# =============================
def _get_creds():
    """Load Google credentials from environment variable."""
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set or file not found.")
    return Credentials.from_service_account_file(creds_path, scopes=SCOPES)


def _get_async_client_manager():
    """Create async manager for gspread client."""
    return gspread_asyncio.AsyncioGspreadClientManager(_get_creds)


# =============================
# UTILITY
# =============================
def _chunked(iterable, n):
    """Yield successive n-sized chunks from iterable."""
    iterator = iter(iterable)
    for first in iterator:
        yield [first, *list(islice(iterator, n - 1))]


# =============================
# MAIN FUNCTIONS (ALL ASYNC)
# CÁC HÀM NÀY GIỜ ĐÂY SẼ NHẬN CLIENT ĐÃ XÁC THỰC
# =============================

async def export_rows(
    gc: AsyncioGspreadClient,  # <-- SỬA: Nhận client đã xác thực
    spreadsheet_id: str,
    title: str,
    rows: Sequence[Sequence[object]],
    header_row: Optional[Sequence[str]] = None,
    checkbox_columns: Optional[Sequence[str]] = None,
):
    """
    Export data to a Google Sheet with checkbox columns (from your File 2).
    Checkboxes appear as real ☐ / ☑ cells (no TRUE/FALSE text).
    """
    # --- BỎ ĐI: Không xác thực lại ở đây ---
    # agcm = _get_async_client_manager()
    # gc = await agcm.authorize()
    
    # Sử dụng 'gc' được truyền vào
    sh = await gc.open_by_key(spreadsheet_id)

    # --- Open or create worksheet ---
    try:
        ws = await sh.worksheet(title)
        print(f"📄 Using existing worksheet: {title}")
    except gspread.WorksheetNotFound:
        ws = await sh.add_worksheet(title=title, rows="100", cols="26")
        print(f"📄 Created new worksheet: {title}")

    # --- Determine sheetId ---
    sheet_id = getattr(ws, "id", None)
    if not sheet_id:
        props = getattr(ws, "_properties", {})
        sheet_id = props.get("sheetId")
    if not sheet_id:
        raise RuntimeError("Unable to determine worksheet sheetId for batch requests.")

    # =============================
    # CASE 1: HEADER PROVIDED
    # =============================
    if header_row:
        # --- Write header if missing ---
        try:
            existing_values = await ws.get_values("1:1")
            if not existing_values or len(existing_values[0]) < len(header_row):
                header_cells = [Cell(row=1, col=i + 1, value=v) for i, v in enumerate(header_row)]
                await ws.update_cells(header_cells, value_input_option="RAW")
                print("🧩 Header row added.")
        except Exception as e:
            print(f"Warning: Failed to check/add header row: {e}")

        # --- Freeze + bold header ---
        try:
            await sh.batch_update({
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                    {
                        "repeatCell": {
                            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold",
                        }
                    },
                ]
            })
        except Exception as e:
            print(f"Warning: Failed to format header: {e}")

        # --- Write data rows ---
        try:
            existing_rows_count = len(await ws.get_all_values())
        except Exception:
            existing_rows_count = 0
        
        start_row_ui = existing_rows_count + 1
        
        cells_to_update: List[Cell] = []
        for r_idx, row_data in enumerate(rows):
            row_index_ui = start_row_ui + r_idx
            for c_idx, cell_value in enumerate(row_data):
                cells_to_update.append(
                    Cell(row=row_index_ui, col=c_idx + 1, value="" if cell_value is None else str(cell_value))
                )

        for chunk in _chunked(cells_to_update, 10000):
            await ws.update_cells(chunk, value_input_option="RAW")

        # --- Add checkboxes with proper UI ---
        if checkbox_columns:
            header_map = {h.lower(): i + 1 for i, h in enumerate(header_row)}
            checkbox_cols = [
                header_map.get(col.lower())
                for col in checkbox_columns
                if header_map.get(col.lower())
            ]

            if checkbox_cols:
                requests = []
                api_start_index = start_row_ui - 1
                api_end_index = api_start_index + len(rows)
                
                for col_idx in checkbox_cols:
                    grid_range = {
                        "sheetId": sheet_id,
                        "startRowIndex": api_start_index,
                        "endRowIndex": api_end_index,
                        "startColumnIndex": col_idx - 1,
                        "endColumnIndex": col_idx,
                    }
                    
                    requests.append({
                        "setDataValidation": {
                            "range": grid_range,
                            "rule": {
                                "condition": {"type": "BOOLEAN"},
                                "showCustomUi": True,
                            },
                        }
                    })
                    requests.append({
                        "updateCells": {
                            "range": grid_range,
                            "fields": "userEnteredValue",
                        }
                    })
                
                try:
                    await sh.batch_update({"requests": requests})
                    print(f"✅ Added {len(rows)} checkbox row(s) starting at row {start_row_ui}.")
                except Exception as e:
                    print(f"Warning: failed to add checkboxes: {e}")

    # =============================
    # CASE 2: NO HEADER → APPEND
    # =============================
    else:
        safe_rows = [[("" if c is None else str(c)) for c in row] for row in rows]
        await ws.append_rows(safe_rows, value_input_option="RAW")

    print(f"✅ Exported {len(rows)} rows to sheet '{title}' successfully.")
    return {"sheet": title, "added": len(rows), "url": getattr(ws, 'url', None)}


async def update_sheet_cell(
    gc: AsyncioGspreadClient,  # <-- SỬA: Nhận client đã xác thực
    spreadsheet_id: str, 
    title: str, 
    row: int, 
    col: int, 
    value
):
    """
    (Nâng cấp từ File 1) Cập nhật một ô duy nhất.
    """
    # --- BỎ ĐI: Không xác thực lại ở đây ---
    # agcm = _get_async_client_manager()
    # gc = await agcm.authorize()

    sh = await gc.open_by_key(spreadsheet_id)
    try:
        ws = await sh.worksheet(title)
    except gspread.WorksheetNotFound:
        raise RuntimeError(f"Sheet '{title}' not found in spreadsheet.")
    
    await ws.update_cell(row, col, value)
    print(f"✅ Updated cell R{row}C{col} in sheet '{title}'.")
    return {"sheet": title, "updated_cell": f"R{row}C{col}", "new_value": value}


async def read_sheet_data(
    gc: AsyncioGspreadClient,  # <-- SỬA: Nhận client đã xác thực
    spreadsheet_id: str, 
    title: str
):
    """
    (Nâng cấp từ File 1) Đọc tất cả dữ liệu từ một sheet.
    """
    # --- BỎ ĐI: Không xác thực lại ở đây ---
    # agcm = _get_async_client_manager()
    # gc = await agcm.authorize()
    
    sh = await gc.open_by_key(spreadsheet_id)
    try:
        ws = await sh.worksheet(title)
    except gspread.WorksheetNotFound:
        raise RuntimeError(f"Sheet '{title}' not found in spreadsheet.")
    
    print(f"✅ Reading all data from sheet '{title}'.")
    values = await ws.get_all_values()
    return values

# =============================
# CÁCH SỬ DỤNG (VÍ DỤ)
# =============================

async def main():
    # --- THAY THẾ CÁC GIÁ TRỊ NÀY ---
    MY_SPREADSHEET_ID = "YOUR_SPREADSHEET_ID_HERE"
    SHEET_NAME_TO_READ = "MVP_Content_Plan"
    
    # --- SỬA: XÁC THỰC MỘT LẦN DUY NHẤT Ở ĐÂY ---
    print("Đang xác thực client...")
    agcm = _get_async_client_manager()
    try:
        # 'gc' là client đã được xác thực
        gc = await agcm.authorize() 
        print("Xác thực thành công.")
    except Exception as e:
        print(f"LỖI XÁC THỰC: {e}")
        print("Vui lòng kiểm tra file credentials.json và biến môi trường GOOGLE_APPLICATION_CREDENTIALS.")
        return # Thoát nếu không xác thực được
    # --- KẾT THÚC SỬA ---

    # 1. Ví dụ dùng read_sheet_data
    try:
        # SỬA: Truyền 'gc' vào hàm
        data = await read_sheet_data(gc, MY_SPREADSHEET_ID, SHEET_NAME_TO_READ)
        print(f"Đọc được {len(data)} hàng từ '{SHEET_NAME_TO_READ}'.")
        # print(data)
    except Exception as e:
        print(f"Lỗi khi đọc Sheet '{SHEET_NAME_TO_READ}': {e}")

    # 2. Ví dụ dùng update_sheet_cell
    try:
        # SỬA: Truyền 'gc' vào hàm
        await update_sheet_cell(gc, MY_SPREADSHEET_ID, SHEET_NAME_TO_READ, row=1, col=1, value="HELLO ASYNC")
    except Exception as e:
        print(f"Lỗi khi cập nhật ô: {e}")

    # 3. Ví dụ dùng export_rows (kiểu đơn giản, giống File 1)
    rows_to_add_simple = [
        ["Data 1", "Data 2", "Data 3"],
        ["Data 4", "Data 5", "Data 6"]
    ]
    try:
        # SỬA: Truyền 'gc' vào hàm
        await export_rows(
            gc,  # <-- THÊM gc
            spreadsheet_id=MY_SPREADSHEET_ID,
            title="SimpleExport",
            rows=rows_to_add_simple,
            header_row=None # Không có header
        )
    except Exception as e:
        print(f"Lỗi khi export đơn giản: {e}")

    # 4. Ví dụ dùng export_rows (kiểu phức tạp với header và checkbox)
    my_header = ["Tên", "Tuổi", "Đã Hoàn Thành", "Ghi Chú"]
    my_data = [
        ["Alice", 30, "TRUE", "Ghi chú 1"],
        ["Bob", 25, "FALSE", "Ghi chú 2"],
    ]
    try:
        # SỬA: Truyền 'gc' vào hàm
        await export_rows(
            gc,  # <-- THÊM gc
            spreadsheet_id=MY_SPREADSHEET_ID,
            title="ComplexExport",
            rows=my_data,
            header_row=my_header,
            checkbox_columns=["Đã Hoàn Thành"] # Cột này sẽ là checkbox
        )
    except Exception as e:
        print(f"Lỗi khi export phức tạp: {e}")


if __name__ == "__main__":
    # Đừng quên đặt biến môi trường GOOGLE_APPLICATION_CREDENTIALS
    # VÍ DỤ:
    # os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "D:\\path\\to\\your\\credentials.json"
    
    # Chạy hàm main bất đồng bộ
    asyncio.run(main())