import asyncio
import json
import logging
import os
import platform
import shutil
import socket
import urllib.request
from pathlib import Path

import yaml

from fastapi import (
    BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import asr, audio, llm, storage, tasks
from app.config import APIConfig, Config, LLMConfig, OllamaConfig, load_config
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
if config is not None:
    storage.set_data_dir(config.storage.data_dir)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="FunASR Meeting Transcription")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ALLOWED_AUDIO_EXTS = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "webm"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        headers={"cache-control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/m/{meeting_id}", response_class=HTMLResponse)
async def meeting_page(meeting_id: str):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    return HTMLResponse(
        (STATIC_DIR / "meeting.html").read_text(encoding="utf-8"),
        headers={"cache-control": "no-cache, no-store, must-revalidate"},
    )


@app.post("/api/upload")
async def upload(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    title: str = Form(...),
):
    ext = (audio.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(415, detail=f"不支持的音频格式：.{ext or '未知'}（仅支持 wav / mp3 / m4a / aac / flac / ogg / opus）")
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


@app.get("/api/settings")
async def get_settings():
    return {"data_dir": str(storage.get_data_dir())}


@app.post("/api/settings")
async def set_settings(payload: dict):
    new_dir = (payload.get("data_dir") or "").strip()
    if not new_dir:
        raise HTTPException(400, "请选择数据目录")
    try:
        p = Path(new_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        (p / ".write_test").write_text("ok", encoding="utf-8")
        (p / ".write_test").unlink()
    except Exception as e:
        raise HTTPException(400, f"该目录不可写：{e}")
    previous = str(storage.get_data_dir())
    _persist_data_dir(str(p))
    storage.set_data_dir(str(p))
    return {"data_dir": str(p), "previous_dir": previous}


@app.post("/api/settings/test")
async def test_settings(payload: dict):
    d = (payload.get("data_dir") or "").strip()
    if not d:
        raise HTTPException(400, "请选择数据目录")
    try:
        p = Path(d).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        (p / ".write_test").write_text("ok", encoding="utf-8")
        (p / ".write_test").unlink()
    except Exception as e:
        raise HTTPException(400, f"该目录不可写：{e}")
    return {"data_dir": str(p), "writable": True}


def _copytree_files_only(src: Path, dst: Path) -> None:
    """Copy src -> dst recursively using copyfile only (no metadata ops).

    shutil.copytree runs copystat on directories at the end, which fails with
    EPERM on drvfs/9p mounts (/mnt/x in WSL). This hand-rolled version only
    mkdir + copyfile, so it's safe across ext4 / 9p / NTFS.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            _copytree_files_only(item, dst / item.name)
        elif item.is_file():
            shutil.copyfile(str(item), str(dst / item.name))


@app.post("/api/settings/migrate")
async def migrate_data(payload: dict):
    from_dir = (payload.get("from_dir") or "").strip()
    if not from_dir:
        raise HTTPException(400, "请指定来源目录")
    src = Path(from_dir).expanduser().resolve()
    if not src.exists():
        raise HTTPException(400, f"来源目录不存在：{from_dir}")
    dst = storage.get_data_dir()
    moved, errors = [], []
    for item in src.iterdir():
        if not (item.is_dir() and (item / "meta.json").exists()):
            continue
        target = dst / item.name
        if target.exists():
            errors.append(f"{item.name}: target exists, skipped")
            continue
        try:
            _copytree_files_only(item, target)
            shutil.rmtree(str(item))
            moved.append(item.name)
        except Exception as e:
            errors.append(f"{item.name}: {e}")
    return {"moved": moved, "count": len(moved), "to_dir": str(dst), "errors": errors}


def _persist_data_dir(new_dir: str) -> None:
    p = Path("config.yaml")
    if not p.exists():
        return
    raw = yaml.safe_load(p.read_text()) or {}
    raw.setdefault("storage", {})["data_dir"] = new_dir
    p.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


@app.get("/api/settings/llm")
async def get_llm_settings():
    if config is None:
        return {}
    return {
        "mode": config.llm.mode,
        "api": {"base_url": config.llm.api.base_url, "model": config.llm.api.model, "has_key": bool(config.llm.api.api_key)},
        "ollama": {"base_url": config.llm.ollama.base_url, "model": config.llm.ollama.model},
    }


@app.post("/api/settings/llm")
async def set_llm_settings(payload: dict):
    if config is None:
        raise HTTPException(500, "config not loaded")
    mode = payload.get("mode", config.llm.mode)
    if mode not in ("api", "ollama"):
        raise HTTPException(400, "mode must be api or ollama")
    api = payload.get("api") or {}
    ollama = payload.get("ollama") or {}
    config.llm.mode = mode
    if api.get("base_url") is not None:
        config.llm.api.base_url = api["base_url"]
    if api.get("model"):
        config.llm.api.model = api["model"]
    if api.get("api_key"):
        config.llm.api.api_key = api["api_key"]
    if ollama.get("base_url") is not None:
        config.llm.ollama.base_url = ollama["base_url"]
    if ollama.get("model"):
        config.llm.ollama.model = ollama["model"]
    _persist_llm_config()
    return {"ok": True}


@app.post("/api/settings/llm/test")
async def test_llm_settings(payload: dict):
    cur = config.llm if config else None
    mode = payload.get("mode", cur.mode if cur else "ollama")
    if mode not in ("api", "ollama"):
        raise HTTPException(400, "mode must be api or ollama")
    api = payload.get("api") or {}
    ollama = payload.get("ollama") or {}
    cfg = LLMConfig(
        mode=mode,
        api=APIConfig(
            base_url=api.get("base_url") or (cur.api.base_url if cur else ""),
            api_key=api.get("api_key") or (cur.api.api_key if cur else ""),
            model=api.get("model") or (cur.api.model if cur else ""),
        ),
        ollama=OllamaConfig(
            base_url=ollama.get("base_url") or (cur.ollama.base_url if cur else ""),
            model=ollama.get("model") or (cur.ollama.model if cur else ""),
            api_key=(cur.ollama.api_key if cur else "ollama"),
        ),
        polish_chunk_minutes=cur.polish_chunk_minutes if cur else 6,
        temperature=cur.temperature if cur else 0.3,
        max_retries=cur.max_retries if cur else 2,
    )
    ok, reply = llm.test_connection(cfg)
    return {"ok": ok, "reply": reply if ok else None, "error": None if ok else reply}


@app.get("/api/settings/llm/models")
async def list_llm_models(base_url: str = "http://localhost:11434/v1"):
    tags_url = base_url.rstrip("/")
    if tags_url.endswith("/v1"):
        tags_url = tags_url[:-3]
    tags_url = tags_url + "/api/tags"
    try:
        req = urllib.request.Request(tags_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}


def _persist_llm_config() -> None:
    p = Path("config.yaml")
    if not p.exists():
        return
    raw = yaml.safe_load(p.read_text()) or {}
    raw.setdefault("llm", {})
    raw["llm"]["mode"] = config.llm.mode
    raw["llm"]["api"] = {
        "base_url": config.llm.api.base_url,
        "api_key": config.llm.api.api_key,
        "model": config.llm.api.model,
    }
    raw["llm"]["ollama"] = {
        "base_url": config.llm.ollama.base_url,
        "model": config.llm.ollama.model,
        "api_key": config.llm.ollama.api_key,
    }
    p.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


@app.get("/api/browse")
async def browse_dir(path: str = ""):
    """List subdirectories of a server-side path (for the directory picker UI)."""
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except Exception:
        return {"path": path, "parent": None, "dirs": [], "exists": False, "writable": False, "error": "invalid path"}
    parent = str(base.parent) if str(base.parent) != str(base) else None
    dirs, error, exists = [], None, base.exists()
    if not exists:
        error = f"path not exist: {base}"
    else:
        try:
            for item in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                if item.is_dir() and not item.name.startswith("."):
                    dirs.append({"name": item.name, "path": str(item)})
        except PermissionError:
            error = "permission denied"
        except Exception as e:
            error = str(e)
    writable = False
    if exists:
        try:
            probe = base / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except Exception:
            pass
    return {"path": str(base), "parent": parent, "dirs": dirs, "exists": exists, "writable": writable, "error": error}


def _detect_platform() -> dict:
    sysname = platform.system()
    is_wsl = False
    if sysname == "Linux":
        try:
            if "microsoft" in Path("/proc/version").read_text().lower():
                is_wsl = True
        except Exception:
            pass
    if sysname == "Darwin":
        label = "macOS"
    elif sysname == "Windows":
        label = "Windows"
    elif is_wsl:
        label = "Windows (WSL)"
    else:
        label = "Linux"
    return {
        "system": sysname,
        "is_wsl": is_wsl,
        "home_dir": os.path.expanduser("~"),
        "platform_label": label,
    }


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
        **_detect_platform(),
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
        text = _to_plain_text(data["raw"], (data.get("meta") or {}).get("speaker_names") or {})
        path = mdir / "export.txt"
        path.write_text(text, encoding="utf-8")
        media_type = "text/plain"
    elif format == "srt":
        text = _to_srt(data["raw"], (data.get("meta") or {}).get("speaker_names") or {})
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


@app.put("/api/meetings/{meeting_id}/speakers")
async def rename_speakers(meeting_id: str, payload: dict):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    names = payload.get("names", {})
    if not isinstance(names, dict):
        raise HTTPException(400, "说话人名格式错误")
    storage.update_meta(meeting_id, speaker_names=names)
    return {"ok": True, "speaker_names": names}


@app.put("/api/meetings/{meeting_id}/sentence")
async def edit_sentence(meeting_id: str, payload: dict):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    idx = payload.get("index")
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        raise HTTPException(400, "句子序号格式错误")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "句子内容不能为空")
    data = storage.get_meeting(meeting_id)
    if data is None or data.get("raw") is None:
        raise HTTPException(404, "尚无识别结果，无法编辑")
    sentences = data["raw"].get("sentences") or []
    if idx < 0 or idx >= len(sentences):
        raise HTTPException(400, "句子序号超出范围")
    sentences[idx]["text"] = text
    storage.save_raw(meeting_id, data["raw"])
    return {"ok": True, "index": idx, "text": text}


def _hotwords_path() -> Path:
    return storage.get_data_dir() / "hotwords.txt"


@app.get("/api/settings/hotwords")
async def get_hotwords():
    p = _hotwords_path()
    if not p.exists():
        return {"hotwords": []}
    words = [w.strip() for w in p.read_text(encoding="utf-8").splitlines() if w.strip()]
    return {"hotwords": words}


@app.post("/api/settings/hotwords")
async def set_hotwords(payload: dict):
    words = payload.get("hotwords") or []
    if not isinstance(words, list):
        raise HTTPException(400, "热词格式错误")
    non_empty = [str(w).strip() for w in words if str(w).strip()]
    seen, cleaned = set(), []
    for w in non_empty:
        if w not in seen:
            seen.add(w)
            cleaned.append(w)
    p = _hotwords_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(cleaned), encoding="utf-8")
    return {"ok": True, "count": len(cleaned), "duplicates": len(non_empty) - len(cleaned)}


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


def _spk_label(spk, names: dict) -> str:
    return names.get(str(spk)) or names.get(spk) or f"说话人{spk}"


def _to_plain_text(raw: dict, names: dict | None = None) -> str:
    names = names or {}
    if not raw:
        return ""
    lines = []
    for s in raw.get("sentences", []):
        lines.append(f"[{_fmt_ts(s['start'])}] {_spk_label(s['spk'], names)}  {s['text']}")
    return "\n".join(lines)


def _to_srt(raw: dict, names: dict | None = None) -> str:
    names = names or {}
    if not raw:
        return ""
    lines = []
    for i, s in enumerate(raw.get("sentences", []), 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(s['start'])} --> {_srt_ts(s['end'])}")
        lines.append(f"[{_spk_label(s['spk'], names)}] {s['text']}")
        lines.append("")
    return "\n".join(lines)


def _srt_ts(ms: int) -> str:
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
