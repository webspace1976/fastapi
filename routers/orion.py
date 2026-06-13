import re,urllib3,urllib.parse,os,json,atexit, html, sqlite3, pickle, sys, traceback
import asyncio
import pandas as pd

# from logging.handlers import RotatingFileHandler
from time import perf_counter,time,ctime
from datetime import datetime
# from orionsdk import SwisClient
from fastapi.responses import HTMLResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Form, Request, Response
# from pydantic import ValidationError
from typing import Any

# Local imports
import utils.fastapi_mymodule as mymodule
import utils.orion_dashboard as orion_dashboard
import mainconfig as mainconfig
import config.orion_config as orion_config
# from mainpydantic import OrionCheckRequest, OrionResponse
from utils.session_manager import OrionSession, update_session_audit
from utils.orion_db_manager import sync_orion_data
from utils.orion_db_manager import OrionDatabaseManager
from utils.analysis_sqlite import sync_syslog_to_routing_db


# --- Setup ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = mainconfig.setup_module_logger(__name__)

router  = APIRouter()
# start   = perf_counter()

# --- Directories ---
curr_dir= os.path.dirname(__file__)
log_dir=os.path.abspath(os.path.join(curr_dir, '..', 'logs'))
data_dir=os.path.abspath(os.path.join(curr_dir, '..', 'data'))
icon_dir = mainconfig.ICONS_DIR
# session_dir = os.path.abspath(os.path.join(data_dir, 'orion_sessions'))  # Directory to store session files
session_dir = mainconfig.SESSION_DIR  # Directory to store session files
SESSION_LOG_FILE = os.path.join(session_dir, "orion_session_log.json")

DB_ORION_PATH = mainconfig.DB_ORION_PATH


for directory in [log_dir, data_dir, session_dir]:
    if not os.path.exists(directory):
        os.makedirs(directory)


#   golbal var    
sitedown_list=[]    
dict_query = {}     
detailsurl=""

############## main
templates = Jinja2Templates(directory="templates")

# Shared read-only engine for all SELECT endpoints — pool handles open/close automatically.
# Writes still go through OrionDatabaseManager (via sync_orion_data).
from sqlalchemy import create_engine as _create_engine
_orion_read_engine = _create_engine(
    f"sqlite:///{mainconfig.DB_ORION_PATH}",
    connect_args={"check_same_thread": False}
)

@router.get("/dashboard", response_class=HTMLResponse)
async def get_orion_dashboard_tabs(request: Request):
    """Main Orion monitoring dashboard with tabs for login, nodes status, and site topology."""
    return templates.TemplateResponse("orion_dashboard_tabs.html", {"request": request})


@router.get("/check_form", response_class=HTMLResponse)
async def get_device_output_form(request: Request):
    return templates.TemplateResponse("orion_login.html", {"request": request})

@router.post("/check_output", response_class=HTMLResponse)
async def run_orioncheck_route(
    request: Request,
    response: Response, # Added response to set cookies
    npm_server: str = Form(...),
    npm_uname: str = Form(...),
    npm_passwd: str = Form(...),
):
    # 20260211 Create/Retrieve persistent session
    manager = OrionSession(npm_server, npm_uname, npm_passwd)

    try:
        # One single call to get the persistent client
        swis_client, session_id = manager.get_client()

        # AUDIT LOG: Capture the login event
    # Update the audit log with duration tracking
        update_session_audit(
            session_id=session_id,
            username=npm_uname,
            npm_server=npm_server,
            ip_address=request.client.host
        )

        loop = asyncio.get_running_loop()

        # 2. Execute the heavy lifting in a thread pool
        # get_orion_dashboard_html will now find/create the pickle based on this hash
        rendered_html, final_session_id = await loop.run_in_executor(
            None,
            # get_orion_dashboard_html,
            orion_dashboard.get_orion_dashboard_html,
            request,
            npm_server,
            npm_uname,
            npm_passwd,
            session_id,
        )

        # 3. Attach the hash-based session_id to the cookie
        # Setting httponly=True and samesite='lax' for security
        response = HTMLResponse(content=rendered_html)
        response.set_cookie(
            key="session_id", 
            value=final_session_id, 
            httponly=True, 
            path="/",
            samesite="lax"
        )
        
        return response

    except ConnectionError as ce:
        # Handle failed logins or unreachable servers
        logger.error(f"Login failed for {npm_uname}: {ce}")
        return HTMLResponse(content=f"""
            <script>
                alert("ACCESS DENIED / SERVER DOWN\\n\\nError: {html.escape(str(ce))}");
                window.location.href = "/check_form"; 
            </script>
        """, status_code=401)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return HTMLResponse(content="<h2>An unexpected error occurred.</h2>", status_code=500)

