#!/usr/bin/env python3

import sqlite3, html, os, sys, logging, subprocess, json, re
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict

# 202512 Import mainconfig module
sys.path.append("..")
import mainconfig as mainconfig
import utils.fastapi_mymodule as fastapi_mymodule

from fastapi import APIRouter, Request, Query, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=mainconfig.TEMPLATES_DIR)

DB_PATH = mainconfig.DB_PATH
LOG_BASE_URL = "../logs/core_logs/"

log_directory = mainconfig.LOGS_DIR
log_file = os.path.join(log_directory, 'monitor.log')
logger = logging.getLogger('monitor')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@router.get("/", response_class=HTMLResponse)
async def monitor_dashboard(request: Request):
    conn = get_db_conn()

    # cursor = conn.cursor()
    
    # # 1. BGP Status (Standard)
    # bgp_peers = conn.execute("SELECT * FROM bgp_peer_status ORDER BY hostname, neighbor_ip").fetchall()
    
    # # 2. OSPF Advanced Report (Logic from CGI monitor.py)
    # # This matches your 'get_comprehensive_ospf_report' function
    # ospf_report = []
    
    # # Get all current peers that are NOT Full
    # cursor.execute("""
    #     SELECT hostname, process, neighbor_routerid, neighbor_address, interface, state, 
    #            verbose_uptime, last_updated_ts, source_log_file
    #     FROM ospf_peer_status
    #     WHERE UPPER(state) NOT LIKE 'FULL%'
    # """)
    # current_non_full = cursor.fetchall()
    
    # # Get historical disappearances or state changes
    # # (Simplified version of your Step 2 logic for the dashboard)
    # cursor.execute("""
    #     SELECT s1.* FROM ospf_state_changes s1
    #     JOIN (
    #         SELECT hostname, neighbor_address, MAX(timestamp) as max_ts 
    #         FROM ospf_state_changes GROUP BY hostname, neighbor_address
    #     ) s2 ON s1.hostname = s2.hostname AND s1.neighbor_address = s2.neighbor_address 
    #     AND s1.timestamp = s2.max_ts
    #     WHERE UPPER(s1.to_state) NOT LIKE 'FULL%'
    # """)
    # historical_issues = cursor.fetchall()

    recent_bgp_flaps, recent_ospf_flaps = get_recently_changed_peers(conn)
    problem_peers, problem_bgp, problem_ospf = get_problem_peers(conn)

    bgp_peers = get_bgp_current_status(conn)
    ospf_peers = get_ospf_current_status(conn)

    html_problem = html_problem_peers(conn, problem_bgp, problem_ospf, recent_bgp_flaps, recent_ospf_flaps)

    html_bgp = html_bgp_peers(conn, recent_bgp_flaps, problem_bgp)
    
    html_ospf = html_ospf_peers(conn, recent_ospf_flaps, problem_ospf)


    conn.close()
    
    return templates.TemplateResponse("monitor_summary.html", {
        "request": request,
        "bgp_peers": bgp_peers,
        # "ospf_non_full": current_non_full,
        # "ospf_history": historical_issues,
        "html_java_script": html_java_script,
        "problem_peers":problem_peers,
        "problem_bgp": problem_bgp,
        "problem_ospf":problem_ospf,
        "bgp_peers":bgp_peers,
        "ospf_peers":ospf_peers,
        "html_problem":html_problem,
        "html_bgp":html_bgp,
        "html_ospf":html_ospf
       

    })

@router.post("/flush")
async def flush_status(background_tasks: BackgroundTasks):
    """Replaces the CGI flush_status logic using background tasks."""
    def run_sync():
        script_path = os.path.join(mainconfig.BASE_DIR, "utils", "analysis_sqlite.py")
        subprocess.run(["python", script_path], capture_output=True)

    background_tasks.add_task(run_sync)
    return {"status": "success", "message": "Database sync started in background."}

@router.get("/history", response_class=HTMLResponse)
async def peer_history(
    request: Request, 
    host_ip: str, 
    neighbor_ip: str, 
    protocol: str = "BGP"
):
    conn = get_db_conn()
    table = "bgp_state_changes" if protocol == "BGP" else "ospf_state_changes"
    history = conn.execute(
        f"SELECT * FROM {table} WHERE host_ip=? AND neighbor_ip=? ORDER BY timestamp DESC",
        (host_ip, neighbor_ip)
    ).fetchall()
    conn.close()

    return templates.TemplateResponse("monitor_history.html", {
        "request": request,
        "history": history,
        "neighbor": neighbor_ip,
        "protocol": protocol
    })


def get_recently_changed_peers(conn):
    if conn is None:
        return [], []
    # bgp_peers = set(row['neighbor_ip'] for row in conn.execute(
        # "SELECT DISTINCT neighbor_ip FROM bgp_state_changes"
    bgp_peers = conn.execute(        
        "SELECT * FROM bgp_state_changes"
    ).fetchall()
    # ospf_peers = set(row['neighbor_address'] for row in conn.execute(
    #     "SELECT DISTINCT neighbor_address FROM ospf_state_changes"
    ospf_peers = conn.execute(
        "SELECT * FROM ospf_state_changes"
    ).fetchall()
    return bgp_peers, ospf_peers

def get_problem_peers(conn):
    if conn is None:
        return set(), [], []
    problem_bgp = conn.execute(
        "SELECT * FROM bgp_peer_status WHERE state != 'Established'"
    ).fetchall()
    
    # problem_ospf = conn.execute(
    #     "SELECT * FROM ospf_peer_status WHERE UPPER(state) NOT LIKE 'FULL%'"
    # ).fetchall()

    problem_ospf = get_persistent_non_full_peers(conn)
    # problem_ospf = get_comprehensive_ospf_report(conn)
    
    since_time = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    recent_bgp = conn.execute(
        "SELECT DISTINCT neighbor_ip FROM bgp_state_changes WHERE timestamp >= ?",
        (since_time,)
    ).fetchall()
    
    recent_ospf = conn.execute(
        "SELECT DISTINCT neighbor_address FROM ospf_state_changes WHERE timestamp >= ?",
        (since_time,)
    ).fetchall()
    
    problem_ips = set()
    for row in problem_bgp + recent_bgp:
        problem_ips.add(row['neighbor_ip'])
    for row in problem_ospf + recent_ospf:
        problem_ips.add(row['neighbor_address'])
    
    return problem_ips, problem_bgp, problem_ospf

def get_ospf_current_status(conn):
    if conn is None:
        return []
    try:
        query = "SELECT * FROM ospf_peer_status ORDER BY hostname, process, neighbor_address, verbose_uptime DESC"
    except sqlite3.OperationalError as e:
        logger.error(f"Error get_ospf_current_status query: {e}")
        return []
    return conn.execute(query).fetchall()

def get_bgp_current_status(conn):
    if conn is None:
        return []
    try:
        query = "SELECT * FROM bgp_peer_status ORDER BY hostname, vpn_instance, neighbor_ip"
    except sqlite3.OperationalError as e:
        logger.error(f"Error get_bgp_current_status query: {e}")
        return []
    return conn.execute(query).fetchall()

