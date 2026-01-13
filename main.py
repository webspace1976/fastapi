import os, re , asyncio, json, csv, io
from typing import List
from collections import defaultdict
from datetime import datetime
from fastapi import FastAPI, Form, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import mainconfig as mainconfig

# import from local scripts
# from scripts.fastapi_getweboutput import run_getweboutput
# from scripts.session_manager import get_or_create_session_id
# from scripts.fastapi_orion_check import get_orion_dashboard_html
# from mainpydantic import OrionCheckRequest, OrionResponse



# import from routers
from routers import devices, monitor, orion

app = FastAPI(
    title="SOC Network-Tools Portal",
    description="Network monitoring and device management system",
    version="2025.12.09"
)

# Import the function from  websocket_server_ds.py
from utils.websocket_server_ds import start_websocket_server_in_background

#startup
@app.on_event("startup")
async def startup_event():
    start_websocket_server_in_background()


# from fastapi_utils.tasks import repeat_every . Not used currently
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from utils.orion_db_manager import cleanup_expired_sessions
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def start_scheduler():
    # Schedule the task to run at 7:00 (7am) and 19:00 (7pm) every day
    scheduler.add_job(
        cleanup_expired_sessions, 
        'cron', 
        hour='7,19', 
        minute=0,
        args=[24] # Passes 24 to the max_age_hours argument
    )
    scheduler.start()

@app.on_event("shutdown")
async def shutdown_scheduler():
    scheduler.shutdown()
#startup

# Set up folder paths and mount 
templates = Jinja2Templates(directory="templates")
# curr_dir = os.path.dirname(__file__)
icons_dir = mainconfig.ICONS_DIR
data_dir = mainconfig.DATA_DIR
logs_dir = mainconfig.LOGS_DIR
session_dir = mainconfig.SESSION_DIR
app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")
app.mount("/data", StaticFiles(directory=data_dir), name="data")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Logging configuration
logger = mainconfig.setup_module_logger(__name__)

# Include routers
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["Monitoring"])
app.include_router(orion.router, prefix="/api/orion", tags=["Orion"])

# --- site index ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin/session-log", response_class=HTMLResponse)
async def show_all_session_logs(request: Request):
    log_file = os.path.join(session_dir, "orion_session_log.json")
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
                "count": len(entries),
                "last_seen": latest.get("timestamp")
            })

        grouped_data.sort(key=lambda x: x["last_seen"], reverse=True)

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
    base_dir = os.path.join(os.path.dirname(__file__), "logs")
    full_path = os.path.join(base_dir, subpath)

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

@app.get("/logs/{file_name}", response_class=FileResponse)
async def get_log_file(file_name: str):
    file_path = os.path.join(os.path.dirname(__file__), "logs", file_name)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=404, detail="File not found")

# --- Directory listing for note data ---
@app.get("/edit", response_class=HTMLResponse)
async def edit_tab(filename: str):
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
    form_data = await request.form()
    filename = form_data.get("filename", "")
    content = form_data.get("content", "")

    file_path = os.path.join(os.path.dirname(__file__), "data", filename)

    # Save the content to the file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return HTMLResponse(content=f"<h1>{filename} saved successfully!</h1><a href='/edit?filename={filename}'>Go back to edit</a>")

@app.get("/orionmap", response_class=HTMLResponse)
async def oriondataviz(request: Request):
    return templates.TemplateResponse("orion_map.html", {"request": request})

log_file_path = os.path.join(logs_dir, "alert_center.log")
@app.get("/admin/alerts", response_class=HTMLResponse)
async def get_alert_center(
    request: Request,
    level: str = Query(default=None),     # e.g., ERROR or WARNING
    group_by: str = Query(default=None),  # "date" or "module"
    export: bool = Query(default=False)
):
    alerts = []
    log_file_path = os.path.join(logs_dir, "alert_center.log")

    if os.path.exists(log_file_path):
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                match = re.match(r"^(.*?) \| (\w+) \| (.*?) \| (.*)", line)
                if match:
                    timestamp, log_level, module, message = match.groups()

                    if level and log_level.upper() != level.upper():
                        continue  # skip if not matching filter

                    alerts.append({
                        "timestamp": timestamp,
                        "level": log_level,
                        "module": module,
                        "message": message.strip(),
                        "date": timestamp.split(" ")[0]
                    })
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
