# app/main.py
from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict
from dotenv import load_dotenv
load_dotenv()

import json
import asyncio
import re 
import requests # <-- Giữ lại cho Tool 3
from pydantic import BaseModel # <-- Giữ lại cho Tool 3
from app.services.sheets import export_rows, read_sheet_data, update_sheet_cell 
from gspread_asyncio import AsyncioGspreadClient
from app.media import remix_video_by_scenes, SceneSegment, auto_subtitle_and_bgm
from app.routers.video import SPREADSHEET_ID
from fastapi import Request
from fastapi.responses import StreamingResponse
from app.dependencies import get_sheet_client

# ... (STREAMING_EVENTS, STREAMING_RESULTS, Imports, Lifespan giữ nguyên) ...
from fastapi import (
    FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Depends
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from app.services.sheets import _get_async_client_manager
from app.dependencies import get_sheet_client 
from .media import auto_subtitle_and_bgm, flip_video_horizontal, upload_to_dropbox
from app.routers import analyze, keywords, export, mvp, video
from app.routers.video import _to_public_url

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server đang khởi động...")
    print("Đang xác thực Google Sheet Client...")
    try:
        agcm = _get_async_client_manager()
        gc = await agcm.authorize()
        app.state.gc = gc 
        print("Xác thực Google Sheet Client thành công.")
    except Exception as e:
        print(f"LỖI NGHIÊM TRỌNG: Không thể xác thực Google Sheet: {e}")
        app.state.gc = None 
    
    yield
    
    print("Server đang tắt.")

app = FastAPI(
    title="Marketing Flow Automation",
    description="MVP: Analyze URL+Keyword combined (Gemini), plus individual endpoints",
    version="0.3.1",
    lifespan=lifespan
)

JOB_STATUS: Dict[str, Dict] = {}

# ... (Hàm run_video_job giữ nguyên) ...
async def run_video_job(
    job_id: str,
    temp_video_path: str,
    final_output_path: str,
    bgm_path: Optional[str],
    language: Optional[str],
    burn_in: bool,
    temp_workdir: Path,
    flip_video: bool
):
    try:
        video_to_process = temp_video_path
        
        if flip_video:
            flipped_path = str(temp_workdir / "flipped.mp4")
            try:
                await run_in_threadpool(flip_video_horizontal, temp_video_path, flipped_path, do_upload=False)
                video_to_process = flipped_path
            except Exception as e:
                JOB_STATUS[job_id] = {"status": "failed", "error": f"Failed to flip video: {e}"}
                shutil.rmtree(temp_workdir)
                return
        
        final_path_str = await run_in_threadpool(
            auto_subtitle_and_bgm,
            video_path=video_to_process,
            output_path=final_output_path,
            bgm_path=bgm_path,
            language=language,
            burn_in=burn_in,
            do_upload=False 
        )
        JOB_STATUS[job_id] = {"status": "complete", "path": final_path_str}
    
    except Exception as e:
        JOB_STATUS[job_id] = {"status": "failed", "error": str(e)}
    
    finally:
        if temp_workdir.exists():
            shutil.rmtree(temp_workdir)

# --- [GIỮ LẠI] HELPER GỌI WEBHOOK NỀN (CHO TOOL 3) ---
def call_n8n_webhook_in_background(
    webhook_url: str, 
    payload: dict
):
    try:
        requests.post(webhook_url, json=payload, timeout=5)
        print(f"Đã kích hoạt webhook cho job: {payload.get('callback_job_id')}")
    except requests.exceptions.ReadTimeout:
        pass 
    except Exception as e:
        print(f"LỖI khi gọi webhook nền: {e}")
# --- KẾT THÚC ---

# ... (Hàm _normalize_tiktok_url_main, _find_sheet_cell_coords_main, _upload_and_update_remix_sheet, run_remix_job giữ nguyên) ...
def _normalize_tiktok_url_main(url: str) -> str:
    if not url: return ""
    url_no_params = url.split('?')[0]
    return url_no_params
async def _find_sheet_cell_coords_main(
    gc: AsyncioGspreadClient,
    sheet_title: str,
    lookup_url: str, # Đây là URL đã được chuẩn hóa
    target_col_name: str,
    url_col_name: str = "Link Video gốc"
) -> (Optional[int], Optional[int]):
    try:
        data = await read_sheet_data(gc, SPREADSHEET_ID, sheet_title)
        if not data:
            print(f"[main.py] Sheet '{sheet_title}' trống.")
            return None, None
        headers = [str(h).strip().lower() for h in data[0]]
        try:
            url_col_idx = headers.index(url_col_name.lower())
        except ValueError:
            print(f"[main.py] LỖI: Không tìm thấy cột URL '{url_col_name}' in sheet '{sheet_title}'.")
            return None, None
        try:
            target_col_idx = headers.index(target_col_name.lower())
        except ValueError:
            print(f"[main.py] LỖI: Không tìm thấy cột Target '{target_col_name}' in sheet '{sheet_title}'.")
            return None, None
        for i, row in enumerate(data[1:]):
            if not row or len(row) <= url_col_idx:
                continue
            sheet_url_raw = row[url_col_idx]
            if not sheet_url_raw:
                continue
            sheet_url_normalized = _normalize_tiktok_url_main(sheet_url_raw)
            if sheet_url_normalized == lookup_url: 
                target_row = i + 2
                target_col = target_col_idx + 1
                return target_row, target_col
        print(f"[main.py] CẢNH BÁO: Không tìm thấy URL '{lookup_url}' in column '{url_col_name}'.")
        return None, None
    except Exception as e:
        print(f"[main.py] Lỗi khi đọc/tìm kiếm sheet '{sheet_title}': {e}")
        return None, None
async def _upload_and_update_remix_sheet(
    gc: AsyncioGspreadClient,
    local_file_path: str,
    keyword: str,
    source_url: str
) -> str:
    SHEET_TITLE = "Source Chỉnh sửa Video"
    URL_COLUMN = "Link Video gốc"
    TARGET_COLUMN = "Remix Video Link"
    dropbox_url = upload_to_dropbox(local_file_path)
    print(f"Đã tải lên Dropbox: {dropbox_url}")
    normalized_lookup_url = _normalize_tiktok_url_main(source_url)
    (target_row, target_col) = await _find_sheet_cell_coords_main(
        gc,
        SHEET_TITLE,
        normalized_lookup_url,
        TARGET_COLUMN,
        URL_COLUMN
    )
    if target_row and target_col:
        print(f"[main.py] Đang cập nhật sheet '{SHEET_TITLE}' tại ô (R{target_row}, C{target_col})...")
        await update_sheet_cell(
            gc,
            SPREADSHEET_ID,
            SHEET_TITLE,
            target_row,
            target_col,
            dropbox_url
        )
        print(f"[main.py] Cập nhật link Dropbox vào sheet thành công.")
    else:
        print(f"[main.py] CẢNH BÁO: Không tìm thấy hàng cho URL '{normalized_lookup_url}' trong sheet '{SHEET_TITLE}'. Không thể cập nhật link Dropbox.")
    return dropbox_url
async def run_remix_job(
    job_id: str,
    gc: AsyncioGspreadClient, 
    temp_workdir: Path,
    source_video_path: str,
    source_url: str,
    keyword: str,
    do_remix: bool,
    highlights_json: str,
    segments_json: str,
    bgm_path_str: Optional[str],
    remove_original_audio: bool,
    burn_in: bool,
    flip_video: bool
):
    try:
        video_to_process = source_video_path
        if do_remix:
            print(f"[{job_id}] Bắt đầu Remix...")
            try:
                highlights_data = json.loads(highlights_json)
                highlights = [SceneSegment(**s) for s in highlights_data if s]
                if not highlights:
                    raise ValueError("Không có highlights hợp lệ để remix.")
                remix_path = str(temp_workdir / "remixed.mp4")
                await run_in_threadpool(
                    remix_video_by_scenes,
                    video_to_process, 
                    remix_path, 
                    highlights
                )
                video_to_process = remix_path
                print(f"[{job_id}] Remix hoàn tất.")
            except Exception as e_remix:
                print(f"[{job_id}] LỖI Remix: {e_remix}. Sẽ dùng video gốc.")
                video_to_process = source_video_path 
        if flip_video:
            print(f"[{job_id}] Bắt đầu Flip...")
            flipped_path = str(temp_workdir / "flipped.mp4")
            try:
                await run_in_threadpool(flip_video_horizontal, video_to_process, flipped_path, do_upload=False)
                video_to_process = flipped_path
                print(f"[{job_id}] Flip hoàn tất.")
            except Exception as e_flip:
                JOB_STATUS[job_id] = {"status": "failed", "error": f"Failed to flip video: {e_flip}"}
                shutil.rmtree(temp_workdir)
                return
        print(f"[{job_id}] Bắt đầu Subtitle/BGM...")
        stem = Path(video_to_process).stem
        out_name = f"{stem}_{job_id}.mp4" if burn_in else f"{stem}_{job_id}.mkv"
        final_output_path = str(EXPORTS_DIR / out_name)
        await run_in_threadpool(
            auto_subtitle_and_bgm,
            video_path=video_to_process,
            output_path=final_output_path,
            bgm_path=bgm_path_str,
            language=None, 
            segments_json=segments_json,
            burn_in=burn_in,
            remove_original_audio=remove_original_audio,
            do_upload=False 
        )
        print(f"[{job_id}] Subtitle/BGM hoàn tất. Path: {final_output_path}")
        print(f"[{job_id}] Bắt đầu Upload và cập nhật Sheet...")
        await _upload_and_update_remix_sheet(
            gc=gc,
            local_file_path=final_output_path,
            keyword=keyword,
            source_url=source_url
        )
        JOB_STATUS[job_id] = {"status": "complete", "path": final_output_path}
    except Exception as e:
        print(f"[{job_id}] LỖI NGHIÊM TRỌNG: {e}")
        JOB_STATUS[job_id] = {"status": "failed", "error": str(e)}
    finally:
        if temp_workdir.exists():
            shutil.rmtree(temp_workdir)

# --- [GIỮ LẠI] ENDPOINTS CHO POLLING (CHỈ DÀNH CHO TOOL 3) ---
class PublishRequest(BaseModel):
    row_index: int
    video_title: str
    webhook_url: str 

# (ĐÃ XÓA endpoint /reports/start-refresh và class ReportRefreshRequest)

@app.post("/publish/start", tags=["Publishing"])
async def start_publishing_job(
    req: PublishRequest,
    background_tasks: BackgroundTasks
):
    job_id = str(uuid4())
    JOB_STATUS[job_id] = {"status": "processing"}
    n8n_payload = {
        "row_index": req.row_index,
        "title": req.video_title,
        "event": "ready_for_processing",
        "callback_job_id": job_id
    }
    background_tasks.add_task(
        call_n8n_webhook_in_background,
        req.webhook_url,
        n8n_payload
    )
    return {"status": "processing", "job_id": job_id}

@app.post("/publish/complete/{job_id}", tags=["Publishing"])
async def complete_publishing_job(job_id: str):
    if job_id not in JOB_STATUS:
        print(f"CẢNH BÁO: Job ID {job_id} không tìm thấy trong JOB_STATUS.")
        return {"status": "job_not_found", "job_id": job_id}
    JOB_STATUS[job_id] = {"status": "complete"}
    print(f"Job {job_id} đã hoàn tất.")
    return {"status": "complete", "job_id": job_id}
# --- [KẾT THÚC] ---


# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers ----
app.include_router(analyze.router,  prefix="/analyze",  tags=["Analyze URL"])
app.include_router(keywords.router, prefix="/keywords", tags=["Keyword Report"])
app.include_router(export.router,   prefix="/export",   tags=["Export"])
app.include_router(mvp.router,      prefix="/mvp",      tags=["MVP"])
app.include_router(video.router, tags=["Video"])

# ---- Static media ----
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")
TEMP_DIR = Path(MEDIA_ROOT) / "temp_uploads"
EXPORTS_DIR = Path(MEDIA_ROOT) / "exports"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

# ---- Health & debug ----
@app.get("/health")
def health():
    return {"status": "ok"}
# ... (các endpoint debug khác giữ nguyên) ...
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

# ---- Auto-subtitle endpoint (Tool 3 CŨ) ----
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


# ---- Endpoint MỚI (Tool 3 MỚI) ----
@app.post("/process-remix", tags=["Video"])
async def process_remix_video(
    background_tasks: BackgroundTasks,
    gc: AsyncioGspreadClient = Depends(get_sheet_client), 
    
    source_video_path: str = Form(...),
    source_url: str = Form(...),
    keyword: str = Form(...),
    do_remix: bool = Form(False),
    highlights_json: str = Form("[]"),
    segments_json: str = Form("[]"),
    remove_original_audio: bool = Form(False),
    burn_in: bool = Form(True),
    flip_video: bool = Form(False),
    bgm: Optional[UploadFile] = File(None)
):
    job_id = str(uuid4())
    workdir = TEMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    
    bgm_path_str: Optional[str] = None
    
    try:
        if bgm:
            bgm_path = workdir / (bgm.filename or "music.mp3")
            try:
                with bgm_path.open("wb") as f:
                    await run_in_threadpool(shutil.copyfileobj, bgm.file, f)
            finally:
                await bgm.close()
            bgm_path_str = str(bgm_path) # <-- ĐÃ SỬA LỖI TYPO (từ bgGg)
            
        if not os.path.exists(source_video_path):
             raise HTTPException(status_code=404, detail=f"Source video path not found: {source_video_path}")

    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "failed", "error": f"File save error: {e}"})

    JOB_STATUS[job_id] = {"status": "processing"}

    background_tasks.add_task(
        run_remix_job,
        job_id,
        gc,
        workdir,
        source_video_path,
        source_url,
        keyword,
        do_remix,
        highlights_json,
        segments_json,
        bgm_path_str,
        remove_original_audio,
        burn_in,
        flip_video
    )

    return {"status": "processing", "job_id": job_id}



# ---- Endpoint to check job status ----
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