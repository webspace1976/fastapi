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
    """Level 2 — devices inside one site as nodes with L2 direct connections.
    Core device (Switch/Firewall/Router by DeviceType, or 'CORE' in name) is
    returned with is_core=True so the frontend can pin it to the centre."""
    if not site:
        raise HTTPException(status_code=400, detail="site required")
    CORE_TYPES = {"Switch", "Firewall", "Router", "Telus CE"}
    try:
        with _orion_read_engine.connect() as conn:
            node_df = pd.read_sql_query("""
                SELECT ncp.NodeID, ncp.NodeName, ncp.IPaddress,
                       ncp.HA, ncp.Closet, ncp.Floor, ncp.Building,
                       ncp.DeviceType, ncp.SiteType, ncp.Status,
                       ncp.StatusDescription, ncp.DetailsUrl
                FROM [Orion.NodesCustomProperties] ncp
                WHERE ncp.Site = :site
                ORDER BY ncp.Closet, ncp.Floor, ncp.NodeName
            """, conn, params={"site": site})
            # FIX: join via NodeID (NCP.Site is ground truth for same/cross-site).
            # LEFT JOIN NPM.Interfaces on node name prefix + exact port string match.
            # NPM.Interfaces is a down-ports-only table — every row has a DownTime.
            # A match means that port is currently DOWN; NULL means port is UP.
            # SUBSTR(i.NodeName, 1, INSTR-1) extracts the switch name prefix.
            # TRIM(SUBSTR(i.NodeName, INSTR+1)) extracts "PortName · Desc" remainder.
            edge_df = pd.read_sql_query("""
                SELECT t.SourceNodeID, t.SourceNodeName,
                       t.TargetNodeID, t.TargetNodeName,
                       t.SourceInterface, t.TargetInterface,
                       src_ncp.Site    AS SrcSite,
                       tgt_ncp.Site    AS TgtSite,
                       t.LayerType,
                       -- Port down if NPM.Interfaces has this node+port (down-only table)
                       CASE WHEN iface.NodeName IS NOT NULL THEN 1 ELSE 0 END AS SrcPortDown,
                       iface.DownTime  AS SrcPortDownSince,
                       iface.DetailsUrl AS SrcPortUrl
                FROM [Orion.Topology] t
                LEFT JOIN [Orion.NodesCustomProperties] src_ncp ON t.SourceNodeID  = src_ncp.NodeID
                LEFT JOIN [Orion.NodesCustomProperties] tgt_ncp ON t.TargetNodeID  = tgt_ncp.NodeID
                LEFT JOIN [Orion.NPM.Interfaces] iface
                       ON SUBSTR(iface.NodeName, 1, INSTR(iface.NodeName, ' ') - 1) = t.SourceNodeName
                      AND TRIM(SUBSTR(iface.NodeName, INSTR(iface.NodeName, ' ') + 1)) = t.SourceInterface
                WHERE t.LayerType = 'L2'
                  AND (src_ncp.Site = :site OR tgt_ncp.Site = :site)
            """, conn, params={"site": site})
        node_ids = set(str(r["NodeID"]) for _, r in node_df.iterrows())
        nodes = []
        for _, r in node_df.iterrows():
            nid = str(r["NodeID"])
            try: is_up = int(str(r.get("Status") or "1")) == 1
            except: is_up = True
            dtype = r["DeviceType"] or ""
            name_upper = (r["NodeName"] or "").upper()
            # Core detection: Switch/Firewall/Router/Telus CE type OR 'CORE' in name
            is_core = dtype in CORE_TYPES or "CORE" in name_upper
            nodes.append({
                "id": f"node:{nid}", "label": r["NodeName"] or nid,
                "type": "device", "is_core": is_core,
                "ha": r["HA"] or "", "closet": r["Closet"] or "",
                "floor": r["Floor"] or "", "building": r["Building"] or "",
                "device_type": dtype, "ip": r["IPaddress"] or "",
                "details_url": r["DetailsUrl"] or "",
                "status_desc": r["StatusDescription"] or "",
                "is_up": is_up, "in_site": True,
            })
        seen_edges, edges = set(), []
        for _, r in edge_df.iterrows():
            src_id = f"node:{r['SourceNodeID']}"
            tgt_id = f"node:{r['TargetNodeID']}"
            if src_id == tgt_id: continue
            key = tuple(sorted([src_id, tgt_id]))
            if key in seen_edges: continue
            seen_edges.add(key)
            # NCP-derived site comparison — accurate even when Topology.SourceSite is wrong
            cross_site = (r.get("SrcSite") or "") != (r.get("TgtSite") or "")
            for side_id, side_name, in_site_flag in [
                (src_id, r["SourceNodeName"], str(r["SourceNodeID"]) in node_ids),
                (tgt_id, r["TargetNodeName"], str(r["TargetNodeID"]) in node_ids),
            ]:
                if side_id not in {n["id"] for n in nodes}:
                    nodes.append({
                        "id": side_id, "label": side_name or side_id,
                        "type": "device", "is_core": False,
                        "in_site": False, "is_up": True,
                        "ha": "", "closet": "", "floor": "", "building": "",
                        "device_type": "", "ip": "", "details_url": "",
                        "status_desc": "",
                    })
                    node_ids.add(side_id.replace("node:", ""))
            src_if = str(r.get("SourceInterface") or "").replace("None","").strip()
            tgt_if = str(r.get("TargetInterface") or "").replace("None","").strip()
            src_port = src_if.split(" · ")[0] if " · " in src_if else src_if
            tgt_port = tgt_if.split(" · ")[0] if " · " in tgt_if else tgt_if
            lbl = f"{src_port}↔{tgt_port}" if (src_port and tgt_port) else (src_port or tgt_port or "")
            src_port_down = bool(r.get("SrcPortDown"))
            src_port_down_since = str(r.get("SrcPortDownSince") or "").strip()
            src_port_url = str(r.get("SrcPortUrl") or "").strip()
            # Colour priority: port down > cross-site > normal
            if src_port_down:
                edge_color = "#ef4444"  # red — port is currently down
            elif cross_site:
                edge_color = "#f97316"  # orange — cross-site uplink
            else:
                edge_color = "#22c55e"  # green — same-site, port up
            edges.append({
                "id": f"e:{src_id}-{tgt_id}", "source": src_id, "target": tgt_id,
                "label": lbl, "source_interface": src_if, "target_interface": tgt_if,
                "cross_site": cross_site,
                "port_down": src_port_down,
                "port_down_since": src_port_down_since,
                "port_url": src_port_url,
                "color": edge_color,
            })
        in_site_nodes = [n for n in nodes if n.get("in_site", True)]
        return {
            "level": 2, "site": site, "nodes": nodes, "edges": edges,
            "summary": {
                "devices_in_site":  len(in_site_nodes),
                "external_nodes":   len([n for n in nodes if not n.get("in_site", True)]),
                "total_edges":      len(edges),
                "cross_site_edges": sum(1 for e in edges if e.get("cross_site")),
            },
        }
    except Exception as e:
        logger.error("topo/site: %s", e)
        return {"nodes": [], "edges": [], "error": str(e)}


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