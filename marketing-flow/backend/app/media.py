import os
import subprocess
import tempfile
import dropbox
import gspread
import json
from pathlib import Path
from typing import Optional, List, Tuple
from tqdm import tqdm
from pydantic import BaseModel # <-- ĐÃ THÊM
from pathlib import Path
from typing import Optional
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
# ---------- FFmpeg / ffprobe resolvers ----------
def get_ffmpeg_bin() -> str:
    env = os.getenv("FFMPEG_BIN")
    if env:
        return env
    return "ffmpeg"

def get_ffprobe_bin() -> str:
    env = os.getenv("FFPROBE_BIN")
    if env:
        return env
    ff = os.getenv("FFMPEG_BIN")
    if ff:
        p = Path(ff)
        guess = p.with_name("ffprobe.exe" if p.suffix.lower() == ".exe" else "ffprobe")
        if guess.exists():
            return str(guess)
    return "ffprobe"

def ensure_ffmpeg_on_path():
    try:
        ff = get_ffmpeg_bin()
        p = Path(ff)
        if p.exists():
            ff_dir = str(p.parent)
            os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


# --- Cấu trúc dữ liệu cho Scene (ĐÃ THÊM) ---
# (Class này được dùng bởi hàm remix_video_by_scenes)
class SceneSegment(BaseModel):
    start_sec: float
    end_sec: float
    duration_sec: float


# ---------- SRT / ASS helpers ----------
def _ts_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def _ts_ass(t: float) -> str:
    # h:mm:ss.cs (centiseconds)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))  # 2 decimals
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def write_srt(segments: List[Tuple[int, float, float, str]], srt_path: str):
    lines = []
    for i, start, end, text in segments:
        lines.append(f"{i}")
        lines.append(f"{_ts_srt(start)} --> {_ts_srt(end)}")
        lines.append(text.strip())
        lines.append("")
    Path(srt_path).write_text("\n".join(lines), encoding="utf-8")

def write_ass(
    segments: List[Tuple[int, float, float, str]],
    ass_path: str,
    *,
    font: str = "Arial",
    fontsize: int = 22,
    margin_v: int = 80,
    margin_h: int = 60,
    # ASS colors are &HAABBGGRR (AA = alpha). Yellow text, black outline, translucent black box.
    primary="&H00FFFF00&",      # yellow
    outlinecol="&H00000000&",  # black
    backcol="&H60000000&",      # box ~62% opaque black
    outline: int = 1,
):
    header = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BottomBox,{font},{fontsize},{primary},&H000000FF&,{outlinecol},{backcol},0,0,0,0,100,100,0,0,3,{outline},0,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Escape ASS special chars
    def esc(t: str) -> str:
        return t.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")

    lines = [header]
    for _i, start, end, text in segments:
        txt = esc(text.strip()).replace("\n", r"\N")
        lines.append(f"Dialogue: 0,{_ts_ass(start)},{_ts_ass(end)},BottomBox,,0,0,0,,{txt}\n")
    Path(ass_path).write_text("".join(lines), encoding="utf-8")


# ---- Subtitle text shaping (wrap to ~2 lines) ----
def split_long_line(text: str, max_len: int = 36, max_lines: int = 2) -> str:
    words = text.strip().split()
    if not words:
        return ""
    lines, line = [], []
    for w in words:
        test = (" ".join(line + [w])).strip()
        if len(test) > max_len and line:
            lines.append(" ".join(line))
            line = [w]
            if len(lines) >= max_lines - 1:
                rem = words[len(" ".join(lines + line).split()):]
                line.extend(rem)
                break
        else:
            line.append(w)
    if line:
        lines.append(" ".join(line))
    return "\n".join(lines[:max_lines])


