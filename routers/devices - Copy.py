from fastapi import APIRouter, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import os, asyncio, pickle, json, logging
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from models import DeviceCheckRequest, DeviceResponse
import utils.network as network_utils
import mainconfig as mainconfig

logger = logging.getLogger(__name__)


router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Directory for logs
LOG_DIR = mainconfig.LOGS_DIR / "core_logs"
LOG_DIR.mkdir(exist_ok=True)

@router.get("/check_form", response_class=HTMLResponse)
async def device_check_page(request: Request):
    """Device check form page"""
    return templates.TemplateResponse(mainconfig.TEMPLATE_GETDEVICEOUTPUT_FORM, {
        "request": request,
        "core_devices": mainconfig.CORE_DEVICES
    })

@router.post("/check_output", response_class=HTMLResponse)
async def device_check(
    request: Request,
    background_tasks: BackgroundTasks,
    check_type: Optional[str] = Form("core"),
    core_ipaddress: List[str] = Form([]),
    core_uname: str = Form(""),
    core_passwd: str = Form(""),
    # bgp_event: bool = Form(False)
):
    form_data = {
        "check_type": check_type or 'core',
        "core_uname": core_uname,
        "core_passwd": core_passwd,
        "core_ipaddress": core_ipaddress
    }
        
    # Run the blocking function in a thread pool
    loop = asyncio.get_running_loop()
    content_html = await loop.run_in_executor(None, network_utils.run_getweboutput, form_data)

    # Render into the Jinja2 template
    return templates.TemplateResponse(mainconfig.TEMPLATE_GETDEVICEOUTPUT_HTML, {
        "request": request,
        "content": content_html
    })

# @router.post("/check")
# async def api_device_check(request: DeviceCheckRequest):
#     """API endpoint"""
#     device_manager = NetworkDeviceManager(**request.dict())
#     try:
#         results = await device_manager.execute_checks()
#         return DeviceResponse(success=True, message="Completed", results=results)
#     except Exception as e:
#         return DeviceResponse(success=False, message=str(e))

# @router.get("/check/{ip}/status")
# async def get_check_status(ip: str):
#     progress_file = LOG_DIR / f"progress_{ip}.json"

#     async def event_generator():
#         last_progress = -1
#         while True:
#             if not progress_file.exists():
#                 yield f"data: {json.dumps({'progress': 100, 'status': 'failed', 'ip': ip, 'error': 'Progress file not found'})}\n\n"
#                 break

#             try:
#                 data = json.loads(progress_file.read_text())
#                 progress = data.get("progress", 0)
#                 status = data.get("status", "unknown")

#                 if progress != last_progress:
#                     yield f"data: {json.dumps({'progress': progress, 'status': status, 'ip': ip})}\n\n"
#                     last_progress = progress

#                 if status in ["completed", "failed"]:
#                     break
#             except json.JSONDecodeError:
#                 logger.error(f"Invalid JSON in progress file for {ip}")
#                 yield f"data: {json.dumps({'progress': 0, 'status': 'failed', 'ip': ip, 'error': 'Invalid progress data'})}\n\n"
#                 break
#             except Exception as e:
#                 logger.error(f"Error reading progress for {ip}: {e}")
#                 yield f"data: {json.dumps({'progress': 0, 'status': 'failed', 'ip': ip, 'error': str(e)})}\n\n"
#                 break

#             await asyncio.sleep(1)

#     return StreamingResponse(event_generator(), media_type="text/event-stream")


# @router.get("/check/{ip}/results")
# async def get_check_results(ip: str):
#     results_file = LOG_DIR / f"results_{ip}.json"
#     if not results_file.exists():
#         raise HTTPException(status_code=404, detail="Results not ready")

#     try:
#         results = json.loads(results_file.read_text())
#         return results
#     except json.JSONDecodeError:
#         raise HTTPException(status_code=500, detail="Invalid results format")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error reading results: {str(e)}")

# async def execute_device_check(ip: str, log_file: Path, progress_file: Path, manager_file: Path):
#     try:
#         with open(manager_file, "rb") as f:
#             device_manager: NetworkDeviceManager = pickle.load(f)

#         # Override session_log if needed
#         device_manager.results = []
#         device_manager.completed = 0
#         device_manager.total = 1

#         # Execute
#         await device_manager.execute_checks()

#         # Save full results
#         results_file = LOG_DIR / f"results_{ip}.json"
#         results_file.write_text(json.dumps(device_manager.results, indent=2))

#         # Update progress
#         progress_file.write_text(json.dumps({
#             "progress": 100,
#             "status": "completed",
#             "completed_at": datetime.now().isoformat(),
#             "results_file": str(results_file.name)
#         }))

#     except pickle.UnpicklingError:
#         logger.error(f"Invalid pickle file for {ip}")
#         progress_file.write_text(json.dumps({
#             "progress": 0,
#             "status": "failed",
#             "error": "Invalid manager file"
#         }))
#     except Exception as e:
#         logger.error(f"Execution failed for {ip}: {e}")
#         progress_file.write_text(json.dumps({
#             "progress": 0,
#             "status": "failed",
#             "error": str(e)
#         }))
#     finally:
#         # Cleanup
#         manager_file.unlink(missing_ok=True)
