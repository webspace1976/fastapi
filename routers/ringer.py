import requests
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import mainconfig as mainconfig
logger = mainconfig.setup_module_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/opsapi")
async def get_ops_tracking(
    request: Request,
    method: str = Query("fetchOpsTracking"),
    search: str = Query(...), 
    eventid: str = Query(""),
    open: int = Query(0)
):
    base_url = "https://ringer.healthbc.org/opsapi"
    params = {"method": method, "search": search, "eventid": eventid, "open": open}
    
    try:
        response = requests.get(base_url, params=params, verify=False, timeout=10)
        raw_data = response.json() 
    except Exception as e:
        return HTMLResponse(content=f"Error: {e}", status_code=500)

    # We send the data as-is to the template to ensure no nested fields are missed
    return templates.TemplateResponse("ops_tracking.html", {
        "request": request, 
        "cases": raw_data,
        "search_query": search
    })