# --- probe video size to scale font/margins
def ffprobe_size(path: str) -> tuple[int, int]:
    try:
        r = subprocess.run(
            [get_ffprobe_bin(), "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return (1080, 1920)


# --- regroup into short captions using word timestamps
def regroup_segments_by_words(ws_segments, max_chars=36, max_dur=2.8):
    out = []
    idx = 1
    for seg in ws_segments:
        words = getattr(seg, "words", None)
        if not words:
            out.append((idx, seg.start, seg.end, split_long_line(seg.text, max_chars)))
            idx += 1
            continue
        buf, buf_start = [], None
        for w in words:
            if buf_start is None:
                buf_start = w.start
            candidate = " ".join([*buf, w.word]).strip()
            too_long = len(candidate) > max_chars
            too_slow = (w.end - buf_start) >= max_dur
            if (too_long or too_slow) and buf:
                text = split_long_line(" ".join(buf), max_chars)
                out.append((idx, buf_start, w.start, text)); idx += 1
                buf, buf_start = [w.word], w.start
            else:
                buf.append(w.word)
        if buf:
            text = split_long_line(" ".join(buf), max_chars)
            out.append((idx, buf_start, words[-1].end, text)); idx += 1
    return out


# --- create clean mono 16k WAV to improve ASR
def preprocess_audio(src_path: str, out_wav: str):
    cmd = [
        get_ffmpeg_bin(), "-y", "-loglevel", "error",
        "-i", src_path,
        "-vn",
        "-af", "highpass=f=180,lowpass=f=6500,afftdn=nf=-20,loudnorm=I=-18:TP=-1.5:LRA=11",
        "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le",
        out_wav
    ]
    subprocess.run(cmd, check=True)


def transcribe_to_srt(
    video_path: str,
    srt_path: str,
    language: Optional[str] = None,
    model_size: str = "base",
    compute_type: str = "int8",
) -> List[Tuple[int, float, float, str]]:
    ensure_ffmpeg_on_path()

    try:
        import torch  # type: ignore
        _has_cuda = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    except Exception:
        _has_cuda = False

    from faster_whisper import WhisperModel

    prefer = os.getenv("WHISPER_MODEL")
    try:
        if prefer:
            model = WhisperModel(prefer, device=("cuda" if _has_cuda else "cpu"),
                                 compute_type=("float16" if _has_cuda else compute_type))
        elif _has_cuda:
            try:
                model = WhisperModel("large-v3", device="cuda", compute_type="float16")
            except Exception:
                model = WhisperModel("medium", device="cuda", compute_type="float16")
        else:
            model = WhisperModel("medium", device="cpu", compute_type=compute_type)
        _ = model.transcribe(audio=video_path, language=language or "vi",
                             vad_filter=True, beam_size=1, best_of=1)
    except Exception:
        model = WhisperModel(model_size, device="cpu", compute_type=compute_type)

    # --- SỬA LỖI LOGIC: ---
    # Toàn bộ logic xử lý (preprocess, transcribe, regroup)
    # PHẢI nằm TRONG khối `with tempfile.TemporaryDirectory()`
    # để file `clean_wav` không bị xóa quá sớm.
    with tempfile.TemporaryDirectory() as _tmp:
        clean_wav = str(Path(_tmp) / "clean.wav")
        preprocess_audio(video_path, clean_wav)

        segments_gen, _info = model.transcribe(
            audio=clean_wav,
            language=language or "vi",
            task="transcribe",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=260),
            word_timestamps=True,
            temperature=[0.0, 0.2, 0.4],
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False,
            beam_size=5,
            best_of=5,
            initial_prompt="Tiếng Việt có dấu, đọc số liệu chính xác, không thêm từ thừa."
        )

        segs = regroup_segments_by_words(segments_gen, max_chars=36, max_dur=2.8)
        write_srt(segs, srt_path)  # keep an SRT for debugging/soft-sub
        return segs
    # --- KẾT THÚC SỬA LỖI ---


def safe_quote(path: str) -> str:
    p = Path(path).as_posix()
    return p.replace(":", r"\:").replace("'", r"'\''")


# ---- FFprobe helpers ----
def _ffprobe_select(path: str, stream_type: str) -> bool:
    try:
        r = subprocess.run(
            [
                get_ffprobe_bin(), "-v", "error",
                "-select_streams", f"{stream_type}:0",
                "-show_entries", "stream=index",
                "-of", "default=nw=1:nk=1",
                path,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
        return r.stdout.strip() != ""
    except Exception:
        return False

def has_video(path: str) -> bool:
    return _ffprobe_select(path, "v")

def has_audio(path: str) -> bool:
    return _ffprobe_select(path, "a")

def ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            [get_ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ---- Input validation/repair ----
def _looks_like_html(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(1024).lower()
        return b"<html" in head or b"<!doctype" in head
    except Exception:
        return False

def _has_mp4_magic(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
        return b"ftyp" in head
    except Exception:
        return False

def try_rewrap_mp4(input_path: str, output_path: str) -> bool:
    cmd = [
        get_ffmpeg_bin(), "-y", "-loglevel", "error",
        "-analyzeduration", "200M", "-probesize", "200M",
        "-fflags", "+genpts",
        "-i", input_path,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode == 0


def synthesize_black_video_with_audio(audio_src: str, out_path: str, width=1080, height=1080, fps=30):
    dur = ffprobe_duration(audio_src)
    cmd = [get_ffmpeg_bin(), "-y", "-loglevel", "error", "-stats", "-f", "lavfi"]
    if dur > 0:
        cmd += ["-t", f"{dur}"]
    cmd += [
        "-i", f"color=size={width}x{height}:rate={fps}:color=black",
        "-i", audio_src,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", out_path
    ]
    run_ffmpeg(cmd)

def synthesize_silence_for_video(video_src: str, out_path: str, sr=48000):
    dur = ffprobe_duration(video_src)
    cmd = [get_ffmpeg_bin(), "-y", "-loglevel", "error", "-stats", "-i", video_src, "-f", "lavfi"]
    if dur > 0:
        cmd += ["-t", f"{dur}"]
    cmd += [
        "-i", f"anullsrc=r={sr}:cl=stereo",
        "-shortest",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        out_path
    ]
    run_ffmpeg(cmd)


def run_ffmpeg(cmd: list) -> None:
    if cmd and Path(cmd[0]).name.lower() in ("ffmpeg", "ffmpeg.exe"):
        cmd[0] = get_ffmpeg_bin()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed (code {proc.returncode}).\nBIN: {cmd[0]}\nCMD: {' '.join(cmd)}\n\nSTDERR:\n{proc.stderr}"
        )

# Load your service account JSON
sheet_id = "1hcFoYNhmJdizx5s2id8gl_iPz_74fp5cZYz0I1bAJH8"
SERVICE_ACCOUNT_FILE = "C:\\Users\\tt\\Downloads\\ati-demo-472613-ab3aec4504a0.json"

def append_dropbox_link_to_sheet(sheet_id: str, dropbox_link: str, column_name: str = "Dropbox link"):
    """
    Append Dropbox link to a Google Sheet row matching the video name.
    """
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
 # Open sheet
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.sheet1  # or specify worksheet name

    # Ensure header row exists
    headers = worksheet.row_values(1)
    if not headers:
        worksheet.update_cell(1, 1, column_name)
        headers = [column_name]

    # Find or create Dropbox column
    if column_name not in headers:
        worksheet.update_cell(1, len(headers) + 1, column_name)
        col_index = len(headers) + 1
    else:
        col_index = headers.index(column_name) + 1

    # Find next empty row
    next_row = len(worksheet.col_values(col_index)) + 1

    # Append Dropbox link
    worksheet.update_cell(next_row, col_index, dropbox_link)
    print(f"✅ Added Dropbox link to sheet at row {next_row}, column '{column_name}'.")

# Hardcode your Dropbox access token
# Thay dropbox token của bạn vào đây
DROPBOX_ACCESS_TOKEN = "sl.u.AGEf0w_EzWqBUS2A5kBM4etZ8VJBHN6hdHQE_C61wUNz5xIaT40hVfMazYz6_z6c0bLBUuJLVIwm8ucCAhb2JQAUWb2uvniZGAGGq9NOBXBnbtQU4HiESFnQqE4HIK2lbYjp78l0mT0DcBpBoDzv1tFqpnQPCp57ADu5wbm4kfk2knyYZKMrn805L9qxs23Lw36a32nyRFhPM1iaQzurYeoRVWjR3TgAbwN7RPndJ0-qx_e6T40fAg0SzpukLuhF51uS_j5ILqYhFASVFltXMkKNgV2xfQdPcn68G9skHfdLhXGJogmEywErRz9A05TBr4W7dedepS67JnmUraR6MeISTwJdKSXT37nCX8H9YaCvqsl7zRtvfvaw7Uv3xR67IpSplpTF8cf65ifg7ZPiEM6rUBwVmjGFi1uMdO_q_piVHA3GyWvPjxpkvoHKTEDiA1H_hcz9noaWDc9pAJiO9BKEw08pyqdLQieTNroKIfBKY6p88bBBWumzySSiwZFIcruBd2UpZbPydBg79uG31ctQf7ETw_x00gA6IBpq0WToEaeRpLzL8G3vYYbvykFxftF-Sk8e4KV7c7NbxwCbj55G6UPSEwkTg3_cTT0tskdwrfIGGN_712QE2H2zW75FpLJ6groCHr3u5CXA6O2H_p3-ioZsqvDuS0MWT830nAqPD8Qx6x0gNsxCsRPT3GVwehXh_inDPWiYUuF5bVfUNJcZolbg8keT_D-Ja4eJoULyga1mRXboFatrpgdIwbHp9KgJy4en9ykGtWPwIZ4mPFzuolHPNLlqq0QI5K_u43jxUE3TDZXc0bYmodCf_q8io32RRaGUrWMD0A5IjjFJmL9v6p-EwCvHbrxbi-qT8Dq1FXLUfoi0eCzUN_BVEW76GqB0j1RBJ9B7Dwclenoj0_q6Bzfi63FNRp7Ctv5Pj1C68uYr03WSe7LwudRTEZBys0zQCL1MjnIKSJczdxXzB-QCBqfnHTH2EXRvunpkXc4Z-U8XxL3cMW58lVVk9ZRueWkSreM-R7dHBX2scDcM9LVXn3BHRuyoVwsWvWh6luxirzT3mvwonHEK9lAApUFBgKlE_W29Bpq1WWK2AVatQdLPODXNeBn7uf35EPSMIbR8YNtXXBLh3WZpZB-nYW0WOikIUaYuiHP0gMZw6d4tSPh4hEYHYUYHR5WETtOl2aa1GFbroMadmImDusjHrqAkfT9Z9Gz55lD6ZxuDyPPq-TDu_JdE-p7_N0jHNediAqsDBF6OGnp0YlYphE5YF2jzr00ttf1ATb1P7aem-qRPVzHpLoMR6s6a6t9FshrIWED6PmMX2WShhfmRn-byQlaHqMo6IjnQlYh0d7yF7TVSe7NctJ_s3WTOelOUfr4aOoZ8lrP1r5eZbsbpBCP0BnuFGOFUEh0yVWDx4IWSWvxafRXb" 
DROPBOX_UPLOAD_PATH = "/Videos"
dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)

def upload_to_dropbox(local_file_path: str, dropbox_path: str = DROPBOX_UPLOAD_PATH) -> str:
    """
    Uploads a local file to Dropbox.
    Returns the shared link.
    """
    file_name = Path(local_file_path).name
    dropbox_file_path = f"{dropbox_path}/{file_name}"

    with open(local_file_path, "rb") as f:
        dbx.files_upload(f.read(), dropbox_file_path, mode=dropbox.files.WriteMode.overwrite)

    # Create a shared link
    shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_file_path)
    return shared_link_metadata.url

### Add subtitle and BGM ###

def auto_subtitle_and_bgm(
    video_path: str,
    output_path: str,
    bgm_path: Optional[str] = None,
    language: Optional[str] = None,
    segments_json: Optional[str] = None,
    burn_in: bool = True,
    crf: int = 18,
    preset: str = "medium",
    initial_bgm_gain: float = 0.35, # <-- Giữ nguyên 0.20 (hoặc 0.35 tùy bạn)
    duck_threshold: float = 0.05,
    duck_ratio: float = 12.0,
    duck_attack_ms: int = 5,
    duck_release_ms: int = 250,
    remove_original_audio: bool = False,
    flip_video: bool = False,
    do_upload: bool = True
) -> str:
    """Generate subtitles and optionally mix or replace background music."""
    ensure_ffmpeg_on_path()

    video_path = str(Path(video_path).resolve())
    output_path = str(Path(output_path).resolve())
    os.makedirs(Path(output_path).parent, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # --- Validate / repair ---
        # (Toàn bộ khối 'Validate / repair' giữ nguyên)
        file_ok = Path(video_path).exists() and Path(video_path).stat().st_size > 0
        if not file_ok:
            raise RuntimeError("Downloaded file is empty or missing.")
        if _looks_like_html(video_path):
            raise RuntimeError("Downloaded file appears to be HTML (not media).")
        v_has_video = has_video(video_path)
        v_has_audio = has_audio(video_path)
        if not (v_has_video or v_has_audio):
            repaired = str(Path(tmp) / "rewrap.mp4")
            if try_rewrap_mp4(video_path, repaired):
                video_path = repaired
                v_has_video = has_video(video_path)
                v_has_audio = has_audio(video_path)
        if not (v_has_video or v_has_audio):
            raise RuntimeError("Input has no detectable streams.")
        if not v_has_video and v_has_audio:
            synth_path = str(Path(tmp) / "av_input.mp4")
            synthesize_black_video_with_audio(video_path, synth_path)
            video_path = synth_path
            v_has_video = v_has_audio = True
        elif v_has_video and not v_has_audio and not bgm_path:
            synth_path = str(Path(tmp) / "va_input.mp4")
            synthesize_silence_for_video(video_path, synth_path)
            video_path = synth_path
            v_has_video = v_has_audio = True

        # --- [SỬA ĐỔI] Transcribe HOẶC Dùng segments_json ---
        srt_path = str(Path(tmp) / "subs.srt")
        cues = [] # Khởi tạo list
        
        if segments_json and segments_json != "[]":
            print("[auto_subtitle] Đã nhận segments_json, bỏ qua transcription.")
            try:
                # segments_json là một chuỗi JSON của list[dict]
                segments_data = json.loads(segments_json)
                
                # Chuyển đổi nó sang định dạng 'cues' (List[Tuple[int, float, float, str]])
                for i, seg in enumerate(segments_data):
                    start = seg.get("start_sec")
                    end = seg.get("end_sec")
                    text = seg.get("text")
                    if start is not None and end is not None and text is not None:
                        cues.append((i + 1, float(start), float(end), str(text)))
                
                if not cues:
                     raise ValueError("segments_json hợp lệ nhưng không parse được cues.")
                     
                # Vẫn tạo file SRT (để dùng cho softsub nếu 'burn_in' là False)
                write_srt(cues, srt_path)

            except Exception as e_parse:
                print(f"LỖI parse segments_json: {e_parse}. Sẽ chạy transcription lại (Fallback).")
                cues = transcribe_to_srt(video_path, srt_path, language=language)
        
        else:
            # Logic cũ: Chạy transcription nếu không có segments_json
            print("[auto_subtitle] Không có segments_json, chạy transcription mới...")
            cues = transcribe_to_srt(video_path, srt_path, language=language)
        # --- KẾT THÚC SỬA ĐỔI ---

        # --- Build ASS subtitles (for hardsub) ---
        # (Khối này giữ nguyên, nó sẽ dùng 'cues' (đã sửa hoặc thô) từ bước trên)
        vw, vh = ffprobe_size(video_path)
        dyn_font = max(34, min(65, int(round(vh * 0.060))))
        dyn_margin_v = max(80, int(round(vh * 0.09)))
        dyn_margin_h = max(40, int(round(vw * 0.05)))
        ass_path = str(Path(tmp) / "subs.ass")
        write_ass(
            cues, ass_path,
            fontsize=dyn_font, margin_v=dyn_margin_v, margin_h=dyn_margin_h,
            primary="&H00FFFFFF&", # Màu trắng (như bạn đã sửa)
            outlinecol="&H00000000&",
            backcol="&H50000000&",
            outline=3
        )

        # === PHẦN SỬA LỖI BẮT ĐẦU TỪ ĐÂY ===
        
        # --- [A] XÂY DỰNG INPUTS ---
        cmd = [get_ffmpeg_bin(), "-y", "-loglevel", "error", "-stats", "-i", video_path]

        used_bgm = False
        vid_dur = ffprobe_duration(video_path)
        bgm_is_looped = False # Khởi tạo biến

        if bgm_path:
            bgm_path = str(Path(bgm_path).resolve())
            try:
                bgm_dur = ffprobe_duration(bgm_path)
            except Exception:
                bgm_dur = 0.0

            if bgm_dur and vid_dur and (bgm_dur + 0.5) < vid_dur:
                cmd += ["-stream_loop", "-1", "-i", bgm_path]
                bgm_is_looped = True
            else:
                cmd += ["-i", bgm_path]
            used_bgm = True
            
        # [SỬA] Thêm input subtitle (nếu là softsub) NGAY BÂY GIỜ
        if not burn_in:
            cmd += ["-i", srt_path]

        # --- [B] XÂY DỰNG FILTER_COMPLEX (Audio + Video Filters) ---
        filter_complex_parts = []
        out_audio_label: Optional[str] = None
        
        # Audio logic (Giữ nguyên, chỉ sửa `volume=1` thành `volume=1.5`)
        if remove_original_audio:
            if used_bgm:
                bgm_chain = "[1:a]aformat=channel_layouts=stereo,aresample=48000"
                if vid_dur and bgm_is_looped:
                    bgm_chain += f",atrim=0:{vid_dur:.3f},asetpts=N/SR/TB"
                fade_out_start = max(0.0, (vid_dur - 0.8)) if vid_dur else 0.0
                bgm_chain += (
                    f",volume={initial_bgm_gain},"
                    f"afade=t=in:st=0:d=0.8"
                )
                if vid_dur:
                    bgm_chain += f",afade=t=out:st={fade_out_start:.3f}:d=0.8"
                bgm_chain += "[aout]"
                filter_complex_parts.append(bgm_chain)
                out_audio_label = "[aout]"
            else:
                out_audio_label = None
        else:
            if used_bgm and v_has_audio:
                # [SỬA] Tăng âm lượng voice ở đây
                voice_chain = "[0:a]aformat=channel_layouts=stereo,aresample=48000,volume=1.5[voice]"
                bgm_chain = "[1:a]aformat=channel_layouts=stereo,aresample=48000"
                if vid_dur and bgm_is_looped:
                    bgm_chain += f",atrim=0:{vid_dur:.3f},asetpts=N/SR/TB"
                bgm_chain += f",volume={initial_bgm_gain}[bgmv]"
                duck = (
                    "[bgmv][voice]sidechaincompress="
                    f"threshold={duck_threshold}:ratio={duck_ratio}:attack={duck_attack_ms}:"
                    f"release={duck_release_ms}:makeup=8[ducked]"
                )
                mix = "[voice][ducked]amix=inputs=2:duration=first:weights=1 1,volume=2[aout]"
                filter_complex_parts.append(";".join([voice_chain, bgm_chain, duck, mix]))
                out_audio_label = "[aout]"
            elif used_bgm and not v_has_audio:
                bgm_chain = "[1:a]aformat=channel_layouts=stereo,aresample=48000"
                if vid_dur and bgm_is_looped:
                    bgm_chain += f",atrim=0:{vid_dur:.3f},asetpts=N/SR/TB"
                bgm_chain += f",volume={initial_bgm_gain}[aout]"
                filter_complex_parts.append(bgm_chain)
                out_audio_label = "[aout]"
            elif not used_bgm and v_has_audio:
                # [SỬA] Tăng âm lượng voice ở đây (khi không có BGM)
                voice_chain = "[0:a]aformat=channel_layouts=stereo,aresample=48000,volume=1.5[aout]"
                filter_complex_parts.append(voice_chain)
                out_audio_label = "[aout]"
            else:
                out_audio_label = None

        # Video filter logic
        video_filters = []
        if flip_video:
            video_filters.append("hflip")
        if burn_in:
            video_filters.append(f"subtitles='{safe_quote(ass_path)}'")
        
        video_filter_string = ",".join(video_filters)
        video_input_label = "0:v:0"
        video_output_label = "[vout]"
        
        if video_filter_string:
            filter_complex_parts.append(f"[{video_input_label}]{video_filter_string}{video_output_label}")
        
        if filter_complex_parts:
            cmd += ["-filter_complex", ";".join(filter_complex_parts)]

        # --- [C] XÂY DỰNG MAPPING ---
        # Map video
        if video_filter_string:
            cmd += ["-map", video_output_label] # Map video đã lọc
        else:
            cmd += ["-map", video_input_label]  # Map video gốc
            
        # Map audio
        if out_audio_label and out_audio_label != "0:a:0":
            cmd += ["-map", out_audio_label] 
        elif out_audio_label == "0:a:0":
             cmd += ["-map", "0:a:0"] # Trường hợp audio gốc, không filter
        else:
            cmd += ["-an"] 

        # [SỬA] Map subtitle (nếu là softsub)
        if not burn_in:
            srt_index = 2 if used_bgm else 1 # Input 0:video, Input 1:bgm, Input 2:srt HOẶC Input 0:video, Input 1:srt
            cmd += ["-map", f"{srt_index}:0"]

        # --- [D] XÂY DỰNG CODECS VÀ OUTPUT ---
        if burn_in or flip_video:
            cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
        else:
             if not output_path.lower().endswith(".mkv"):
                 output_path = str(Path(output_path).with_suffix(".mkv"))
             cmd += ["-c:v", "copy"]

        if out_audio_label:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        
        # [SỬA] Thêm codec subtitle (nếu là softsub)
        if not burn_in:
            cmd += ["-c:s", "srt"]
            
        cmd += ["-shortest", output_path]
        
        # === KẾT THÚC PHẦN SỬA LỖI ===

        run_ffmpeg(cmd)
        
        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
             raise RuntimeError("FFmpeg command finished but output file is missing or empty.")

        # --- Upload logic (Giữ nguyên) ---
        if do_upload:
            try:
                dropbox_url = upload_to_dropbox(output_path)
                print(f"Uploaded to Dropbox: {dropbox_url}")
                append_dropbox_link_to_sheet(sheet_id, dropbox_url)
            except Exception as e_upload:
                print(f"LỖI (media.py upload): {e_upload}")

        return output_path
# --- Hàm lật video (Giữ nguyên) ---

def flip_video_horizontal(
    input_path: str,
    output_path: str,
    crf: int = 23,
    preset: str = "fast",
    do_upload: bool = True
) -> str:
    """
    Lật video theo chiều ngang (trái sang phải) bằng FFmpeg.
    Âm thanh được sao chép mà không cần mã hóa lại.
    """
    cmd = [
        get_ffmpeg_bin(), # Dùng helper để tìm ffmpeg
        "-y",
        "-i", str(input_path),
        "-vf", "hflip",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    
    run_ffmpeg(cmd)
    if do_upload:
        try:
            dropbox_url = upload_to_dropbox(output_path)
            print(f"Uploaded to Dropbox: {dropbox_url}")
            # --- APPEND LINK TO GOOGLE SHEET ---
            append_dropbox_link_to_sheet(sheet_id, dropbox_url)
        except Exception as e_upload:
            print(f"LỖI (media.py upload flip): {e_upload}")

    # Trả về đường dẫn local
    return output_path




# --- HÀM MỚI: REMIX VIDEO ---
# (Thêm hàm này vào cuối file)

def remix_video_by_scenes(
    input_path: str,
    output_path: str,
    scenes_to_keep: List[SceneSegment],
    crf: int = 22,
    preset: str = "fast"
) -> str:
    """
    Tự động cắt và nối lại video dựa trên danh sách các SceneSegment.
    Sử dụng FFmpeg filter_complex 'concat' để nối cả video và audio.
    """
    if not scenes_to_keep:
        raise ValueError("Danh sách cảnh (scenes_to_keep) không được rỗng.")

    filter_parts = []
    stream_labels = []
    
    # 1. Tạo các phân đoạn trim (cắt) cho từng cảnh
    for i, scene in enumerate(scenes_to_keep):
        start = scene.start_sec
        end = scene.end_sec
        
        video_trim = f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS[v{i}]"
        audio_trim = f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a{i}]"
        
        filter_parts.append(video_trim)
        filter_parts.append(audio_trim)
        stream_labels.append(f"[v{i}][a{i}]")

    # 2. Tạo lệnh concat (nối)
    num_scenes = len(scenes_to_keep)
    concat_filter = f"{''.join(stream_labels)}concat=n={num_scenes}:v=1:a=1[outv][outa]"
    filter_parts.append(concat_filter)

    # 3. Xây dựng lệnh FFmpeg hoàn chỉnh
    full_filter_complex = ";".join(filter_parts)
    
    cmd = [
        get_ffmpeg_bin(), 
        "-y",
        "-i", str(input_path),
        "-filter_complex", full_filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path)
    ]
    
    run_ffmpeg(cmd)
    
    if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
       raise RuntimeError("FFmpeg remix command finished but output file is missing or empty.")

    return str(output_path)