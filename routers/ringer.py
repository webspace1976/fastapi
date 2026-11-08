import requests, json, os, re, asyncio
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


def _http_get(url: str, params: dict, timeout: int):
    """Blocking GET — wraps requests.get for use with asyncio.to_thread.
    Every Ringer call in this file goes through this helper so the event loop
    is never blocked while waiting on ringer.healthbc.org. This was previously
    a likely cause of multi-day freeze-ups under --workers 1: any slow/hung
    response from Ringer blocked the entire app, not just this request."""
    return requests.get(url, params=params, verify=False, timeout=timeout)


def load_ignore_list():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f).get("ignore_list", [])
    return ["bchydro2752838","bchydro2753010"] # Fallback


# ---------------------------------------------------------------------------
# Ringer response unwrapping (2026-11 fix)
# Ringer used to return a bare JSON list:  [ {case}, {case}, ... ]
# It now returns a wrapped object:         {"api_ts": ..., "cases": [...], "ts": ...}
# Every isinstance(..., list) check in this file silently produced an empty
# page against the wrapped shape -- no error, no log line, just "no outages".
# Always run Ringer payloads through these helpers first. They accept BOTH
# shapes, so the code survives if Ringer ever switches back.
def _unwrap_cases(payload):
    """Return the case list from a Ringer payload of either shape."""
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    if isinstance(payload, dict):
        cases = payload.get("cases")
        if isinstance(cases, list):
            return [c for c in cases if isinstance(c, dict)]
        # A single-case object (detail response in the old shape)
        if "record_id" in payload or "Events" in payload:
            return [payload]
    return []


def _unwrap_single_case(payload):
    """Return one case dict from a fetchOpsTrackingById payload, or None."""
    cases = _unwrap_cases(payload)
    return cases[0] if cases else None

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
            response = await asyncio.to_thread(_http_get, base_url, params, 10)
            detail_case = _unwrap_single_case(response.json())
            # Return a specific small template for the inside of the card
            return templates.TemplateResponse("ops_detail_snippet.html", {
                "request": request,
                "case": detail_case or {}
            })
        except Exception as e:
            return HTMLResponse(content=f"<p style='color:red;'>Error: {e}</p>")
    
    # 2. Global Search Logic (Existing)
    params = {"method": "fetchOpsTracking", "search": search or "", "open": open}
    try:
        response = await asyncio.to_thread(_http_get, base_url, params, 10)
        cases = _unwrap_cases(response.json())
        
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
        response = await asyncio.to_thread(_http_get, base_url, params, 10)
        # Ringer may return [case], a bare case, or {"cases": [case]} -- unwrap all three
        case_data = _unwrap_single_case(response.json()) or {}
            
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

                    # 20260714 Track the most recent activity for this outage so we can sort by it below
                    existing["latest_record_id"] = event.get("record_id", existing.get("latest_record_id", 0))
                    existing["Update"] = event.get("Update", existing.get("Update"))

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
                    event["latest_record_id"] = event.get("record_id", 0)
                    # event["Update"] = event.get("Update")
                    outage_tracker[h_id] = event

    # Show the most recently updated/reported outage first
    return sorted(
        outage_tracker.values(),
        key=lambda x: x.get("latest_record_id", 0),
        reverse=True
    )

REAL_OUTAGE_SOURCES = ("bchydro", "fortis")

def is_real_outage(event: dict) -> bool:
    """Real alert = utility source AND event Name starts with 'Power Outage'
    (covers 'Power Outage', 'Power Outage Nearby', 'Power Outage Restored')."""
    src = (event.get("Source") or "").strip().lower()
    name = (event.get("Name") or "").strip().lower()
    return any(s in src for s in REAL_OUTAGE_SOURCES) and name.startswith("power outage")

async def _fetch_case(base_url: str, case_id, timeout: int = 10) -> dict | None:
    """Fetch one case's details. Retry once; return None if it still fails."""
    params = {"method": "fetchOpsTrackingById", "id": case_id}
    for attempt in (1, 2):
        try:
            r = await asyncio.to_thread(_http_get, base_url, params, timeout)
            r.raise_for_status()
            return _unwrap_single_case(r.json())
        except Exception as e:
            if attempt == 2:
                logger.warning(f"Case {case_id} detail fetch failed: {e}")
    return None


def _collect_case_events(case: dict) -> list:
    """All alarm/event objects attached to a case dict.
    The full case (fetchOpsTrackingById) carries its alarms in "Events";
    accept an "Alarms" list too, in case Ringer ever splits them."""
    events = []
    for key in ("Events", "Alarms"):
        items = case.get(key)
        if isinstance(items, list):
            events.extend(e for e in items if isinstance(e, dict) and "Name" in e)
    return events


