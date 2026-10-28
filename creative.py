"""ESN Jarvis Creative Studio: local video rendering, vector logos and app handoffs.

Opt-in subsystem, deliberately isolated from Pterodactyl/customer workloads.
All media inputs must already exist beneath ESN_MEDIA_ROOT/inputs, and all
outputs stay beneath the media root. Never execute untrusted scripts or shell.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import connections

ROOT = Path(os.environ.get("ESN_MEDIA_ROOT", "./media")).expanduser()
ENABLED = os.environ.get("ESN_CREATIVE_ENABLED", "0") == "1"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
FPS = {24, 30, 60}
SIZES = {"short": (720, 1280), "short-hd": (1080, 1920), "landscape": (1920, 1080)}
IDENT = re.compile(r"^[a-zA-Z0-9._-]{1,100}$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_RENDER_LIMIT = threading.BoundedSemaphore(1)


def workspace() -> Path:
    base = ROOT.resolve()
    for folder in ("inputs", "exports", "work"):
        (base / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
    return base


def input_asset(filename: str, allowed: set[str]) -> Path:
    if not isinstance(filename, str) or not IDENT.fullmatch(filename) or filename.startswith("."):
        raise ValueError("Use a plain input filename (no directories)")
    p = workspace() / "inputs" / filename
    if p.suffix.lower() not in allowed or not p.is_file() or p.is_symlink():
        raise ValueError("Input file does not exist or has an unsupported format")
    if not p.resolve().is_relative_to((workspace() / "inputs").resolve()):
        raise ValueError("Media asset must be inside inputs")
    if p.stat().st_size > 1024 * 1024 * 1024:
        raise ValueError("Media asset exceeds 1 GiB")
    return p


def run_tool(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError("Install FFmpeg and FFprobe on the isolated media worker") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Render or probe exceeded its time limit") from exc
    except subprocess.CalledProcessError as exc:
        # Never log arbitrary video metadata or full ffmpeg stderr.
        raise RuntimeError("Media processing failed; verify the input codecs and resources") from exc


def probe(path: Path) -> dict:
    raw = run_tool(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], 20)
    info = json.loads(raw.stdout)
    duration = float(info.get("format", {}).get("duration") or 0)
    if not (0 < duration < 3600):
        raise ValueError("Input must have a finite duration below one hour")
    if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        raise ValueError("Input must contain a video stream")
    return {"duration": duration}


def clean_title(value) -> str:
    if not isinstance(value, str) or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValueError("Titles must be up to 100 printable characters")
    return value


def validate_video_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or not isinstance(spec.get("clips"), list):
        raise ValueError("Expected a JSON edit plan with clips")
    clips = spec["clips"]
    if not 1 <= len(clips) <= 8:
        raise ValueError("1-8 clips required")
    mode = spec.get("format", "short")
    fps = spec.get("fps", 30)
    if mode not in SIZES or fps not in FPS:
        raise ValueError("Unsupported export format or frame rate")
    grade = spec.get("grade", "cinematic")
    if grade not in ("natural", "cinematic", "punchy"):
        raise ValueError("Unsupported color grade")
    plan = []
    total = 0
    for item in clips:
        if not isinstance(item, dict):
            raise ValueError("Invalid clip entry")
        path = input_asset(item.get("file"), VIDEO_EXT)
        length = probe(path)["duration"]
        start = float(item.get("start", 0))
        duration = float(item.get("duration", min(3, length - start)))
        if not (0 <= start < length and .1 <= duration <= 30 and start + duration <= length + .05):
            raise ValueError("Clip trim is outside the source duration or is too long")
        title = clean_title(item.get("title", ""))
        plan.append({"file": path, "start": start, "duration": duration, "title": title})
        total += duration
    if total > 60:
        raise ValueError("Video length must be <= 60 seconds")
    music = spec.get("music")
    audio = input_asset(music, AUDIO_EXT) if music else None
    return {"clips": plan, "duration": total, "music": audio, "format": mode, "fps": fps, "grade": grade}


def safe_name(raw: str) -> str:
    """Keep generated titles/branding out of file paths."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", raw)[:50].strip("-") or "design"


def render_video(spec: dict) -> dict:
    """Render from real uploaded/local clips; no AI generation or cloud calls.

    Crops to requested aspect ratio. Titles are burned in. Optional user-supplied
    music is mixed as the final audio track. This is a basic editing engine; it
    does not pretend to reproduce complex commercial editor effects yet.
    """
    if not _RENDER_LIMIT.acquire(blocking=False):
        raise RuntimeError("A render is already running")
    try:
        return _render_video(spec)
    finally:
        _RENDER_LIMIT.release()


