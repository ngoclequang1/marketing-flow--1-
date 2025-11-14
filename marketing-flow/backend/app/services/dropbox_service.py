import os
import dropbox
from pathlib import Path
from typing import Optional

# --- Lấy cấu hình từ .env ---
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
DROPBOX_UPLOAD_PATH = os.getenv("DROPBOX_UPLOAD_PATH", "/MarketingAppUploads")

if not DROPBOX_ACCESS_TOKEN:
    print("CẢNH BÁO: DROPBOX_ACCESS_TOKEN chưa được set. Upload sẽ thất bại.")

def upload_to_dropbox(
    file_path: str, 
    file_name: Optional[str] = None
) -> str:
    """
    Tải một file local lên Dropbox và trả về một shared link (link chia sẻ).
    """
    if not DROPBOX_ACCESS_TOKEN:
        raise RuntimeError("DROPBOX_ACCESS_TOKEN is not set.")
    
    dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
    
    if not file_name:
        file_name = Path(file_path).name
        
    # Đường dẫn đầy đủ trên Dropbox
    dropbox_file_path = f"{DROPBOX_UPLOAD_PATH}/{file_name}"

    try:
        print(f"Bắt đầu upload lên Dropbox: {dropbox_file_path}...")
        with open(file_path, "rb") as f:
            # Upload file, ghi đè (overwrite) nếu file đã tồn tại
            dbx.files_upload(
                f.read(), 
                dropbox_file_path, 
                mode=dropbox.files.WriteMode.overwrite
            )
        
        print(f"Upload thành công. Đang tạo shared link...")

        # --- Tạo Shared Link ---
        # Kiểm tra xem link đã tồn tại chưa
        try:
            links = dbx.sharing_list_shared_links(path=dropbox_file_path, direct_only=True).links
            if links:
                url = links[0].url
            else:
                # Nếu chưa có, tạo link mới
                shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_file_path)
                url = shared_link_metadata.url
        
        except dropbox.exceptions.ApiError as e:
            # Lỗi "shared_link_already_exists" là bình thường, chúng ta sẽ lấy link cũ
            if e.error.is_shared_link_already_exists():
                links = dbx.sharing_list_shared_links(path=dropbox_file_path, direct_only=True).links
                if not links:
                    raise Exception("Lỗi: Link đã tồn tại nhưng không thể lấy được.")
                url = links[0].url
            else:
                raise e

        # Chuyển link từ ?dl=0 (preview) thành ?dl=1 (direct download)
        final_url = url.replace("?dl=0", "?dl=1")
        
        print(f"Dropbox link: {final_url}")
        return final_url

    except dropbox.exceptions.ApiError as err:
        print(f"*** Lỗi Dropbox API: {err}")
        raise RuntimeError(f"Lỗi Dropbox API: {err}")
    except Exception as err:
        print(f"*** Lỗi không xác định khi upload Dropbox: {err}")
        raise RuntimeError(f"Lỗi Dropbox: {err}")