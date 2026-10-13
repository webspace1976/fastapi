#!/usr/bin/env python3
"""
monitor.py — BGP/OSPF peer monitoring router.

Fix notes (Oct 2026)
--------------------
  1. STALE ROWS: the status tables keep one row per peer *per snapshot*.  The
     dashboard used to SELECT * and de-duplicate by "lowest uptime", which picks
     the OLDEST snapshot (the one taken right after the peer came up).  That is
     why rows showed "0057h33m / 2026-05-03" months after the fact.  All
     "current status" reads now take the newest snapshot per peer.
  2. get_persistent_non_full_peers() ran its queries but threw the results away
     and then executed db.execute_query("").  Rewritten.
  3. Problem BGP peers were read from ALL snapshots (old non-established rows
     counted as problems forever).  Now latest snapshot only.
  4. is_flap / is_problem were keyed by neighbor IP only, so one bad device
     flagged every other device peering with the same IP.  Now keyed by
     (hostname, neighbor_address).
  5. "recent changes" compared ISO strings with a 'T' separator against a
     space-separated cutoff.  Now compared with SQLite datetime().
  6. parse_uptime / format_uptime unified (handles 1d, 3w, 1y, h:m, h:m:s).
  7. /flush: runs the script with cwd + PYTHONPATH set, a timeout, a lock
     (no overlapping runs) and exposes the result at GET /flush/status.
  8. Removed circular-import-prone `import utils.fastapi_mymodule` (unused) and
     `sys.path.append("..")`.
  9. Reflected-XSS in the history page: hostname/neighbor were echoed unescaped.
 10. Added age_hours / is_stale to every peer row so frozen data is visible.
"""

import os
import re
import sys
import html
import asyncio
import logging
import threading
import subprocess
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

import mainconfig

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from database.db_manager import DatabaseManager, get_db

# ── Module-level singletons ──────────────────────────────────────────────────
router = APIRouter()
templates = Jinja2Templates(directory=mainconfig.TEMPLATES_DIR)
logger = mainconfig.setup_module_logger(__name__)

DB_PATH = mainconfig.DB_PATH
ORION_DB_PATH = mainconfig.DB_ORION_PATH
CORE_LOGS_DIR = mainconfig.CORE_LOGS_DIR

# A peer row whose last_updated_ts is older than this is flagged is_stale.
STALE_HOURS = float(os.getenv("PEER_STALE_HOURS", "12"))


# ── Uptime parsing ───────────────────────────────────────────────────────────

_UPTIME_SENTINEL = {
    "never": 99_999 * 60,
    "****h": 9_999 * 60,
}
_UNIT_MINUTES = {"y": 365 * 1440, "w": 7 * 1440, "d": 1440, "h": 60, "m": 1}
_UNIT_TOKEN = re.compile(r"(\d+)\s*([ywdhm])")
_UNIT_FULL = re.compile(r"(?:\d+\s*[ywdhm]\s*)+")


def parse_uptime(up_str) -> int:
    """
    Convert vendor uptime strings to total minutes.

    Supported: 0057h33m, 5d12h, 1w4d, 2y3w4d, 3w, 1y, 45m, 01:23:45, 45:30,
    2768:19:43, ****h (sentinel), never (sentinel), bare integer (minutes).
    Unparseable input returns 0.
    """
    raw = str(up_str).strip().lower() if up_str is not None else ""
    if not raw:
        return 0

    for token, minutes in _UPTIME_SENTINEL.items():
        if raw.startswith(token):
            return minutes

    if ":" in raw:                       # H:M[:S]
        try:
            nums = [int(x) for x in raw.split(":")]
        except ValueError:
            return 0
        return nums[0] * 60 + nums[1] if len(nums) >= 2 else 0

    if _UNIT_FULL.fullmatch(raw):        # any combination of y/w/d/h/m units
        return sum(int(n) * _UNIT_MINUTES[u] for n, u in _UNIT_TOKEN.findall(raw))

    try:
        return int(raw)
    except ValueError:
        return 0