def get_peer_history(conn, hostname, protocol, ip):
    if conn is None:
        return []
    table = 'bgp_state_changes' if protocol == 'bgp' else 'ospf_state_changes'
    neighbor_column = 'neighbor_ip' if protocol == 'bgp' else 'neighbor_address'
    try:
        query = f"SELECT * FROM {table} WHERE {neighbor_column} = ? AND hostname = ? ORDER BY timestamp DESC"
    except sqlite3.OperationalError as e:
        logger.error(f"Error get_peer_history query: {e}")
        return []
    return conn.execute(query, (ip, hostname)).fetchall()

def parse_uptime(up_str):
    """
    Convert various uptime strings to total minutes (int).
    Supported formats:
        - 1y0w, 2y3w4d
        - 1w4d, 5d12h, 3h45m
        - 01:23:45, 45:30
        - ****h, never
        - 123 (minutes, fallback)
    Returns: int (minutes)
    """    
    up_str = str(up_str).strip() if up_str is not None else "0"
    
    if up_str.startswith('****h'):
        up_str = '9999h48m'  # Treat invalid or long uptime as longest for sorting
    elif up_str == "never":
        up_str = '99999h48m'
        
    try:
        if 'h' in up_str and up_str.endswith('m'):
            h_part, m_part = up_str.split('h')
            return int(h_part) * 60 + int(m_part.rstrip('m'))
        elif 'd' in up_str and up_str.endswith('h'):
            d_part, h_part = up_str.split('d')
            return int(d_part) * 24 * 60 + int(h_part.rstrip('h')) * 60        
        elif 'w' in up_str and up_str.endswith('d'):
            w_part, d_part = up_str.split('w')
            return int(w_part) * 7 * 24 * 60 + int(d_part.rstrip('d')) * 24 * 60  
        elif 'y' in up_str and up_str.endswith('w'):
            y_part, w_part = up_str.split('y')
            return int(y_part) * 365 * 7 * 24 * 60 + int(w_part.rstrip('w')) * 7 * 24 * 60  
        elif ':' in up_str:
            parts = [int(x) for x in up_str.split(':')]
            if len(parts) == 3:
                h, m, s = parts
                return h * 60 + m + s / 60
            elif len(parts) == 2:
                m, s = parts
                return m + s / 60
        else:
            return int(up_str)  # Fallback to integer if no special format
    except (ValueError, AttributeError):
        return 0  # Default to 0 for unparseable values

def get_persistent_non_full_peers(conn):
    """Get peers that are persistently not FULL (never recovered)"""
    cursor = conn.cursor()
    
    # Step 1: Get the very last event for each peer (regardless of state), remove duplicates by ROWID- 20251126
    cursor.execute("""
        SELECT s1.hostname, s1.process, s1.neighbor_address, s1.interface, s1.to_state, s1.timestamp, s1.log_file
        FROM ospf_state_changes s1
        JOIN (
            SELECT hostname, process, neighbor_address, MAX(timestamp) AS max_ts, MAX(ROWID) AS max_rowid
            FROM ospf_state_changes
            GROUP BY hostname, process, neighbor_address
        ) s2 ON s1.hostname = s2.hostname 
            AND s1.process = s2.process 
            AND s1.neighbor_address = s2.neighbor_address 
            AND s1.timestamp = s2.max_ts
            AND s1.ROWID = s2.max_rowid
        WHERE UPPER(s1.to_state) NOT LIKE 'FULL%'
    """)
    last_events_non_full = cursor.fetchall()
    
    # Exit early if no matching events
    if not last_events_non_full:
        return []
    
    # Step 2: Get current FULL peers with composite keys (excluding interface)
    cursor.execute("""
        SELECT hostname, process, neighbor_address
        FROM ospf_peer_status
        WHERE UPPER(state) LIKE 'FULL%'
    """)
    current_full_peers = cursor.fetchall()
    
    # Create set of composite keys for current FULL peers
    full_peer_keys = set()
    for peer in current_full_peers:
        key = (peer[0], peer[1], peer[2])  # hostname, process, address
        full_peer_keys.add(key)
    
    # Step 3: Filter peers that are still not FULL
    persistent_non_full = []
    for event in last_events_non_full:
        # Create matching composite key for event
        event_key = (event[0], event[1], event[2])
        
        # Only include if not in current FULL peers
        if event_key not in full_peer_keys:
            persistent_non_full.append({
                'hostname': event[0],
                'process': event[1],
                'neighbor_address': event[2],
                'interface': event[3],
                'last_state': event[4],
                'timestamp': event[5],
                'source_log_file': event[6]
            })
    
    return persistent_non_full

def get_comprehensive_ospf_report(conn):
    """Comprehensive OSPF report including peers with no event history"""
    cursor = conn.cursor()
    
    # Step 1: Get all current OSPF peers from peer status table
    cursor.execute("""
        SELECT hostname, process, neighbor_routerid, neighbor_address, interface, state, 
               verbose_uptime, last_updated_ts, source_log_file
        FROM ospf_peer_status
        WHERE UPPER(state) NOT LIKE 'FULL%'
    """)
    current_peers = cursor.fetchall()
    
    # Create dictionary for current peers
    current_peer_dict = {}
    for peer in current_peers:
        key = (peer[0], peer[1], peer[3], peer[4])  # (host, process, address, interface)
        current_peer_dict[key] = {
            'state': peer[5],
            'router_id': peer[2],
            'uptime': peer[6],
            'last_seen': peer[7],
            'source_log_file': peer[8]
        }
    
    # Step 2: Get all historical state change events
    cursor.execute("""
        SELECT hostname, process, neighbor_address, interface, 
               from_state, to_state, timestamp, log_file
        FROM ospf_state_changes
    """)
    all_events = cursor.fetchall()
    
    # Process events with timestamp parsing
    event_dict = {}
    for event in all_events:
        host, process, addr, intf, from_state, to_state, ts, log_file = event
        key = (host, process, addr, intf)
        
        # Parse timestamp
        log_year = log_file[:4] if log_file and len(log_file) >= 4 else None
        event_time = parse_any_timestamp(ts, log_year)
        
        if not event_time:
            continue
            
        # Track last event per peer
        if key not in event_dict or event_time > event_dict[key]['datetime']:
            event_dict[key] = {
                'from_state': from_state,
                'to_state': to_state,
                'timestamp': ts,
                'log_file': log_file,
                'datetime': event_time
            }
    
    # Step 3: Get all peers from log files (day0 peers)
    log_peers = set()
    cursor.execute("SELECT DISTINCT hostname, process, neighbor_address, interface FROM ospf_peer_status")
    for row in cursor.fetchall():
        log_peers.add((row[0], row[1], row[2], row[3]))
    
    # Step 4: Identify all unique peers from all sources
    all_peer_keys = set(current_peer_dict.keys()) | set(event_dict.keys()) | log_peers
    
    # Step 5: Classify peers and generate report
    report = []
    
    for key in all_peer_keys:
        host, process, addr, intf = key
        current_info = current_peer_dict.get(key)
        event_info = event_dict.get(key)
        
        # Initialize sort_time with minimum datetime
        sort_time = datetime.min
        
        # Case 1: Peer exists in current status
        if current_info:
            current_state = current_info['state'].upper()
            router_id = current_info['router_id']
            
            # Subcase 1a: Has event history
            if event_info:
                if current_state == 'FULL':
                    status = "FULL (stable)"
                else:
                    status = f"Current: {current_state}"
                last_event = f"{event_info['from_state']} → {event_info['to_state']}"
                timestamp = event_info['timestamp']
                log_source = event_info['log_file']
                sort_time = event_info['datetime']
            
            # Subcase 1b: No event history (day0 peer)
            else:
                status = "FULL (no events)" if current_state == 'FULL' else f"Current: {current_state}"
                last_event = "No state change events"
                timestamp = current_info['last_seen']  # Use last snapshot time
                log_source = current_info['source_file']
                
                # Parse last seen timestamp for sorting
                last_seen_dt = parse_any_timestamp(timestamp)
                if last_seen_dt:
                    sort_time = last_seen_dt
                
                # Calculate first seen time from uptime if available
                if current_info['uptime']:
                    status += f" | Up since: {current_info['uptime']}"
        
        # Case 2: Peer missing from current status
        else:
            router_id = "Unknown"
            
            # Subcase 2a: Has event history
            if event_info:
                status = "Disappeared"
                last_event = f"{event_info['from_state']} → {event_info['to_state']}"
                timestamp = event_info['timestamp']
                log_source = event_info['log_file']
                sort_time = event_info['datetime']
                
                # Special case: Last seen as FULL but disappeared
                if event_info['to_state'].upper() == 'FULL':
                    status = "Disappeared after FULL"
            
            # Subcase 2b: Log-only peer (no current status, no events)
            else:
                status = "Historical peer (no current status)"
                last_event = "No recorded events"
                timestamp = "N/A"
                log_source = "Command output"
        
        report.append({
            'hostname': host,
            'process': process,
            'router_id': router_id,
            'neighbor_address': addr,
            'interface': intf,
            'last_state': status,
            'last_event': last_event,
            'timestamp': timestamp,
            'source_log_file': log_source,
            'sort_time': sort_time  # Add datetime object for sorting
        })
    
    # Step 6: Sort by sort_time
    report.sort(key=lambda x: x['sort_time'], reverse=True)
    
    return report

