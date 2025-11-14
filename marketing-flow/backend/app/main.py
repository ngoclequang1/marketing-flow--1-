# app/main.py
from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict
from dotenv import load_dotenv
load_dotenv()

# 1. Imports
from fastapi import (
    FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# --- THÊM: Imports cho Lifespan (Google Sheets) ---
from contextlib import asynccontextmanager
# Đảm bảo đường dẫn này đúng. Nếu file sheets.py của bạn ở app/services/sheets.py:
from app.services.sheets import _get_async_client_manager
# ---------------------------------------------------

# --- IMPORT CHỨC NĂNG TỪ MEDIA ---
# Giả sử file media.py nằm trong cùng thư mục app/
from .media import auto_subtitle_and_bgm, flip_video_horizontal

# 2. Correctly import all routers
from app.routers import analyze, keywords, export, mvp, video
# IMPORT THE HELPER FUNCTION FROM video.py
from app.routers.video import _to_public_url

# ---- 3. THÊM: Định nghĩa Lifespan cho Google Sheets ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Khởi động Server ---
    print("Server đang khởi động...")
    # Khởi tạo Google Sheet Client MỘT LẦN
    print("Đang xác thực Google Sheet Client...")
    try:
        agcm = _get_async_client_manager()
        gc = await agcm.authorize()
        # Lưu client vào 'app.state' để các request có thể dùng
        app.state.gc = gc 
        print("Xác thực Google Sheet Client thành công.")
    except Exception as e:
        print(f"LỖI NGHIÊM TRỌNG: Không thể xác thực Google Sheet: {e}")
        app.state.gc = None # Báo lỗi
    
    yield
    
    # --- Tắt Server ---
    print("Server đang tắt.")
# ------------------------------------------------------


# 4. SỬA: Khởi tạo FastAPI với Lifespan
app = FastAPI(
    title="Marketing Flow Automation",
    description="MVP: Analyze URL+Keyword combined (Gemini), plus individual endpoints",
    version="0.3.1",
    lifespan=lifespan  # <-- Thêm Lifespan vào đây
)

# ---- 5. Job Status "Database" ----
JOB_STATUS: Dict[str, Dict] = {}


# ---- 6. Helper function (Code của bạn - Giữ nguyên) ----
def run_video_job(
    job_id: str,
    temp_video_path: str,
    final_output_path: str,
    bgm_path: Optional[str],
    language: Optional[str],
    burn_in: bool,
    temp_workdir: Path,
    flip_video: bool
):
    """
    This is the heavy-lifting function that runs in the background.
    It updates the JOB_STATUS dictionary when it's done.
    """
    try:
        video_to_process = temp_video_path
        
        if flip_video:
            flipped_path = str(temp_workdir / "flipped.mp4")
            try:
                flip_video_horizontal(temp_video_path, flipped_path)
                video_to_process = flipped_path
            except Exception as e:
                JOB_STATUS[job_id] = {"status": "failed", "error": f"Failed to flip video: {e}"}
                shutil.rmtree(temp_workdir)
                return
        
        final_path_str = auto_subtitle_and_bgm(
            video_path=video_to_process,
            output_path=final_output_path,
            bgm_path=bgm_path,
            language=language,
            burn_in=burn_in,
        )
        JOB_STATUS[job_id] = {"status": "complete", "path": final_path_str}
    
    except Exception as e:
        JOB_STATUS[job_id] = {"status": "failed", "error": str(e)}
    
    finally:
        if temp_workdir.exists():
            shutil.rmtree(temp_workdir)


# ---- CORS (Code của bạn - Giữ nguyên) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers (Code của bạn - Giữ nguyên) ----
app.include_router(analyze.router,  prefix="/analyze",  tags=["Analyze URL"])
app.include_router(keywords.router, prefix="/keywords", tags=["Keyword Report"])
app.include_router(export.router,   prefix="/export",   tags=["Export"])
app.include_router(mvp.router,      prefix="/mvp",      tags=["MVP"])
app.include_router(video.router, tags=["Video"])

# ---- Static media (Code của bạn - Giữ nguyên) ----
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")
TEMP_DIR = Path(MEDIA_ROOT) / "temp_uploads"
EXPORTS_DIR = Path(MEDIA_ROOT) / "exports"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

# ---- Health & debug (Code của bạn - Giữ nguyên) ----
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/ffmpeg_cmd")
def debug_ffmpeg_cmd():
    from app.routers.video import _resolve_ffmpeg_path
    exe = _resolve_ffmpeg_path()
    return {"ffmpeg_bin": exe}

@app.get("/debug/ffmpeg")
def debug_ffmpeg():
    import subprocess
    from app.routers.video import _resolve_ffmpeg_path
    exe = _resolve_ffmpeg_path()
    try:
        out = subprocess.run(
            [exe, "-version"], check=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        return {"ok": True, "bin": exe, "version": out.stdout.splitlines()[0]}
    except Exception as e:
        return {"ok": False, "bin": exe, "err": str(e)}


# ---- Auto-subtitle endpoint (Code của bạn - Giữ nguyên) ----
@app.post("/process", tags=["Video"])
async def process_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    bgm: Optional[UploadFile] = File(None),
    burn_in: bool = Form(True),
    language: Optional[str] = Form(None),
    flip: bool = Form(False, description="Flip video horizontally")
):
    job_id = str(uuid4())
    workdir = TEMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    
    video_path = workdir / (video.filename or "input.mp4")
    bgm_path_str: Optional[str] = None
    
    try:
        try:
            with video_path.open("wb") as f:
                await run_in_threadpool(shutil.copyfileobj, video.file, f)
        finally:
            await video.close()
            
        if bgm:
            bgm_path = workdir / (bgm.filename or "music.mp3")
            try:
                with bgm_path.open("wb") as f:
                    await run_in_threadpool(shutil.copyfileobj, bgm.file, f)
            finally:
                await bgm.close()
            bgm_path_str = str(bgm_path)
    
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "failed", "error": f"File save error: {e}"})

    stem = video_path.stem
    if flip:
        stem += "_flipped"
    
    out_name = f"{stem}_{job_id}.mp4" if burn_in else f"{stem}_{job_id}.mkv"
    out_path = EXPORTS_DIR / out_name

    JOB_STATUS[job_id] = {"status": "processing"}

    background_tasks.add_task(
        run_video_job,
        job_id,
        str(video_path),
        str(out_path),
        bgm_path_str,
        language,
        burn_in,
        workdir,
        flip
    )

    return {"status": "processing", "job_id": job_id}


# ---- Endpoint to check job status (Code của bạn - Giữ nguyên) ----
@app.get("/process/status/{job_id}", tags=["Video"])
def get_job_status(job_id: str):
    status = JOB_STATUS.get(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    if status["status"] == "complete":
        path = status.get("path")
        if not path:
            status["status"] = "failed"
            status["error"] = "Job reported complete but output path was missing."
            JOB_STATUS[job_id] = status
            return status
            
        public_url = _to_public_url(path)
        
        return {"status": "complete", "download_url": public_url}
        
    return status