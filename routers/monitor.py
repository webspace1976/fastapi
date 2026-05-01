#!/usr/bin/env python3
"""
monitor.py — BGP/OSPF peer monitoring router.

Refactor notes (2026):
  - Removed all HTML-string-building functions (html_bgp_peers, html_ospf_peers,
    html_problem_peers, html_state_event).  Rendering now lives in Jinja2 templates.
  - New JSON API endpoints power the topology view and allow future JS-driven
    dashboards without a full page reload.
  - DatabaseManager used consistently; no bare sqlite3.connect() calls remain.
  - get_recently_changed_peers / get_problem_peers now accept a time_window_hours
    parameter (default 12) so callers can tune the lookback.
  - parse_uptime consolidated into one regex-first implementation; dead branches
    removed.
  - Removed duplicate dict key 'bgp_peers' in monitor_dashboard context.
  - html_state_event used print() instead of list-append — removed entirely;
    moved to a proper template.
  - filterTable() JS helper and row-deduplication logic stay in templates.
"""

import os
import re
import sys
import logging
import subprocess
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

sys.path.append("..")
import mainconfig
import utils.fastapi_mymodule as fastapi_mymodule

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from database.db_manager import DatabaseManager

# ── Module-level singletons ──────────────────────────────────────────────────
router = APIRouter()
templates = Jinja2Templates(directory=mainconfig.TEMPLATES_DIR)
logger = mainconfig.setup_module_logger(__name__)

DB_PATH = mainconfig.DB_PATH
CORE_LOGS_DIR = mainconfig.CORE_LOGS_DIR


# ── Uptime parsing ───────────────────────────────────────────────────────────

_UPTIME_SENTINEL = {
    "never":  99_999 * 60,
    "****h":   9_999 * 60,
}

def parse_uptime(up_str) -> int:
    """
    Convert vendor uptime strings to total minutes.

    Supported formats
    -----------------
    1y0w / 2y3w4d  →  years + weeks + days
    1w4d / 5d12h / 3h45m
    01:23:45 / 45:30 / 2768:19:43  (h:m:s or h:m or large-h:m:s)
    ****h  →  sentinel 9999 h
    never  →  sentinel 99999 h
    bare integer  →  treated as minutes
    """
    raw = str(up_str).strip() if up_str is not None else "0"

    # Sentinel shortcuts
    for token, minutes in _UPTIME_SENTINEL.items():
        if raw.startswith(token):
            return minutes

    try:
        # --- colon-separated (H:M:S or H:M or large-H:M:S) ---
        if ":" in raw and not any(c in raw for c in "yYwWdDhHmM"):
            parts = [int(x) for x in raw.split(":")]
            if len(parts) == 3:
                h, m, s = parts
                return h * 60 + m
            if len(parts) == 2:
                h, m = parts
                return h * 60 + m

        # --- unit-based (order matters: longest match first) ---
        # years + weeks
        m = re.fullmatch(r"(\d+)y(\d+)w", raw)
        if m:
            return int(m.group(1)) * 365 * 24 * 60 + int(m.group(2)) * 7 * 24 * 60

        # years + weeks + days
        m = re.fullmatch(r"(\d+)y(\d+)w(\d+)d", raw)
        if m:
            return (int(m.group(1)) * 365 * 24 * 60
                    + int(m.group(2)) * 7 * 24 * 60
                    + int(m.group(3)) * 24 * 60)

        # weeks + days
        m = re.fullmatch(r"(\d+)w(\d+)d", raw)
        if m:
            return int(m.group(1)) * 7 * 24 * 60 + int(m.group(2)) * 24 * 60

        # days + hours
        m = re.fullmatch(r"(\d+)d(\d+)h", raw)
        if m:
            return int(m.group(1)) * 24 * 60 + int(m.group(2)) * 60

        # hours + minutes
        m = re.fullmatch(r"(\d+)h(\d+)m", raw)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))

        # hours only
        m = re.fullmatch(r"(\d+)h", raw)
        if m:
            return int(m.group(1)) * 60

        # generic dXhYmZ
        m = re.search(r"(?:(\d+)d\s*)?(?:(\d+)h\s*)?(\d+)m", raw)
        if m:
            d = int(m.group(1) or 0)
            h = int(m.group(2) or 0)
            mn = int(m.group(3) or 0)
            return d * 1440 + h * 60 + mn

        return int(raw)

    except (ValueError, AttributeError):
        return 0


