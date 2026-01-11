# devices.py
from fastapi import APIRouter, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import List
from uuid import uuid4
import json, logging
from pathlib import Path

# Import the refactored utilities
import mainconfig as mainconfig
from utils.network import NetworkDeviceManager, LOG_OUTPUT_DIR, get_file_list_fastapi
from utils.fastapi_mymodule import list_reports
from utils.task_db_manager import task_db_manager

# --- Configuration ---
logger = mainconfig.setup_module_logger("devices")
router = APIRouter()

# Templates directory setup: must be accessible by FastAPI main app
templates = Jinja2Templates(directory=mainconfig.TEMPLATES_DIR)

@router.get("/check_form", response_class=HTMLResponse)
async def get_device_output_form(request: Request):

    # FILE-BASED LISTING WITH DB QUERY
    reports_data = task_db_manager.get_completed_tasks()

    return templates.TemplateResponse("template_getdeviceoutput_form.html", {
        "request": request,
        "core_devices": mainconfig.CORE_DEVICES,
        "reports_data": reports_data
    })

@router.post("/check_output", response_class=HTMLResponse)
async def device_check(
    request: Request,
    background_tasks: BackgroundTasks, 
    check_type: str = Form(...),
    core_uname: str = Form(...),
    core_passwd: str = Form(...),
    # This will be a list of strings like ['cisco_ios:10.10.10.1', 'arista_eos:10.10.10.2']
    core_ipaddress: List[str] = Form([]), 
):
    """
    Handles form data, initiates the network check as a background task, 
    and redirects the user to the progress view.
    """
    iplist_unique = [ip.strip() for ip in core_ipaddress if ip.strip()]

    if not iplist_unique:
        return HTMLResponse("<p>No Core IP address provided.</p>")

    task_id = str(uuid4())
    total_ips = len(iplist_unique)

    # 1. Instantiate the manager
    manager = NetworkDeviceManager(
        task_id=task_id,
        iplist_with_os=iplist_unique,
        username=core_uname,
        password=core_passwd,
        check_type=check_type,
    )
    
    # 2. Add the long-running check to the background task queue
    background_tasks.add_task(manager.execute_checks)
    logger.info(f"Task {task_id} queued for {total_ips} devices.")
    
    # 3. Return the progress page immediately
    # The client-side JS will use 'task_id' to poll for status updates
    return templates.TemplateResponse(
        "device_check_progress.html", 
        {"request": request, "task_id": task_id, "total_ips": total_ips}
    )

@router.get("/status/{task_id}", response_class=JSONResponse)
async def get_check_status(task_id: str):
    """Returns the current progress and status of a background task."""
    status_data = task_db_manager.get_task_status(task_id)

    if not status_data:
        raise HTTPException(status_code=404, detail="Task not found.")

    return JSONResponse(status_data)


@router.get("/results/{task_id}", response_class=HTMLResponse)
async def get_check_results(request: Request, task_id: str):
    """Displays the final results after the task is complete."""
    
    # CRITICAL: Use the DB manager instead of the global dictionary
    status_data = task_db_manager.get_task_status(task_id)
    results_file_path = LOG_OUTPUT_DIR / f"final_results_{task_id}.json"
    
    results = None
    
    # 1. Check DB first, as it contains the full results payload
    if status_data and status_data.get("status") == "completed" and status_data.get("results"):
        results = status_data["results"]
        log_filename = status_data.get("log_filename", f"N/A - (Task ID: {task_id})")
        
    # 2. If DB status is missing or not completed, try to load from the JSON file
    elif results_file_path.exists():
        try:
            with open(results_file_path, "r") as f:
                results = json.load(f)
            
            # Fallback for log_filename if status_data was cleaned up
            log_filename = results[0].get("output_file", f"N/A - (Task ID: {task_id})")
            
        except (FileNotFoundError, IndexError, json.JSONDecodeError):
            # 3. If file exists but is corrupted/empty
             raise HTTPException(
                status_code=500, 
                detail="Historical results file is corrupt or empty."
            )
            
    # 3. Final check: if 'results' is still None, the task is not ready
    if results is None:
        if status_data:
            # Task is running or failed before file creation.
            raise HTTPException(
                status_code=400, 
                detail=f"Task {task_id} is not yet completed. Current status: {status_data.get('status')}."
            )
        else:
            # Historical task ID not found in DB or as a file
            raise HTTPException(
                status_code=404, 
                detail=f"Task {task_id} not found."
            )

    # 4. If we reached here, 'results' is loaded, proceed to render the template.
    combined_html_output = "".join(
        r["analysis_html"] for r in results if r.get("status") == "success" and r.get("analysis_html")
    )

    error_messages = [
        f"<b>{r.get('ip', 'Unknown')}</b>: {r.get('error', 'Unknown failure')}" 
        for r in results if r.get("status") != "success"
    ]
    
    return templates.TemplateResponse(
        "device_check_results.html", 
        {
            "request": request, 
            "task_id": task_id, 
            "timstamp": status_data.get("timestamp", "N/A"),
            "combined_html": combined_html_output, 
            "errors": error_messages,
            "log_filename": log_filename,
        }
    )

# ----------------------------------------------------------------------
# Utility Endpoint (File Listing)
# ----------------------------------------------------------------------

@router.get("/files/reports", response_class=HTMLResponse)
async def get_available_reports(request: Request):
    """Returns the dropdown HTML for available log/report files (Migrated mymodule logic)."""
    file_list = get_file_list_fastapi() 

    # Render a simple template for the file list dropdown
    return templates.TemplateResponse(
        "file_list_dropdown.html", # Requires a simple template
        {"request": request, "file_list": file_list}
    )
