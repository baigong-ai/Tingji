import asyncio
import logging
import socket
from pathlib import Path

from fastapi import (
    BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import asr, audio, storage, tasks
from app.config import Config, load_config
from app.dns_hosts import install_if_present as install_dns_hosts

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Optional DNS override: read dns_hosts.txt if present (helps on machines
# where mDNSResponder can't resolve modelscope.cn but direct IP access works).
if install_dns_hosts():
    log.info("dns_hosts.txt loaded")

CONFIG_PATH = Path("config.yaml")
config: Config = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else None

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="FunASR Meeting Transcription")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ALLOWED_AUDIO_EXTS = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "webm"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/m/{meeting_id}", response_class=HTMLResponse)
async def meeting_page(meeting_id: str):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    return (STATIC_DIR / "meeting.html").read_text(encoding="utf-8")


@app.post("/api/upload")
async def upload(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    title: str = Form(...),
):
    ext = (audio.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(415, detail=f"unsupported format: {ext}")
    uploads_dir = storage.DATA_DIR / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = uploads_dir / f"upload_{asyncio.get_event_loop().time()}.{ext}"
    tmp_path.write_bytes(await audio.read())
    meeting_id = storage.create_meeting(title=title, audio_path=str(tmp_path), ext=ext)
    tmp_path.unlink(missing_ok=True)
    state = tasks.register_task(meeting_id)
    background_tasks.add_task(tasks.run_pipeline, meeting_id, config)
    return {"task_id": state["task_id"], "meeting_id": meeting_id}


@app.get("/api/tasks/{task_id}")
async def task_status(task_id: str):
    state = tasks.get_progress(task_id)
    if state is None:
        raise HTTPException(404)
    return state


@app.get("/api/meetings")
async def list_meetings():
    return storage.list_meetings()


@app.get("/api/info")
async def server_info():
    return _collect_server_info()


def _collect_server_info() -> dict:
    host = config.server.host if config else "0.0.0.0"
    port = config.server.port if config else 8000
    ips = _lan_ipv4s()
    urls = []
    if host in ("0.0.0.0", "::", ""):
        for ip in ips:
            urls.append(f"http://{ip}:{port}")
        urls.append(f"http://127.0.0.1:{port}")
    else:
        urls.append(f"http://{host}:{port}")
    return {
        "hostname": socket.gethostname(),
        "port": port,
        "bind_host": host,
        "urls": urls,
        "lan_ips": ips,
    }


def _lan_ipv4s() -> list[str]:
    """Return non-loopback IPv4 addresses reachable on the LAN."""
    seen: set[str] = set()
    out: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip in seen:
                continue
            seen.add(ip)
            out.append(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127.") and ip not in seen:
            out.insert(0, ip)
            seen.add(ip)
    except Exception:
        pass
    return out


@app.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: str):
    data = storage.get_meeting(meeting_id)
    if data is None:
        raise HTTPException(404)
    return data


@app.get("/api/meetings/{meeting_id}/audio")
async def get_audio(meeting_id: str):
    data = storage.get_meeting(meeting_id)
    if data is None:
        raise HTTPException(404)
    audio_path = storage.meeting_dir(meeting_id) / data["meta"]["audio_file"]
    if not audio_path.exists():
        raise HTTPException(404)
    return FileResponse(audio_path)


@app.get("/api/meetings/{meeting_id}/export")
async def export(meeting_id: str, format: str = "md"):
    data = storage.get_meeting(meeting_id)
    if data is None:
        raise HTTPException(404)
    mdir = storage.meeting_dir(meeting_id)
    if format == "md":
        path = mdir / "processed.md"
        media_type = "text/markdown"
    elif format == "txt":
        text = _to_plain_text(data["raw"])
        path = mdir / "export.txt"
        path.write_text(text, encoding="utf-8")
        media_type = "text/plain"
    elif format == "srt":
        text = _to_srt(data["raw"])
        path = mdir / "export.srt"
        path.write_text(text, encoding="utf-8")
        media_type = "application/x-subrip"
    else:
        raise HTTPException(400, "format must be md/txt/srt")
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post("/api/meetings/{meeting_id}/retry-llm")
async def retry_llm(meeting_id: str, background_tasks: BackgroundTasks):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    task_id = await tasks.retry_llm(meeting_id, config)
    return {"task_id": task_id}


@app.delete("/api/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    storage.delete_meeting(meeting_id)
    return {"ok": True}


def _fmt_ts(ms: int) -> str:
    s = ms / 1000
    h, rem = divmod(int(s), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _to_plain_text(raw: dict) -> str:
    if not raw:
        return ""
    lines = []
    for s in raw.get("sentences", []):
        lines.append(f"[{_fmt_ts(s['start'])}] 说话人{s['spk']}  {s['text']}")
    return "\n".join(lines)


def _to_srt(raw: dict) -> str:
    if not raw:
        return ""
    lines = []
    for i, s in enumerate(raw.get("sentences", []), 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(s['start'])} --> {_srt_ts(s['end'])}")
        lines.append(f"[说话人{s['spk']}] {s['text']}")
        lines.append("")
    return "\n".join(lines)


def _srt_ts(ms: int) -> str:
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
