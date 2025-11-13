# app/routers/video.py
# ====================
# Video download + analysis + TikTok viral analyze.

# --- STANDARD LIB ---
import os
import time
import uuid
import string
import pathlib
import subprocess
import urllib.parse
import shutil
import re
from typing import List, Optional, Dict, Any

# --- THIRD-PARTY ---
import cv2
import numpy as np
import requests
from yt_dlp import YoutubeDL
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl

# --- PATHS / CONFIG ---
MEDIA_ROOT = pathlib.Path(os.getenv("MEDIA_ROOT", "media")).resolve()
VIDEO_DIR = MEDIA_ROOT / "videos"
AUDIO_DIR = MEDIA_ROOT / "audio"
THUMB_DIR = MEDIA_ROOT / "thumbnails"

# Use env var for portability; if you prefer hard-code, replace with:
# FFMPEG_BIN = r"D:\tools\ffmpeg\bin\ffmpeg.exe"
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")

for d in (VIDEO_DIR, AUDIO_DIR, THUMB_DIR):
    d.mkdir(parents=True, exist_ok=True)

TIKTOK_PROXY = os.getenv("TIKTOK_PROXY", "https://tiktok.infrabases.com")

# Desktop UA to avoid bot walls
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

router = APIRouter(prefix="/video", tags=["Video"])

# ---------- MODELS ----------
class DownloadResp(BaseModel):
    ok: bool
    source_url: str
    saved_path: str
    bytes: int
    note: Optional[str] = None
    saved_url: Optional[str] = None  # public URL (so frontend can load it)

class SceneCut(BaseModel):
    frame_idx: int
    ts_sec: float
    diff_score: float

class AnalyzeResp(BaseModel):
    ok: bool
    path: str
    width: int
    height: int
    fps: float
    frames: int
    duration_sec: float
    mean_brightness: float
    motion_score: float
    scene_cuts: List[SceneCut]
    thumbnails: List[str]

class AllInOneResp(BaseModel):
    download: DownloadResp
    analysis: AnalyzeResp

class SceneSegment(BaseModel):
    start_sec: float
    end_sec: float
    duration_sec: float

# --- 3.1 Content deliverables models ---
class PlatformCaptions(BaseModel):
    facebook: str
    instagram: str
    tiktok: str
    youtube_shorts: str

class ContentDeliverables(BaseModel):
    # Artifacts created by backend (frontend will build captions from MVP)
    video_stub_path: str                    # downloaded video path
    carousel_images: List[str]              # public URLs of generated images
    captions: Optional[PlatformCaptions] = None  # leave empty; frontend supplies real captions
    cta_comments: Optional[List[str]] = None
    carousel_zip_url: Optional[str] = None       # optional prebuilt zip (if you add later)

class ViralAnalyzeResp(BaseModel):
    ok: bool
    source_url: str
    video_path: str
    audio_path: str
    audio_format: str
    scenes: List[SceneSegment]
    stats: Dict[str, float]
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    content_deliverables: ContentDeliverables

# ---------- HELPERS ----------
SAFE_CHARS = f"-_.() {string.ascii_letters}{string.digits}"

def _to_public_url(local_path: str) -> Optional[str]:
    """Map an absolute path inside MEDIA_ROOT to a /media/... URL for the client."""
    p = pathlib.Path(local_path)
    try:
        rel = p.resolve().relative_to(MEDIA_ROOT)
    except Exception:
        return None
    return "/media/" + rel.as_posix()

def _safe_filename(name: str, ext: str = ".mp4") -> str:
    base = "".join(c for c in name if c in SAFE_CHARS).strip().replace(" ", "_")
    if not base:
        base = f"vid_{int(time.time())}"
    return f"{base}{ext}"

