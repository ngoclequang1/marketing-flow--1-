# app/dependencies.py
from fastapi import Request, HTTPException
from gspread_asyncio import AsyncioGspreadClient

async def get_sheet_client(request: Request) -> AsyncioGspreadClient:
    """
    Lấy Google Sheet client đã được xác thực từ 'app.state'.
    
    Đây là một Dependency Injection:
    - Nó được gọi tự động bởi FastAPI mỗi khi router cần.
    - Nó lấy 'request' và truy cập 'request.app.state.gc'
      (nơi mà 'main.py' đã lưu client lúc khởi động).
    - Nếu 'gc' không tồn tại (lỗi khởi động), nó sẽ báo lỗi 503 Service Unavailable.
    """
    if not hasattr(request.app.state, "gc") or request.app.state.gc is None:
        raise HTTPException(
            status_code=503, 
            detail="Google Sheet service not available. Check server logs."
        )
    return request.app.state.gc