def format_uptime(up_str) -> str:
    """Human-friendly uptime; wrapped in a warning span when < 12 h (use |safe)."""
    if not up_str or up_str == "N/A":
        return "N/A"
    s = str(up_str)
    if s.startswith("****"):
        return "&gt;9999 Hours"
    if s.lower().startswith("never"):
        return "Never"

    minutes = parse_uptime(s)
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    display = f"{days}d {hours}h" if days else f"{hours}h {mins}m"

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
        for fmt in _TS_FORMATS:
            try:
                return datetime.strptime(candidate.split(".")[0], fmt)
            except (ValueError, IndexError):
                pass

    logger.warning("Timestamp parse failed: %r", ts_str)
    return None


def _parse_db_ts(value) -> Optional[datetime]:
    """Parse a last_updated_ts column value (handles ISO 'T' and space forms)."""
    if not value:
        return None
    s = str(value).strip().replace("T", " ")[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return parse_any_ts(str(value))


def get_time_from_logfile(log_file: str) -> Optional[datetime]:
    m = re.match(r"(\d{8})_(\d{6})_", log_file)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


# ── DB query helpers ─────────────────────────────────────────────────────────

def _rows(db: DatabaseManager, sql: str, params: Optional[dict] = None) -> List[dict]:
    """Run a query and always return a list of plain dicts."""
    return [dict(r) for r in (db.execute_query(sql, params or {}) or [])]


# Newest snapshot per peer.  IFNULL() keeps NULL vpn_instance / process /
# snapshot-id rows from silently dropping out of the join.
_LATEST_BGP_SQL = """
    SELECT p.*
    FROM bgp_peer_status p
    JOIN (
        SELECT hostname, IFNULL(vpn_instance,'') AS vi, neighbor_address,
               MAX(IFNULL(last_snapshot_id,0)) AS sid
        FROM bgp_peer_status
        GROUP BY hostname, IFNULL(vpn_instance,''), neighbor_address
    ) l
      ON  p.hostname = l.hostname
      AND IFNULL(p.vpn_instance,'') = l.vi
      AND p.neighbor_address = l.neighbor_address
      AND IFNULL(p.last_snapshot_id,0) = l.sid
    WHERE UPPER(p.hostname) NOT LIKE '%LGH%'
"""

_LATEST_OSPF_SQL = """
    SELECT p.*
    FROM ospf_peer_status p
    JOIN (
        SELECT hostname, IFNULL(process,'') AS pr, neighbor_address,
               MAX(IFNULL(last_snapshot_id,0)) AS sid
        FROM ospf_peer_status
        GROUP BY hostname, IFNULL(process,''), neighbor_address
    ) l
      ON  p.hostname = l.hostname
      AND IFNULL(p.process,'') = l.pr
      AND p.neighbor_address = l.neighbor_address
      AND IFNULL(p.last_snapshot_id,0) = l.sid
"""


def get_bgp_current_status(db: DatabaseManager) -> List[dict]:
    """Latest-snapshot BGP peers (LGH excluded)."""
    if db is None:
        return []
    return _rows(db, _LATEST_BGP_SQL)


def get_ospf_current_status(db: DatabaseManager) -> List[dict]:
    """Latest-snapshot OSPF peers."""
    if db is None:
        return []
    return _rows(db, _LATEST_OSPF_SQL + " ORDER BY p.hostname, p.process, p.neighbor_address")


def get_recently_changed_peers(db: DatabaseManager, time_window_hours: int = 12):
    """Return (bgp_changes, ospf_changes) within the lookback window."""
    if db is None:
        return [], []
    since = (datetime.now() - timedelta(hours=time_window_hours)).strftime("%Y-%m-%d %H:%M:%S")
    # datetime() normalises 'T' vs ' ' separators; plain string compare did not.
    bgp = _rows(db, "SELECT * FROM bgp_state_changes WHERE datetime(last_updated_ts) >= datetime(:since)",
                {"since": since})
    ospf = _rows(db, "SELECT * FROM ospf_state_changes WHERE datetime(last_updated_ts) >= datetime(:since)",
                 {"since": since})
    return bgp, ospf


def get_problem_peers(db: DatabaseManager, time_window_hours: int = 12):
    """
    Returns (problem_ip_set, problem_bgp_rows, problem_ospf_rows).

    problem_ips: union of non-established BGP (latest snapshot), persistent
    non-FULL OSPF, and recent flaps.
    """
    if db is None:
        return set(), [], []

    problem_bgp = [r for r in get_bgp_current_status(db)
                   if str(r.get("state") or "").upper() != "ESTABLISHED"]
    problem_ospf = get_persistent_non_full_peers(db)

    recent_bgp, recent_ospf = get_recently_changed_peers(db, time_window_hours)

    problem_ips: set = set()
    for row in problem_bgp + recent_bgp + problem_ospf + recent_ospf:
        if row.get("neighbor_address"):
            problem_ips.add(row["neighbor_address"])

    return problem_ips, problem_bgp, problem_ospf


def get_peer_history(db: DatabaseManager, hostname: str, protocol: str, ip: str) -> list:
    if db is None:
        return []
    table = "bgp_state_changes" if protocol.lower() == "bgp" else "ospf_state_changes"
    sql = f"""
        SELECT * FROM {table}
        WHERE neighbor_address = :ip AND hostname = :hostname
        ORDER BY datetime(last_updated_ts) DESC
    """
    return _rows(db, sql, {"ip": ip, "hostname": hostname})


def _e(value) -> str:
    """HTML-escape any value for safe interpolation (N/A for empty)."""
    return html.escape(str(value)) if value not in (None, "") else "N/A"


def display_history_page(db: DatabaseManager, hostname: str, protocol: str, neighbor: str) -> list:
    proto = protocol.lower()
    out: List[str] = []
    out.append(f"<h1>History for {html.escape(protocol.upper())} Peer: "
               f"{html.escape(hostname)} {html.escape(neighbor)}</h1>")

    history = get_peer_history(db, hostname, protocol, neighbor)
    if db is None or not history:
        out.append(
            f"<p>No historical state change events found for {html.escape(neighbor)}. "
            f"Use 'Flush Status' to initialize data.</p>"
        )
        return out

    table = "bgp_peer_status" if proto == "bgp" else "ospf_peer_status"
    current_rows = _rows(
        db,
        f"SELECT * FROM {table} WHERE neighbor_address = :ip AND hostname = :hostname "
        f"ORDER BY last_snapshot_id DESC LIMIT 1",
        {"ip": neighbor, "hostname": hostname},
    )
    cur = current_rows[0] if current_rows else None

    if cur:
        out.append("<div style='background: #e9ecef; padding: 15px; border-radius: 5px; margin-bottom: 20px;'>")
        out.append("<h3>Current Status</h3>")
        second = (f"Uptime: <strong>{_e(cur.get('up_down_time'))}</strong>" if proto == "bgp"
                  else f"Interface: <strong>{_e(cur.get('interface'))}</strong>")
        out.append(f"<p>State: <strong>{_e(cur.get('state'))}</strong> | {second} | "
                   f"Last Check: {_e(cur.get('last_updated_ts'))}</p>")
        out.append("</div>")

    out.append("<h3>State Change History</h3>")
    out.append("<div class='table-container'><table>")

    if proto == "bgp":
        out.append("<tr><th>Hostname</th><th>VPN Instance</th><th>State Change</th>"
                   "<th>last_updated_ts</th><th>LogFile</th></tr>")
    else:
        out.append("<tr><th>Hostname</th><th>Process</th><th>Interface</th><th>State Change</th>"
                   "<th>last_updated_ts</th><th>Log File</th></tr>")

    seen = set()
    for entry in history:
        key = (entry.get("hostname"), entry.get("neighbor_address"), entry.get("last_updated_ts"),
               entry.get("from_state"), entry.get("to_state"))
        if key in seen:
            continue
        seen.add(key)

        log_file = entry.get("log_file")
        log_link = (f"<a href='{html.escape(str(CORE_LOGS_DIR))}/{html.escape(str(log_file))}' "
                    f"target='_blank'>{html.escape(str(log_file))}</a>") if log_file else "N/A"
        change = f"{_e(entry.get('from_state'))} → {_e(entry.get('to_state'))}"

        if proto == "bgp":
            out.append(f"<tr><td>{_e(entry.get('hostname'))}</td><td>{_e(entry.get('vpn_instance'))}</td>"
                       f"<td>{change}</td><td>{_e(entry.get('last_updated_ts'))}</td><td>{log_link}</td></tr>")
        else:
            out.append(f"<tr><td>{_e(entry.get('hostname'))}</td><td>{_e(entry.get('process'))}</td>"
                       f"<td>{_e(entry.get('interface'))}</td><td>{change}</td>"
                       f"<td>{_e(entry.get('last_updated_ts'))}</td><td>{log_link}</td></tr>")

    out.append("</table></div>")
    return out


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
        results = _rows(db, sql, params)
        if not results:
            logger.info("No status for %s peer: host=%s, neighbor=%s", protocol, host_ip, neighbor)
            return None
        return results[0]
    except Exception as exc:
        logger.error("get_peer_status error (%s): %s", protocol, exc)
        return None


# ── OSPF persistence helpers ─────────────────────────────────────────────────

def get_persistent_non_full_peers(db: DatabaseManager) -> List[dict]:
    """
    Peers whose most recent OSPF state-change event is NOT FULL *and* which are
    still not FULL in the latest status snapshot.
    """
    last_events = _rows(db, """
        SELECT hostname, process, neighbor_address, interface,
               to_state, last_updated_ts, log_file
        FROM (
            SELECT s.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY hostname, process, neighbor_address
                       ORDER BY datetime(last_updated_ts) DESC, ROWID DESC
                   ) AS rn
            FROM ospf_state_changes s
            WHERE UPPER(hostname) NOT LIKE '%LGH%'
        )
        WHERE rn = 1 AND UPPER(to_state) NOT LIKE 'FULL%'
    """)
    if not last_events:
        return []

    full_keys = {
        (r.get("hostname"), r.get("process"), r.get("neighbor_address"))
        for r in get_ospf_current_status(db)
        if str(r.get("state") or "").upper().startswith(("FULL", "ESTABLISHED"))   # Arista rows historically stored 'established'
    }

    return [
        {
            "hostname":         e["hostname"],
            "process":          e["process"],
            "neighbor_address": e["neighbor_address"],
            "interface":        e["interface"],
            "state":            e["to_state"],      # alias so templates can treat it like a status row
            "last_state":       e["to_state"],
            "last_updated_ts":  e["last_updated_ts"],
            "log_file":         e["log_file"],
        }
        for e in last_events
        if (e["hostname"], e["process"], e["neighbor_address"]) not in full_keys
    ]


# ── Topology data builder ────────────────────────────────────────────────────

def build_topology_data(db: DatabaseManager) -> Tuple[list, list]:
    """
    Return (raw_data, services) from the LATEST snapshot of each peer.

    raw_data rows: hostname, host_ip, local_router_id, neighbor_address,
                   service, state, last_updated_ts, protocol
    """
    raw: List[Dict] = []
    for r in get_bgp_current_status(db):
        raw.append({
            "hostname":         r.get("hostname"),
            "host_ip":          r.get("host_ip"),
            "local_router_id":  r.get("local_router_id"),
            "neighbor_address": r.get("neighbor_address"),
            "service":          r.get("vpn_instance") or "",
            "state":            r.get("state") or "",
            "last_updated_ts":  r.get("last_updated_ts"),
            "protocol":         "BGP",
        })
    for r in get_ospf_current_status(db):
        raw.append({
            "hostname":         r.get("hostname"),
            "host_ip":          r.get("host_ip"),
            "local_router_id":  r.get("process_routerid"),
            "neighbor_address": r.get("neighbor_address"),
            "service":          r.get("vrf") or "",
            "state":            r.get("state") or "",
            "last_updated_ts":  r.get("last_updated_ts"),
            "protocol":         "OSPF",
            "process":          r.get("process") or r.get("host_ip"),
        })

    services = sorted({r["service"] for r in raw if r["service"]})
    return raw, services


def build_orion_topology_data(db: DatabaseManager, site: Optional[str] = None) -> Tuple[List[Dict], List[Dict]]:
    """Return node/link graph data from Orion.Topology.

    ORION_DB_PATH is a local SQLite mirror, so '[Orion.Topology]' must exist there as a
    table (the syslog sync reads '[Orion.SyslogTracking]' the same way).  If it does not,
    the failure is logged and an empty graph is returned instead of a 500.
    """
    query = """
        SELECT SourceNodeID, SourceNodeName, SourceInterface,
               TargetNodeID, TargetNodeName, TargetInterface,
               SourceSite, TargetSite, LayerType
        FROM [Orion.Topology]
    """
    params = {}
    if site:
        query += " WHERE SourceSite LIKE :site OR TargetSite LIKE :site"
        params = {"site": f"%{site}%"}

    try:
        rows = _rows(db, query, params)
    except Exception as exc:
        logger.error("Orion topology query failed: %s", exc)
        return [], []

    nodes: Dict[str, Dict] = {}
    links: List[Dict] = []

    for row in rows:
        source_id = str(row.get("SourceNodeID") or "")
        source_name = str(row.get("SourceNodeName") or "").strip()
        target_id = str(row.get("TargetNodeID") or "")
        target_name = str(row.get("TargetNodeName") or "").strip()
        if not source_id or not target_id:
            continue

        src_key = f"{source_name} ({source_id})" if source_name else source_id
        tgt_key = f"{target_name} ({target_id})" if target_name else target_id

        if src_key not in nodes:
            nodes[src_key] = {"id": src_key, "label": source_name or source_id,
                              "site": row.get("SourceSite", ""), "type": "orion"}
        if tgt_key not in nodes:
            nodes[tgt_key] = {"id": tgt_key, "label": target_name or target_id,
                              "site": row.get("TargetSite", ""), "type": "orion"}

        links.append({
            "source": src_key,
            "target": tgt_key,
            "protocol": "ORION",
            "service": row.get("LayerType", ""),
            "state": "unknown",
            "source_site": row.get("SourceSite", ""),
            "target_site": row.get("TargetSite", ""),
            "source_interface": row.get("SourceInterface", ""),
            "target_interface": row.get("TargetInterface", ""),
            "is_up": True,
            "color": "#888",
            "source_type": "orion",
        })

    return list(nodes.values()), links


def merge_peer_and_orion_topology(peer_rows: List[Dict], orion_nodes: List[Dict], orion_links: List[Dict]) -> Dict[str, List[Dict]]:
    """Combine peer topology with Orion topology into a single graph payload."""
    nodes: Dict[str, Dict] = {node["id"]: node for node in orion_nodes}
    links: List[Dict] = []

    for row in peer_rows:
        src = row["hostname"]
        dst = row.get("neighbor_address")
        if not dst or src == dst:
            continue

        if src not in nodes:
            nodes[src] = {"id": src, "label": src, "type": "peer"}
        if dst not in nodes:
            nodes[dst] = {"id": dst, "label": dst, "type": "peer"}

        is_up = any(k in str(row.get("state", "")).upper() for k in ("EST", "FULL"))
        links.append({
            "source": src,
            "target": dst,
            "protocol": row["protocol"],
            "service": row.get("service", ""),
            "state": row.get("state", ""),
            "is_up": is_up,
            "color": "#2ECC40" if is_up else "#FF4136",
            "source_type": "peer",
        })

    links.extend(orion_links)
    return {"nodes": list(nodes.values()), "links": links}


@router.get("/api/orion_topology")
def api_orion_topology(site: Optional[str] = None):
    db = get_db(ORION_DB_PATH)
    nodes, links = build_orion_topology_data(db, site)
    return JSONResponse({"nodes": nodes, "links": links})


@router.get("/api/topology/merged")
def api_merged_topology(
    protocol: str = "all",
    service:  str = "all",
    site: Optional[str] = None,
):
    peer_rows, _ = build_topology_data(get_db(DB_PATH))
    orion_nodes, orion_links = build_orion_topology_data(get_db(ORION_DB_PATH), site)

    filtered = [
        r for r in peer_rows
        if (protocol == "all" or r["protocol"] == protocol.upper())
        and (service == "all" or r.get("service", "") == service)
    ]
    return JSONResponse(merge_peer_and_orion_topology(filtered, orion_nodes, orion_links))


# ── Dashboard helpers ────────────────────────────────────────────────────────

def _annotate_peers(rows: List[dict], uptime_field: str, flap_keys: set, problem_keys: set) -> List[dict]:
    """Add template flags to each (already de-duplicated) peer row, newest-flap first."""
    now = datetime.now()
    out = []
    for peer in sorted(rows, key=lambda p: parse_uptime(p.get(uptime_field) or "0")):
        d = dict(peer)
        key = (d.get("hostname"), d.get("neighbor_address"))
        d["is_flap"] = key in flap_keys
        d["is_problem"] = key in problem_keys
        d["uptime_minutes"] = parse_uptime(d.get(uptime_field) or "0")
        d["uptime_html"] = format_uptime(d.get(uptime_field) or "")

        # last_updated_ts is the time of the last *event or snapshot*; uptime/neighbour detail
        # is only valid as of the last SNAPSHOT, whose time is encoded in last_snapshot_id
        # ("YYYYMMDD_HHMMSS", set by analysis_sqlite.py).  Event-only rows have no snapshot id.
        snap = None
        try:
            snap = datetime.strptime(str(d.get("last_snapshot_id") or ""), "%Y%m%d_%H%M%S")
        except ValueError:
            pass
        d["snapshot_ts"] = snap.isoformat(sep=" ") if snap else None
        ref = snap or _parse_db_ts(d.get("last_updated_ts"))
        age = (now - ref).total_seconds() / 3600 if ref else None
        d["age_hours"] = round(age, 1) if age is not None else None
        d["is_stale"] = age is not None and age > STALE_HOURS
        out.append(d)
    return out


def _keys(rows: List[dict]) -> set:
    return {(r.get("hostname"), r.get("neighbor_address")) for r in rows}


# ── FastAPI routes ───────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def monitor_dashboard(request: Request):
    def _build_dashboard_data():
        db = get_db(DB_PATH)
        recent_bgp_flaps, recent_ospf_flaps = get_recently_changed_peers(db)
        problem_ips, problem_bgp, problem_ospf = get_problem_peers(db)
        bgp_rows = get_bgp_current_status(db)
        ospf_rows = get_ospf_current_status(db)

        bgp_flap_keys, ospf_flap_keys = _keys(recent_bgp_flaps), _keys(recent_ospf_flaps)
        bgp_problem_keys, ospf_problem_keys = _keys(problem_bgp), _keys(problem_ospf)

        annotated_bgp = _annotate_peers(bgp_rows, "up_down_time", bgp_flap_keys, bgp_problem_keys)
        annotated_ospf = _annotate_peers(ospf_rows, "verbose_uptime", ospf_flap_keys, ospf_problem_keys)

        return {
            "bgp_peers":         annotated_bgp,
            "ospf_peers":        annotated_ospf,
            "problem_bgp":       problem_bgp,
            "problem_ospf":      problem_ospf,
            "problem_ips":       problem_ips,
            "recent_bgp_flaps":  recent_bgp_flaps,
            "recent_ospf_flaps": recent_ospf_flaps,
            # IP-only sets kept for template backward-compat
            "bgp_flap_ips":      {k[1] for k in bgp_flap_keys},
            "ospf_flap_ips":     {k[1] for k in ospf_flap_keys},
            "stale_hours":       STALE_HOURS,
            "stale_bgp_count":   sum(1 for p in annotated_bgp if p["is_stale"]),
            "stale_ospf_count":  sum(1 for p in annotated_ospf if p["is_stale"]),
        }

    ctx = await asyncio.to_thread(_build_dashboard_data)
    ctx["request"] = request
    ctx["core_logs_dir"] = CORE_LOGS_DIR
    return templates.TemplateResponse("monitor_summary.html", ctx)


@router.get("/topology", response_class=HTMLResponse)
def get_topology_page(request: Request):
    db = get_db(DB_PATH)
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
    """Node-link JSON consumed by Cytoscape in the topology template."""
    db = get_db(DB_PATH)
    raw_data, _ = build_topology_data(db)

    id_to_host: Dict[str, str] = {}
    for row in raw_data:
        if row.get("host_ip"):
            id_to_host[row["host_ip"]] = row["hostname"]
        if row.get("local_router_id"):
            id_to_host[row["local_router_id"]] = row["hostname"]

    nodes: Dict[str, Dict] = {}
    links: List[Dict] = []

    for row in raw_data:
        if not ((protocol == "all" or row["protocol"] == protocol.upper())
                and (service == "all" or row["service"] == service)):
            continue

        src = row["hostname"]
        dst = id_to_host.get(row["neighbor_address"])
        if not dst or src == dst:
            continue

        is_up = any(k in str(row["state"]).upper() for k in ("EST", "FULL"))
        for host in (src, dst):
            nodes.setdefault(host, {"id": host, "label": host})

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
    """Filterable JSON peer list (latest snapshot only)."""
    db = get_db(DB_PATH)
    raw_data, _ = build_topology_data(db)

    _, problem_bgp, problem_ospf = get_problem_peers(db)
    problem_keys = _keys(problem_bgp) | _keys(problem_ospf)

    result = []
    for row in raw_data:
        if protocol != "all" and row["protocol"] != protocol.upper():
            continue
        if service != "all" and row["service"] != service:
            continue
        is_problem = (row["hostname"], row["neighbor_address"]) in problem_keys
        if problem_only and not is_problem:
            continue
        row["is_problem"] = is_problem
        result.append(row)

    return JSONResponse(result)


# ── Flush (DB sync) ──────────────────────────────────────────────────────────

_flush_lock = threading.Lock()
_flush_state: Dict[str, object] = {
    "running": False, "started": None, "finished": None, "returncode": None, "error": None,
}
FLUSH_TIMEOUT_SEC = int(os.getenv("FLUSH_TIMEOUT_SEC", "900"))


@router.post("/flush")
async def flush_status(background_tasks: BackgroundTasks):
    """Trigger database sync in the background (one run at a time)."""
    if not _flush_lock.acquire(blocking=False):
        return JSONResponse({"status": "busy", "message": "A sync is already running."}, status_code=409)

    _flush_state.update(running=True, started=datetime.now().isoformat(timespec="seconds"),
                        finished=None, returncode=None, error=None)

    def _run():
        base = str(mainconfig.BASE_DIR)
        script = os.path.join(base, "utils", "analysis_sqlite.py")
        # Run from the project root with it on PYTHONPATH, otherwise the script's
        # `import mainconfig` / `import utils.*` fails and the sync silently does nothing.
        env = dict(os.environ)
        env["PYTHONPATH"] = base + os.pathsep + env.get("PYTHONPATH", "")
        try:
            result = subprocess.run(
                [sys.executable, script], cwd=base, env=env,
                capture_output=True, text=True, timeout=FLUSH_TIMEOUT_SEC,
            )
            _flush_state["returncode"] = result.returncode
            if result.returncode != 0:
                _flush_state["error"] = (result.stderr or result.stdout or "")[-2000:]
                logger.error("Flush script failed (rc=%s): %s", result.returncode, _flush_state["error"])
            else:
                logger.warning("Flush completed OK")   # WARNING so it shows at the default log level
        except subprocess.TimeoutExpired:
            _flush_state["error"] = f"Timed out after {FLUSH_TIMEOUT_SEC}s"
            logger.error("Flush script timed out")
        except Exception as exc:
            _flush_state["error"] = str(exc)
            logger.error("Flush script error: %s", exc)
        finally:
            _flush_state.update(running=False, finished=datetime.now().isoformat(timespec="seconds"))
            _flush_lock.release()

    background_tasks.add_task(_run)
    return {"status": "success", "message": "Database sync started in background."}


@router.get("/flush/status")
def flush_status_info():
    """Result of the last/ongoing sync so the UI can show failures."""
    return JSONResponse(_flush_state)


@router.get("/history", response_class=HTMLResponse)
async def peer_history(
    request: Request,
    hostname:  str,
    neighbor:  str,
    protocol:  str = "BGP",
):
    def _build_history_html():
        db = get_db(DB_PATH)
        return "".join(display_history_page(db, hostname, protocol, neighbor))

    full_html_string = await asyncio.to_thread(_build_history_html)
    # html_history is already escaped piece-by-piece (render with |safe);
    # the plain values below are escaped by Jinja autoescape.
    return templates.TemplateResponse("monitor_history.html", {
        "request":      request,
        "html_history": full_html_string,
        "neighbor":     neighbor,
        "protocol":     protocol,
        "hostname":     hostname,
    })