def _render_video(spec: dict) -> dict:
    plan = validate_video_spec(spec)
    job_id = secrets.token_hex(12)
    export = workspace() / "exports" / f"edit-{job_id}.mp4"
    width, height = SIZES[plan["format"]]
    fps = plan["fps"]
    grade = {"natural": "eq=saturation=1.0:contrast=1.0", "cinematic": "eq=saturation=1.16:contrast=1.08,unsharp=3:3:0.45", "punchy": "eq=saturation=1.33:contrast=1.2,unsharp=3:3:0.6"}[plan["grade"]]
    with tempfile.TemporaryDirectory(prefix="esn-creative-", dir=workspace() / "work") as tmp:
        tmpdir = Path(tmp)
        segments = []
        for i, clip in enumerate(plan["clips"]):
            dest = tmpdir / f"segment_{i:02d}.mp4"
            filters = [f"scale={width}:{height}:force_original_aspect_ratio=increase", f"crop={width}:{height}", "setsar=1", f"fps={fps}", grade]
            if clip["title"]:
                caption = tmpdir / f"caption_{i:02d}.txt"
                caption.write_text(clip["title"], encoding="utf-8")
                # Internal tempdir is generated on the server and never comes from the request.
                filters.append("drawtext=textfile='" + str(caption) + "':expansion=none:fontcolor=white:fontsize=" + str(max(27, width // 14)) + ":borderw=3:bordercolor=black@0.85:x=(w-text_w)/2:y=h*0.75")
            filters.append("format=yuv420p")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-ss", str(clip["start"]), "-t", str(clip["duration"]), "-i", str(clip["file"]), "-an", "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2", "-movflags", "+faststart", str(dest)]
            run_tool(cmd, 220)
            segments.append(dest)
        listing = tmpdir / "concat.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in segments), encoding="utf-8")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-protocol_whitelist", "file,pipe", "-i", str(listing)]
        if plan["music"]:
            cmd += ["-stream_loop", "-1", "-protocol_whitelist", "file,pipe", "-i", str(plan["music"])]
            cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-af", "volume=0.8", "-t", str(plan["duration"]), "-threads", "2", "-movflags", "+faststart", str(export)]
        else:
            cmd += ["-map", "0:v:0", "-c:v", "copy", "-movflags", "+faststart", str(export)]
        run_tool(cmd, 220)
    if not export.exists() or export.stat().st_size == 0:
        raise RuntimeError("Render did not produce an output file")
    result = {"filename": export.name, "bytes": export.stat().st_size, "format": plan["format"], "width": width, "height": height, "fps": fps, "clips": len(plan["clips"])}
    result["handoff"] = create_handoff(plan, export.stem)
    return result


def create_handoff(plan: dict, base: str) -> dict:
    """Creates an editable project handoff, not a claim of CapCut remote control."""
    folder = workspace() / "exports"
    timeline = {"format": plan["format"], "fps": plan["fps"], "note": "Import the prepared clips into CapCut or After Effects. CapCut export is manual.", "clips": [], "music": plan["music"].name if plan["music"] else None}
    cursor = 0.0
    for clip in plan["clips"]:
        timeline["clips"].append({"file": clip["file"].name, "source_start": clip["start"], "timeline_start": round(cursor, 3), "duration": clip["duration"], "title": clip["title"]})
        cursor += clip["duration"]
    jsonpath = folder / f"{base}-timeline.json"
    jsonpath.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    jsxpath = folder / f"{base}-after-effects.jsx"
    jsxpath.write_text(after_effects_script(plan), encoding="utf-8")
    zipfile_path = folder / f"{base}-editor-handoff.zip"
    with zipfile.ZipFile(zipfile_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(jsonpath, jsonpath.name)
        z.write(jsxpath, jsxpath.name)
        z.writestr("README.txt", "CapCut: copy your original media and import it according to the timeline JSON. There is no official supported headless CapCut export API.\nAfter Effects: make a folder called inputs next to the JSX script and place the original source video files inside. Run File > Scripts > Run Script File in installed licensed After Effects, then render in that app.\n")
    return {"timeline": jsonpath.name, "after_effects_script": jsxpath.name, "editor_zip": zipfile_path.name}


def after_effects_script(plan: dict) -> str:
    """Generate real ExtendScript, for running only by a licensed local AE install."""
    width, height = SIZES[plan["format"]]
    # JSON is valid JS quoted syntax; no interpreted code from user-controlled text.
    clips = [{"file": v["file"].name, "start": v["start"], "duration": v["duration"], "title": v["title"]} for v in plan["clips"]]
    return """// ESN Jarvis After Effects handoff. Run inside a trusted local After Effects session.\n(function () {\n  app.beginUndoGroup('ESN Jarvis Edit');\n  try {\n    var project = app.project || app.newProject();\n    var comp = project.items.addComp('ESN Jarvis', %d, %d, 1, %s, %d);\n    var clips = %s;\n    var cursor = 0;\n    for (var i=0; i<clips.length; i++) {\n      var c = clips[i];\n      var file = new File(new File($.fileName).parent.fsName + '/inputs/' + c.file);\n      if (!file.exists) throw new Error('Missing source: ' + c.file);\n      var footage = project.importFile(new ImportOptions(file));\n      var layer = comp.layers.add(footage);\n      layer.startTime = cursor - c.start;\n      layer.inPoint = cursor;\n      layer.outPoint = cursor + c.duration;\n      if (c.title) {\n        var title = comp.layers.addText(c.title);\n        title.inPoint = cursor; title.outPoint = cursor + c.duration;\n        title.property('Position').setValue([%d, %d]);\n      }\n      cursor += c.duration;\n    }\n    alert('ESN edit prepared in After Effects. Verify composition and render manually or with aerender.');\n  } finally { app.endUndoGroup(); }\n})();\n""" % (width, height, json.dumps(plan["duration"]), plan["fps"], json.dumps(clips, ensure_ascii=True), width // 2, int(height * .78))


def logo_design(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("Expected logo design settings")
    name = spec.get("brand", "ESN")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 28 or any(ord(c) < 32 for c in name):
        raise ValueError("Brand name must be 1-28 characters")
    symbol = spec.get("symbol", "orbit")
    if symbol not in ("orbit", "monogram", "shield"):
        raise ValueError("Supported symbols: orbit, monogram, shield")
    primary = spec.get("primary", "#7C65F5")
    background = spec.get("background", "#0B1020")
    if not HEX.fullmatch(primary) or not HEX.fullmatch(background):
        raise ValueError("Colors must be #RRGGBB")
    safe = html.escape(name.strip(), quote=True)
    symbol_svg = {
        "orbit": f'<ellipse cx="128" cy="120" rx="85" ry="41" transform="rotate(-34 128 120)" fill="none" stroke="{primary}" stroke-width="11"/><circle cx="125" cy="119" r="40" fill="{primary}"/><circle cx="193" cy="64" r="14" fill="#FFFFFF"/>',
        "monogram": f'<rect x="45" y="40" width="164" height="164" rx="44" fill="{primary}"/><text x="127" y="151" text-anchor="middle" fill="#FFFFFF" font-size="82" font-weight="700" font-family="DejaVu Sans,Arial,sans-serif">{html.escape(name.strip()[0].upper())}</text>',
        "shield": f'<path d="M128 30L212 67V133Q200 192 128 224Q55 192 44 133V67Z" fill="{primary}"/><path d="M82 120L114 150L178 88" fill="none" stroke="#FFFFFF" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"/>',
    }[symbol]
    font_size = min(105, max(30, int(565 / (0.68 * max(len(name.strip()), 1)))))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="512" viewBox="0 0 1024 512"><rect width="1024" height="512" rx="70" fill="{background}"/><g transform="translate(120 125)">{symbol_svg}</g><text x="425" y="295" fill="#FFFFFF" font-family="DejaVu Sans,Arial,sans-serif" font-weight="700" font-size="{font_size}">{safe}</text><path d="M430 325H868" stroke="{primary}" stroke-width="6" stroke-linecap="round"/></svg>'''
    out = workspace() / "exports" / ("logo-" + secrets.token_hex(12))
    svg_path = out.with_suffix(".svg")
    svg_path.write_text(svg, encoding="utf-8")
    result = {"svg": svg_path.name, "format": "editable vector SVG"}
    try:
        import cairosvg
        pngpath = out.with_suffix(".png")
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(pngpath), output_width=1024, output_height=512)
        result["png"] = pngpath.name
    except ImportError:
        result["png"] = None
    return result


def asset_list() -> list[dict]:
    listing = []
    for p in (workspace() / "inputs").iterdir():
        if p.is_file() and not p.is_symlink() and IDENT.fullmatch(p.name) and p.suffix.lower() in VIDEO_EXT | AUDIO_EXT:
            listing.append({"name": p.name, "bytes": p.stat().st_size})
    return sorted(listing, key=lambda a: a["name"])[:100]


def db():
    connection = sqlite3.connect(workspace() / "studio.sqlite3", timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE IF NOT EXISTS studio_jobs(id TEXT PRIMARY KEY,kind TEXT,status TEXT,created_at TEXT,finished_at TEXT,result_json TEXT,error TEXT)")
    connection.commit()
    return connection


def enqueue(kind: str, spec: dict) -> str:
    if kind not in ("render", "logo"):
        raise ValueError("Unknown creative operation")
    ident = secrets.token_hex(12)
    with db() as con:
        con.execute("INSERT INTO studio_jobs(id,kind,status,created_at) VALUES(?,?,?,?)", (ident, kind, "queued", datetime.now(timezone.utc).isoformat()))
    # Do not store user-provided copy/prompt in databases or external systems.
    threading.Thread(target=_execute, args=(ident, kind, spec), daemon=True).start()
    return ident


def _execute(ident: str, kind: str, spec: dict):
    with db() as con:
        con.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (ident,))
    try:
        output = render_video(spec) if kind == "render" else logo_design(spec)
    except Exception as exc:
        with db() as con:
            con.execute("UPDATE studio_jobs SET status='failed',finished_at=?,error=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), str(exc)[:150], ident))
    else:
        with db() as con:
            con.execute("UPDATE studio_jobs SET status='completed',finished_at=?,result_json=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), json.dumps(output), ident))


def get_jobs() -> list[dict]:
    with db() as con:
        return [dict(row) for row in con.execute("SELECT id,kind,status,created_at,finished_at,error,result_json FROM studio_jobs ORDER BY created_at DESC LIMIT 30")]


def _authorized(handler) -> bool:
    token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return connections.session_valid(token) or handler.authorized()


def _csrf_ok(handler) -> bool:
    # Bearer clients need no cookies; browser sessions require an origin + CSRF token.
    if handler.authorized():
        return True
    token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return connections.session_valid(token) and handler.headers.get("Origin") == connections.PUBLIC_ORIGIN and secrets.compare_digest(handler.headers.get("X-ESN-CSRF", ""), connections.csrf_token(token))


def handle(handler) -> bool:
    path = urlsplit(handler.path).path
    if path != "/studio" and not path.startswith("/api/studio/"):
        return False
    if not ENABLED:
        handler.send_json(503, {"error": "Studio disabled; set ESN_CREATIVE_ENABLED=1 on an isolated media worker"})
        return True
    if path == "/studio" and handler.command == "GET":
        page = Path(__file__).with_name("web") / "studio.html"
        handler.send_html(page.read_bytes())
        return True
    if not _authorized(handler):
        handler.send_json(401, {"error": "Sign in to Connections first"})
        return True
    if handler.command == "GET":
        if path == "/api/studio/assets":
            handler.send_json(200, {"assets": asset_list()})
            return True
        if path == "/api/studio/jobs":
            jobs = get_jobs()
            for j in jobs:
                j["result"] = json.loads(j.pop("result_json")) if j["result_json"] else None
            handler.send_json(200, {"jobs": jobs})
            return True
        if path.startswith("/api/studio/file/"):
            name = unquote(path[len("/api/studio/file/"):])
            if not IDENT.fullmatch(name) or not name.startswith(("edit-", "logo-")):
                handler.send_json(404, {"error": "Unknown file"}); return True
            file = workspace() / "exports" / name
            if not file.is_file() or file.is_symlink() or file.suffix not in (".mp4", ".svg", ".png", ".json", ".jsx", ".zip"):
                handler.send_json(404, {"error": "Unknown file"}); return True
            import mimetypes
            handler.send_response(200)
            handler.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            handler.send_header("Content-Disposition", 'attachment; filename="' + file.name + '"')
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Content-Length", str(file.stat().st_size))
            handler.end_headers()
            with file.open("rb") as f:
                shutil.copyfileobj(f, handler.wfile)
            return True
    if handler.command == "POST" and path in ("/api/studio/logo", "/api/studio/render"):
        if not _csrf_ok(handler):
            handler.send_json(403, {"error": "Request rejected"}); return True
        try:
            payload = connections.read_json(handler)
            if path.endswith("render"):
                # Validate before enqueue to provide clear immediate errors.
                validate_video_spec(payload)
            else:
                # Syntactic check; output happens in the worker.
                if not isinstance(payload.get("brand"), str):
                    raise ValueError("Brand name required")
            ident = enqueue("render" if path.endswith("render") else "logo", payload)
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json(400, {"error": str(exc)[:160]}); return True
        handler.send_json(202, {"job_id": ident, "status": "queued"}); return True
    handler.send_json(404, {"error": "Not found"})
    return True
