# app/main.py
from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict, List

# 1. Imports
from fastapi import (
    FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- IMPORT CHỨC NĂNG TỪ MEDIA ---
from .media import (
    auto_subtitle_and_bgm, 
    remix_video_by_scenes,
    SceneSegment  # Import Pydantic model từ media.py
)

# 2. Correctly import all routers
from app.routers import analyze, keywords, export, mvp, video
# IMPORT THE HELPER FUNCTION FROM video.py
from app.routers.video import _to_public_url

app = FastAPI(
    title="Marketing Flow Automation",
    description="MVP: Analyze URL+Keyword combined (Gemini), plus individual endpoints",
    version="0.3.1",
)

# ---- 3. Job Status "Database" ----
# (Simple in-memory dictionary)
JOB_STATUS: Dict[str, Dict] = {}


# ---- 4. Helper function to run in the background (MODIFIED FOR FLIP) ----
def run_video_job(
    job_id: str,
    temp_video_path: str,
    final_output_path: str,
    bgm_path: Optional[str],
    language: Optional[str],
    burn_in: bool,
    temp_workdir: Path,
    flip_video: bool  # <-- ADDED FLIP PARAM
):
    """
    This is the heavy-lifting function that runs in the background.
    It updates the JOB_STATUS dictionary when it's done.
    """
    try:
        # --- Run subtitle/BGM/flip logic all at once ---
        final_path_str = auto_subtitle_and_bgm(
            video_path=temp_video_path,
            output_path=final_output_path,
            bgm_path=bgm_path,
            language=language,
            burn_in=burn_in,
            flip_video=flip_video  # <-- Pass flip param
        )
        
        # Job succeeded: update status with the final path
        if not final_path_str or not Path(final_path_str).exists():
             raise RuntimeError("Processing finished but output file was not found.")
             
        JOB_STATUS[job_id] = {"status": "complete", "path": final_path_str}
    
    except Exception as e:
        # Job failed: update status with the error
        JOB_STATUS[job_id] = {"status": "failed", "error": str(e)}
    
    finally:
        # Clean up the temporary upload directory
        if temp_workdir.exists():
            shutil.rmtree(temp_workdir)


# ---- 5. NEW: Helper function for REMIX jobs ----
def run_remix_job(
    job_id: str,
    original_video_path: str,
    scenes_to_keep: List[SceneSegment],
    final_output_path: str
):
    """
    Runs the remix (cut + concat) job in the background.
    """
    try:
        final_path_str = remix_video_by_scenes(
            input_path=original_video_path,
            output_path=final_output_path,
            scenes_to_keep=scenes_to_keep # Sửa tên tham số ở đây
        )
        
        if not final_path_str or not Path(final_path_str).exists():
             raise RuntimeError("Remix finished but output file was not found.")
        
        JOB_STATUS[job_id] = {"status": "complete", "path": final_path_str}
        
    except Exception as e:
        JOB_STATUS[job_id] = {"status": "failed", "error": f"Remix failed: {e}"}
    
    # We do NOT clean up the original video, as it's not temporary


# ---- CORS (Correct) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers (Correct) ----
app.include_router(analyze.router,  prefix="/analyze",  tags=["Analyze URL"])
app.include_router(keywords.router, prefix="/keywords", tags=["Keyword Report"])
app.include_router(export.router,   prefix="/export",   tags=["Export"])
app.include_router(mvp.router,      prefix="/mvp",      tags=["MVP"])
app.include_router(video.router, tags=["Video"])

# ---- Static media (Correct) ----
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")
# Create subdirectories for clarity
TEMP_DIR = Path(MEDIA_ROOT) / "temp_uploads"
EXPORTS_DIR = Path(MEDIA_ROOT) / "exports"
VIDEO_DIR = Path(MEDIA_ROOT) / "videos" # <-- THÊM DÒNG NÀY
TEMP_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True) # <-- THÊM DÒNG NÀY

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

# ---- Health & debug (Correct) ----
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


# ---- MODIFIED Auto-subtitle endpoint ----
@app.post("/process", tags=["Video"])
async def process_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    bgm: Optional[UploadFile] = File(None),
    burn_in: bool = Form(True),
    language: Optional[str] = Form(None),
    flip: bool = Form(False, description="Flip video horizontally")
):
    """
    Starts a background job to process the video.
    Returns a Job ID immediately.
    """
    job_id = str(uuid4())
    workdir = TEMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    
    video_path = workdir / (video.filename or "input.mp4")
    bgm_path_str: Optional[str] = None
    
    try:
        # --- Save files quickly ---
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

    # Define the *final* output path (in the public exports dir)
    stem = video_path.stem
    if flip:
        stem += "_flipped"
    
    out_name = f"{stem}_{job_id}.mp4" if burn_in else f"{stem}_{job_id}.mkv"
    # *** LƯU Ý: Vẫn lưu vào EXPORTS, không phải VIDEOS. VIDEOS là nơi lưu file GỐC. ***
    out_path = EXPORTS_DIR / out_name 

    # Set initial job status
    JOB_STATUS[job_id] = {"status": "processing"}

    # --- Add the HEAVY task to the background ---
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

    # --- Return IMMEDIATELY ---
    return {"status": "processing", "job_id": job_id}


# ---- NEW Pydantic model for Remix endpoint ----
class RemixRequest(BaseModel):
    video_path: str  # Server-side path (e.g., "media/videos/abc.mp4")
    scenes: List[SceneSegment]


# ---- NEW Remix endpoint (MODIFIED) ----
@app.post("/remix", tags=["Video"])
async def remix_video_endpoint(
    request: RemixRequest,
    background_tasks: BackgroundTasks
):
    """
    Starts a background job to remix a video based on selected scenes.
    Returns a Job ID immediately.
    """
    job_id = str(uuid4())
    
    # Resolve the full, absolute path on the server
    # Giả định video_path gửi lên là 'media/videos/abc.mp4'
    original_video_path = Path.cwd() / request.video_path
    
    if not original_video_path.exists():
        # Thử một đường dẫn tuyệt đối (fallback)
        original_video_path = Path(request.video_path)
        if not original_video_path.exists():
             raise HTTPException(status_code=404, detail=f"Original video not found at: {request.video_path}")

    # --- FIX: Lưu file remix vào VIDEO_DIR ---
    out_name = f"{original_video_path.stem}_remix_{job_id}.mp4"
    out_path = VIDEO_DIR / out_name # <-- ĐÃ THAY ĐỔI

    # Set initial job status
    JOB_STATUS[job_id] = {"status": "processing"}

    # --- Add the REMIX task to the background ---
    background_tasks.add_task(
        run_remix_job,
        job_id,
        str(original_video_path),
        request.scenes, # Sửa tên tham số
        str(out_path)
    )

    # --- Return IMMEDIATELY ---
    return {"status": "processing", "job_id": job_id}


# ---- Endpoint to check job status (MODIFIED) ----
@app.get("/process/status/{job_id}", tags=["Video"])
def get_job_status(job_id: str):
    """
    Client polls this endpoint to check if the job is done.
    """
    status = JOB_STATUS.get(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    if status["status"] == "complete":
        path = status.get("path")
        if not path or not Path(path).exists():
            status["status"] = "failed"
            status["error"] = "Job reported complete but output file was missing."
            JOB_STATUS[job_id] = status 
            return status
            
        public_url = _to_public_url(path)
        
        # --- FIX: Trả về cả server_path ---
        return {
            "status": "complete", 
            "download_url": public_url,
            "server_path": path  # <-- Đã thêm
        }
        
    return status