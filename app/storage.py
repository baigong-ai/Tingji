import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")


def _slugify(title: str) -> str:
    s = re.sub(r"[^\w一-龥\-]", "-", title.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40] or "untitled"


def _write_meta(mdir: Path, meta: dict) -> None:
    (mdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_meta(mdir: Path) -> dict | None:
    f = mdir / "meta.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _read_json(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _read_text(p: Path):
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def create_meeting(title: str, audio_path: str, ext: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    meeting_id = f"{ts}-{_slugify(title)}"
    mdir = DATA_DIR / meeting_id
    mdir.mkdir(parents=True, exist_ok=True)
    dst = mdir / f"audio.{ext}"
    shutil.copy(audio_path, dst)
    meta = {
        "id": meeting_id,
        "title": title,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "audio_file": f"audio.{ext}",
        "audio_wav": None,
        "duration_ms": 0,
        "status": "pending",
        "spk_count": 0,
        "error": None,
    }
    _write_meta(mdir, meta)
    return meeting_id


def list_meetings() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    items = []
    for d in DATA_DIR.iterdir():
        if not d.is_dir():
            continue
        meta = _read_meta(d)
        if meta:
            items.append(meta)
    items.sort(key=lambda m: m["created_at"], reverse=True)
    return items


def get_meeting(meeting_id: str) -> dict | None:
    mdir = DATA_DIR / meeting_id
    meta = _read_meta(mdir)
    if not meta:
        return None
    return {
        "meta": meta,
        "raw": _read_json(mdir / "raw.json"),
        "processed": _read_text(mdir / "processed.md"),
        "summary": _read_text(mdir / "summary.md"),
    }


def save_raw(meeting_id: str, raw: dict) -> None:
    (DATA_DIR / meeting_id / "raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_processed(meeting_id: str, md: str) -> None:
    (DATA_DIR / meeting_id / "processed.md").write_text(md, encoding="utf-8")


def save_summary(meeting_id: str, md: str) -> None:
    (DATA_DIR / meeting_id / "summary.md").write_text(md, encoding="utf-8")


def update_meta(meeting_id: str, **fields) -> None:
    mdir = DATA_DIR / meeting_id
    meta = _read_meta(mdir)
    if meta is None:
        return
    meta.update(fields)
    _write_meta(mdir, meta)


def delete_meeting(meeting_id: str) -> None:
    mdir = DATA_DIR / meeting_id
    if mdir.exists():
        shutil.rmtree(mdir)


def meeting_dir(meeting_id: str) -> Path:
    return DATA_DIR / meeting_id
