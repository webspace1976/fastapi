import requests, json, os
from fastapi import APIRouter, Request, Query, HTTPException
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
#     search: str = Query(None), 
#     id: str = Query(None), # Added ID parameter
#     eventid: str = Query(""),
#     open: int = Query(0)
# ):
#     base_url = "https://ringer.healthbc.org/opsapi"
    
#     # Logic switch: If ID is provided, use the specific detail method
#     if id:
#         params = {"method": "fetchOpsTrackingById", "id": id}
#     else:
#         params = {"method": method, "search": search, "eventid": eventid, "open": open}
    
#     try:
#         # Note: Added verify=False as per your existing config for internal healthbc certs
#         response = requests.get(base_url, params=params, verify=False, timeout=10)
#         raw_data = response.json()
        
#         # If fetching by ID, Ringer usually returns a single object or a list with one item
#         # Ensure 'cases' is always a list for the Jinja template loop
#         cases = raw_data if isinstance(raw_data, list) else [raw_data]
            
#     except Exception as e:
#         logger.error(f"Ringer API Error: {e}")
#         return HTMLResponse(content=f"Error fetching data: {e}", status_code=500)

#     return templates.TemplateResponse("ops_tracking.html", {
#         "request": request, 
#         "cases": cases,
#         "search_query": search or id
#     })

@router.get("/opsapi")
async def get_ops_tracking(
    request: Request,
    method: str = Query("fetchOpsTracking"),
    search: str = Query(None), 
    caseid: str = Query(None), # Added ID parameter
    eventid: str = Query(""),
    open: int = Query(0)
):
    base_url = "https://ringer.healthbc.org/opsapi"
    
    # 1. Detail Fetch Logic (Lazy Load)
    if caseid:
        params = {"method": "fetchOpsTrackingById", "id": caseid}
        try:
            response = requests.get(base_url, params=params, verify=False, timeout=10)
            detail_data = response.json()
            # Return a specific small template for the inside of the card
            return templates.TemplateResponse("ops_detail_snippet.html", {
                "request": request,
                "case": detail_data[0] if isinstance(detail_data, list) else detail_data
            })
        except Exception as e:
            return HTMLResponse(content=f"<p style='color:red;'>Error: {e}</p>")
    
    # 2. Global Search Logic (Existing)
    params = {"method": "fetchOpsTracking", "search": search or "", "open": open}
    try:
        response = requests.get(base_url, params=params, verify=False, timeout=10)
        cases = response.json()
        
        # Apply your duration fix
        #    raw_time = case.get('create_datetime')
        #    case['dynamic_duration'] = get_dynamic_duration(raw_time) # Your existing function
            
    except Exception as e:
        return HTMLResponse(content=f"Error: {e}")

    return templates.TemplateResponse("ops_tracking.html", {"request": request, "search": search, "cases": cases})

@router.get("/opsapi/detail/{caseid}.html", response_class=HTMLResponse)
async def get_case_detail(request: Request, caseid: str):
    base_url = "https://ringer.healthbc.org/opsapi"
    params = {"method": "fetchOpsTrackingById", "id": caseid}
    
    # Initialize case_data as an empty dict to avoid NameError if the try block fails
    case_data = {} 

    try:
        response = requests.get(base_url, params=params, verify=False, timeout=10)
        raw_data = response.json()
        
        # Ringer returns a list for this method; we need the first item
        if isinstance(raw_data, list) and len(raw_data) > 0:
            case_data = raw_data[0]
        else:
            case_data = raw_data # Handle case where it might be a single dict
            
    except Exception as e:
        logger.error(f"Detail Fetch Error for {caseid}: {e}")
        # Optionally return a specific error message to the UI
        return HTMLResponse(content=f"<p>Error loading details for {caseid}</p>", status_code=500)

    # Now case_data is defined, even if the API returned nothing
    return templates.TemplateResponse("ops_detail_snippet.html", {
        "request": request,
        "case": case_data  # This line will no longer throw NameError
    })

@router.get("/opsapi/test/{filename}")
async def get_ops_test_data(request: Request, filename: str):
    # Path to the file you uploaded
    data_dir = mainconfig.DATA_DIR
    json_path = os.path.join(data_dir, filename)
    
# Security check: Ensure the file is actually a .json file
    if not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are supported")

    try:
        if not os.path.exists(json_path):
            raise HTTPException(status_code=404, detail=f"File {json_path} not found")

        with open(json_path, "r", encoding="utf-8") as f:
            cases = json.load(f)

        # # Process the data (apply your duration fix)
        # for case in cases:
        #     # Check for the different timestamp keys we've seen in your logs
        #     raw_time = case.get('create_datetime') or case.get('LastChange')
        #     if raw_time:
        #         case['dynamic_duration'] = get_dynamic_duration(raw_time)
            
        #     # Feature: Highlight "Interface Down" events for VGH testing
        #     desc = case.get('ShortDescription', '').lower()
        #     if "goes down" in desc or "down" in desc:
        #         case['status_color'] = "red" # You can use this in your HTML
        #     else:
        #         case['status_color'] = "normal"

        return templates.TemplateResponse("ops_tracking.html", {
            "request": request,
            "cases": cases,
            "search_query": f"TEST_FILE: {filename}"
        })

    except Exception as e:
        logger.error(f"Test File Error: {e}")
        return HTMLResponse(content=f"Error processing {filename}: {str(e)}", status_code=500)

