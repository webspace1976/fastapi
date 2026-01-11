from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import sqlite3
import json
from typing import Optional

from models import MonitorRequest
from utils.database import DatabaseManager
import myconfig as myconfig 

router = APIRouter()
templates = Jinja2Templates(directory="templates")
db_manager = DatabaseManager(myconfig.DATA_DIR)

@router.get("/", response_class=HTMLResponse)
async def monitor_dashboard(
    request: Request,
    protocol: Optional[str] = Query(None),
    hostname: Optional[str] = Query(None),
    neighbor: Optional[str] = Query(None),
    flush: bool = Query(False)
):
    """BGP/OSPF monitoring dashboard"""
    
    if flush:
        # Trigger analysis update
        from utils.network import trigger_analysis_update
        success, message = await trigger_analysis_update()
        return JSONResponse({"status": "success" if success else "error", "message": message})
    
    if protocol and neighbor and hostname:
        # Show peer history
        history = db_manager.get_peer_history(hostname, protocol, neighbor)
        return templates.TemplateResponse("monitor_history.html", {
            "request": request,
            "protocol": protocol,
            "hostname": hostname,
            "neighbor": neighbor,
            "history": history
        })
    
    # Show main dashboard
    conn = db_manager.get_connection()
    try:
        # Get problem peers
        problem_ips, problem_bgp, problem_ospf = db_manager.get_problem_peers(conn)
        
        # Get recent changes
        recent_bgp, recent_ospf = db_manager.get_recently_changed_peers(conn)
        
        # Get current status
        bgp_peers = db_manager.get_bgp_current_status(conn)
        ospf_peers = db_manager.get_ospf_current_status(conn)
        
        return templates.TemplateResponse("monitor_dashboard.html", {
            "request": request,
            "problem_bgp": problem_bgp,
            "problem_ospf": problem_ospf,
            "recent_bgp": recent_bgp,
            "recent_ospf": recent_ospf,
            "bgp_peers": bgp_peers,
            "ospf_peers": ospf_peers,
            "problem_count": len(problem_bgp) + len(problem_ospf)
        })
    finally:
        conn.close()

@router.get("/api/peers/bgp")
async def get_bgp_peers():
    """API endpoint for BGP peers"""
    conn = db_manager.get_connection()
    try:
        peers = db_manager.get_bgp_current_status(conn)
        return {"peers": peers}
    finally:
        conn.close()

@router.get("/api/peers/ospf")
async def get_ospf_peers():
    """API endpoint for OSPF peers"""
    conn = db_manager.get_connection()
    try:
        peers = db_manager.get_ospf_current_status(conn)
        return {"peers": peers}
    finally:
        conn.close()

@router.get("/api/problems")
async def get_problem_peers():
    """API endpoint for problem peers"""
    conn = db_manager.get_connection()
    try:
        problem_ips, problem_bgp, problem_ospf = db_manager.get_problem_peers(conn)
        return {
            "bgp_problems": problem_bgp,
            "ospf_problems": problem_ospf,
            "total_problems": len(problem_bgp) + len(problem_ospf)
        }
    finally:
        conn.close()

@router.post("/api/flush")
async def flush_database():
    """Flush and update database"""
    from utils.network import trigger_analysis_update
    success, message = await trigger_analysis_update()
    return {"status": "success" if success else "error", "message": message}