def _guess_name_from_url(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        tail = pathlib.Path(p.path).name or "video"
        return tail[:64]
    except Exception:
        return "video"

def _save_bytes_to_file(b: bytes, filename: str) -> str:
    out = VIDEO_DIR / filename
    with open(out, "wb") as f:
        f.write(b)
    return str(out)

def _normalize_tiktok_url(url: str) -> str:
    """Force a stable layout for TikTok; strip troublesome params and force English."""
    if "tiktok.com" in url and "lang=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}lang=en"
    url = re.sub(r"[?&](is_copy_url|is_from_webapp|sender_device|sender_web_id|sec_user_id)=[^&]+", "", url)
    return url

def _download_via_tiktok_proxy(url: str) -> Optional[bytes]:
    """Try proxy first for TikTok."""
    stripped = url.replace("https://", "").replace("http://", "")
    try_urls = [
        f"{TIKTOK_PROXY}/{stripped}",
        f"{TIKTOK_PROXY}/?u={urllib.parse.quote(url, safe='')}",
    ]
    headers = {
        "User-Agent": UA_DESKTOP,
        "Referer": "https://www.tiktok.com/",
        "Accept": "*/*",
    }
    for u in try_urls:
        try:
            r = requests.get(u, timeout=30, stream=True, headers=headers, allow_redirects=True)
            ctype = r.headers.get("Content-Type", "").lower()
            if r.status_code == 200 and (
                ctype.startswith("video")
                or "application/octet-stream" in ctype
                or ctype == ""
            ):
                return r.content
        except Exception:
            continue
    return None

def _download_via_yt_dlp(url: str) -> str:
    """Download to VIDEO_DIR via yt-dlp and return the saved file path (raises on failure)."""
    url = _normalize_tiktok_url(url)
    outtmpl = str(VIDEO_DIR / (str(uuid.uuid4()) + ".%(ext)s"))

    # Attempts escalate: vanilla -> headers -> cookiesfrombrowser
    attempts: List[Dict[str, Any]] = []

    base_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "noprogress": True,
        "merge_output_format": "mp4",
        "format": "mp4/bestvideo+bestaudio/best",
        "retries": 3,
        "nocheckcertificate": True,
        "geo_bypass": True,
    }

    attempts.append(dict(base_opts))  # 1) vanilla
    attempts.append({                 # 2) UA + extractor args
        **base_opts,
        "http_headers": {
            "User-Agent": UA_DESKTOP,
            "Referer": "https://www.tiktok.com/",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {"tiktok": {"app_language": ["en"], "region": ["US"]}},
    })
    attempts.append({                 # 3) cookies from browser (optional)
        **attempts[-1],
        "cookiesfrombrowser": ("chrome",),  # or ("edge",)
    })

    last_err: Optional[Exception] = None
    for opts in attempts:
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = ydl.prepare_filename(info)
                candidates = [path, os.path.splitext(path)[0] + ".mp4"]
                for c in candidates:
                    if os.path.exists(c):
                        return c
                latest = max(VIDEO_DIR.glob("*"), key=lambda p: p.stat().st_mtime, default=None)
                if latest:
                    return str(latest)
        except Exception as e:
            last_err = e
            continue

    raise HTTPException(status_code=422, detail=f"TikTok download error (yt-dlp): {last_err}")

def _video_capture_meta(path: str) -> Dict[str, Any]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(400, f"Cannot open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
    cap.release()
    duration = (frames / fps) if fps > 0 else 0.0
    return dict(width=width, height=height, fps=fps, frames=frames, duration_sec=duration)

def _analyze_video_basic(path: str, sample_every: int = 10) -> AnalyzeResp:
    """Basic CV analysis: brightness, motion, naive scene cuts, and thumbnails."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(400, "Cannot open video for analysis.")

    fps  = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
    nfrm = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
    h    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
    duration = (nfrm / fps) if fps > 0 else 0.0

    prev_gray = None
    brightness_vals, motion_vals = [], []
    scene_cuts: List[SceneCut] = []
    diffs = []

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness_vals.append(float(gray.mean()))
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                score = float(diff.mean())
                motion_vals.append(score)
                diffs.append((frame_idx, score))
            prev_gray = gray
        frame_idx += 1
    cap.release()

    mean_brightness = float(np.mean(brightness_vals)) if brightness_vals else 0.0
    motion_score = float(np.mean(motion_vals)) if motion_vals else 0.0

    if diffs:
        scores = np.array([s for _, s in diffs], dtype=np.float32)
        thr = float(scores.mean() + 2.0 * scores.std())
        for fidx, s in diffs:
            if s >= thr:
                ts = fidx / fps if fps > 0 else 0.0
                scene_cuts.append(SceneCut(frame_idx=fidx, ts_sec=ts, diff_score=float(s)))

    # thumbnails (3 points)
    thumbs = []
    points = [0.15, 0.5, 0.85] if nfrm > 0 else []
    cap = cv2.VideoCapture(path)
    for p in points:
        target = int(max(0, min(nfrm - 1, round(nfrm * p))))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = cap.read()
        if ok:
            name = f"{uuid.uuid4().hex}_t{target}.jpg"
            out = THUMB_DIR / name
            cv2.imwrite(str(out), frame)
            thumbs.append(_to_public_url(str(out)) or str(out))
    cap.release()

    return AnalyzeResp(
        ok=True, path=path, width=w, height=h, fps=fps, frames=nfrm,
        duration_sec=duration, mean_brightness=mean_brightness,
        motion_score=motion_score, scene_cuts=scene_cuts, thumbnails=thumbs
    )

# ---------- FFmpeg helpers ----------
def _resolve_ffmpeg_path() -> str:
    """Return absolute path to ffmpeg or raise a clear error."""
    exe = FFMPEG_BIN
    if os.path.sep in exe or (os.path.altsep and os.path.altsep in exe):
        ap = os.path.abspath(exe)
        if os.path.isfile(ap):
            return ap
        raise HTTPException(500, f"FFmpeg not found at '{exe}'. Set FFMPEG_BIN to a valid full path.")
    which = shutil.which(exe)
    if which and os.path.isfile(which):
        return which
    raise HTTPException(500, "FFmpeg not found on PATH and FFMPEG_BIN is not a valid path.")

def _ffmpeg_preflight() -> str:
    exe = _resolve_ffmpeg_path()
    try:
        out = subprocess.run([exe, "-version"], check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return out.stdout.splitlines()[0]
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"FFmpeg exists but failed: {e.stdout[:300]}")

def _extract_audio_ffmpeg(video_path: str, out_ext: str = ".mp3", abr: str = "192k") -> str:
    """Extract audio track with ffmpeg. Returns audio file path."""
    exe = _resolve_ffmpeg_path()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    audio_file = AUDIO_DIR / f"{stem}{out_ext.lower()}"

    cmd = [exe, "-y", "-i", video_path, "-vn"]
    if out_ext.lower() == ".mp3":
        cmd += ["-acodec", "libmp3lame", "-ab", abr]
    elif out_ext.lower() == ".wav":
        cmd += ["-acodec", "pcm_s16le", "-ac", "1", "-ar", "44100"]
    else:
        raise HTTPException(400, f"Unsupported audio extension: {out_ext}. Use .mp3 or .wav")
    cmd += [str(audio_file)]

    try:
        cmd = [str(c) for c in cmd]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return str(audio_file)
    except FileNotFoundError:
        raise HTTPException(500, f"CreateProcess failed (WinError 2). Tried exe: {exe!r}")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="ignore") if isinstance(e.stderr, (bytes, bytearray)) else str(e.stderr)
        raise HTTPException(500, f"ffmpeg audio extract failed: {err[:300]}")

# ---------- Scene detection ----------
def _detect_scenes_hsv(path: str, hist_bins: int = 32, diff_thr: float = 0.45, min_gap_frames: int = 10):
    """Scene boundary detection using HSV hist correlation. Returns (cuts, fps, nframes)."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(400, "Cannot open video for scene detection.")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
    nfrm = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    cuts = [0]
    prev_hist = None
    last_cut = 0
    idx = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [hist_bins, hist_bins], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

        if prev_hist is not None:
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            diff = 1.0 - float(corr)
            if diff >= diff_thr and (idx - last_cut) >= min_gap_frames:
                cuts.append(idx)
                last_cut = idx
        prev_hist = hist
        idx += 1

    cap.release()
    if cuts and cuts[-1] != nfrm - 1:
        cuts.append(nfrm - 1)
    return cuts, fps, nfrm

def _segments_from_cuts(cuts: List[int], fps: float) -> List[SceneSegment]:
    segs: List[SceneSegment] = []
    for i in range(len(cuts) - 1):
        start_f = cuts[i]
        end_f   = cuts[i + 1]
        start_t = max(0.0, start_f / fps if fps > 0 else 0.0)
        end_t   = max(start_t, end_f / fps if fps > 0 else start_t)
        segs.append(SceneSegment(
            start_sec=round(start_t, 3),
            end_sec=round(end_t, 3),
            duration_sec=round(end_t - start_t, 3)
        ))
    return segs

def _scene_stats(segs: List[SceneSegment]) -> Dict[str, float]:
    if not segs:
        return dict(count=0, mean=0, median=0, p90=0, shortest=0, longest=0)
    arr = np.array([s.duration_sec for s in segs], dtype=np.float32)
    return {
        "count": float(len(segs)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "p90": float(np.percentile(arr, 90)),
        "shortest": float(np.min(arr)),
        "longest": float(np.max(arr)),
    }

# ---------- 3.1 Content deliverables helpers ----------
def _extract_carousel_images(video_path: str, num_images: int = 5) -> List[str]:
    """
    Grab `num_images` evenly spaced frames and save to THUMB_DIR.
    Returns public URLs suitable for frontend use.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(400, "Cannot open video for carousel generation.")

    nfrm = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if nfrm <= 0:
        cap.release()
        return []

    idxs = np.linspace(int(nfrm * 0.05), int(nfrm * 0.95), num=num_images, dtype=int)
    urls: List[str] = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        name = f"carousel_{uuid.uuid4().hex}_f{idx}.jpg"
        out_path = THUMB_DIR / name
        cv2.imwrite(str(out_path), frame)
        public = _to_public_url(str(out_path)) or str(out_path)
        urls.append(public)

    cap.release()
    return urls

# NOTE: We intentionally return empty captions; the frontend builds real captions from MVP.
def _generate_platform_captions(_: str, __: Dict[str, float]) -> PlatformCaptions:
    return PlatformCaptions(facebook="", instagram="", tiktok="", youtube_shorts="")

def _build_content_deliverables(video_path: str,
                                source_url: str,
                                stats: Dict[str, float]) -> ContentDeliverables:
    carousel = _extract_carousel_images(video_path, num_images=5)
    caps = _generate_platform_captions(source_url, stats)  # empty placeholders (frontend will override)
    ctas = [
        "Bạn thấy điểm nào đáng bàn nhất? Bình luận để mình làm phần tiếp theo!",
        "👉 Lưu lại để xem sau & tag một người bạn cần xem!",
        "Muốn mình đào sâu phần nào trong video này? Comment nhé!",
    ]
    return ContentDeliverables(
        video_stub_path=video_path,
        carousel_images=carousel,
        captions=caps,           # kept for compatibility; values are empty strings
        cta_comments=ctas,
        carousel_zip_url=None,   # set later if you implement zipping
    )

# ---------- ENDPOINTS ----------
@router.post("/download", response_model=DownloadResp)
def download_video(url: HttpUrl):
    url = _normalize_tiktok_url(str(url))
    saved_path = None
    note = None

    # Prefer proxy for TikTok first (fast, no cookies).
    if "tiktok.com" in url:
        data = _download_via_tiktok_proxy(url)
        if data:
            fname = _safe_filename(_guess_name_from_url(url), ".mp4")
            saved_path = _save_bytes_to_file(data, fname)
            note = "Downloaded via TikTok proxy."
        else:
            note = "Proxy failed; falling back to yt-dlp."

    if not saved_path:
        try:
            saved_path = _download_via_yt_dlp(url)
        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(422, f"Downloader error: {e}")

        if not os.path.exists(saved_path):
            raise HTTPException(422, "Download failed (file missing after yt-dlp).")

    return DownloadResp(
        ok=True,
        source_url=url,
        saved_path=saved_path,
        bytes=os.path.getsize(saved_path),
        note=note,
        saved_url=_to_public_url(saved_path)
    )

@router.post("/analyze", response_model=AnalyzeResp)
def analyze_video(path: Optional[str] = Query(None), url: Optional[HttpUrl] = Query(None)):
    if not path and not url:
        raise HTTPException(400, "Provide either 'path' or 'url'.")

    local_path = None
    if path:
        local_path = path
        if not os.path.exists(local_path):
            raise HTTPException(404, f"File not found: {local_path}")
    else:
        dl = download_video(url=url)  # reuse logic
        local_path = dl.saved_path

    meta = _video_capture_meta(local_path)
    analysis = _analyze_video_basic(local_path)

    analysis.width  = meta["width"]
    analysis.height = meta["height"]
    analysis.fps    = meta["fps"]
    analysis.frames = meta["frames"]
    analysis.duration_sec = meta["duration_sec"]

    return analysis

@router.post("/download-and-analyze", response_model=AllInOneResp)
def download_and_analyze(url: HttpUrl):
    dl = download_video(url=url)
    analysis = analyze_video(path=dl.saved_path)
    return AllInOneResp(download=dl, analysis=analysis)

@router.post("/viral-analyze", response_model=ViralAnalyzeResp)
def viral_analyze(
    url: HttpUrl,
    audio_ext: str = Query(".mp3", pattern=r"^\.(mp3|wav)$"),
    scene_sensitivity: float = Query(0.45, ge=0.1, le=0.9),
    min_scene_gap_frames: int = Query(10, ge=1)
):
    """
    Viral analysis for TikTok (and others via yt-dlp):
      - Input: TikTok link
      - Output: audio file (.mp3/.wav) + scene segments (start/end/duration)
               + 3.1 Content deliverables (carousel images; captions left empty for frontend MVP)
    """
    # 1) Download video
    dl = download_video(url=url)
    video_path = dl.saved_path

    # 2) Extract audio
    _ffmpeg_preflight()
    audio_path = _extract_audio_ffmpeg(video_path, out_ext=audio_ext)
    audio_format = os.path.splitext(audio_path)[1].lstrip(".").lower()

    # 3) Scene detection -> segments + stats
    cuts, fps, _ = _detect_scenes_hsv(
        video_path,
        hist_bins=32,
        diff_thr=scene_sensitivity,
        min_gap_frames=min_scene_gap_frames
    )
    segs = _segments_from_cuts(cuts, fps)
    stats = _scene_stats(segs)

    # 4) Build 3.1 Content deliverables (images; captions empty to be filled by MVP on frontend)
    content_deliv = _build_content_deliverables(
        video_path=video_path,
        source_url=str(url),
        stats=stats
    )

    return ViralAnalyzeResp(
        ok=True,
        source_url=str(url),
        video_path=video_path,
        audio_path=audio_path,
        audio_format=audio_format,
        scenes=segs,
        stats=stats,
        video_url=_to_public_url(video_path),
        audio_url=_to_public_url(audio_path),
        content_deliverables=content_deliv,
    )