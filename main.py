import os, re , asyncio, json, csv, io
from typing import List
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Form, Request, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import mainconfig as mainconfig
from utils.auth import get_current_user



### Path Traversal guards for `/edit` and `/save`
from pathlib import Path
DATA_DIR = Path(__file__).parent / "data"
ALLOWED_EXTENSIONS = {".txt", ".json", ".html"}

# Import startup dependencies
from utils.websocket_server_ds import start_websocket_server_in_background
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from utils.orion_db_manager import cleanup_expired_sessions

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Single lifespan handler — replaces the two deprecated @app.on_event handlers.
    Startup order is explicit and deterministic."""
    # --- startup ---
    start_websocket_server_in_background()

    scheduler.add_job(
        cleanup_expired_sessions,
        'cron',
        hour='7,19',
        minute=0,
        args=[24]  # max_age_hours
    )
    scheduler.start()

    yield  # app runs here

    # --- shutdown ---
    scheduler.shutdown()


app = FastAPI(
    title="SOC Network-Tools Portal",
    description="Network monitoring and device management system",
    redirect_slashes=False,
    version="2025.12.09",
    lifespan=lifespan,
)

# Set up folder paths and mount 
templates = Jinja2Templates(directory="templates")
icons_dir = mainconfig.ICONS_DIR
data_dir = mainconfig.DATA_DIR
logs_dir = mainconfig.LOGS_DIR
session_dir = mainconfig.SESSION_DIR
app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")
app.mount("/data", StaticFiles(directory=data_dir), name="data")
app.mount("/static", StaticFiles(directory="static"), name="static")

# import from routers
from routers import devices, monitor, orion, ringer, auth_login

# Logging configuration
logger = mainconfig.setup_module_logger(__name__)

# Wire up DEBUG_MODE and LOG_LEVEL env var (refactor report items #21 and #23)
import logging as _logging
from logging.handlers import RotatingFileHandler
_log_level = os.getenv("LOG_LEVEL", "DEBUG" if mainconfig.DEBUG_MODE else "WARNING").upper()
logging_root = _logging.getLogger()
logging_root.setLevel(getattr(_logging, _log_level, _logging.WARNING))

# NOTE: alert_center.log previously grew unbounded (refactor report #23 area).
# An ever-growing log file made /admin/alerts re-read + regex the whole file on
# every request, which is a likely cause of the multi-day freeze-up — see patch below.
# If setup_module_logger() already attaches a FileHandler for alert_center.log,
# swap that handler for a RotatingFileHandler here so the file can't grow forever:
for _h in list(logging_root.handlers):
    if isinstance(_h, _logging.FileHandler) and not isinstance(_h, RotatingFileHandler):
        _path = _h.baseFilename
        logging_root.removeHandler(_h)
        _h.close()
        _rotating = RotatingFileHandler(_path, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
        _rotating.setFormatter(_h.formatter)
        logging_root.addHandler(_rotating)

# Include routers
app.include_router(auth_login.router, tags=["Auth"])

# app.include_router(devices.router, prefix="/api/devices", tags=["Devices"], dependencies=[Depends(get_current_user)])
# app.include_router(monitor.router, prefix="/api/monitor", tags=["Monitoring"], dependencies=[Depends(get_current_user)])

app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["Monitoring"])
app.include_router(orion.router, prefix="/api/orion", tags=["Orion"])
app.include_router(ringer.router, prefix="/api/ringer", tags=["Ringer"])


# --- site index ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
    # return templates.TemplateResponse("index_base.html", {"request": request})


@app.get("/health")
async def health():
    """Cheap liveness check — intentionally does no file I/O or blocking calls.
    Used by Docker healthcheck / systemd watchdog / external cron watchdog to
    detect a frozen event loop (process alive, but not answering HTTP)."""
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/admin/session-log", response_class=HTMLResponse)
async def show_all_session_logs(request: Request):
    log_file = mainconfig.SESSION_LOG_JSON
    grouped_sessions = defaultdict(list)

    # all_sessions  = []
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                all_sessions  = json.load(f)
        except Exception as e:
            all_sessions  = [{"error": str(e)}]

        # Group by session_id
        for entry in all_sessions:
            sid = entry.get("session_id")
            if sid:
                grouped_sessions[sid].append(entry)

        # Convert to list and sort by latest timestamp in group
        grouped_data = []
        for sid, entries in grouped_sessions.items():
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            latest = entries[0]
            grouped_data.append({
                "session_id": sid,
                "npm_server": latest.get("npm_server"),
                "username": latest.get("username"),
                "ip": latest.get("ip"),
                "start_time": latest.get("start_time"),
                "last_activity": latest.get("last_activity"),
                "duration_minutes": latest.get("duration_minutes"),
            })

        grouped_data.sort(key=lambda x: x["last_activity"], reverse=True)

    return templates.TemplateResponse("admin_sessions.html", {
        "request": request,
        "sessions": grouped_data
    })

# --- WebSocket SSH bridge ---
@app.get("/webssh", response_class=HTMLResponse)
async def get_webssh_page(ip: str):
    try:
        # Construct the correct path to xterm.html
        xterm_file_path = os.path.join(os.path.dirname(__file__), "static", "xterm.html")

        # Read the xterm.html file
        with open(xterm_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Replace placeholders in the HTML with the IP address
        html_content = html_content.replace("{{ip}}", ip)

        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(content="Error: xterm.html not found.", status_code=404)

# --- Directory listing for logs ---
@app.get("/logs/{subpath:path}", response_class=HTMLResponse)
async def serve_log_or_list(subpath: str, request: Request):
    # base_dir = os.path.join(os.path.dirname(__file__), "logs")
    # full_path = os.path.join(base_dir, subpath)
    base_dir = Path(__file__).parent / "logs"
    full_path = (base_dir / subpath).resolve()
    if not str(full_path).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")


    # Clean up trailing slash for directory listing
    if os.path.isdir(full_path):
        try:
            files = os.listdir(full_path)
            files.sort()
            items = []

            for name in files:
                item_path = os.path.join(full_path, name)
                modified = datetime.fromtimestamp(os.path.getmtime(item_path)).strftime("%m/%d/%Y %I:%M %p")
                size = "<dir>" if os.path.isdir(item_path) else os.path.getsize(item_path)
                items.append({
                    "name": name,
                    "modified": modified,
                    "size": size,
                    "is_dir": os.path.isdir(item_path)
                })

            return templates.TemplateResponse("logs_index.html", {
                "request": request,
                "title": f"/logs/{subpath}/" if subpath else "/logs/",
                "items": items,
                "current_path": subpath.rstrip("/"),
            })
        except Exception as e:
            return HTMLResponse(content=f"Error reading directory: {e}", status_code=500)

    elif os.path.isfile(full_path):
        return FileResponse(full_path)

    else:
        raise HTTPException(status_code=404, detail="File or directory not found")

# @app.get("/logs/{file_name}", response_class=FileResponse)
# async def get_log_file(file_name: str):
#     file_path = os.path.join(os.path.dirname(__file__), "logs", file_name)
#     if os.path.isfile(file_path):
#         return FileResponse(file_path)
#     else:
#         raise HTTPException(status_code=404, detail="File not found")

# --- Directory listing for note data ---
@app.get("/edit", response_class=HTMLResponse)
async def edit_tab(filename: str):
    target = (DATA_DIR / filename).resolve()
    if not str(target).startswith(str(DATA_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if target.suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")

    file_path = os.path.join(os.path.dirname(__file__), "data", filename)
    try:
        # Read the file content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = "No content available. Start writing!"

    # Return an editable HTML page
    return f"""
    <html>
    <head>
        <title>Edit {filename}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
            }}
            textarea {{
                width: 100%;
                height: 80vh;
                font-family: Arial, sans-serif;
                font-size: 14px;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
            }}
            button {{
                margin-top: 10px;
                padding: 10px 20px;
                font-size: 16px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
            }}
            button:hover {{
                background-color: #45a049;
            }}
        </style>
    </head>
    <body>
        <h1>Edit {filename}</h1>
        <form method="post" action="/save">
            <input type="hidden" name="filename" value="{filename}">
            <textarea name="content">{content}</textarea>
            <br>
            <button type="submit">Save</button>
        </form>
    </body>
    </html>
    """

@app.post("/save")
async def save_tab(request: Request):
    # FIX: read form data FIRST — filename was used before it was read from the form
    form_data = await request.form()
    filename = form_data.get("filename", "")
    content = form_data.get("content", "")

    # Validate filename AFTER reading it
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Filename required")

    target = (DATA_DIR / filename).resolve()
    if not str(target).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if target.suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")

    target.write_text(content, encoding="utf-8")
    return HTMLResponse(content=f"<h1>{filename} saved successfully!</h1><a href='/edit?filename={filename}'>Go back to edit</a>")

@app.get("/orionmap", response_class=HTMLResponse)
async def oriondataviz(request: Request):
    return templates.TemplateResponse("orion_map.html", {"request": request})

log_file_path = os.path.join(logs_dir, "alert_center.log")

# Compiled once at module load — avoids recompiling the regex on every line/request
_ALERT_LINE_RE = re.compile(
    r"^(.*?)\s-\s(\w+)\s-\s\[(.*?):(\d+)\]\s-\s(.*?)\(\)\s-\s(.*)"
)
# Hard cap on how many lines we'll ever parse per request. Even with rotation in
# place (see logging setup above), this bounds worst-case blocking time and is a
# second line of defense against the freeze this endpoint could previously cause.
_ALERT_MAX_LINES = 20000

def _parse_alert_log_sync(path: str, level_filter: str | None) -> list[dict]:
    """Blocking file read + regex parse. Always call via asyncio.to_thread from
    an async route — never call this directly inside `async def`."""
    alerts = []
    if not os.path.exists(path):
        return alerts

    with open(path, "r", encoding="utf-8") as f:
        # Only look at the tail of the file — bounds worst-case work regardless
        # of how large the (now-rotated) log file gets.
        lines = f.readlines()[-_ALERT_MAX_LINES:]

    for line in lines:
        # Format: Timestamp - Level - [Module:Line] - Function() - Message
        match = _ALERT_LINE_RE.search(line)
        if not match:
            continue
        timestamp, log_level, module, lineno, func_name, message = match.groups()

        if level_filter and log_level.upper() != level_filter.upper():
            continue  # skip if not matching filter

        alerts.append({
            "timestamp": timestamp,
            "level": log_level,
            "module": f"{module}:{lineno}",  # Combines file and line
            "function": func_name,
            "message": message.strip(),
            "date": timestamp.split(" ")[0],
        })
    return alerts


@app.get("/admin/alerts", response_class=HTMLResponse)
async def get_alert_center(
    request: Request,
    level: str = Query(default=None),     # e.g., ERROR or WARNING
    group_by: str = Query(default=None),  # "date" or "module"
    export: bool = Query(default=False)
):
    # FIX: file read + regex parsing previously ran synchronously inside this
    # async route. On a large/unrotated alert_center.log this could block the
    # entire event loop (single worker) for seconds, which is a strong
    # candidate for the "app stops answering on the port after days" symptom.
    # Now offloaded to a thread so other requests keep being served.
    alerts = await asyncio.to_thread(_parse_alert_log_sync, log_file_path, level)

    # ✅ Sort by timestamp DESCENDING
    alerts.sort(key=lambda x: x["timestamp"], reverse=True)

    # --- Export to CSV ---
    if export:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["timestamp", "level", "module", "message"])
        writer.writeheader()

        # Remove 'date' field before writing
        export_alerts = [
            {k: v for k, v in alert.items() if k in writer.fieldnames}
            for alert in alerts
        ]
        writer.writerows(export_alerts)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=alerts.csv"}
        )

    # --- Grouping ---
    grouped_alerts = {}
    if group_by in {"date", "module"}:
        for alert in alerts:
            key = alert[group_by]
            grouped_alerts.setdefault(key, []).append(alert)
        # Sort each group's entries descending by timestamp
        for key in grouped_alerts:
            grouped_alerts[key].sort(key=lambda a: a["timestamp"], reverse=True)
    else:
        grouped_alerts = {"All": sorted(alerts, key=lambda a: a["timestamp"], reverse=True)}

    return templates.TemplateResponse("admin_alerts.html", {
        "request": request,
        "grouped_alerts": grouped_alerts,
        "filter_level": level or "All",
        "group_by": group_by or "None",
    })