def format_uptime(up_str: str) -> str:
    """Return a human-friendly uptime string, with HTML warning for < 12 h."""
    if not up_str or up_str == "N/A":
        return "N/A"
    if up_str.startswith("****"):
        return "&gt;9999 Hours"

    minutes = parse_uptime(up_str)

    if ":" in up_str:
        parts = [int(x) for x in up_str.split(":")]
        if len(parts) == 3:
            h, m, _ = parts
            days, rem_h = divmod(h, 24)
            display = f"{days}d {rem_h}h" if days else f"{h}h {m}m"
        else:
            display = f"{parts[0]}m"
    else:
        display = up_str

    if minutes < 12 * 60:
        return f"<span class='uptime-warning'>{display}</span>"
    return display


# ── Timestamp parsing ────────────────────────────────────────────────────────

_TS_FORMATS = [
    "%b %d %H.%M.%S.%f %Y",   # HPE:      "Jul 10 10.30.20.918 2025"
    "%b %d %H:%M:%S %Y",       # Cisco:    "Jul 10 10:30:20 2025"
    "%Y-%m-%d %H:%M:%S",       # Standard: "2025-07-10 09:02:54"
    "%b %d %H.%M.%S %Y",       # Alt:      "Jul 10 10.30.20 2025"
    "%b %d %H.%M.%S:%f %Y",    # HPE var:  "Jul 10 10.30.20:918 2025"
    "%Y%m%d_%H%M%S",            # Filename: "20250804_212423"
]

def parse_any_ts(ts_str: str, log_year: str = None) -> Optional[datetime]:
    """Robust timestamp parser covering multiple vendor formats."""
    if not ts_str or not isinstance(ts_str, str):
        return None

    cleaned = ts_str.strip()
    cleaned = re.sub(r"(\d{2}):(\d{3})\s+(\d{4})$", r"\1.\2 \3", cleaned)
    cleaned = cleaned.replace("  ", " ")

    candidates = [cleaned]
    if log_year:
        candidates.append(f"{cleaned} {log_year}")

    for candidate in candidates:
        for fmt in _TS_FORMATS:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                pass
        # Strip fractional seconds and retry
        for fmt in _TS_FORMATS:
            try:
                return datetime.strptime(candidate.split(".")[0], fmt)
            except (ValueError, IndexError):
                pass

    logger.warning("Timestamp parse failed: %r", ts_str)
    return None


def get_time_from_logfile(log_file: str) -> Optional[datetime]:
    m = re.match(r"(\d{8})_(\d{6})_", log_file)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


# ── DB query helpers ─────────────────────────────────────────────────────────

def get_bgp_current_status(db: DatabaseManager) -> Tuple[List, List]:
    if db is None:
        return []
    return db.execute_query(
        "SELECT * FROM bgp_peer_status WHERE UPPER(hostname) NOT LIKE '%LGH%'"
    )


def get_ospf_current_status(db: DatabaseManager) -> list:
    if db is None:
        return []
    return db.execute_query(
        "SELECT * FROM ospf_peer_status ORDER BY hostname, process, neighbor_address, verbose_uptime DESC"
    )


def get_recently_changed_peers(db: DatabaseManager, time_window_hours: int = 12):
    """Return (bgp_changes, ospf_changes) within the lookback window."""
    if db is None:
        return [], []
    since = (datetime.now() - timedelta(hours=time_window_hours)).strftime("%Y-%m-%d %H:%M:%S")
    bgp = db.execute_query(
        "SELECT * FROM bgp_state_changes WHERE last_updated_ts >= :since", {"since": since}
    )
    ospf = db.execute_query(
        "SELECT * FROM ospf_state_changes WHERE last_updated_ts >= :since", {"since": since}
    )
    return bgp, ospf


