import os, gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _client():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set or file not found.")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)

def export_rows(spreadsheet_id: str, title: str, rows: list[list]):
    gc = _client()
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows="100", cols="26")
    safe_rows = [[("" if c is None else str(c)) for c in row] for row in rows]
    ws.append_rows(safe_rows, value_input_option="RAW")
    return {"sheet": title, "added": len(safe_rows)}