@router.get("/map_data")
async def get_map_data(site: str = None):
    if not site:
        return {"nodes": [], "edges": []}

    query = """
        SELECT SourceNodeID, SourceNodeName, TargetNodeID, TargetNodeName, SourceInterface
        FROM [Orion.Topology]
        WHERE SourceSite LIKE :site OR TargetSite LIKE :site
    """
    try:
        with _orion_read_engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params={"site": f"%{site}%"})
    except Exception as e:
        logger.error("map_data DB error: %s", e)
        return {"nodes": [], "edges": [], "error": str(e)}

    # 2. Build vis.js format
    nodes = []
    edges = []
    seen_nodes = set()

    for _, row in df.iterrows():
        # Add Source Node
        if row['SourceNodeID'] not in seen_nodes:
            # Example logic: If name contains 'CORE', put at level 0
            level = 0 if 'CORE' in row['SourceNodeName'].upper() else 1
            nodes.append({
                "id": row['SourceNodeID'], 
                "label": row['SourceNodeName'], 
                "level": level,  # Enforces vertical position
                "shape": "box", 
                "color": "#007bff"
            })
            seen_nodes.add(row['SourceNodeID'])

            # nodes.append({"id": row['SourceNodeID'], "label": row['SourceNodeName'], "shape": "dot", "color": "#007bff"})
            # seen_nodes.add(row['SourceNodeID'])
        
        # Add Target Node
        if row['TargetNodeID'] not in seen_nodes:
            nodes.append({
                "id": row['TargetNodeID'], 
                "label": row['TargetNodeName'], 
                "shape": "box", 
                "level": 2 if 'CORE' not in row['TargetNodeName'].upper() else 0
            })
            seen_nodes.add(row['TargetNodeID'])

        # Add Edge (The Connection)
        edges.append({
            "from": row['SourceNodeID'], 
            "to": row['TargetNodeID'], 
            "label": row['SourceInterface'],
            "font": {"size": 10, "align": "middle"},
            "arrows": 'to' # Shows direction of connectivity
        })

    return {"nodes": nodes, "edges": edges}