def get_problem_peers(db: DatabaseManager, time_window_hours: int = 12):
    """
    Returns (problem_ip_set, problem_bgp_rows, problem_ospf_rows).

    problem_ips: union of non-established BGP, non-FULL OSPF, and recent flaps.
    """
    if db is None:
        return set(), [], []

    problem_bgp = db.execute_query(
        "SELECT * FROM bgp_peer_status "
        "WHERE UPPER(state) != 'ESTABLISHED' AND UPPER(hostname) NOT LIKE '%LGH%'"
    )
    problem_ospf = get_persistent_non_full_peers(db)

    since = (datetime.now() - timedelta(hours=time_window_hours)).strftime("%Y-%m-%d %H:%M:%S")
    recent_bgp = db.execute_query(
        "SELECT DISTINCT neighbor_address FROM bgp_state_changes WHERE last_updated_ts >= :since",
        {"since": since}
    )
    recent_ospf = db.execute_query(
        "SELECT DISTINCT neighbor_address FROM ospf_state_changes WHERE last_updated_ts >= :since",
        {"since": since}
    )

    problem_ips: set = set()
    for row in list(problem_bgp) + list(recent_bgp):
        problem_ips.add(row["neighbor_address"])
    for row in list(problem_ospf) + list(recent_ospf):
        problem_ips.add(row["neighbor_address"])

    return problem_ips, problem_bgp, problem_ospf


def get_peer_history(db: DatabaseManager, hostname: str, protocol: str, ip: str) -> list:
    if db is None:
        return []
    table = "bgp_state_changes" if protocol.lower() == "bgp" else "ospf_state_changes"
    sql = f"""
        SELECT * FROM {table}
        WHERE neighbor_address = :ip AND hostname = :hostname
        ORDER BY last_updated_ts DESC
    """
    return db.execute_query(sql, {"ip": ip, "hostname": hostname})


def get_peer_status(
    db: DatabaseManager,
    protocol: str,
    host_ip: str,
    instance_name: str,
    neighbor: str,
) -> Optional[dict]:
    p = protocol.lower()
    if p == "bgp":
        sql = """
            SELECT * FROM bgp_peer_status
            WHERE host_ip = :host_ip AND vpn_instance = :instance AND neighbor_address = :neighbor
            ORDER BY last_snapshot_id DESC LIMIT 1
        """
        params = {"host_ip": host_ip, "instance": instance_name, "neighbor": neighbor}
    elif p == "ospf":
        sql = """
            SELECT * FROM ospf_peer_status
            WHERE host_ip = :host_ip AND neighbor_address = :neighbor
            ORDER BY last_snapshot_id DESC LIMIT 1
        """
        params = {"host_ip": host_ip, "neighbor": neighbor}
    else:
        logger.warning("Unsupported protocol: %s", protocol)
        return None

    try:
        results = db.execute_query(sql, params)
        if not results:
            logger.info("No status for %s peer: host=%s, neighbor=%s", protocol, host_ip, neighbor)
            return None
        row = results[0]
        uptime_key = "up_down_time" if p == "bgp" else "verbose_uptime"
        logger.info(
            "%s status %s/%s: state=%s uptime=%s",
            protocol, host_ip, neighbor, row["state"], row[uptime_key],
        )
        return dict(row)
    except Exception as exc:
        logger.error("get_peer_status error (%s): %s", protocol, exc)
        return None


# ── OSPF persistence helpers ─────────────────────────────────────────────────

def get_persistent_non_full_peers(db: DatabaseManager) -> list:
    """
    Peers whose *most recent* OSPF state-change event is NOT FULL and who
    are still not FULL in the current status table.
    """
    # Use raw cursor because we need ROWID
    # conn = db._get_connection()  # adjust to your DatabaseManager's actual method
    # cursor = conn.cursor()

    db.execute_query("""
        SELECT s1.hostname, s1.process, s1.neighbor_address, s1.interface,
               s1.to_state, s1.last_updated_ts, s1.log_file
        FROM ospf_state_changes s1
        JOIN (
            SELECT hostname, process, neighbor_address,
                   MAX(last_updated_ts) AS max_ts, MAX(ROWID) AS max_rowid
            FROM ospf_state_changes
            GROUP BY hostname, process, neighbor_address
        ) s2
            ON  s1.hostname         = s2.hostname
            AND s1.process          = s2.process
            AND s1.neighbor_address = s2.neighbor_address
            AND s1.last_updated_ts  = s2.max_ts
            AND s1.ROWID            = s2.max_rowid
        WHERE UPPER(s1.to_state) NOT LIKE 'FULL%'
          AND UPPER(s1.hostname) NOT LIKE '%LGH%'
    """)
    last_non_full = db.execute_query("")

    if not last_non_full:
        return []

    db.execute_query("""
        SELECT hostname, process, neighbor_address
        FROM ospf_peer_status
        WHERE UPPER(state) LIKE 'FULL%'
    """)
    full_keys = {(r[0], r[1], r[2]) for r in db.execute_query("")}

    return [
        {
            "hostname":         e[0],
            "process":          e[1],
            "neighbor_address": e[2],
            "interface":        e[3],
            "last_state":       e[4],
            "last_updated_ts":  e[5],
            "log_file":         e[6],
        }
        for e in last_non_full
        if (e[0], e[1], e[2]) not in full_keys
    ]


