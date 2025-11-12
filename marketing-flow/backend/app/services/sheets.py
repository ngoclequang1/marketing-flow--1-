import os
import gspread_asyncio
from google.oauth2.service_account import Credentials
from gspread import Cell
from typing import List, Optional, Sequence
from itertools import islice


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
# MAIN FUNCTION
# =============================
async def export_rows(
    spreadsheet_id: str,
    title: str,
    rows: Sequence[Sequence[object]],
    header_row: Optional[Sequence[str]] = None,
    checkbox_columns: Optional[Sequence[str]] = None,
):
    """
    Export data to a Google Sheet with checkbox columns.
    Checkboxes appear as real ☐ / ☑ cells (no TRUE/FALSE text).
    """
    agcm = _get_async_client_manager()
    gc = await agcm.authorize()
    sh = await gc.open_by_key(spreadsheet_id)

    # --- Open or create worksheet ---
    try:
        ws = await sh.worksheet(title)
        print(f"📄 Using existing worksheet: {title}")
    except Exception:
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
        
        # Hàng bắt đầu (UI-based, 1-based)
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
                
                # --- SỬA LỖI LOGIC TÍNH TOÁN PHẠM VI ---
                # Google API là 0-based. Hàng UI 1 là API index 0.
                # start_row_ui là hàng UI đầu tiên ta viết (ví dụ: 2)
                # 'startRowIndex' (0-based) sẽ là start_row_ui - 1
                api_start_index = start_row_ui - 1
                
                # 'endRowIndex' là (exclusive)
                # Nó sẽ là (chỉ số bắt đầu) + (số hàng đã thêm)
                api_end_index = api_start_index + len(rows)
                
                for col_idx in checkbox_cols:
                    grid_range = {
                        "sheetId": sheet_id,
                        "startRowIndex": api_start_index, # <-- SỬA LỖI
                        "endRowIndex": api_end_index,     # <-- SỬA LỖI
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
                    # Clear text (FALSE/TRUE)
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