#20251031
# def get_peer_status(protocol: str, hostname: str, instance_name: str, neighbor: str) -> Optional[Dict]:
#     """
#     Return current peer status from the latest snapshot.
#     """
#     conn = get_db_connection()
#     if conn is None:
#         return None

#     try:
#         if protocol.lower() == 'bgp':
#             row = conn.execute(
#                 """
#                 SELECT * FROM bgp_peer_status
#                 WHERE hostname = ? AND vpn_instance = ? AND neighbor_ip = ?
#                 ORDER BY last_snapshot_id DESC
#                 LIMIT 1
#                 """,
#                 (hostname, instance_name, neighbor)
#             ).fetchone()

#         elif protocol.lower() == 'ospf':
#             row = conn.execute(
#                 """
#                 SELECT * FROM ospf_peer_status
#                 WHERE hostname = ? AND neighbor_address = ?
#                 ORDER BY last_snapshot_id DESC
#                 LIMIT 1
#                 """,
#                 (hostname, neighbor)
#             ).fetchone()
#         else:
#             row = None

#         if row is None:
#             logger.info(f"No current status found for {protocol} peer: hostname={hostname}, neighbor={neighbor}")
#         else:
#             if protocol.lower() == 'bgp':
#                 logger.info(f"{hostname} Found current status for {protocol} peer {neighbor}: state={row['state']}, verbose_uptime={row['up_down_time']}")
#             elif protocol.lower() == 'ospf':
#                 logger.info(f"{hostname} Found current status for {protocol} peer {neighbor}: state={row['state']}, verbose_uptime={row['verbose_uptime']}")

#         return dict(row) if row else None

#     except sqlite3.Error as e:
#         logger.error(f"get_peer_status error: {e}")
#         return None
#     finally:
#         conn.close()