# ── Topology data builder ────────────────────────────────────────────────────

def build_topology_data(db: DatabaseManager) -> Tuple[list, list]:
    """
    Return (raw_data, services) ready for the topology template / API.

    raw_data rows have a unified schema:
        hostname, host_ip, local_router_id, neighbor_address,
        service, state, last_updated_ts, protocol
    """
    bgp_rows = db.execute_query("""
        SELECT hostname, host_ip, local_router_id, neighbor_address,
               vpn_instance AS service, state, last_updated_ts, 'BGP' AS protocol
        FROM bgp_peer_status
    """)
    ospf_rows = db.execute_query("""
        SELECT hostname, host_ip, process_routerid AS local_router_id, neighbor_address,
               COALESCE(vrf, '') AS service, state, last_updated_ts, 'OSPF' AS protocol,
               host_ip AS process
        FROM ospf_peer_status
    """)

    raw: List[Dict] = [dict(r) for r in (bgp_rows + ospf_rows)]
    services = sorted({r["service"] for r in raw if r["service"]})
    return raw, services


# ── FastAPI routes ───────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def monitor_dashboard(request: Request):
    db = DatabaseManager(DB_PATH)
    recent_bgp_flaps, recent_ospf_flaps = get_recently_changed_peers(db)
    problem_ips, problem_bgp, problem_ospf = get_problem_peers(db)
    bgp_peers = get_bgp_current_status(db)
    ospf_peers = get_ospf_current_status(db)

    # Build flap/problem lookup sets for the template
    bgp_flap_ips  = {r["neighbor_address"] for r in recent_bgp_flaps}
    ospf_flap_ips = {r["neighbor_address"] for r in recent_ospf_flaps}
    problem_bgp_ips  = {r["neighbor_address"] for r in problem_bgp}
    problem_ospf_ips = {r["neighbor_address"] for r in problem_ospf}

    # Annotate rows in-place so templates can use simple flags
    for peer in bgp_peers:
        d = dict(peer)
        d["is_flap"]    = d["neighbor_address"] in bgp_flap_ips
        d["is_problem"] = d["neighbor_address"] in problem_bgp_ips
        d["uptime_html"] = format_uptime(d.get("up_down_time") or "")

    for peer in ospf_peers:
        d = dict(peer)
        d["is_flap"]    = d["neighbor_address"] in ospf_flap_ips
        d["is_problem"] = d["neighbor_address"] in problem_ospf_ips
        d["uptime_html"] = format_uptime(d.get("verbose_uptime") or "")

    # Annotated peer lists for the template
    annotated_bgp = []
    seen = set()
    all_sorted = sorted(bgp_peers, key=lambda p: parse_uptime(p.get("up_down_time") or "0"))
    for peer in all_sorted:
        key = (peer["hostname"], peer.get("vpn_instance"), peer["neighbor_address"])
        if key not in seen:
            seen.add(key)
            d = dict(peer)
            d["is_flap"]     = d["neighbor_address"] in bgp_flap_ips
            d["is_problem"]  = d["neighbor_address"] in problem_bgp_ips
            d["uptime_html"] = format_uptime(d.get("up_down_time") or "")
            annotated_bgp.append(d)

    annotated_ospf = []
    seen = set()
    all_sorted = sorted(ospf_peers, key=lambda p: parse_uptime(p.get("verbose_uptime") or "0"))
    for peer in all_sorted:
        key = (peer["hostname"], peer["neighbor_address"])
        if key not in seen:
            seen.add(key)
            d = dict(peer)
            d["is_flap"]     = d["neighbor_address"] in ospf_flap_ips
            d["is_problem"]  = d["neighbor_address"] in problem_ospf_ips
            d["uptime_html"] = format_uptime(d.get("verbose_uptime") or "")
            annotated_ospf.append(d)

    return templates.TemplateResponse("monitor_summary.html", {
        "request":            request,
        "bgp_peers":          annotated_bgp,
        "ospf_peers":         annotated_ospf,
        "problem_bgp":        problem_bgp,
        "problem_ospf":       problem_ospf,
        "problem_ips":        problem_ips,
        "recent_bgp_flaps":   recent_bgp_flaps,
        "recent_ospf_flaps":  recent_ospf_flaps,
        "bgp_flap_ips":       bgp_flap_ips,
        "ospf_flap_ips":      ospf_flap_ips,
        "core_logs_dir":      CORE_LOGS_DIR,
    })


