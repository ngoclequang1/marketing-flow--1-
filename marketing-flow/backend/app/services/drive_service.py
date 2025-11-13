import os
from pathlib import Path
from typing import Optional  # <-- 1. ĐÂY LÀ DÒNG BỊ THIẾU
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# --- 2. ĐỊNH NGHĨA SCOPES (PHẠM VI QUYỀN) ---
# Thêm quyền 'drive' vào 'spreadsheets'
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def _get_creds():
    """Tải credentials (dùng chung cho cả Sheets và Drive)."""
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set or file not found.")
    
    # Sử dụng SCOPES đã cập nhật
    return Credentials.from_service_account_file(creds_path, scopes=SCOPES)

def upload_to_drive(
    file_path: str, 
    folder_id: str, 
    file_name: Optional[str] = None # <-- Dòng này bây giờ đã hợp lệ
) -> str:
    """
    Tải một file lên thư mục Google Drive được chỉ định và trả về link
    để xem (webViewLink).
    """
    creds = _get_creds()
    service = None
    
    try:
        service = build("drive", "v3", credentials=creds)
        
        if not file_name:
            file_name = Path(file_path).name
            
        file_metadata = {
            "name": file_name,
            "parents": [folder_id] # Chỉ định thư mục để upload
        }
        
        # Xác định loại file (MIME type)
        media = MediaFileUpload(file_path, resumable=True)
        
        print(f"Bắt đầu tải lên Google Drive: {file_name}...")
        
        # Thực hiện upload
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink" # Đã xóa webContentLink
        ).execute()
        
        file_id = file.get("id")
        web_view_link = file.get("webViewLink")
        
        print(f"Đã tải lên thành công: {file_name} (ID: {file_id})")
        
        # --- QUAN TRỌNG: Chia sẻ file ---
        # Tạo quyền cho bất kỳ ai (public) cũng có thể xem
        permission = {
            "type": "anyone",
            "role": "reader"
        }
        service.permissions().create(fileId=file_id, body=permission).execute()
        
        print(f"Đã chia sẻ file (public read): {web_view_link}")
        
        # Trả về link để xem
        return web_view_link

    except HttpError as error:
        print(f"Lỗi khi upload lên Google Drive: {error}")
        raise RuntimeError(f"Lỗi Google Drive: {error}")
    except Exception as e:
        print(f"Lỗi không xác định trong drive_service: {e}")
        raise e