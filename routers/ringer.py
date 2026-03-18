import requests
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import mainconfig as mainconfig
logger = mainconfig.setup_module_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Example API calls:
# global search https://ringer.healthbc.org/opsapi?method=fetchOpsTracking&search=&eventid=&open=0
# case search https://ringer.healthbc.org/opsapi?method=fetchOpsTrackingById&id=369483
# specific search https://ringer.healthbc.org/opsapi?method=fetchOpsTracking&search=VCH-RLL-02A-R1-PDU01|2025-12-15|00:00:00|2026-03-15|23:59:00&eventid=&open=0
# open=1 (Active/Open Cases Only Live) or open=0 (All Cases Historical)

# @router.get("/opsapi")
# async def get_ops_tracking(
#     request: Request,
#     method: str = Query("fetchOpsTracking"),
#     search: str = Query(...), 
#     eventid: str = Query(""),
#     open: int = Query(0)
# ):
#     base_url = "https://ringer.healthbc.org/opsapi"
#     params = {"method": method, "search": search, "eventid": eventid, "open": open}
    
#     try:
#         response = requests.get(base_url, params=params, verify=False, timeout=10)
#         raw_data = response.json() 
#     except Exception as e:
#         return HTMLResponse(content=f"Error: {e}", status_code=500)

#     # We send the data as-is to the template to ensure no nested fields are missed
#     return templates.TemplateResponse("ops_tracking.html", {
#         "request": request, 
#         "cases": raw_data,
#         "search_query": search
#     })
@router.get("/opsapi")
async def get_ops_tracking(
    request: Request,
    method: str = Query("fetchOpsTracking"),
    search: str = Query(None), 
    id: str = Query(None), # Added ID parameter
    eventid: str = Query(""),
    open: int = Query(0)
):
    base_url = "https://ringer.healthbc.org/opsapi"
    
    # Logic switch: If ID is provided, use the specific detail method
    if id:
        params = {"method": "fetchOpsTrackingById", "id": id}
    else:
        params = {"method": method, "search": search, "eventid": eventid, "open": open}
    
    try:
        # Note: Added verify=False as per your existing config for internal healthbc certs
        response = requests.get(base_url, params=params, verify=False, timeout=10)
        raw_data = response.json()
        
        # If fetching by ID, Ringer usually returns a single object or a list with one item
        # Ensure 'cases' is always a list for the Jinja template loop
        cases = raw_data if isinstance(raw_data, list) else [raw_data]
            
    except Exception as e:
        logger.error(f"Ringer API Error: {e}")
        return HTMLResponse(content=f"Error fetching data: {e}", status_code=500)

    return templates.TemplateResponse("ops_tracking.html", {
        "request": request, 
        "cases": cases,
        "search_query": search or id
    })