@router.get("/site_topology")
async def get_site_topology(site: str = None, ha: str = None):
    # Topology query — joins NCP for HA on both sides
    topo_query = """
        SELECT t.SourceNodeID, t.SourceNodeName, t.TargetNodeID, t.TargetNodeName,
               t.SourceInterface, t.TargetInterface, t.SourceSite, t.TargetSite, t.LayerType,
               scp_source.HA as SourceHA, scp_target.HA as TargetHA
        FROM [Orion.Topology] t
        LEFT JOIN [Orion.NodesCustomProperties] scp_source ON t.SourceNodeID = scp_source.NodeID
        LEFT JOIN [Orion.NodesCustomProperties] scp_target ON t.TargetNodeID = scp_target.NodeID
    """
    topo_params = {}
    topo_conditions = []
    if site and site != "all":
        topo_conditions.append("(t.SourceSite LIKE :site OR t.TargetSite LIKE :site)")
        topo_params["site"] = f"%{site}%"
    if ha and ha != "all":
        topo_conditions.append("(scp_source.HA = :ha OR scp_target.HA = :ha)")
        topo_params["ha"] = ha
    if topo_conditions:
        topo_query += " WHERE " + " AND ".join(topo_conditions)

    # Raw reference table query
    raw_query = """
        SELECT scp.Site, scp.Address, scp.City, scp.TotalNodes, scp.DownCount,
               n.NodeID, n.NodeName, n.Status, n.StatusDescription,
               cp.HA, cp.DeviceType
        FROM [Orion.SitesCustomProperties] scp
        LEFT JOIN [Orion.NodesCustomProperties] cp ON scp.Site = cp.Site
        LEFT JOIN [Orion.Nodes] n ON cp.NodeID = n.NodeID
    """
    raw_params = {}
    raw_conditions = []
    if site and site != "all":
        raw_conditions.append("scp.Site LIKE :site")
        raw_params["site"] = f"%{site}%"
    if ha and ha != "all":
        raw_conditions.append("cp.HA = :ha")
        raw_params["ha"] = ha
    if raw_conditions:
        raw_query += " WHERE " + " AND ".join(raw_conditions)  # FIX: WHERE not AND
    raw_query += " ORDER BY scp.Site, n.NodeName"

    # Site metadata for node enrichment
    site_meta_query = "SELECT Site, Address, City, TotalNodes, DownCount FROM [Orion.SitesCustomProperties]"
    site_meta_params = {}
    if site and site != "all":
        site_meta_query += " WHERE Site LIKE :site"
        site_meta_params["site"] = f"%{site}%"

    try:
        with _orion_read_engine.connect() as conn:
            df = pd.read_sql_query(topo_query, conn, params=topo_params)
            raw_df = pd.read_sql_query(raw_query, conn, params=raw_params)
            site_meta_df = pd.read_sql_query(site_meta_query, conn, params=site_meta_params)
    except Exception as e:
        logger.error("site_topology DB error: %s", e)
        return {"nodes": [], "edges": [], "raw_data": [], "error": str(e)}

    # Convert raw data to list of dicts, grouped by site with down nodes only
    raw_data = []
    site_down_nodes = {}  # Temp dict to group nodes by site
    
    for _, row in raw_df.iterrows():
        site_name = row.get("Site")
        if not site_name:
            continue
            
        if site_name not in site_down_nodes:
            site_down_nodes[site_name] = {
                "site": site_name,
                "address": row.get("Address"),
                "city": row.get("City"),
                "total_nodes": int(row["TotalNodes"]) if str(row.get("TotalNodes") or "").isdigit() else 0,
                "down_count": int(row["DownCount"]) if str(row.get("DownCount") or "").isdigit() else 0,
                "down_nodes": []
            }
        
        # Add down node to this site's list
        node_id = row.get("NodeID")
        if node_id:
            site_down_nodes[site_name]["down_nodes"].append({
                "node_id": node_id,
                "node_name": row.get("NodeName"),
                "status": row.get("Status"),
                "status_description": row.get("StatusDescription"),
                "ha": row.get("HA"),
                "device_type": row.get("DeviceType")
            })
    
    # Flatten for table display: one row per down node (not per site)
    for site_name, site_info in site_down_nodes.items():
        for down_node in site_info["down_nodes"]:
            raw_data.append({
                "node_id": down_node["node_id"],
                "node_name": down_node["node_name"],
                "site": site_name,
                "address": site_info["address"],
                "city": site_info["city"],
                "ha": down_node["ha"],
                "status": down_node["status"],
                "status_description": down_node["status_description"],
                "device_type": down_node["device_type"],
                "total_nodes_in_site": site_info["total_nodes"],
                "down_count_in_site": site_info["down_count"]
            })

    site_metadata = {}
    for _, row in site_meta_df.iterrows():
        site_name = str(row["Site"] or "").strip()
        if not site_name:
            continue
        site_metadata[site_name] = {
            "id": f"site:{site_name}",
            "label": site_name,
            "type": "site",
            "address": row.get("Address"),
            "city": row.get("City"),
            "total_nodes": int(row["TotalNodes"]) if str(row.get("TotalNodes") or "").isdigit() else row.get("TotalNodes"),
            "down_count": int(row["DownCount"]) if str(row.get("DownCount") or "").isdigit() else row.get("DownCount")
        }

    site_nodes = {}
    device_nodes = {}
    edges = []
    seen_edge_keys = set()

    def make_site_id(site_name):
        return f"site:{site_name}" if site_name else None

    def make_device_id(node_id):
        return f"node:{node_id}" if node_id else None

    for _, row in df.iterrows():
        for side in ["Source", "Target"]:
            site_name = row[f"{side}Site"]
            if site_name:
                site_id = make_site_id(site_name)
                if site_id and site_id not in site_nodes:
                    site_info = site_metadata.get(site_name)
                    if site_info:
                        site_nodes[site_id] = site_info.copy()
                        site_nodes[site_id].setdefault("ha", row[f"{side}HA"])
                    else:
                        site_nodes[site_id] = {
                            "id": site_id,
                            "label": site_name,
                            "type": "site",
                            "ha": row[f"{side}HA"],
                            "address": None,
                            "city": None,
                            "total_nodes": None,
                            "down_count": None
                        }

            node_id = row[f"{side}NodeID"]
            node_name = row[f"{side}NodeName"]
            site_name = row[f"{side}Site"]
            if node_id and node_name:
                device_nodes[make_device_id(node_id)] = {
                    "id": make_device_id(node_id),
                    "label": node_name,
                    "site": site_name,
                    "ha": row[f"{side}HA"],
                    "type": "device"
                }

                site_node_id = make_site_id(site_name)
                if site_node_id and site_node_id != make_device_id(node_id):
                    edge_key = (site_node_id, make_device_id(node_id), row[f"{side}Interface"] or "")
                    if edge_key not in seen_edge_keys:
                        edges.append({
                            "source": site_node_id,
                            "target": make_device_id(node_id),
                            "label": row[f"{side}Interface"] or "",
                            "type": "membership",
                            "protocol": "ORION",
                            "interface": row[f"{side}Interface"] or "",
                            "site_role": side.lower(),
                            "is_up": True,
                            "color": "#4B7BE5"
                        })
                        seen_edge_keys.add(edge_key)

        src = make_device_id(row["SourceNodeID"])
        tgt = make_device_id(row["TargetNodeID"])
        if src and tgt and src != tgt:
            edge_key = (src, tgt, row["SourceInterface"] or row["TargetInterface"] or row["LayerType"])
            if edge_key not in seen_edge_keys:
                edges.append({
                    "source": src,
                    "target": tgt,
                    "label": row["SourceInterface"] or row["TargetInterface"] or row["LayerType"] or "",
                    "type": "link",
                    "protocol": row["LayerType"] or "ORION",
                    "source_site": row["SourceSite"],
                    "target_site": row["TargetSite"],
                    "source_interface": row["SourceInterface"],
                    "target_interface": row["TargetInterface"],
                    "is_up": True,
                    "color": "#888"
                })
                seen_edge_keys.add(edge_key)

        source_site_name = row["SourceSite"]
        target_site_name = row["TargetSite"]
        if source_site_name and target_site_name and source_site_name != target_site_name:
            source_site_id = make_site_id(source_site_name)
            target_site_id = make_site_id(target_site_name)
            site_edge_key = tuple(sorted([source_site_id, target_site_id])) + ("site_link",)
            if site_edge_key not in seen_edge_keys:
                edges.append({
                    "source": source_site_id,
                    "target": target_site_id,
                    "label": row["LayerType"] or "",
                    "type": "site_link",
                    "protocol": row["LayerType"] or "ORION",
                    "source_site": source_site_name,
                    "target_site": target_site_name,
                    "is_up": True,
                    "color": "#34A853",
                    "weight": 2
                })
                seen_edge_keys.add(site_edge_key)

    nodes = list(site_nodes.values()) + list(device_nodes.values())
    return {"nodes": nodes, "edges": edges, "raw_data": raw_data}