def parse_any_timestamp(ts_str, log_year=None):
    """Robust timestamp parser with enhanced error handling"""
    if not ts_str or not isinstance(ts_str, str):
        return None
        
    # Clean common issues
    cleaned = ts_str.strip()
    cleaned = re.sub(r'(\d{2}):(\d{3})\s+(\d{4})$', r'\1.\2 \3', cleaned)  # Fix HPE micros
    cleaned = cleaned.replace('  ', ' ')  # Fix double spaces
    
    formats = [
        '%b %d %H.%M.%S.%f %Y',  # HPE: "Jul 10 10.30.20.918 2025"
        '%b %d %H:%M:%S %Y',      # Cisco: "Jul 10 10:30:20 2025"
        '%Y-%m-%d %H:%M:%S',      # Standard: "2025-07-10 09:02:54"
        '%b %d %H.%M.%S %Y',      # Alternative: "Jul 10 10.30.20 2025"
        '%b %d %H.%M.%S:%f %Y',   # HPE variant: "Jul 10 10.30.20:918 2025"
        '%Y%m%d_%H%M%S',          # Filename format: "20250804_212423"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    
    # Fallback with year extraction
    if log_year:
        for fmt in formats:
            try:
                return datetime.strptime(f"{cleaned} {log_year}", fmt)
            except ValueError:
                continue
    
    # Try parsing without microseconds
    for fmt in formats:
        try:
            # Try without fractional seconds
            return datetime.strptime(cleaned.split('.')[0], fmt)
        except (ValueError, IndexError):
            continue
    
    logger.warning(f"Timestamp parse failed: '{ts_str}'")
    return None

def get_time_from_logfile(log_file):
    m = re.match(r"(\d{8})_(\d{6})_", log_file)
    if m:
        date_part, time_part = m.groups()
        try:
            return datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")
        except Exception:
            return None
    return None

def print_html_header(title):
    print("Content-type: text/html; charset=utf-8\n")
    print(f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>{title}</title>')
    print("""
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f8f9fa; color: #212529; margin: 0; }
        h1, h2 { color: #343a40; border-bottom: 2px solid #dee2e6; padding-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
        table { border-collapse: collapse; width: 100%; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        th, td { border: 1px solid #dee2e6; padding: 10px; text-align: left; vertical-align: middle; }
        th { background-color: #e9ecef; position: sticky; top: 0; }
        a { color: #007bff; text-decoration: none; font-weight: bold; }
        a:hover { text-decoration: underline; }
        .container { max-width: 1600px; margin: auto; background: white; padding: 10px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        .back-link { display: inline-block; margin: 20px 0; font-size: 1.1em; }
        .status-down, .status-init, .status-exstart, .status-idle, .status-active, .status-connect { background-color: #f8d7da; color: #721c24; }
        .status-full, .status-established { background-color: #d4edda; color: #155724; }
        .recent-flap { background-color: #ffdddd !important; border-left: 4px solid #dc3545; }
        .problem-peer { background-color: #fff3cd !important; border-left: 4px solid #ffc107; font-weight: bold; }
        .group-header { background-color: #6c757d; color: white; font-size: 1.1em; padding: 10px 15px; }
        .toggle-btn { background: #6c757d; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.9em; transition: all 0.2s; }
        .toggle-btn:hover { background: #5a6268; }
        .collapsed .table-content { display: none; }
        .toggle-icon { display: inline-block; width: 20px; text-align: center; }
        .section-container { margin-bottom: 30px; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; }
        .section-header { background-color: #e9ecef; display: flex; justify-content: space-between; align-items: center; }
        .section-title { margin: 0; flex-grow: 1; }
        .table-container { font-size: 12px; max-height: 500px; overflow-y: auto; }
        .summary-tabs { display: flex; margin-bottom: 20px; border-bottom: 1px solid #dee2e6; }
        .tab-btn { padding: 10px 20px; background: #e9ecef; border: none; cursor: pointer; border-radius: 5px 5px 0 0; margin-right: 5px; }
        .tab-btn.active { background: #6c757d; color: white; font-weight: bold; }
        .problem-count { background-color: #dc3545; color: white; border-radius: 50%; width: 25px; height: 25px; display: inline-flex; justify-content: center; align-items: center; font-size: 0.8em; margin-left: 10px; }
        .uptime-warning { color: #d63384; font-weight: bold; }
        .no-problems { padding: 20px; text-align: center; color: #6c757d; font-style: italic; }
        .filter-row { background-color: #f1f1f1; position: sticky; margin: 0; }
        .filter-row input { width: 100%; padding: 0px; margin: 0; box-sizing: border-box; border: 1px solid #dee2e6; border-radius: 4px; }   
    </style>       
    """)
    print(f"<script>{html_java_script}</script></head>")
    print(f'''    
    <body><div class='container'>
    <form method='post' enctype='multipart/form-data' action='getweboutput.py' target='_blank'>
        <h3 style='margin:0'> KDC/eNG Core Switch log check:</h3>

        <div class="flex-container" style="display:flex;justify-content: space-around;">
            <div style="width:50%;">
                Device IP address (Multi-Select): <br>
                <select name="core_ipaddress" multiple style="width:350px;height:200px;" >
                    <option value="hp_comware:10.102.102.80">LAB-eNG-KEL-Core 10.102.102.80  </option>
                    <option value="hp_comware:10.102.102.79">LAB-eNG-KAM-Core 10.102.102.79    </option>
                    <option value="hp_comware:10.8.8.15">LAB-eNG-CC-Core 10.8.8.15 </option>
                    <option value="hp_comware:10.8.8.16">LAB-eNG-CW-Core 10.8.8.16 </option>
                    <option value="hp_comware:10.251.0.75">KDC-R4.7-Core-1 10.251.0.75 </option>
                    <option value="hp_comware:10.251.0.76">KDC-R4.23-Core-2 10.251.0.76 </option>
                    <option value="hp_comware:10.251.18.216">KDC-DMZ-KAM 10.251.18.216</option>
                    <option value="hp_comware:10.251.18.217">KDC-DMZ-KEL 10.251.18.217</option>
                    <option value="cisco_ios:10.26.101.127">NS-LGH-LGAC-01A-C9600-Core1 10.26.101.127 </option>
                    <option value="cisco_ios:10.26.101.128">NS-LGH-LGAC-PIMS-C9600-Core2 10.26.101.128 </option>
                    <option value="arista_eos:10.26.101.7">VGH-JPS3730-Core1 10.26.101.7</option>
                    <option value="arista_eos:10.26.101.8">VGH-JPNB9-Core-2 10.26.101.8</option>            
                </select>
            </div>   
            <div>
            <div style="text-align: end;">
                SA-User name:         <input type="text" name="core_uname" placeholder="soc2019_sa">
                User password:        <input type="password" name="core_passwd">
                <input type="submit" value="Submit" ></form>     
            </div>
            <div id="report-list-container" style="margin-bottom: 20px;text-align: end;">
          ''')
    
    # 20251127 NEW SECTION: Handle the listing of reports 
    report_list = fastapi_mymodule.list_reports(log_directory)
    if 'show_reports' in form or not form.getvalue("iplist"):
        fastapi_mymodule.generate_dropdown_list(report_list)   

    print('''</div></div></div>''')

def display_summary_page(conn):
    print_html_header("BGP & OSPF Monitoring Dashboard")
    
    recent_bgp_flaps, recent_ospf_flaps = get_recently_changed_peers(conn)
    problem_ips, problem_bgp, problem_ospf = get_problem_peers(conn)

    # problem_ospf = get_persistent_non_full_peers(conn)
    # problem_count = len(problem_ips)
    bgp_peers = get_bgp_current_status(conn)
    ospf_peers = get_ospf_current_status(conn)

    # problem_ospf = get_comprehensive_ospf_report(conn)

    
    print(f"""
    <div style='display:flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'>
        <h2 style='margin:0'>BGP&OSPF Peer Analyzer</h2>
        <div style='text-align: right; margin: 0; display:none;'>
            <button class='toggle-btn' onclick='flushStatus()'>Flush Status</button>
        </div>
    </div>
    <div class='summary-tabs'>
        <button class='tab-btn' data-tab='problem-peers' onclick='showTab(\"problem-peers\")'>
        Problem Peers <span class='problem-count'>{len(problem_bgp) + len(problem_ospf)}</span></button>
    """)
    # print(f"""        
    #     <button class='tab-btn' data-tab='all-event' onclick='showTab(\"all-event\")'>
    #     State Change Event {len(recent_bgp_flaps) + len(recent_ospf_flaps)}</button>
    # """)
    print(f"""        
        <button class='tab-btn' data-tab='all-bgp' onclick='showTab(\"all-bgp\")'>All BGP Peers {len(bgp_peers)}</button>
        <button class='tab-btn' data-tab='all-ospf' onclick='showTab(\"all-ospf\")'>All OSPF Peers {len(ospf_peers)}</button>
    </div>
    """)

    html_problem_peers(conn, problem_bgp, problem_ospf, recent_bgp_flaps, recent_ospf_flaps)

    # html_state_event(conn, recent_bgp_flaps, recent_ospf_flaps)

    html_bgp_peers(conn, recent_bgp_flaps, problem_bgp)
    
    html_ospf_peers(conn, recent_ospf_flaps, problem_ospf)
    
    print("</body></html>")

def html_problem_peers(conn, problem_bgp, problem_ospf, recent_bgp_flaps, recent_ospf_flaps):

    problem_count = len(problem_bgp) + len(problem_ospf)

    html_output = ["<div id='problem-peers' class='tab-content'>"]

    if conn is None or problem_count == 0:
        html_output.append("<div class='no-problems'><h3>No Problem Peers Found</h3>")
        if conn is None:
            html_output.append("<p>Database not available. Use 'Flush Status' to initialize.</p>")
        else:
            html_output.append("<p>All peers are in stable state with no recent issues.</p>")
        html_output.append("</div>")
    else:
        html_output.append(f"""
            <div class='problem-tabs' style='margin-bottom: 20px;'>
                <button class='tab-btn active' data-tab='problem-bgp' onclick='showSubTab("problem-bgp")'>
                    BGP Issues <span class='problem-count'>{len(problem_bgp)}</span>
                </button>
                <button class='tab-btn' data-tab='problem-ospf' onclick='showSubTab("problem-ospf")'>
                    OSPF Issues <span class='problem-count'>{len(problem_ospf)}</span>
                </button>
            </div>
        """)

        html_output.append(f"""<div id='problem-bgp' class='subtab-content'>
                           <h4 style='margin:0'>BGP Peers Last state NOT in \"Established\": {len(problem_bgp)} </h4>""")
        if problem_bgp:
            html_output.append("""
            <table id='problem-bgp-table' style='font-size: 12px;'>
            <thead>
                <tr><th>Device</th><th>Instance</th><th>Neighbor</th><th>Duration</th><th>Last State</th><th>Last Check</th></tr>
                <tr class='filter-row'>
                    <td><input type='text' onkeyup="filterTable('problem-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-bgp-table')"></td>
                </tr>
            </thead>
            """)
            all_problem_bgp_peers = sorted(problem_bgp, key=lambda p: parse_uptime(p['up_down_time'] or "0:00"))
            seen_bgp = set()
            for peer in all_problem_bgp_peers:
                key = (peer['hostname'], peer['neighbor_ip'])
                if key not in seen_bgp:
                    seen_bgp.add(key)
                    row_classes = []
                    if peer['state'] != 'Established':
                        row_classes.append("status-down")
                    if peer['neighbor_ip'] in recent_bgp_flaps:
                        row_classes.append("recent-flap")
                    row_classes.append("problem-peer")
                    display_instance = f"{peer['vpn_instance'] or 'N/A'}"
                    history_link = f"<a href='?protocol=bgp&hostname={peer['hostname']}&neighbor={peer['neighbor_ip']}'>{peer['neighbor_ip']}</a>"
                    logfile_link = f"<a href='..\logs\core\{peer['source_log_file']}' target='_blank'>{peer['last_updated_ts'] or 'N/A'}</a>"

                    up_time = peer['up_down_time'] or "N/A"
                    if up_time.startswith('****'):
                        up_time = "&gt;9999 Hours"
                    elif parse_uptime(up_time) < 12*60 and up_time != "N/A":
                        up_time = f"<span class='uptime-warning'>{up_time}</span>"
                
                    html_output.append(f"""
                    <tr class='{' '.join(row_classes)}'>
                    <td>{peer['hostname'] or 'N/A'}</td>
                    <td>{display_instance}</td>
                    <td>{history_link}</td>
                    <td>{up_time}</td>
                    <td>{peer['state'] or 'N/A'}</td>
                    <td>{logfile_link}</td></tr>
                    """)
            html_output.append("</table>")
        html_output.append("</div>")

        # html_output.append("<div id='problem-ospf' class='subtab-content' style='display:none;'>")
        html_output.append(f"""<div id='problem-ospf' class='subtab-content' style='display:none;'>
        <h4 style='margin:0'>OSPF peer Last state NOT in "Full": {len(problem_ospf)} </h4>""")

        if problem_ospf:
            html_output.append("<table id='problem-ospf-table' style='font-size: 12px;'>")
            html_output.append("""<thead><tr><th>Device</th><th>Process</th><th>Neighbor</th><th>Interface</th><th>Last State</th><th stytle="width:15px">Last Check</th></tr>
                <tr class='filter-row'>
                    <td><input type='text' onkeyup="filterTable('problem-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('problem-ospf-table')"></td>
                </tr>
            </thead>""")
            seen_ospf = set()
            for peer in problem_ospf :
                key = (peer['hostname'], peer['neighbor_address'])
                if key not in seen_ospf:
                    seen_ospf.add(key)
                    history_link = f"<a href='?protocol=ospf&hostname={peer['hostname']}&neighbor={peer['neighbor_address']}'>{peer['neighbor_address']}</a>"
                    logfile_link = f"<a href='..\logs\core\{peer['source_log_file']}' target='_blank'>{peer['timestamp'] or 'N/A'}</a>"

                    html_output.append(f"<tr class='{' '.join(row_classes)}'>")
                    html_output.append(f"<td>{peer['hostname'] or 'N/A'}</td>")
                    html_output.append(f"<td>{peer['process'] or 'N/A'}</td>")
                    html_output.append(f"<td>{history_link}</td>")
                    html_output.append(f"<td>{peer['interface'] or 'N/A'}</td>")
                    html_output.append(f"<td>{peer['last_state'] or 'N/A'}</td>")
                    html_output.append(f"<td>{logfile_link}</td></tr>")
            html_output.append("</table>")
        else:
            print("<p>No OSPF problem peers found.</p>")          
        html_output.append("</div>") # Close the problem-ospf sub-tab

    html_output.append("</div>") # Close the main problem-peers tab

    return "".join(html_output)

def html_state_event(conn, recent_bgp_flaps, recent_ospf_flaps):

    print("<div id='all-event' class='tab-content'>")
    if conn is None or len(recent_bgp_flaps) == 0:
        print("<div class='no-problems'>")
        print("<h3>No State Event Found</h3>")
        if conn is None:
            print("<p>Database not available. Use 'Flush Status' to initialize.</p>")
        else:
            print("<p>All peers are in stable state with no recent issues.</p>")
        print("</div>")
    else:
        print(f"""
        <div style='margin-left: -20px; margin-top: -20px;'>
            <button class='tab-btn' data-tab='event-bgp' onclick='showSubTab(\"event-bgp\")'>BGP event {len(recent_bgp_flaps)}</button>
            <button class='tab-btn' data-tab='event-ospf' onclick='showSubTab(\"event-ospf\")'>OSPF event {len(recent_ospf_flaps)}</button>
        </div>
        """)

        print("""
        <div id='event-bgp' class='subtab-content' style='display:none;'>
            <div class='section-container' id='event-bgp-section'>
                <div class='section-header'>
                    <h2 class='section-title'> BGP State Event - last 200</h2>
                    <p id='event-bgp-count' >Visible BGP Event: <span>0</span></p>
                    <button class='toggle-btn' onclick=\"toggleSection('event-bgp-section')\">
                    <span id='event-bgp-section-icon'>▼</span> Toggle</button>
                </div>
        """)

        print("<div class='table-content'>")
        # print(f"<h4 style='margin:0'>BGP state event found: {len(recent_bgp_flaps)} </h4>")
        if recent_bgp_flaps:
            print("""
            <div class='table-container'>
            <table id='event-bgp-table' style='font-size: 12px;'>
            <thead>
                <tr><th>Device</th><th>Instance</th><th>Neighbor</th><th>Current</th><th>UpTime</th><th>From</th><th>To</th><th>Last Check</th></tr>
                <tr class='filter-row'>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-bgp-table')"></td>
                </tr>
            </thead>
            <tbody>                                   
            """)
            # Sort and limit BGP events to the last 200
            recent_bgp_flaps_sorted = sorted(recent_bgp_flaps, key=lambda x: x['timestamp'], reverse=True)
            recent_bgp_flaps_limited = recent_bgp_flaps_sorted[:200] if len(recent_bgp_flaps_sorted) > 200 else recent_bgp_flaps_sorted

            for peer in recent_bgp_flaps_limited:
                display_instance = f"{peer['vpn_instance'] or 'N/A'}"
                history_link = f"<a href='?protocol=bgp&hostname={peer['hostname']}&neighbor={peer['neighbor_ip']}'>{peer['neighbor_ip']}</a>"
                logfile_link = f"<a href='..\logs\core\{peer['log_file']}' target='_blank'>{peer['log_file'] or 'N/A'}</a>"

                current_status = conn.execute(
                    "SELECT up_down_time, state FROM bgp_peer_status WHERE neighbor_ip = ? AND hostname = ?", 
                    (peer['neighbor_ip'], peer['hostname'])
                ).fetchone()

                print(f"""
                <tr>
                    <td>{peer['hostname'] or 'N/A'}</td>
                    <td>{display_instance}</td>
                    <td>{history_link}</td>
                    <td>{current_status['state'] or 'N/A'}</td>
                    <td>{current_status['up_down_time']}</td>
                    <td>{peer['from_state']}</td>
                    <td>{peer['to_state'] or 'N/A'}</td>
                    <td>{logfile_link}</td>
                </tr>
                """)
            print("</tbody></table></div>")
        else:
            print("<p>No BGP State Event found.</p>")
        print("</div>")
        print("</div></div>")                 

        print("""
        <div id='event-ospf' class='subtab-content' style='display:none;'>
            <div class='section-container' id='event-ospf-section'>
                <div class='section-header'>
                    <h2 class='section-title'> OSPF State Event</h2>
                    <p id='event-ospf-count' style='align-right:20%'>Visible OSPF Event: <span>0</span></p>
                    <button class='toggle-btn' onclick=\"toggleSection('event-ospf-section')\">
                    <span id='event-ospf-section-icon'>▼</span> Toggle</button>
                </div>
        """)

        print("<div class='table-content'>")
        # print(f"<h4 style='margin:0'>OSPF State Event: {len(recent_ospf_flaps)} </h4>")
        if recent_ospf_flaps:
            print("<table id='event-ospf-table' style='font-size: 12px;'>")
            print(f"""
            <thead>
                  <tr>
                    <th>Device</th><th>Process</th><th>Area</th><th>Neighbor</th><th>Interface</th><th>State</th><th>Last Check</th>
                  </tr>
                <tr class='filter-row'>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                    <td><input type='text' onkeyup="filterTable('event-ospf-table')"></td>
                </tr>                  
            </thead>
        <tbody>
        """)
            seen_ospf = set()
            for peer in recent_ospf_flaps:
                key = (peer['hostname'], peer['neighbor_address'])
                if key not in seen_ospf:
                    seen_ospf.add(key)

                    current_status = conn.execute(
                        "SELECT * FROM ospf_peer_status WHERE neighbor_address = ? AND hostname = ?", 
                        (neighbor, hostname)
                    ).fetchone()

                    history_link = f"<a href='?protocol=ospf&hostname={peer['hostname']}&neighbor={peer['neighbor_address']}'>{peer['neighbor_address']}</a>"
                    logfile_link = f"<a href='..\logs\core\{peer['log_file']}' target='_blank'>{peer['log_file'] or 'N/A'}</a>"
                    # print(f"<tr class='{' '.join(row_classes)}'>")
                    print(f"<tr>")
                    print(f"<td>{peer['hostname'] or 'N/A'}</td>")
                    print(f"<td>{peer['process'] or 'N/A'}</td>")
                    print(f"<td>{peer['neighbor_address'] or 'N/A'}</td>")
                    print(f"<td>{history_link}</td>")
                    print(f"<td>{peer['from_state'] or 'N/A'}</td>")
                    print(f"<td>{peer['to_state'] or 'N/A'}</td>")
                    print(f"<td>{logfile_link}</td></tr>")
        else:
            print("<p>No OSPF State Event found.</p>")
        print("</tbody></table></div>")
        print("</div>")
    print("</div></div>")    

def html_bgp_peers(conn, recent_bgp_flaps, problem_bgp):
    html_output = []

    html_output.append("""
        <div id='all-bgp' class='tab-content' style='display:none;'>
        <div class='section-container' id='bgp-section'>
        <div class='section-header'>
        <h2 class='section-title'>All BGP Peers </h2>
        <p id='bgp-count' style='align-right:20%'>Visible BGP Peers: <span>0</span></p>
        <button class='toggle-btn' onclick="toggleSection('bgp-section')">
        <span id='bgp-section-icon'>▼</span> Toggle</button>
        </div>
    """)
    
    html_output.append("<div class='table-content'>")
    bgp_peers = get_bgp_current_status(conn)
    if conn is None or not bgp_peers: 
        html_output.append("<p style='padding: 20px;'>No BGP peer status data found. Use 'Flush Status' to initialize.</p>")
    else:
        html_output.append("""
        <div class='table-container'>
        <table id='bgp-table'>
            <thead>
                <tr><th>Device</th><th>Instance</th><th>RemoteAS</th><th>Neighbor</th><th>Duration</th><th>Last State</th><th>Last Check</th></tr>
                <tr class='filter-row'>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                    <td><input type='text' onkeyup="filterTable('bgp-table')"></td>
                </tr>
            </thead>
        <tbody>
        """)

        all_bgp_peers = sorted(bgp_peers, key=lambda p: parse_uptime(p['up_down_time'] or "0:00"))
        seen_bgp = set()
        for peer in all_bgp_peers:
            key = (peer['hostname'], peer['vpn_instance'], peer['neighbor_ip'])
            if key not in seen_bgp:
                seen_bgp.add(key)
                row_classes = [f"status-{str(peer['state']).lower()}"]
                if peer['neighbor_ip'] in recent_bgp_flaps: 
                    row_classes.append("recent-flap")
                if peer['neighbor_ip'] in problem_bgp:
                    row_classes.append("problem-peer")
                    
                display_instance = f"{peer['vpn_instance'] or 'N/A'}"
                history_link = f"<a href='?protocol=bgp&hostname={peer['hostname']}&neighbor={peer['neighbor_ip']}'>{peer['neighbor_ip']}</a>"
                logfile_link = f"<a href='..\logs\core\{peer['source_log_file']}' target='_blank'>{peer['last_updated_ts'] or 'N/A'}</a>"
                
                up_time = peer['up_down_time'] or "N/A"
                if up_time.startswith('****'):
                    up_time = "&gt;9999 Hours"
                elif parse_uptime(up_time) < 12*60 and up_time != "N/A":
                    up_time = f"<span class='uptime-warning'>{up_time}</span>"
                
                html_output.append(f"<tr class='{' '.join(row_classes)}'>")
                html_output.append(f"<td>{peer['hostname'] or 'N/A'}</td>")
                html_output.append(f"<td>{display_instance}</td>")
                html_output.append(f"<td>{peer['remote_as']}</td>")
                html_output.append(f"<td>{history_link}</td>")
                html_output.append(f"<td>{up_time}</td>")
                html_output.append(f"<td>{peer['state'] or 'N/A'}</td>")
                html_output.append(f"<td>{logfile_link}</td></tr>")
        html_output.append("</tbody></table>")
        html_output.append("</div>")
    html_output.append("</div></div></div>")    

    return "".join(html_output)

def html_ospf_peers(conn, recent_ospf_flaps, problem_ospf):
    html_output = []
    html_output.append("""
        <div id='all-ospf' class='tab-content' style='display:none;'>
        <div class='section-container' id='ospf-section'>
        <div class='section-header'>
        <h2 class='section-title'>All OSPF Peers</h2>
        <p id='ospf-count'>Visible OSPF Peers: <span>0</span></p>
        <button class='toggle-btn' onclick="toggleSection('ospf-section')">
        <span id='ospf-section-icon'>▼</span> Toggle</button>
        </div>
    """)
    
    html_output.append("<div class='table-content'>")
    ospf_peers = get_ospf_current_status(conn)
    if conn is None or not ospf_peers: 
        html_output.append("<p style='padding: 20px;'>No OSPF data found. Use 'Flush Status' to initialize.</p>")
    else:        
        html_output.append("""
<div class='table-container'>
<table id='ospf-table'>
    <thead>
        <tr>
            <th>Device</th>
            <th>Process</th>
            <th>VRF</th>
            <th>Neighbor</th>
            <th>Duration</th>
            <th>Last State:Mode</th>
            <th>Last Event</th>
            <th>Last Check</th>
        </tr>
        <tr class='filter-row'>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>             
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
            <td><input type='text' onkeyup="filterTable('ospf-table')"></td>
        </tr>
    </thead>
    <tbody>
        """)

        all_ospf_peers = sorted(ospf_peers, key=lambda p: parse_uptime(p['verbose_uptime'] or "0:00"))
        seen_ospf = set()
        for peer in all_ospf_peers:
            key = (peer['hostname'], peer['neighbor_address'])
            if key not in seen_ospf:
                seen_ospf.add(key)
                row_classes = [f"status-{str(peer['state']).lower().replace('/', '')}"]
                if peer['neighbor_address'] in recent_ospf_flaps: 
                    row_classes.append("recent-flap")
                if peer['neighbor_address'] in problem_ospf:
                    row_classes.append("problem-peer")

                history_link = f"<a href='?protocol=ospf&hostname={peer['hostname']}&neighbor={peer['neighbor_address']}'>{peer['neighbor_address']}</a>"
                logfile_link = f"<a href='..\logs\core\{peer['source_log_file']}' target='_blank'>{peer['last_updated_ts'] or 'N/A'}</a>"

                up_time = peer['verbose_uptime'] or "N/A"
                if up_time.startswith('****'):
                    up_time = "&gt;9999 Hours"
                elif parse_uptime(up_time) < 12*60 and up_time != "N/A":
                    up_time = f"<span class='uptime-warning'>{up_time}</span>"

                html_output.append(f"<tr class='{' '.join(row_classes)}'>")
                html_output.append(f"<td>{peer['hostname'] or 'N/A'}</td>")
                html_output.append(f"<td>{peer['process'] or 'N/A'}</td>")
                html_output.append(f"<td>{peer['vrf'] or 'N/A'}</td>")
                html_output.append(f"<td>{history_link}</td>")
                html_output.append(f"<td>{up_time}</td>") 
                html_output.append(f"<td>{peer['state'] or 'N/A'} : {peer['mode'] or 'N/A'}</td>")
                html_output.append(f"<td>{peer['last_down_time'] or 'N/A'}</td>")
                html_output.append(f"<td>{logfile_link}</td></tr>")
        html_output.append("</tbody></table>")
        html_output.append("</div>")
    html_output.append("</div></div></div>")    

    return "".join(html_output)

def display_history_page(conn, hostname, protocol, neighbor):
    print_html_header(f"History for {protocol.upper()} Peer: {neighbor}")
    print(f"<h1>History for {protocol.upper()} Peer: {hostname} {neighbor}</h1>")
    print("<a href='monitor.py' class='back-link'>← Back to Dashboard</a>")
    
    history = get_peer_history(conn, hostname, protocol, neighbor)
    if conn is None or not history:
        print(f"<p>No historical state change events found for {neighbor}. Use 'Flush Status' to initialize data.</p>")
    else:
        current_status = None
        if protocol == 'bgp':
            current_status = conn.execute(
                "SELECT * FROM bgp_peer_status WHERE neighbor_ip = ? AND hostname = ?", 
                (neighbor, hostname)
            ).fetchone()
        elif protocol == 'ospf':
            current_status = conn.execute(
                "SELECT * FROM ospf_peer_status WHERE neighbor_address = ? AND hostname = ?", 
                (neighbor, hostname)
            ).fetchone()
        
        if current_status:
            print("<div style='background: #e9ecef; padding: 15px; border-radius: 5px; margin-bottom: 20px;'>")
            print("<h3>Current Status</h3>")
            if protocol == 'bgp':
                print(f"<p>State: <strong>{current_status['state'] or 'N/A'}</strong> | ")
                print(f"Uptime: <strong>{current_status['up_down_time'] or 'N/A'}</strong> | ")
                print(f"Last Check: {current_status['last_updated_ts'] or 'N/A'}</p>")
            else:  # OSPF
                print(f"<p>State: <strong>{current_status['state'] or 'N/A'}</strong> | ")
                print(f"Interface: <strong>{current_status['interface'] or 'N/A'}</strong> | ")
                print(f"Last Check: {current_status['last_updated_ts'] or 'N/A'}</p>")
            print("</div>")
        
        print("<h3>State Change History</h3>")
        print("<div class='table-container'>")
        print("<table>")
        if protocol == 'bgp':
            print("<tr><th>Hostname</th><th>VPN Instance</th><th>State Change</th><th>Timestamp</th><th>LogFile</th></tr>")
            seen_history = set()
            for entry in history:
                key = (entry['hostname'], entry['neighbor_ip'], entry['timestamp'])
                if key not in seen_history:
                    seen_history.add(key)
                    log_file = entry['log_file']
                    log_link = f"<a href='{LOG_BASE_URL}{log_file}' target='_blank'>{log_file}</a>" if log_file else "N/A"
                    print(f"<tr><td>{entry['hostname'] or 'N/A'}</td>")
                    print(f"<td>{entry['vpn_instance'] or 'N/A'}</td>")
                    print(f"<td>{entry['from_state'] or 'N/A'} → {entry['to_state'] or 'N/A'}</td>")
                    print(f"<td>{entry['timestamp'] or 'N/A'}</td>")
                    print(f"<td>{log_link}</td></tr>")
        elif protocol == 'ospf':
            print("<tr><th>Hostname</th><th>Process</th><th>Interface</th><th>State Change</th><th>Timestamp</th><th>Log File</th></tr>")
            seen_history = set()
            for entry in history:
                key = (entry['hostname'], entry['neighbor_address'], entry['timestamp'])
                if key not in seen_history:
                    seen_history.add(key)
                    log_file = entry['log_file']
                    log_link = f"<a href='{LOG_BASE_URL}{log_file}' target='_blank'>{log_file}</a>" if log_file else "N/A"
                    print(f"<tr><td>{entry['hostname'] or 'N/A'}</td>")
                    print(f"<td>{entry['process'] or 'N/A'}</td>")
                    print(f"<td>{entry['interface'] or 'N/A'}</td>")
                    print(f"<td>{entry['from_state'] or 'N/A'} → {entry['to_state'] or 'N/A'}</td>")
                    print(f"<td>{entry['timestamp'] or 'N/A'}</td>")
                    print(f"<td>{log_link}</td></tr>")
        print("</table>")
        print("</div>")
    print("</div></body></html>")

html_java_script = """
function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    const icon = document.getElementById(sectionId + '-icon');
    if (section && icon) {
        section.classList.toggle('collapsed');
        icon.textContent = section.classList.contains('collapsed') ? '▶' : '▼';
        localStorage.setItem(sectionId + '-collapsed', section.classList.contains('collapsed'));
    }
}

function showTab(tabName) {
    const tab = document.getElementById(tabName);
    if (!tab) return;

    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    document.querySelectorAll('.summary-tabs .tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    tab.style.display = 'block';
    document.querySelector(`.summary-tabs .tab-btn[data-tab="${tabName}"]`).classList.add('active');
    localStorage.setItem('activeTab', tabName);

    if (tabName === 'problem-peers') {
        showSubTab('problem-bgp');
    }
}

function showSubTab(subTabName) {
    const subtab = document.getElementById(subTabName);
    if (!subtab) return;

    document.querySelectorAll('.subtab-content').forEach(subtab => {
        subtab.style.display = 'none';
    });
    document.querySelectorAll('.problem-tabs .tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    subtab.style.display = 'block';
    document.querySelector(`.problem-tabs .tab-btn[data-tab="${subTabName}"]`).classList.add('active');
    localStorage.setItem('activeSubTab', subTabName);
}

function flushStatus() {
    if (confirm("Are you want to flush the status and update the last log analysis?")) {
        const formData = new FormData();
        formData.append('flush', 'true');

        fetch(window.location.href, {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(data => {
            showModal(data.status, data.message, true);
        })
        .catch(error => {
            showModal('error', `Error during flush: ${error.message}`, false);
        });
    }
}

function showModal(status, message, allowReload) {
    let modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: white;
        padding: 20px;
        border: 1px solid #ccc;
        box-shadow: 0 0 10px rgba(0,0,0,0.5);
        z-index: 1000;
        text-align: center;
    `;
    let content = `
        <h3>Flush Status</h3>
        <p>Status: <strong>${status.toUpperCase()}</strong></p>
        <p>Message: ${message}</p>
        <button onclick="this.parentElement.remove()">Close</button>
    `;
    if (allowReload) {
        content += `<button onclick="this.parentElement.remove(); location.reload();">Refresh Page</button>`;
    }
    modal.innerHTML = content;
    document.body.appendChild(modal);
}

function filterTable(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const inputElements = table.querySelectorAll('.filter-row input');
    const rows = table.getElementsByTagName("tr");
    const hasFilter = Array.from(inputElements).some(input => input.value.trim() !== '');
    
    let visibleCount = 0;

    if (!hasFilter) {
        for (let i = 2; i < rows.length; i++) {
            rows[i].style.display = '';
            visibleCount++;
        }
    } else {
        for (let i = 2; i < rows.length; i++) {
            let shouldDisplay = true;
            const cells = rows[i].getElementsByTagName("td");
            for (let j = 0; j < inputElements.length; j++) {
                const filterValue = inputElements[j].value.trim();
                if (filterValue) {
                    const cellValue = cells[j].textContent.trim() || cells[j].innerText.trim();
                    // Check if both filter and cell value are numeric
                    const isNumericFilter = /^\d+$/.test(filterValue);
                    const isNumericCell = /^\d+$/.test(cellValue);
                    if (isNumericFilter && isNumericCell) {
                        const normalizedFilter = parseInt(filterValue, 10);
                        const normalizedCell = parseInt(cellValue, 10);
                        if (normalizedFilter !== normalizedCell) {
                            shouldDisplay = false;
                            break;
                        }
                    } else {
                        // Case-insensitive substring match for non-numeric values
                        if (cellValue.toLowerCase().indexOf(filterValue.toLowerCase()) === -1) {
                            shouldDisplay = false;
                            break;
                        }
                    }
                }
            }
            rows[i].style.display = shouldDisplay ? '' : 'none';
            if (shouldDisplay) visibleCount++;
        }
    }

    const countElement = document.getElementById(tableId === 'bgp-table' ? 'bgp-count' : 'ospf-count');
    if (countElement) {
        countElement.querySelector('span').textContent = visibleCount;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const summaryTabs = document.querySelector('.summary-tabs');
    if (summaryTabs) {
        const activeTab = localStorage.getItem('activeTab') || 'problem-peers';
        showTab(activeTab);

        ['event-bgp-section','event-ospf-section','bgp-section', 'ospf-section'].forEach(id => {
            const isCollapsed = localStorage.getItem(id + '-collapsed') === 'true';
            const section = document.getElementById(id);
            const icon = document.getElementById(id + '-icon');
            if (section && icon) {
                if (isCollapsed) {
                    section.classList.add('collapsed');
                    icon.textContent = '▶';
                }
            }
        });

        if (activeTab === 'problem-peers') {
            const activeSubTab = localStorage.getItem('activeSubTab') || 'problem-bgp';
            showSubTab(activeSubTab);
        }
    } else {
        localStorage.removeItem('activeTab');
        localStorage.removeItem('activeSubTab');
    }
});
"""

def flush_status():
    analysis_script = os.path.join(os.path.dirname(__file__), 'analysis_sqlite.py')
    if not os.path.exists(analysis_script):
        status = "fail"
        message = f"Analysis script not found at {analysis_script}"
        logger.error(f"Flush status: Analysis script not found at {analysis_script}")
    else:
        try:
            result = subprocess.run(
                [sys.executable, analysis_script],
                capture_output=True,
                text=True,
                check=False,
                cwd=os.path.dirname(__file__)
            )
            logger.info(f"Subprocess output: stdout={result.stdout}, stderr={result.stderr}")
            if result.returncode == 0:
                status = "success"
                message = result.stdout.strip() if result.stdout else "Analysis completed successfully."
                logger.info(f"Flush status: Analysis_sqlite.py executed successfully - {message}")
            elif "up to date" in result.stdout.lower():
                status = "info"
                message = "Analysis is already up to date."
                logger.info(f"Flush status: Analysis_sqlite.py is up to date - {message}")
            else:
                status = "fail"
                message = f"Analysis failed: {result.stderr or result.stdout or 'Unknown error, check logs'}"
                logger.error(f"Flush status: Analysis_sqlite.py failed - {message}")
        except Exception as e:
            status = "fail"
            message = f"Unexpected error: {str(e)}"
            logger.error(f"Flush status: Unexpected error - {str(e)}")

    print("Content-type: application/json; charset=utf-8\n")
    print(json.dumps({"status": status, "message": message}))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    conn = get_db_conn()
    
    try:
        from cgi import FieldStorage
        form = FieldStorage()
        hostname = form.getvalue("hostname")
        protocol = form.getvalue("protocol")
        neighbor = form.getvalue("neighbor")
        flush = form.getvalue("flush")
        
        if flush:
            flush_status()
        elif protocol and neighbor and hostname: 
            display_history_page(conn, hostname, protocol, neighbor)
        else: 
            display_summary_page(conn)
    except Exception as e:
        print(f"<h1>An error occurred</h1><p>{html.escape(str(e))}</p></div></body></html>")
    finally:
        if conn: 
            conn.close()