def _merge_events(*event_lists) -> list:
    """Union of event lists, de-duplicated (by event record_id when present,
    else by Name+Node+Start) so merging a search summary with its full case
    never double-counts the primary event."""
    merged, seen = [], set()
    for lst in event_lists:
        for e in lst or []:
            rid = e.get("record_id")
            key = ("id", rid) if rid else ("sig", e.get("Name"), e.get("Node"), e.get("Start"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(e)
    return merged


@router.get("/opsapi/poweroutage", response_class=HTMLResponse)
async def get_poweroutage(request: Request):
    base_url = "https://ringer.healthbc.org/opsapi"

    now = datetime.now()
    # NOTE: the window is 48 hours. An outage whose case was created more
    # than 48h ago will not appear here even if it is still open -- if a
    # long outage "disappears", widen this first before debugging further.
    window_start = now - timedelta(hours=48)
    search_str = (
        f"power outage|{window_start.strftime('%Y-%m-%d')}|{window_start.strftime('%H:%M:%S')}"
        f"|{now.strftime('%Y-%m-%d')}|{now.strftime('%H:%M:%S')}"
    )
    params = {"method": "fetchOpsTracking", "search": search_str, "open": 0}

    is_offline = False
    failed_cases = 0
    display_cases = []          # always defined, so the final return can't fail
    debug_path = os.path.join(mainconfig.DATA_DIR, "debug_active_poweroutages.json")

    try:
        search_response = await asyncio.to_thread(_http_get, base_url, params, 15)
        search_response.raise_for_status()
        # FIX (2026-11): Ringer now wraps the list as {"cases": [...]}.
        # The old isinstance(list) check made case_ids == [] and the page
        # silently rendered zero outages. Unwrap first.
        case_summaries = _unwrap_cases(search_response.json())
        logger.warning(
            "PowerOutage: Ringer search returned %d case(s) for window %s",
            len(case_summaries), search_str,
        )

        # CRITICAL (v2, 2026-11-07): the search payload is a SUMMARY. Its
        # "Events" holds exactly ONE event per case -- the primary/trigger
        # event -- while alarm_count says how many alarms the case really
        # has (e.g. the standing "BC Hydro" case: alarm_count 774, Events 1).
        # Every other alarm, including tonight's wind-storm sites grouped
        # into that case, exists ONLY in the fetchOpsTrackingById response.
        # An earlier version of this fix skipped the ById call whenever
        # Events was non-empty, which made the page show one event per case.
        # So: ALWAYS fetch the full case, then merge.
        fetch_ids = [s["record_id"] for s in case_summaries if s.get("record_id")]

        sem = asyncio.Semaphore(5)   # at most 5 detail calls to Ringer at once

        async def bounded(cid):
            async with sem:
                # 30s, not 10s: the "BC Hydro" case is huge (700+ alarms)
                # and is exactly the one that must not time out.
                return await _fetch_case(base_url, cid, timeout=30)

        fetched = await asyncio.gather(*(bounded(c) for c in fetch_ids)) if fetch_ids else []
        failed_ids = [cid for cid, r in zip(fetch_ids, fetched) if r is None]
        failed_cases = len(failed_ids)
        if failed_ids:
            logger.warning("PowerOutage: ById fetch failed for case id(s): %s", failed_ids)

        # Every detail call failed AND we have no cases at all to fall back
        # on: Ringer is effectively down, so use the cache
        if fetch_ids and failed_cases == len(fetch_ids):
            raise RuntimeError("all case detail fetches failed")

        # Merge each full case with its search summary: full-case events
        # first, plus the summary's primary event if the full case somehow
        # lacks it. If a ById fetch failed, the summary case is the fallback
        # (its one primary event is better than dropping the case entirely).
        summary_by_id = {s["record_id"]: s for s in case_summaries if s.get("record_id")}
        results = []
        total_events = 0
        for cid, full_case in zip(fetch_ids, fetched):
            summary = summary_by_id.get(cid, {})
            if full_case:
                events = _merge_events(
                    _collect_case_events(full_case),
                    _collect_case_events(summary),
                )
                merged_case = dict(full_case)
                merged_case["Events"] = events
                results.append(merged_case)
                total_events += len(events)
            else:
                results.append(summary)
                total_events += len(_collect_case_events(summary))
        logger.warning(
            "PowerOutage: %d case(s) fetched, %d event(s) collected in total",
            len(results), total_events,
        )

        all_detailed_cases = []
        for case in results:
            if not case:
                continue
            real_events = [e for e in case.get("Events", []) if is_real_outage(e)]
            if not real_events:
                continue
            case["Events"] = real_events
            all_detailed_cases.append(case)

        display_cases = get_ha_power_alerts(all_detailed_cases)
        # Diagnostic (WARNING so it survives the default log level): if this
        # ever goes back to "search > 0, display = 0", the filter -- not
        # Ringer -- is the problem, and this line proves it in one look.
        logger.warning(
            "PowerOutage: %d case(s) with real outage events -> %d display row(s)",
            len(all_detailed_cases), len(display_cases),
        )

        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(display_cases, f, indent=4)

    except Exception as e:
        logger.error(f"Ringer API Offline. Loading cache: {e}")
        is_offline = True
        if os.path.exists(debug_path):
            with open(debug_path, "r", encoding="utf-8") as f:
                display_cases = json.load(f)

    return templates.TemplateResponse("ops_poweroutage.html", {
        "request": request,
        "cases": display_cases,
        "is_offline": is_offline,
        "failed_cases": failed_cases,
        "search_str": search_str,
        "last_check": now.strftime("%Y-%m-%d %H:%M:%S"),
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