@router.get("/topology", response_class=HTMLResponse)
def get_topology_page(request: Request):
    db = DatabaseManager(DB_PATH)
    raw_data, services = build_topology_data(db)
    return templates.TemplateResponse("peer_topology.html", {
        "request":        request,
        "raw_data":       raw_data,
        "services":       services,
        "total_sessions": len(raw_data),
    })


@router.get("/api/topology")
def api_topology(
    request: Request,
    protocol: str = "all",
    service:  str = "all",
):
    """
    JSON endpoint consumed by Cytoscape in the topology template.

    Returns { nodes: [...], links: [...] } in node-link format.
    """
    db = DatabaseManager(DB_PATH)
    raw_data, _ = build_topology_data(db)

    # Build identity map: IP/router-id  →  hostname
    id_to_host: Dict[str, str] = {}
    for row in raw_data:
        if row.get("host_ip"):
            id_to_host[row["host_ip"]] = row["hostname"]
        if row.get("local_router_id"):
            id_to_host[row["local_router_id"]] = row["hostname"]

    nodes: Dict[str, Dict] = {}
    links: List[Dict] = []

    for row in raw_data:
        proto_match   = (protocol == "all" or row["protocol"] == protocol.upper())
        service_match = (service == "all"  or row["service"] == service)
        if not (proto_match and service_match):
            continue

        src = row["hostname"]
        dst = id_to_host.get(row["neighbor_address"])
        if not dst or src == dst:
            continue

        is_up = any(k in row["state"].upper() for k in ("EST", "FULL"))
        for host in (src, dst):
            if host not in nodes:
                nodes[host] = {"id": host, "label": host}

        links.append({
            "source":   src,
            "target":   dst,
            "protocol": row["protocol"],
            "service":  row["service"],
            "state":    row["state"],
            "is_up":    is_up,
            "color":    "#2ECC40" if is_up else "#FF4136",
        })

    return JSONResponse({"nodes": list(nodes.values()), "links": links})


@router.get("/api/peers")
def api_peers(
    request: Request,
    protocol: str = "all",
    service:  str = "all",
    problem_only: bool = False,
):
    """Filterable JSON peer list — can power a React/Vue front-end later."""
    db = DatabaseManager(DB_PATH)
    raw_data, _ = build_topology_data(db)

    _, problem_bgp, problem_ospf = get_problem_peers(db)
    problem_ips = {r["neighbor_address"] for r in list(problem_bgp) + list(problem_ospf)}

    result = []
    for row in raw_data:
        if protocol != "all" and row["protocol"] != protocol.upper():
            continue
        if service != "all" and row["service"] != service:
            continue
        if problem_only and row["neighbor_address"] not in problem_ips:
            continue
        row["is_problem"] = row["neighbor_address"] in problem_ips
        result.append(row)

    return JSONResponse(result)


@router.post("/flush")
async def flush_status(background_tasks: BackgroundTasks):
    """Trigger database sync in the background."""
    def _run():
        script = os.path.join(mainconfig.BASE_DIR, "utils", "analysis_sqlite.py")
        result = subprocess.run([sys.executable, script], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Flush script failed: %s", result.stderr)

    background_tasks.add_task(_run)
    return {"status": "success", "message": "Database sync started in background."}


@router.get("/history", response_class=HTMLResponse)
async def peer_history(
    request: Request,
    hostname:  str,
    neighbor:  str,
    protocol:  str = "BGP",
):
    db = DatabaseManager(DB_PATH)
    history = get_peer_history(db, hostname, protocol, neighbor)
    return templates.TemplateResponse("monitor_history.html", {
        "request":  request,
        "history":  history,
        "neighbor": neighbor,
        "protocol": protocol,
        "hostname": hostname,
    })
