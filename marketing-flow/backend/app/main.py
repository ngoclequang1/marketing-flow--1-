# app/main.py
from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict

# 1. Imports
from fastapi import (
    FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# --- IMPORT CHỨC NĂNG TỪ MEDIA ---
from .media import auto_subtitle_and_bgm, flip_video_horizontal

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
        video_to_process = temp_video_path
        
        # --- NEW: Run flip logic first ---
        if flip_video:
            flipped_path = str(temp_workdir / "flipped.mp4")
            try:
                # Call the new function from media.py
                flip_video_horizontal(temp_video_path, flipped_path)
                # Use the flipped video for the next step
                video_to_process = flipped_path
            except Exception as e:
                # If flip fails, stop the job
                JOB_STATUS[job_id] = {"status": "failed", "error": f"Failed to flip video: {e}"}
                shutil.rmtree(temp_workdir)
                return  # Stop execution
        
        # --- Run subtitle/BGM logic on the (possibly) flipped video ---
        final_path_str = auto_subtitle_and_bgm(
            video_path=video_to_process, # <-- Use the correct video path
            output_path=final_output_path,
            bgm_path=bgm_path,
            language=language,
            burn_in=burn_in,
        )
        # Job succeeded: update status with the final path
        JOB_STATUS[job_id] = {"status": "complete", "path": final_path_str}
    
    except Exception as e:
        # Job failed: update status with the error
        JOB_STATUS[job_id] = {"status": "failed", "error": str(e)}
    
    finally:
        # Clean up the temporary upload directory
        if temp_workdir.exists():
            shutil.rmtree(temp_workdir)


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
TEMP_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

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


# ---- 5. MODIFIED Auto-subtitle endpoint ----
@app.post("/process", tags=["Video"])
async def process_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    bgm: Optional[UploadFile] = File(None),
    burn_in: bool = Form(True),
    language: Optional[str] = Form(None),
    flip: bool = Form(False, description="Flip video horizontally") # <-- ADDED FLIP PARAM
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
                await bgm.close() # Close the BGM file too
            bgm_path_str = str(bgm_path)
    
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "failed", "error": f"File save error: {e}"})

    # Define the *final* output path (in the public exports dir)
    stem = video_path.stem
    if flip:
        stem += "_flipped"
    
    out_name = f"{stem}_{job_id}.mp4" if burn_in else f"{stem}_{job_id}.mkv"
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
        workdir,  # Pass the temp dir for cleanup
        flip      # <-- Pass flip param to the job
    )

    # --- Return IMMEDIATELY ---
    return {"status": "processing", "job_id": job_id}


# ---- 6. NEW Endpoint to check job status (FIXED) ----
@app.get("/process/status/{job_id}", tags=["Video"])
def get_job_status(job_id: str):
    """
    Client polls this endpoint to check if the job is done.
    """
    status = JOB_STATUS.get(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    if status["status"] == "complete":
        # --- FIX: Check if path exists before using it ---
        path = status.get("path")
        if not path:
            # If status is "complete" but path is None, the job failed.
            status["status"] = "failed"
            status["error"] = "Job reported complete but output path was missing."
            JOB_STATUS[job_id] = status # Update the global status
            return status # Return the new failed status
            
        # Convert the file path to a public URL for download
        public_url = _to_public_url(path)
        
        # (We no longer pop the job, so the user can refresh and get the link again)
        
        return {"status": "complete", "download_url": public_url}
        
    return status