@router.get("/site_topology_page", response_class=HTMLResponse)
async def get_site_topology_page(request: Request):
    return templates.TemplateResponse("orion_site_topology.html", {"request": request})


@router.get("/orion_analysis", response_class=HTMLResponse)
async def get_analysis_page(request: Request):
    # This renders your orion_custom_properties.html file
    return templates.TemplateResponse("orion_custom_properties.html", {"request": request})

@router.get("/get_custom_properties_data")
async def get_custom_properties_data():
    try:
        with _orion_read_engine.connect() as conn:
            df = pd.read_sql_query("SELECT * FROM [Orion.Nodes]", conn)
        return {"data": df.fillna("").to_dict(orient="records")}
    except Exception as e:
        logger.error("Failed to fetch table data: %s", e)
        return {"data": [], "error": str(e)}

@router.get("/get_site_customproperties_data")
async def get_site_customproperties_data():
    try:
        with _orion_read_engine.connect() as conn:
            df = pd.read_sql_query("SELECT * FROM [Orion.SitesCustomProperties]", conn)
        return {"data": df.fillna("").to_dict(orient="records")}
    except Exception as e:
        logger.error("Failed to fetch table data: %s", e)
        return {"data": [], "error": str(e)}


@router.get("/topology")
async def get_topology_data(site: str = None):
    query = "SELECT * FROM [Orion.Topology]"
    params = {}
    if site:
        query += " WHERE SourceSite LIKE :site OR TargetSite LIKE :site"
        params["site"] = f"%{site}%"
    try:
        with _orion_read_engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        return {"data": df.fillna("").to_dict(orient="records")}
    except Exception as e:
        logger.error("Failed to fetch topology data: %s", e)
        return {"data": [], "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# TWO-LEVEL TOPOLOGY API  +  ON-DEMAND REFRESH
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/topo/filters")
async def get_topo_filters():
    """Dynamic HA list + site-per-HA map for dropdowns. Called once on page load."""
    try:
        with _orion_read_engine.connect() as conn:
            ha_df = pd.read_sql_query("""
                SELECT HA,
                       COUNT(DISTINCT Site) AS site_count,
                       COUNT(*)             AS node_count
                FROM [Orion.NodesCustomProperties]
                WHERE HA IS NOT NULL AND HA != ''
                GROUP BY HA ORDER BY node_count DESC
            """, conn)
            site_df = pd.read_sql_query("""
                SELECT ncp.HA, ncp.Site, scp.City,
                       CAST(scp.TotalNodes AS INTEGER) AS total_nodes,
                       CAST(scp.DownCount  AS INTEGER) AS down_count
                FROM [Orion.SitesCustomProperties] scp
                JOIN  [Orion.NodesCustomProperties] ncp ON scp.Site = ncp.Site
                WHERE ncp.HA IS NOT NULL AND ncp.HA != ''
                  AND ncp.Site IS NOT NULL AND ncp.Site != ''
                GROUP BY ncp.HA, ncp.Site
                ORDER BY ncp.HA, ncp.Site
            """, conn)
        sites_by_ha = {}
        for _, r in site_df.iterrows():
            ha = r["HA"]
            if ha not in sites_by_ha:
                sites_by_ha[ha] = []
            sites_by_ha[ha].append({
                "site": r["Site"], "city": r["City"] or "",
                "total_nodes": int(r["total_nodes"] or 0),
                "down_count":  int(r["down_count"]  or 0),
            })
        return {"ha_list": ha_df.fillna("").to_dict(orient="records"), "sites_by_ha": sites_by_ha}
    except Exception as e:
        logger.error("topo/filters: %s", e)
        return {"ha_list": [], "sites_by_ha": {}, "error": str(e)}


@router.get("/topo/ha")
async def get_topo_level1(ha: str):
    """Level 1 — sites as nodes, inter-site L2 links collapsed to site-pair edges."""
    if not ha:
        raise HTTPException(status_code=400, detail="ha required")
    try:
        with _orion_read_engine.connect() as conn:
            site_df = pd.read_sql_query("""
                SELECT scp.Site, scp.City, scp.Address,
                       CAST(scp.TotalNodes AS INTEGER) AS total_nodes,
                       CAST(scp.DownCount  AS INTEGER) AS down_count, ncp.HA
                FROM [Orion.SitesCustomProperties] scp
                JOIN  [Orion.NodesCustomProperties] ncp ON scp.Site = ncp.Site
                WHERE ncp.HA = :ha AND scp.Site IS NOT NULL AND scp.Site != ''
                GROUP BY scp.Site ORDER BY scp.Site
            """, conn, params={"ha": ha})
            # FIX: join via NodeID, compare NCP.Site on both sides for accurate cross-site detection
            edge_df = pd.read_sql_query("""
                SELECT src.Site AS SrcSite, tgt.Site AS TgtSite,
                       src.HA AS SrcHA, tgt.HA AS TgtHA, COUNT(*) AS link_count
                FROM [Orion.Topology] t
                JOIN  [Orion.NodesCustomProperties] src ON t.SourceNodeID = src.NodeID
                JOIN  [Orion.NodesCustomProperties] tgt ON t.TargetNodeID = tgt.NodeID
                WHERE t.LayerType = 'L2'
                  AND src.Site != tgt.Site
                  AND src.Site IS NOT NULL AND tgt.Site IS NOT NULL
                  AND (src.HA = :ha OR tgt.HA = :ha)
                GROUP BY src.Site, tgt.Site ORDER BY link_count DESC
            """, conn, params={"ha": ha})
        site_ids = set(site_df["Site"].tolist())
        nodes = []
        for _, r in site_df.iterrows():
            dn = int(r["down_count"] or 0)
            nodes.append({
                "id": f"site:{r['Site']}", "label": r["Site"], "type": "site",
                "ha": r["HA"], "city": r["City"] or "", "address": r["Address"] or "",
                "total_nodes": int(r["total_nodes"] or 0), "down_count": dn, "has_down": dn > 0,
            })
        seen, edges = set(), []
        for _, r in edge_df.iterrows():
            key = tuple(sorted([r["SrcSite"], r["TgtSite"]]))
            if key in seen: continue
            seen.add(key)
            cross_ha = r["SrcHA"] != r["TgtHA"]
            edges.append({
                "id": f"e:{r['SrcSite']}|{r['TgtSite']}",
                "source": f"site:{r['SrcSite']}", "target": f"site:{r['TgtSite']}",
                "link_count": int(r["link_count"]), "cross_ha": cross_ha,
                "color": "#f97316" if cross_ha else "#14b8a6",
            })
        return {"level": 1, "ha": ha, "nodes": nodes, "edges": edges,
                "summary": {"sites": len(nodes), "edges": len(edges)}}
    except Exception as e:
        logger.error("topo/ha: %s", e)
        return {"nodes": [], "edges": [], "error": str(e)}


@router.get("/topo/site")
async def get_topo_level2(site: str):
    """Level 2 — devices inside one site, edges built from:
      1. NPM.Interfaces on CORE/Switch nodes (most accurate, has port names + status)
      2. Orion.Topology fallback for any remaining connections

    Key fixes vs previous version:
      - TRIM(ncp.Site) to handle leading/trailing spaces in NCP data
      - Join NPM.Interfaces via NodeID (not NodeName prefix)
      - NPM.Interfaces Status: 1=Up, 2=Down, 4=Shutdown, 0=Unknown
      - No external nodes shown — site-only view as requested
      - Edges come from CORE's port descriptions matching site device names/types
    """
    if not site:
        raise HTTPException(status_code=400, detail="site parameter required")

    CORE_TYPES  = {"Switch", "Firewall", "Router"}
    PORT_STATUS = {"1": "Up", "2": "Down", "4": "Shutdown", "0": "Unknown"}

    try:
        with _orion_read_engine.connect() as conn:

            # ── 1. All devices in this site from NCP ─────────────────────────
            # TRIM() fixes the leading-space bug in NCP Site values
            node_df = pd.read_sql_query("""
                SELECT NodeID, NodeName, IPaddress, DetailsUrl,
                       HA, Closet, Floor, Building, DeviceType,
                       SiteType, Status, StatusDescription
                FROM [Orion.NodesCustomProperties]
                WHERE TRIM(Site) = TRIM(:site)
                ORDER BY DeviceType, NodeName
            """, conn, params={"site": site.strip()})

            # ── 2. NPM.Interfaces for CORE/Switch nodes in this site ──────────
            # Join by NodeID — correct, direct, no string-split tricks needed.
            # We fetch all interfaces on core switches; each row's description
            # tells us what device is on the other end of that port.
            iface_df = pd.read_sql_query("""
                SELECT i.NodeID   AS CoreNodeID,
                       i.NodeName AS IfaceName,
                       i.Status   AS IfaceStatus,
                       i.StatusDescription AS IfaceStatusDesc,
                       i.DetailsUrl AS IfaceUrl,
                       i.DownTime
                FROM [Orion.NPM.Interfaces] i
                JOIN [Orion.NodesCustomProperties] ncp ON i.NodeID = ncp.NodeID
                WHERE TRIM(ncp.Site) = TRIM(:site)
                  AND ncp.DeviceType IN ('Switch','Firewall','Router')
                ORDER BY i.NodeName
            """, conn, params={"site": site.strip()})

    except Exception as e:
        logger.error("topo/site DB error: %s", e)
        return {"nodes": [], "edges": [], "error": str(e)}

    if node_df.empty:
        return {"nodes": [], "edges": [],
                "summary": {"devices_in_site": 0, "total_edges": 0},
                "site": site}

    # ── Build node map from NCP ───────────────────────────────────────────────
    nodes_by_id   = {}   # NodeID → node dict
    nodes_by_name = {}   # NodeName → NodeID  (for edge matching)

    for _, r in node_df.iterrows():
        nid   = str(r["NodeID"]).strip()
        name  = (r["NodeName"] or "").strip()
        dtype = (r["DeviceType"] or "").strip()
        try:
            is_up = int(str(r.get("Status") or "1")) == 1
        except (ValueError, TypeError):
            is_up = True

        node = {
            "id":          f"node:{nid}",
            "label":       name,
            "type":        "device",
            "is_core":     dtype in CORE_TYPES,
            "ha":          (r["HA"]          or "").strip(),
            "closet":      (r["Closet"]      or "").strip(),
            "floor":       (r["Floor"]       or "").strip(),
            "building":    (r["Building"]    or "").strip(),
            "device_type": dtype,
            "ip":          (r["IPaddress"]   or "").strip(),
            "details_url": (r["DetailsUrl"]  or "").strip(),
            "status_desc": (r["StatusDescription"] or "").strip(),
            "is_up":       is_up,
            "in_site":     True,
            "interfaces":  [],   # filled below
        }
        nodes_by_id[nid]   = node
        nodes_by_name[name] = nid

    # ── Attach interfaces to their CORE node ──────────────────────────────────
    # Parse NPM.Interfaces rows: "SwitchName PortName · EndpointDescription"
    # Strip the switch name prefix to get "PortName · EndpointDesc"
    core_interfaces = {}  # CoreNodeID → list of iface dicts
    for _, r in iface_df.iterrows():
        core_nid    = str(r["CoreNodeID"]).strip()
        iface_name  = (r["IfaceName"] or "").strip()
        iface_status= str(r["IfaceStatus"] or "1").strip()
        is_up       = iface_status == "1"

        # Strip the switch name prefix from the full "SwitchName Port · Desc" string
        core_node   = nodes_by_id.get(core_nid)
        sw_name     = core_node["label"] if core_node else ""
        if sw_name and iface_name.startswith(sw_name):
            port_and_desc = iface_name[len(sw_name):].strip()
        else:
            port_and_desc = iface_name

        parts = port_and_desc.split(" · ", 1)
        port  = parts[0].strip()
        desc  = parts[1].strip() if len(parts) > 1 else ""

        iface = {
            "port":        port,
            "description": desc,
            "status":      PORT_STATUS.get(iface_status, "Unknown"),
            "is_up":       is_up,
            "url":         (r["IfaceUrl"]   or "").strip(),
            "down_since":  (r["DownTime"]   or "").strip(),
        }

        if core_node:
            core_node["interfaces"].append(iface)

        if core_nid not in core_interfaces:
            core_interfaces[core_nid] = []
        core_interfaces[core_nid].append({**iface, "core_nid": core_nid})

    # ── Build edges from CORE interface descriptions → site devices ───────────
    # Match by: NodeName in description OR DeviceType keyword in description
    TYPE_KEYWORDS = {
        "UPS":       ["ups", "ups management"],
        "PDU":       ["pdu", "epdu", "eaton", "pdu management", "epdu management"],
        "ATS":       ["ats", "ats management"],
        "Telus CE":  ["telus", "rcmdb", "tvcha", "ciu", "wan", "csid"],
        "Switch":    ["sw", "switch", "core"],
    }

    edges       = []
    seen_edges  = set()

    def add_edge(src_nid, tgt_nid, port, desc, is_up, url):
        key = tuple(sorted([f"node:{src_nid}", f"node:{tgt_nid}"]))
        if key in seen_edges:
            return
        seen_edges.add(key)
        color = "#ef4444" if not is_up else "#22c55e"
        edges.append({
            "id":      f"e:node:{src_nid}-node:{tgt_nid}",
            "source":  f"node:{src_nid}",
            "target":  f"node:{tgt_nid}",
            "label":   port,
            "description": desc,
            "port_up": is_up,
            "color":   color,
            "url":     url,
        })

    for core_nid, ifaces in core_interfaces.items():
        for iface in ifaces:
            desc_lower = iface["description"].lower()
            port       = iface["port"]
            is_up      = iface["is_up"]
            url        = iface["url"]
            matched    = False

            # Priority 1: exact NodeName match in description
            for node_name, tgt_nid in nodes_by_name.items():
                if tgt_nid == core_nid:
                    continue
                if node_name.lower() in desc_lower or desc_lower in node_name.lower():
                    add_edge(core_nid, tgt_nid, port, iface["description"], is_up, url)
                    matched = True
                    break

            # Priority 2: DeviceType keyword match (UPS/PDU/ATS etc.)
            if not matched:
                for dtype, keywords in TYPE_KEYWORDS.items():
                    if any(kw in desc_lower for kw in keywords):
                        # Find a site device of that type
                        for nid, node in nodes_by_id.items():
                            if node["device_type"] == dtype and nid != core_nid:
                                add_edge(core_nid, nid, port, iface["description"], is_up, url)
                                matched = True
                                break
                        if matched:
                            break

    # ── Add remaining intra-site edges from Orion.Topology ───────────────────
    # These catch any connections Orion discovered that NPM.Interfaces doesn't cover
    try:
        with _orion_read_engine.connect() as conn:
            topo_df = pd.read_sql_query("""
                SELECT t.SourceNodeID, t.SourceInterface,
                       t.TargetNodeID, t.TargetInterface
                FROM [Orion.Topology] t
                JOIN [Orion.NodesCustomProperties] src ON t.SourceNodeID = src.NodeID
                JOIN [Orion.NodesCustomProperties] tgt ON t.TargetNodeID = tgt.NodeID
                WHERE t.LayerType = 'L2'
                  AND TRIM(src.Site) = TRIM(:site)
                  AND TRIM(tgt.Site) = TRIM(:site)
            """, conn, params={"site": site.strip()})

        for _, r in topo_df.iterrows():
            src_nid = str(r["SourceNodeID"]).strip()
            tgt_nid = str(r["TargetNodeID"]).strip()
            if src_nid not in nodes_by_id or tgt_nid not in nodes_by_id:
                continue
            src_if  = str(r.get("SourceInterface") or "").replace("None", "").strip()
            port    = src_if.split(" · ")[0] if " · " in src_if else src_if
            add_edge(src_nid, tgt_nid, port, src_if, True, "")

    except Exception as e:
        logger.warning("topo/site topology fallback error: %s", e)

    nodes     = list(nodes_by_id.values())
    in_site   = len(nodes)

    return {
        "level":  2,
        "site":   site,
        "nodes":  nodes,
        "edges":  edges,
        "summary": {
            "devices_in_site": in_site,
            "total_edges":     len(edges),
        },
    }


@router.post("/topo/refresh")
async def topo_refresh_now():
    """On-demand topology refresh — pulls fresh SWIS data into the local DB
    without waiting for the next scheduled sync.

    Uses get_any_active_client() from session_manager which reads the
    ACTIVE_SESSIONS dict (populated when any user logs into the dashboard).
    Only fetches topology + NCP — not the full dashboard payload.
    """
    try:
        from utils.session_manager import get_any_active_client
        from utils.orion_db_manager import sync_orion_data
        from sqlalchemy import text as _sa_text

        client = get_any_active_client()
        if not client:
            return {"ok": False, "error": "No active Orion session — log into the dashboard first."}

        # Pull only the two tables needed for topology rendering
        topo_result = client.query(orion_config.swis_sitetopology)
        ncp_result  = client.query(orion_config.swis_ncp)
        interface_result  = client.query(orion_config.swis_interface) # interface full status 

        data_for_db = {
            "interface_table":        [r for r in (interface_result  or {}).get("results", []) if isinstance(r, dict)],
            "sites_topology":        [r for r in (topo_result  or {}).get("results", []) if isinstance(r, dict)],
            "NodesCustomProperties": [r for r in (ncp_result   or {}).get("results", []) if isinstance(r, dict)],
        }

        sync_orion_data(data_for_db)

        with _orion_read_engine.connect() as conn:
            node_count = conn.execute(_sa_text("SELECT COUNT(*) FROM [Orion.NodesCustomProperties]")).scalar()
            topo_count = conn.execute(_sa_text("SELECT COUNT(*) FROM [Orion.Topology]")).scalar()
            interface_count = conn.execute(_sa_text("SELECT COUNT(*) FROM [Orion.NPM.Interfaces]")).scalar()

        logger.info("topo/refresh: synced %d NCP nodes, %d interfaces", node_count, interface_count)
        return {"ok": True, "nodes": node_count, "interfaces": interface_count}

    except Exception as e:
        logger.error("topo/refresh: %s", e)
        return {"ok": False, "error": str(e)}


@router.get("/get_PeerTracking")
async def get_syslog_tracking():
    """Fetches the latest 200 syslog entries from the SQLite backup."""
    try:
        # Ensure the latest syslogs are in the routing DB
        sync_syslog_to_routing_db(mainconfig.DB_ORION_PATH, mainconfig.DB_PATH)  
        
        conn = sqlite3.connect(mainconfig.DB_PATH)    # load from network_core.db
        conn.row_factory = sqlite3.Row 

        # Attach Orion DB        
        orion_db_path = str(mainconfig.DB_ORION_PATH)
        conn.execute(f"ATTACH DATABASE '{orion_db_path}' AS orion_db")        # Using a dictionary factory makes it easy to convert to JSON for the frontend
        
# OSPF	ENG22-KAM-Core	10.102.102.79	10.244.255.225	FULL	INIT	2026-04-15T02:26:05	2026 ENG22-KAM-Core %%10OSPF/5/OSPF_NBR_CHG: -DevIP=10.251.0.43; OSPF 10 Neighbor 10.244.255.225(Vlan-interface408) changed from FULL to INIT.	SyslogDB
# BGP	ENG22-CW-Core	10.8.8.16	10.251.9.153	ESTABLISHED	IDLE	2026-04-13T20:41:09	%Apr 13 20:41:09:883 2026 ENG22-CW-Core BGP/5/BGP_STATE_CHANGED: BGP.extranet: 10.251.9.153  state has changed from ESTABLISHED to IDLE	20260413_204100_10.8.8.16_jl1700_sa.txt

        query = """
            SELECT 
                logs.*, 
                n.NodeID 
            FROM (
                SELECT 
                    'BGP' as protocol, hostname, host_ip, neighbor_address, 
                    from_state, to_state, last_updated_ts, message, log_file
                FROM bgp_state_changes
                
                UNION ALL -- Much faster than UNION
                
                SELECT 
                    'OSPF' as protocol, hostname, host_ip, neighbor_address, 
                    from_state, to_state, last_updated_ts, message, log_file
                FROM ospf_state_changes
            ) AS logs
            -- Perform the Join ONCE on the combined list
            -- Use a COALESCE to try IP first, then Hostname if needed
            LEFT JOIN orion_db.[Orion.NodesCustomProperties] n ON logs.hostname = n.NodeName
            -- WHERE logs.hostname NOT like "%VGH%"
            ORDER BY logs.last_updated_ts DESC
        """

        # query = """
        #     SELECT LogEntryID, NodeID, NodeName, IPAddress, DateTime, Message 
        #     FROM [Orion.SyslogTracking] 
        #     ORDER BY LogEntryID DESC 
        #     LIMIT 200
        # """
        curr = conn.cursor()
        curr.execute(query)
        rows = curr.fetchall()
        conn.close()
        
        # Convert sqlite3.Row objects to standard dictionaries
        data = [dict(row) for row in rows]
        # print(data)
        
        return {"data": data}
    except Exception as e:
        logger.error(f"Failed to fetch SyslogTracking: {e}")
        return {"data": [], "error": str(e)}


# ── Node Mute List ────────────────────────────────────────────────────────────
NODE_MUTE_CONFIG = os.path.join(data_dir, "node_mute_list.json")

def load_node_mute_list() -> list:
    if os.path.exists(NODE_MUTE_CONFIG):
        with open(NODE_MUTE_CONFIG, "r") as f:
            return json.load(f).get("mute_list", [])
    return []

def save_node_mute_list(mute_list: list):
    with open(NODE_MUTE_CONFIG, "w") as f:
        json.dump({"mute_list": mute_list}, f, indent=2)

@router.get("/nodedown/mute-list")
async def get_node_mute_list():
    return {"mute_list": load_node_mute_list()}

@router.post("/nodedown/mute/{node_name}")
async def mute_node(node_name: str):
    mute_list = load_node_mute_list()
    if node_name not in mute_list:
        mute_list.append(node_name)
        save_node_mute_list(mute_list)
    return {"status": "muted", "node": node_name}

@router.delete("/nodedown/mute/{node_name}")
async def unmute_node(node_name: str):
    mute_list = load_node_mute_list()
    mute_list = [n for n in mute_list if n != node_name]
    save_node_mute_list(mute_list)
    return {"status": "unmuted", "node": node_name}

@router.post("/nodedown/mute-list/save")
async def save_node_mute_list_raw(request: Request):
    data = await request.json()
    new_list = [ln.strip() for ln in data.get("raw_text", "").split("\n") if ln.strip()]
    save_node_mute_list(new_list)
    return {"status": "success", "count": len(new_list)}
