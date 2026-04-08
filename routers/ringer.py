import requests, json, os, re
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import mainconfig as mainconfig
from utils.fastapi_mymodule import get_dynamic_duration 
logger = mainconfig.setup_module_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
CONFIG_PATH = os.path.join(mainconfig.DATA_DIR, "power_config.json")

def load_ignore_list():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f).get("ignore_list", [])
    return ["bchydro2752838","bchydro2753010"] # Fallback

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


########## helper functions for data processing ##########
# Helper to find the latest state per bchydro ID across all sites
def get_ha_power_alerts(raw_data):
    all_events = []
    for case in (raw_data if isinstance(raw_data, list) else []):
        if "Events" in case:
            all_events.extend(case["Events"])

    # Sort by record_id so the newest update is processed last
    all_events.sort(key=lambda x: x.get('record_id', 0))

    outage_tracker = {}
    HYDRO_REGEX = r"((?:bchydro|fortisbc)\d+)"  # Matches bchydro or fortisbc followed by digits
    ignore_list = ignore_list = load_ignore_list() # Load fresh from file
    reserve_list = ["fortisbc30616 "]  # Words that indicate an outage is resolved

    for event in all_events:
        node_text = (event.get("Node") or "")
        name_text = (event.get("Name") or "")
        combined_text = (name_text + " " + node_text).lower()
        
        match = re.search(HYDRO_REGEX, node_text)
        if match:
            h_id = match.group(1)

            # Check ignore list first. If found, skip this entire event.
            if str(h_id) in ignore_list:
                continue            
            # ONLY remove if the text explicitly confirms restoration
            # We ignore the 'End' timestamp because it can be misleading

            is_confirmed_restored = any(word in combined_text for word in ["restored", "completed", "cleared"])

            if is_confirmed_restored:
                if h_id in outage_tracker:
                    del outage_tracker[h_id]
            else:
                current_site = event.get("SiteName", "Unknown Site")
                current_short = event.get("SiteNameShort", "??")
                duration = get_dynamic_duration(event.get("Start"))[0]

                # OPTION 2: Match by HydroID
                if h_id in outage_tracker:
                    # Entry exists for this HydroID, append new site info
                    existing = outage_tracker[h_id]
                    # Update the ETR/Status to the most recent one found in the logs
                    existing["Description"] = event.get("Description", "No ETR")
                    
                    if current_site not in existing["all_sites"]:
                        existing["all_sites"].append(current_site)
                        existing["all_shorts"].append(current_short)
                        
                        # Update the display strings used in the HTML template
                        existing["impacted_site"] = " / ".join(existing["all_sites"])
                        existing["SiteNameShort"] = "/".join(existing["all_shorts"])
                else:
                    # New HydroID detected, create fresh entry
                    event["is_active_outage"] = True
                    event["duration"] = duration
                    event["all_sites"] = [current_site]
                    event["all_shorts"] = [current_short]
                    event["impacted_site"] = current_site
                    event["SiteNameShort"] = current_short
                    outage_tracker[h_id] = event

    return list(outage_tracker.values())


@router.get("/opsapi/poweroutage", response_class=HTMLResponse)
async def get_poweroutage(request: Request):
    base_url = "https://ringer.healthbc.org/opsapi"
    # now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Setup Exact 48-Hour Window
    now = datetime.now()
    yesterday = now - timedelta(hours=48)

    # 2. Format components for the Ringer search string
    # Format: YYYY-MM-DD|HH:MM:SS
    end_date_str = now.strftime("%Y-%m-%d")
    end_time_str = now.strftime("%H:%M:%S")

    start_date_str = yesterday.strftime("%Y-%m-%d")
    start_time_str = yesterday.strftime("%H:%M:%S")

    # 3. Construct the Ringer-specific search string
    # Pattern: query|start_date|start_time|end_date|end_time
    search_str = f"power outage|{start_date_str}|{start_time_str}|{end_date_str}|{end_time_str}"


    params = {
        "method": "fetchOpsTracking",
        "search": search_str,
        "open": 0
    }
    is_offline = False  # Flag to trigger the popup/warning
    debug_path = os.path.join(mainconfig.DATA_DIR, "debug_active_poweroutages.json")

    try:
        # Initial search call
        search_response = requests.get(base_url, params=params, verify=False, timeout=10)
        search_response.raise_for_status()
        case_summaries = search_response.json()
        
        all_detailed_cases = []

        # STEP 2: Loop through each case to fetch full event details
        for summary in (case_summaries if isinstance(case_summaries, list) else []):
            case_id = summary.get("record_id")
            if not case_id:
                continue
                
            # Second API call for the specific Case ID
            detail_params = {"method": "fetchOpsTrackingById", "id": case_id}
            detail_response = requests.get(base_url, params=detail_params, verify=False, timeout=5)
            full_case_data = detail_response.json()

            # Ringer returns a list for ById; append the actual case object
            if isinstance(full_case_data, list) and len(full_case_data) > 0:
                all_detailed_cases.append(full_case_data[0])
            else:
                all_detailed_cases.append(full_case_data)

        # Now pass the full detailed data to your existing filter logic
        # This ensures get_ha_power_alerts can actually see the 'Events' array
        final_active_events = get_ha_power_alerts(all_detailed_cases)

        # Save to JSON for debugging as you requested
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(final_active_events, f, indent=4)

        return templates.TemplateResponse("ops_poweroutage.html", {
            "request": request, 
            "cases": final_active_events,
            "search_str": search_str,
            "last_check": now.strftime("%Y-%m-%d %H:%M:%S")
        })
    
        # if os.path.exists(debug_path):
        #     with open(debug_path, "r", encoding="utf-8") as f:
        #         data = json.load(f)
        #     return {"cases": data}
        # return {"cases": []}

    except Exception as e:
        logger.error(f"Ringer API Offline. Loading cache: {e}")
        is_offline = True
        # Failover: Load from JSON
        if os.path.exists(debug_path):
            with open(debug_path, "r", encoding="utf-8") as f:
                display_cases = json.load(f)
        else:
            display_cases = []

    return templates.TemplateResponse("ops_poweroutage.html", {
        "request": request, 
        "cases": display_cases,
        "is_offline": is_offline, # Pass this to HTML
        "last_check": now.strftime("%Y-%m-%d %H:%M:%S")
    })

# --- New Endpoint to add to ignore list ---
@router.post("/opsapi/ignore-id/{h_id}")
async def ignore_hydroid(h_id: str):
    config = {"ignore_list": load_ignore_list()}
    if h_id not in config["ignore_list"]:
        config["ignore_list"].append(h_id)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f)
    return {"status": "success", "ignored": h_id}

# --- Get the raw list for the notepad ---
@router.get("/opsapi/ignore-list/raw")
async def get_raw_ignore_list():
    current_list = load_ignore_list()
    return {"raw_text": "\n".join(current_list)}

# --- Save the raw list from the notepad ---
@router.post("/opsapi/ignore-list/save")
async def save_raw_ignore_list(request: Request):
    data = await request.json()
    raw_text = data.get("raw_text", "")
    
    # Split by lines, strip whitespace, and remove empty entries
    new_list = [line.strip() for line in raw_text.split("\n") if line.strip()]
    
    with open(CONFIG_PATH, "w") as f:
        json.dump({"ignore_list": new_list}, f)
        
    return {"status": "success"}
