import os, sys, json, re, logging, sqlite3
from datetime import datetime
from logging.handlers import RotatingFileHandler
# 202512 Import mainconfig module
sys.path.append("..")
import mainconfig as mainconfig

# Configure logging
log_directory = mainconfig.LOGS_DIR
log_file = os.path.join(log_directory, 'analysis_sqlite.log')
logger = logging.getLogger('analysis')
logger.setLevel(logging.ERROR)
handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def setup_database(db_path):
    """Set up the SQLite database with corrected table schemas."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Create BGP peer status table with corrected schema 12 columns
    cursor.execute('''CREATE TABLE IF NOT EXISTS bgp_peer_status
        (hostname TEXT, host_ip TEXT, vpn_instance TEXT, local_router_id TEXT, local_as_number TEXT, neighbor_ip TEXT, remote_router_id TEXT, remote_as TEXT, up_down_time TEXT, state TEXT, last_updated_ts TEXT, 
        last_snapshot_id TEXT, source_log_file TEXT,
        PRIMARY KEY (host_ip, vpn_instance, neighbor_ip))''')
    # Create OSPF peer status table with corrected schema 20 columns
    cursor.execute('''CREATE TABLE IF NOT EXISTS ospf_peer_status
        (hostname TEXT, host_ip TEXT, process TEXT, process_routerid TEXT, vrf TEXT, area TEXT, interface TEXT, neighbor_routerid TEXT, neighbor_address TEXT, state TEXT, mode TEXT, verbose_uptime TEXT, state_count TEXT, last_down_time TEXT, last_routerid TEXT, last_local TEXT, last_remote TEXT, last_reason TEXT, last_updated_ts TEXT, last_snapshot_id TEXT, source_log_file TEXT,
        PRIMARY KEY (host_ip, process, neighbor_address)
                   )''')
    # Create tables for BGP/OSPF state changes
    # cursor.execute('CREATE TABLE IF NOT EXISTS ospf_state_changes 
    #               (id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT, process TEXT, neighbor_address    TEXT, interface TEXT, from_state TEXT, to_state TEXT, timestamp TEXT, log_file TEXT)')   
    cursor.execute('''CREATE TABLE IF NOT EXISTS ospf_state_changes 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT, process TEXT, neighbor_address TEXT, interface TEXT, from_state TEXT, to_state TEXT, timestamp TEXT, log_file TEXT,
                    UNIQUE (hostname, process, neighbor_address, interface, from_state, to_state, timestamp, log_file ))''') 
										 
    cursor.execute('CREATE TABLE IF NOT EXISTS bgp_state_changes (id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT, vpn_instance TEXT, neighbor_ip TEXT, from_state TEXT, to_state TEXT, timestamp TEXT, log_file TEXT)')

    # Create table for processed files
    cursor.execute('CREATE TABLE IF NOT EXISTS processed_files (filename TEXT PRIMARY KEY)')

    conn.commit()
    return conn

def cleanup_bgp_peer_status(conn):
    """
    Cleans up the bgp_peer_status table, keeping only the record 
    with the latest last_updated_ts for each unique peer 
    (host_ip, vpn_instance, neighbor_ip).
    """
    cursor = conn.cursor()
    logger.info("Starting BGP peer status cleanup for historical duplicates...")

    # Robust SQL to find the single rowid with the latest timestamp (MAX(last_updated_ts)) 
    # for each unique peer key, and delete all other rows.
    cleanup_sql = '''
        DELETE FROM bgp_peer_status
        WHERE rowid NOT IN (
            SELECT t.rowid
            FROM bgp_peer_status t
            INNER JOIN (
                SELECT 
                    host_ip, 
                    vpn_instance, 
                    neighbor_ip, 
                    MAX(last_updated_ts) AS max_ts
                FROM bgp_peer_status
                GROUP BY host_ip, vpn_instance, neighbor_ip
            ) AS latest_data
            ON t.host_ip = latest_data.host_ip
               AND t.vpn_instance = latest_data.vpn_instance
               AND t.neighbor_ip = latest_data.neighbor_ip
               AND t.last_updated_ts = latest_data.max_ts
        );
    '''
    
    try:
        cursor.execute(cleanup_sql)
        deleted_rows = cursor.rowcount
        conn.commit()
        logger.info(f"Cleanup complete. Deleted {deleted_rows} older duplicate BGP peer records.")
        return deleted_rows
    except sqlite3.Error as e:
        logger.error(f"SQLite error during cleanup: {e}")
        conn.rollback()
        return -1
    
def parse_timestamp(raw_ts_str, log_year):
    """Converts various log timestamp formats to a standard ISO 8601 format."""
    try:
        # HPE format: "Jul 10 16:08:00:614"
        if raw_ts_str.count(':') == 3:
            raw_ts_str = raw_ts_str.replace(':', '.', 2)
            dt_obj = datetime.strptime(f"{raw_ts_str} {log_year}", "%b %d %H.%M.%S.%f %Y")
        # Cisco format: "Jul 2 09:10:07"
        else:
            dt_obj = datetime.strptime(f"{raw_ts_str} {log_year}", "%b %d %H:%M:%S %Y")
        return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
        return f"{raw_ts_str} {log_year}"    

def process_log_file(conn, log_file_path, file_id, log_dir_base):
    """Process a single log file and insert into database."""
    cursor = conn.cursor()
    filename_only = os.path.basename(log_file_path)
    relative_log_path = os.path.relpath(log_file_path, log_dir_base).replace('\\', '/')
    logger.info(f"Processing file: {log_file_path}")
    hostname, vendor = (None, None)

    # Use log file timestamp as last_updated and snapshot_id
    try:
        file_ts_str = '_'.join(filename_only.split('_')[0:2])
        file_dt = datetime.strptime(file_ts_str, '%Y%m%d_%H%M%S')
        last_updated_ts = file_dt.isoformat()
        last_snapshot_id = file_ts_str
    except (ValueError, IndexError):
        last_updated_ts = datetime.now().isoformat()
        last_snapshot_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        logger.warning(f"Could not parse timestamp from filename '{filename_only}', using current time")

    log_year = filename_only.split('_')[0][:4]
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.splitlines()  # Split content into lines
    except Exception as e:
        logger.error(f"Failed to read file '{log_file_path}': {e}")
        return False

    logger.debug(f"Hostname: {hostname}, Vendor: {vendor}")

    if "Hewlett Packard Enterprise" in content:
        vendor = 'hpe'
    elif "show logging " in content:   
        vendor = 'arista'
    elif "show log " in content:
        vendor = 'cisco'

    # Call parse_routing_info directly and get the routing_info dictionary
    try:
        routing_info = parse_routing_info(log_file_path, lines, vendor,None)  # Pass None for json_file to avoid writing
    except Exception as e:
        logger.error(f"Error parse_routing from '{log_file_path}': {e}")
        return False
    if not hostname: hostname = routing_info.get("hostname", None)
    host_ip = routing_info.get("host_ip", None)
    if not host_ip:
        logger.error(f"No host IP found for file '{log_file_path}'")
        return False

    # --- Historical Log Parsing ---
    if vendor == 'hpe':
        # HPE log regex patterns for BGP and OSPF state changes
        # Example log line:
        # BGP
        # %Aug  1 15:01:15:294 2025 ENG22-CC-Core BGP/5/BGP_STATE_CHANGED: BGP.BCCSS: 10.251.0.72  state has changed from ESTABLISHED to IDLE for hold timer expiration caused by peer device.
        # OSPF
        # hpe_bgp_log_regex = re.compile(r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?BGP/5/BGP_STATE_CHANGED(?:_REASON)?:(?: BGP\.([^:]*?):)?\s+([\d\.]+) \s+state has changed from ([\w\/]+) to ([\w\/]+)")
        hpe_bgp_log_regex = re.compile(r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?BGP/5/BGP_STATE_CHANGED:(?: BGP\.([^:]*?):)?\s+([\d\.]+) \s+state has changed from ([\w\/]+) to ([\w\/]+)")
        for match in hpe_bgp_log_regex.finditer(content):
            vpn = match.group(2).strip() if match.group(2) else 'Global'
            timestamp = parse_timestamp(match.group(1), log_year)
            cursor.execute('INSERT OR IGNORE INTO bgp_state_changes (hostname, vpn_instance, neighbor_ip, from_state, to_state, timestamp, log_file) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                (hostname, vpn, match.group(3), match.group(4), match.group(5), timestamp, os.path.basename(log_file_path)))
            
        # %Jul 10 00:39:55:758 2025 ENG22-KEL-Core OSPF/5/OSPF_NBR_CHG: OSPF 7 Neighbor 10.251.8.113(Vsi-interface877) changed from FULL to DOWN.
        # Updated OSPF regex to handle interface names like Twenty-FiveGigE1/0/2
        hpe_ospf_log_regex = re.compile(
            r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?OSPF/5/OSPF_NBR_CHG:.*?OSPF\s+(\d+).*?Neighbor\s+([\d\.]+)\(([\w\-\/]+)\)\s+changed from\s+([\w/]+)\s+to\s+([\w/]+)"
        )        
        for match in hpe_ospf_log_regex.finditer(content):
            timestamp = parse_timestamp(match.group(1), log_year)
            cursor.execute(
                '''INSERT OR IGNORE INTO ospf_state_changes 
                (hostname, process, neighbor_address, interface, from_state, to_state, timestamp, log_file) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                (hostname, match.group(2), match.group(3), match.group(4), match.group(5), match.group(6), timestamp, filename_only)
            )
            logger.debug(f"Inserted OSPF state change: Neighbor {match.group(3)} on {match.group(4)} from {match.group(5)} to {match.group(6)}")

        # Handle OSPF last neighbor down event
        hpe_ospf_last_down_regex = re.compile(
            r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?OSPF/6/OSPF_LAST_NBR_DOWN: OSPF (\d+) Last neighbor down event: Router ID: ([\d\.]+) Local address: ([\d\.]+) Remote address: ([\d\.]+) Reason: ([^\.]+)"
        )
        for match in hpe_ospf_last_down_regex.finditer(content):
            timestamp = parse_timestamp(match.group(1), log_year)
            process = match.group(2)
            router_id = match.group(3)
            local_address = match.group(4)
            remote_address = match.group(5)
            reason = match.group(6).strip()
            # Update ospf_peer_status with last down event details
            cursor.execute(
                '''UPDATE ospf_peer_status 
                SET last_down_time = ?, last_routerid = ?, last_local = ?, last_remote = ?, last_reason = ?
                WHERE hostname = ? AND process = ? AND neighbor_address = ?''',
                (timestamp, router_id, local_address, remote_address, reason, hostname, process, remote_address)
            )
            logger.debug(f"Updated OSPF peer status with last down event: Neighbor {remote_address}, Process {process}, Reason: {reason}")
            
    elif vendor in ('cisco', 'arista'):
        cisco_ospf_log_regex = re.compile(r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}).*?Ospf.*?: Instance (\d+):.*?NGB ([\d\.]+), interface ([\d\.]+) adjacency (dropped|established).*?(?:state was: (\w+))?")  
        for match in cisco_ospf_log_regex.finditer(content):
            from_state, to_state = (match.group(6), 'DOWN') if match.group(5) == 'dropped' else ('DOWN', 'FULL')
            cursor.execute('INSERT INTO ospf_state_changes VALUES (NULL,?,?,?,?,?,?,?,?)', (hostname, match.group(2), match.group(3), match.group(4), from_state, to_state, parse_timestamp((match.group(1)),log_year), os.path.basename(log_file_path)))    

    # Process BGP peers
    if isinstance(routing_info.get("BGP"), list):
        data_rows = "hostname, host_ip, vpn_instance, local_router_id, local_as_number, neighbor_ip, remote_router_id, remote_as, up_down_time, state, last_updated_ts, last_snapshot_id, source_log_file"

        sql_query = f'''
            INSERT INTO bgp_peer_status ({data_rows}) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_ip, vpn_instance, neighbor_ip) 
            DO UPDATE SET
                state = excluded.state,
                up_down_time = excluded.up_down_time,
                remote_router_id = excluded.remote_router_id,
                remote_as = excluded.remote_as,
                last_updated_ts = excluded.last_updated_ts,
                last_snapshot_id = excluded.last_snapshot_id,
                source_log_file = excluded.source_log_file
            WHERE excluded.last_updated_ts > bgp_peer_status.last_updated_ts
        '''

        for bgp_instance in routing_info["BGP"]:
            vpn_instance = bgp_instance.get("VPN_instance", "Global")
            local_router_id = bgp_instance.get("local_router_id")
            local_as_number = bgp_instance.get("local_as_number")
            
            for peer in bgp_instance.get("Peer", []):
                values_to_insert = (
                    hostname, host_ip, vpn_instance, local_router_id, local_as_number,
                    peer.get("neighbor_ip"),
                    peer.get("remote_router_id"), # Make sure to extract this in parse_routing_info
                    peer.get("remote_as"), 
                    peer.get("peer_uptime"), 
                    peer.get("peer_status"), 
                    last_updated_ts, 
                    last_snapshot_id, 
                    relative_log_path
                )
                cursor.execute(sql_query, values_to_insert)

    # Process OSPF peers with 20 rows
    if isinstance(routing_info.get("OSPF"), list):
        # 202512 Update VRF from logs
        hpe_ospf_reason_re = mainconfig.HPE_OSPF_REASON_REGEX
        for match in hpe_ospf_reason_re.finditer(content):
            g = match.groupdict()
            # print(f"Processing HPE OSPF reason log for host IP: {host_ip} process {g['process']} vpn {g.get('vpn_name')}")
            
            # Find the matching OSPF process entry in the routing_info list
            for ospf_process in routing_info.get("OSPF", []):
                if str(ospf_process.get("process")) == g['process']:
                    # Update the VRF in the in-memory data structure
                    ospf_process['vrf'] = g.get('vpn_name')
                    # print(f"Updated {host_ip} VRF for process {g['process']} to {g.get('vpn_name')}")          

        data_rows = "hostname, host_ip, process, process_routerid, vrf, area, interface, neighbor_routerid, neighbor_address, state, mode,  verbose_uptime, state_count, last_down_time, last_routerid, last_local, last_remote, last_reason, last_updated_ts, last_snapshot_id, source_log_file"
        placeholders = ', '.join(['?'] * len(data_rows.split(', ')))

        # Define the SQL for INSERT OR UPDATE (Upsert)
        # This will update current status fields always, but conditionally update event fields.
        sql_upsert_query = f'''
            INSERT INTO ospf_peer_status ({data_rows}) 
            VALUES ({placeholders})
            ON CONFLICT(host_ip, process, neighbor_address) 
            DO UPDATE SET
                -- 1. Snapshot Fields (Always Update)
                
                process_routerid = excluded.process_routerid,
                area = excluded.area,
                interface = excluded.interface,
                neighbor_routerid = excluded.neighbor_routerid,
                state = excluded.state,
                mode = excluded.mode,
                verbose_uptime = excluded.verbose_uptime,
                state_count = excluded.state_count,
                last_updated_ts = excluded.last_updated_ts,
                last_snapshot_id = excluded.last_snapshot_id,
                source_log_file = excluded.source_log_file,

                -- 2. Event/Historical Fields (Update ONLY IF incoming data is NOT NULL)
                hostname = CASE 
                    WHEN excluded.hostname IS NOT NULL AND excluded.hostname != '' 
                    THEN excluded.hostname 
                    ELSE hostname 
                END,                
                vrf = CASE 
                    WHEN excluded.vrf IS NOT NULL AND excluded.vrf != '' 
                    THEN excluded.vrf  -- Use the NEW value
                    ELSE vrf           -- Keep the OLD value
                END,
                last_down_time = CASE 
                    WHEN excluded.last_down_time IS NOT NULL THEN excluded.last_down_time 
                    ELSE last_down_time 
                END,
                last_routerid = CASE 
                    WHEN excluded.last_routerid IS NOT NULL THEN excluded.last_routerid 
                    ELSE last_routerid 
                END,
                last_local = CASE 
                    WHEN excluded.last_local IS NOT NULL THEN excluded.last_local 
                    ELSE last_local 
                END,
                last_remote = CASE 
                    WHEN excluded.last_remote IS NOT NULL THEN excluded.last_remote 
                    ELSE last_remote 
                END,
                last_reason = CASE 
                    WHEN excluded.last_reason IS NOT NULL THEN excluded.last_reason 
                    ELSE last_reason 
                END
        '''

        for ospf_process in routing_info["OSPF"]:
            process = ospf_process.get("process")
            process_routerid = ospf_process.get("process_routerid")
            vrf = ospf_process.get("vrf")
            if process is None:
                # Assign a non-null, standard value for the global/default instance
                # Use the standard default process ID or "Global"
                ospf_process["process"] = "0" # Update the dictionary

            last_events = ospf_process.get("lastevents", {})  # Dictionary of last events by last_remote
            for neighbor in ospf_process.get("neighbors", []):
                address = neighbor.get("neighbor_address")
                event_data = last_events.get(address) if address else None
                values_to_insert = (hostname, host_ip, process, process_routerid, vrf, neighbor.get("Area"), neighbor.get("Interface"), neighbor.get("neighbor_routerid"), address, neighbor.get("state"), neighbor.get("mode"), neighbor.get("uptime"), neighbor.get("state_count"),
                event_data.get("last_time") if event_data else None,
                event_data.get("router_id") if event_data else None,
                event_data.get("last_local") if event_data else None,
                event_data.get("last_remote") if event_data else None,
                event_data.get("last_reason") if event_data else None,
                last_updated_ts, last_snapshot_id, relative_log_path)

                # Execution with the new SQL query
                cursor.execute(sql_upsert_query, values_to_insert)
                logger.debug(f"Upserted OSPF peer: {neighbor.get('neighbor_routerid')} on interface {neighbor.get('Interface')} with last_down_time: {event_data.get('last_time') if event_data else 'None'}")
    
    #  Call the cleanup function after processing each file
    cleanup_bgp_peer_status(conn)   
    conn.commit()
    return True

def parse_routing_info(temp_file_path, lines, vendor, json_file=None):
    # routing_info = {"hostname": None, "vendor": {vendor}, "host_ip": None, "BGP": [], "OSPF": []}
    routing_info = {"hostname": None, "vendor": vendor, "host_ip": None, "BGP": [], "OSPF": []}
    ip_regex = r'(?:\d{1,3}\.){3}\d{1,3}'
    hostname_regex = r"(<|)(.*?)(>|#)"
    
    if not os.path.isfile(temp_file_path):
        logger.error(f"No file exists: {temp_file_path}")
        return routing_info

    file_name = os.path.split(temp_file_path)[1]
    host_ip_match = re.search(ip_regex, file_name)
    if host_ip_match:
        host_ip = host_ip_match.group()
    else:
        logger.error(f"Host IP not found in filename: {file_name}")
        return routing_info

    log_year = file_name.split('_')[0][:4]
    # json_file = os.path.join(log_directory, host_ip+"_peer.json") 
    current_hostname = None
    in_bgp_section = False
    in_ospf_section = False
    current_vpn_instance = "Global"
    current_ospf_process = "0"
    current_ospf_area = None
    current_interface = None
    current_neighbor = None
    local_as = None
    last_down_event = {}

    logger.debug(f"Parsing file: {temp_file_path} for vendor: {vendor}")
    for idx, line in enumerate(lines):
        line = line.strip()
        if not line or "---- More ----" in line:
            continue

        # Extract hostname
        if current_hostname is None:
            hostname_match = re.match(hostname_regex, line)
            if hostname_match:
                current_hostname = hostname_match.group(2)
                routing_info["hostname"] = current_hostname
                routing_info["host_ip"] = host_ip
                logger.debug(f"Extracted hostname: {current_hostname}")

        # bgp or ospf section
        if "BGP is not configured." in line:
            routing_info["BGP"] = "BGP is not configured."
            in_bgp_section = False
            logger.debug("BGP not configured")
            continue
        if "OSPF is not configured." in line:
            routing_info["OSPF"] = "OSPF is not configured."
            in_ospf_section = False
            logger.debug("OSPF not configured")
            continue

        if vendor == 'hpe':

            if line.startswith("BGP local router ID:"):
                router_id = line.split(":")[1].strip()
                in_bgp_section = True
                logger.debug(f"BGP router ID: {router_id}")
                continue

            if in_bgp_section:
                if line.startswith("Local AS number:"):
                    local_as_number = line.split(":")[1].strip()
                    logger.debug(f"BGP local AS: {local_as_number}")
                    continue
                if line.startswith("VPN instance:"):
                    current_vpn_instance = line.split(":")[1].strip()
                    logger.debug(f"BGP VPN instance: {current_vpn_instance}")
                elif line.startswith("Total number of peers:"):
                    peer_total, peer_est = map(int, re.findall(r"\d+", line))
                    bgp_peer = {
                        "VPN_instance": current_vpn_instance,
                        "local_router_id": router_id,
                        "local_as_number": local_as_number,
                        "Total number of peers": peer_total,
                        "Peers in established state": peer_est,
                        "Peer": []
                    }
                    routing_info["BGP"].append(bgp_peer)
                    logger.debug(f"BGP peer totals: {peer_total}, established: {peer_est}")
                elif re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", line):
                    parts = line.split()
                    if len(parts) == 8:
                        peer_info = {
                            "neighbor_ip": parts[0],
                            "remote_as": parts[1],
                            "peer_uptime": parts[-2],
                            "peer_status": parts[-1]
                        }
                        routing_info["BGP"][-1]["Peer"].append(peer_info)
                        logger.debug(f"BGP peer added: {parts[0]}")

            # Handle OSPF section

            if "display ospf peer verbose" in line:
                in_bgp_section = False
                in_ospf_section = True

            if in_ospf_section:
                process_match = re.search(r"Process (\d+) with Router ID ([\d\.]+)", line)
                if process_match:
                    current_process = process_match.group(1)
                    process_routerid = process_match.group(2)
                    current_ospf_process = {
                        "process": current_process,
                        "process_routerid": process_routerid,
                        "neighbors": [],
                        "lastevents": {}  # Changed to a dictionary for peer-specific events
                    }
                    routing_info["OSPF"].append(current_ospf_process)
                    # current_neighbor = None
                    logger.debug(f"OSPF Process {current_process}, Router ID: {process_routerid}")

                elif line.startswith("Area ") and "interface" in line:
                    area_match = re.search(r"Area\s+([\d\.]+)\s+interface\s+([\d\.]+)\(([\w\-\/]+)\)", line)
                    # if area_match and current_ospf_process:
                    current_area = area_match.group(1)
                    interface_ip = area_match.group(2)
                    interface_name = area_match.group(3)
                    current_neighbor = {
                        "Area": current_area,
                        "Interface": f"{interface_ip}({interface_name})",
                        "neighbor_routerid": None,
                        "neighbor_address": None,
                        "uptime": None,
                        "state": None,
                        "mode": None,
                        "state_count": None
                    }
                    # current_ospf_process["neighbors"].append(current_neighbor)
                    logger.debug(f"Verbose OSPF Area {current_area}, Interface {current_neighbor['Interface']}")

                elif line.startswith("Router ID:") and "Address:" in line:
                    routerid_match = re.search(r"Router ID:\s*([\d\.]+)\s+Address:\s*([\d\.]+)", line)
                    # if routerid_match and current_ospf_process and current_neighbor:
                    neighbor_routerid = routerid_match.group(1)
                    neighbor_address = routerid_match.group(2)
                    if current_neighbor is None:
                        # Create neighbor if doesn't exist
                        current_neighbor = {
                            "neighbor_routerid": neighbor_routerid,
                            "neighbor_address": neighbor_address,
                            # ... other fields ...
                        }
                    else:                    
                        current_neighbor["neighbor_routerid"] = neighbor_routerid
                        current_neighbor["neighbor_address"] = neighbor_address
                    # FIX: Append neighbor immediately after getting router ID
                    if current_ospf_process and current_neighbor:
                        current_ospf_process["neighbors"].append(current_neighbor.copy())
                    
                    logger.debug(f"Verbose OSPF neighbor: {neighbor_routerid}, Address: {neighbor_address}")

                # Handle verbose OSPF output
                # if current_neighbor:
                elif line.startswith("State:") and "Mode:" in line:
                    pairs = re.findall(r"(\w+):\s+(.*?)(?=\s+\w+:|$)", line)
                    data = {key.strip(): value.strip() for key, value in pairs}
                    current_neighbor["state"] = data.get("State")
                    current_neighbor["mode"] = data.get("Mode")
                elif line.startswith("Neighbor is up for"):
                    uptime_match = re.search(r"Neighbor is up for\s+([0-9:]+)", line)
                    if uptime_match and current_neighbor:
                        current_neighbor["uptime"] = uptime_match.group(1)
                        logger.debug(f"Set uptime for {current_neighbor['neighbor_routerid']}: {current_neighbor['uptime']}")
                        
                        # FIX: Ensure neighbor is added even if state change count is missing
                        if current_ospf_process and current_neighbor and current_neighbor not in current_ospf_process["neighbors"]:
                            current_ospf_process["neighbors"].append(current_neighbor.copy())
                elif line.startswith("Neighbor state change count:"):
                    state_change_match = re.search(r"Neighbor state change count:\s+(\d+)", line)
                    if state_change_match and current_neighbor:
                        current_neighbor["state_count"] = state_change_match.group(1)
                        logger.debug(f"Set state change count for {current_neighbor['neighbor_routerid']}: {current_neighbor['state_count']}")
                        
                        # FIX: Ensure neighbor is added
                        if current_ospf_process and current_neighbor and current_neighbor not in current_ospf_process["neighbors"]:
                            current_ospf_process["neighbors"].append(current_neighbor.copy())
                    logger.debug(f"Set state change count for {current_neighbor['neighbor_routerid']}: {current_neighbor['state_count']}")

                if line.startswith("Last Neighbor Down Event:"):
                    last_down_event.clear()
                    j = idx + 1
                    while j < len(lines):
                        next_line = lines[j].strip()
                        logger.debug(f"Checking line for last down event: {next_line}")
                        if "---- More ----" in next_line or not next_line:
                            break
                        if next_line.startswith("Router ID:"):
                            last_down_event["router_id"] = re.search(r"Router ID:\s*([\d\.]+)", next_line).group(1)
                        elif next_line.startswith("Local Address:"):
                            last_down_event["last_local"] = re.search(r"Local Address:\s*([\d\.]+)", next_line).group(1)
                        elif next_line.startswith("Remote Address:"):
                            last_down_event["last_remote"] = re.search(r"Remote Address:\s*([\d\.]+)", next_line).group(1)
                        elif next_line.startswith("Time:"):
                            last_down_event["last_time"] = next_line.split("Time:")[1].strip()
                        elif next_line.startswith("Reason:"):
                            last_down_event["last_reason"] = next_line.split("Reason:")[1].strip()
                        j += 1
                    if last_down_event.get("last_remote"):
                        current_ospf_process["lastevents"][last_down_event["last_remote"]] = last_down_event.copy()
                        logger.debug(f"Set last down event for remote {last_down_event['last_remote']} in process {current_process}: {last_down_event}")
                    else:
                        logger.warning(f"No valid last_remote found for last down event in process {current_process}")

        if vendor in ('cisco','arista'):
        # if vendor == 'cisco':
            # logger.error(temp_file_path,vendor)

            if "show ip bgp all" in line or "show ip bgp neighbors" in line:
                in_bgp_section = True
                in_ospf_section = False
                continue
            if "show ip ospf neighbor detail" in line:
                in_bgp_section = False
                in_ospf_section = True
                continue

            if in_bgp_section:
                # Detect new address family
                address_family_match = re.match(r"For address family: (\w+ \w+)", line)
                if address_family_match:
                    current_address_family = address_family_match.group(1)
                    logger.debug(temp_file_path,routing_info["BGP"])
                    continue
                else:
                    current_address_family = None

                # Detect new neighbor block
                # if line.startswith("BGP neighbor is"):
                #     if "IPv4" in current_address_family :
                    # BGP neighbor is 10.26.101.1,  remote AS 65500, internal link
                bgp_ipv4_match = re.match(r"BGP neighbor is (\d+\.\d+\.\d+\.\d+), \s+remote AS (\d+), (\w+) link", line)
                if bgp_ipv4_match:
                    neighbor_ip = bgp_ipv4_match.group(1)
                    vpn_instance =  "Global"
                    remote_as = bgp_ipv4_match.group(2)
                    # elif "VPNv4" in current_address_family:
                    # BGP neighbor is 10.73.119.241,  vrf VCHA-TC2,  remote AS 4255000501,  local AS 4255000101, external link
                bgp_vpnv4_match = re.match(
                    r"BGP neighbor is "
                    r"(\d+\.\d+\.\d+\.\d+),"  # Group 1: Neighbor IP
                    r"\s+(?:vrf ([\w-]+),\s+)?"  # Group 2: Optional VRF name
                    r"remote AS (\d+),"  # Group 3: Remote AS
                    r"\s+(?:local AS (\d+),\s+)?"  # Group 4: Optional Local AS
                    r"(\w+) link",  # Group 5: Link type
                    line
                )
                if bgp_vpnv4_match:
                    neighbor_ip = bgp_vpnv4_match.group(1)
                    vpn_instance =  bgp_vpnv4_match.group(2)
                    remote_as = bgp_vpnv4_match.group(3)    
                    local_as = bgp_vpnv4_match.group(4)                   

                if bgp_vpnv4_match or bgp_ipv4_match:
                    bgp_peer = {
                        "address_family": current_address_family, 
                        "VPN_instance": vpn_instance, 
                        "local_as_number": local_as, 
                        "Peer": []
                        }
                    routing_info["BGP"].append(bgp_peer)
                    logger.debug(temp_file_path,routing_info,neighbor_ip)
                    continue

                if line.startswith("BGP version"):
                # elif line.startswith("BGP version") and bgp_peer:
                    #   BGP version 4, remote router ID 10.26.101.1
                    remote_router_id_match = re.search(r"remote router ID (\d+\.\d+\.\d+\.\d+)", line)
                    remote_router_id = remote_router_id_match.group(1)
                    logger.debug(temp_file_path, routing_info, remote_router_id)

                # Extract state and uptime
                elif line.startswith("BGP state"):
                    state_match = re.search(r"BGP state (?:is|=) (\w+), (up|down) for (.*)",  line)
                    current_neighbor = {
                        "neighbor_ip": neighbor_ip, 
                        "remote_router_id": remote_router_id, 
                        "remote_as": remote_as, 
                        "peer_uptime": state_match.group(3), 
                        "peer_status": state_match.group(1)
                        }
                    routing_info["BGP"][-1]["Peer"].append(current_neighbor)
                    logger.debug(temp_file_path,routing_info["BGP"])                        

            # Handle OSPF section (unchanged, included for context)

            if in_ospf_section:             
                # cisco:    Neighbor 10.253.31.246, interface address 10.8.6.238
                if vendor == "cisco":                
                    neighbor_match = re.match(r"Neighbor (\d+\.\d+\.\d+\.\d+), interface address (\d+\.\d+\.\d+\.\d+)", line)
                    if neighbor_match:
                        current_neighbor = {
                            "neighbor_address": neighbor_match.group(1), 
                            "Interface_address": neighbor_match.group(2), 
                            "Interface": None, 
                            "Area": None, 
                            "neighbor_routerid": None, 
                            "uptime": None, 
                            "state": None, 
                            "state_count": None
                            }
                    elif line.startswith("In the area") and current_neighbor:
                        #    In the area 0 via interface Vlan4042
                        area_match = re.search(r"In the area (\d+) via interface (\S+)", line)
                        if area_match:
                            current_neighbor["Area"] = area_match.group(1)
                            current_neighbor["Interface"] = f"{area_match.group(2)}"
                    elif "State is" in line and current_neighbor: 
                        #    Neighbor priority is 0, State is FULL, 6 state changes
                        state_match = re.search(r"State is (\w+), (\d+) state changes", line)
                        current_neighbor["state"] = state_match.group(1)
                        current_neighbor["state_count"] = state_match.group(2)                    
                    elif line.startswith("Neighbor is up") :    
                        #    Neighbor is up for 27w5d   
                        uptime_match = re.search(r"Neighbor is up for (\d+\w+\d*\w*)", line)
                        current_neighbor["uptime"] = uptime_match.group(1)
                        if current_neighbor.get("Area"):
                            current_ospf_process = {"process": 0, "process_routerid": None, "neighbors": [], "lastevents": {}}
                            routing_info["OSPF"].append(current_ospf_process)                                   
                            current_ospf_process["neighbors"].append(current_neighbor)
                            current_neighbor = None
                    elif line.strip() == "":
                        current_neighbor = None

                if vendor == 'arista':
                    # arista:   Neighbor 10.26.101.73, instance 200, VRF default, interface address 10.26.254.162
                    arista_neighbor_match = re.search(r"Neighbor (\d+\.\d+\.\d+\.\d+), instance (\d+), VRF (\S+), interface address (\d+\.\d+\.\d+\.\d+)", line)
                    if arista_neighbor_match:
                        arista_current_ospf_process = {
                            "process": arista_neighbor_match.group(2), 
                            "process_routerid": None, 
                            "vrf":arista_neighbor_match.group(3), 
                            "neighbors": [], 
                            "lastevents": {}
                            }
                        arista_current_neighbor = {
                            "neighbor_address": arista_neighbor_match.group(1), 
                            "Interface_address": arista_neighbor_match.group(4), 
                            "Interface": None, 
                            "Area": None, 
                            "neighbor_routerid": None, 
                            "uptime": None, 
                            "state": None, 
                            "state_count": None
                            }
                    elif line.startswith("In area") and arista_current_neighbor:
                        #   In area 0.0.0.1 interface Ethernet4/8
                        area_match = re.search(r"In area (\d+\.\d+\.\d+\.\d+) interface (\S+)", line)
                        arista_current_neighbor["Area"] = area_match.group(1)
                        arista_current_neighbor["Interface"] = f"{area_match.group(2)}"
                    elif "State is" in line and arista_current_neighbor: 
                        #  Neighbor priority is 1, State is FULL, 6 state changes
                        state_match = re.search(r"State is (\w+), (\d+) state changes", line)
                        arista_current_neighbor["state"] = state_match.group(1)
                        arista_current_neighbor["state_count"] = state_match.group(2)                    
                    elif line.startswith("Current state") :    
                        #   Current state was established 142d21h ago
                        uptime_match = re.search(r"Current state was established (.*?) ", line)
                        arista_current_neighbor["uptime"] = uptime_match.group(1)
                        # if arista_current_neighbor.get("uptime"):
                        routing_info["OSPF"].append(arista_current_ospf_process)                          
                        arista_current_ospf_process["neighbors"].append(arista_current_neighbor)
                        # arista_current_neighbor = None
                        logger.debug(temp_file_path,vendor,routing_info["OSPF"])
                    elif line.strip() == "":
                        arista_current_neighbor = None                        

    if json_file and isinstance(json_file, (str, os.PathLike)):
        try:
            with open(json_file, 'w') as f:
                json.dump(routing_info, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to write JSON file {json_file}: {e}")

    logger.debug(f"Parsed routing info: {len(routing_info['OSPF'])} OSPF processes")
    return routing_info

def parse_uptime_to_seconds(uptime_str):
    """Convert uptime string (e.g., '536:53:45') to seconds for sorting."""
    if not uptime_str or not isinstance(uptime_str, str):
        return 0
    try:
        days, hours, minutes = map(int, uptime_str.split(':'))
        return days * 86400 + hours * 3600 + minutes * 60
    except (ValueError, AttributeError):
        logger.warning(f"Invalid uptime format '{uptime_str}', defaulting to 0 seconds")
        return 0

def main(log_file_path=None):
    """Main entry point: Process all logs in directory (default) or a single file (if provided)."""
    # log_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs', 'core'))
    # database_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'network_analysis.db'))

    log_directory = mainconfig.CORE_LOGS_DIR
    # log_directory = mainconfig.CORE_MAIN_DIR
    database_path = mainconfig.DB_PATH

    logger.info("Starting network log analysis...")
    connection = setup_database(database_path)

    # 🌟 NEW: Call the cleanup function here
    # cleanup_bgp_peer_status(connection)

    if not os.path.isdir(log_directory):
        logger.error(f"Error: Log directory '{log_directory}' not found.")
        sys.exit(1)  # Or raise an exception if imported

    cursor = connection.cursor()
    cursor.execute("SELECT filename FROM processed_files")
    processed_filenames_db = {row[0] for row in cursor.fetchall()}
    logging.info(f"Found {len(processed_filenames_db)} files already processed in the database.")

    log_file_regex = re.compile(r"^\d{8}_\d{6}_[\d\.]+_[\w-]+_sa\.txt$")
    
    if log_file_path:  # Single-file mode (when called with a path)
        if not os.path.isfile(log_file_path):
            logger.error(f"Single file not found: {log_file_path}")
            connection.close()
            return False  # Or raise ValueError
        filename_only = os.path.basename(log_file_path)
        if filename_only in processed_filenames_db:
            logger.info(f"Single file '{filename_only}' already processed. Skipping.")
            connection.close()
            return True  # Already done
        if os.path.getsize(log_file_path) == 0:
            logger.warning(f"Skipping empty single file: '{filename_only}'")
            cursor.execute("INSERT INTO processed_files (filename) VALUES (?)", (filename_only,))
            connection.commit()
            connection.close()
            return False
        files_to_process = [log_file_path]
    else:  # Directory mode (all new files)
        all_files_on_disk = [(os.path.join(log_directory, filename), filename) for filename in os.listdir(log_directory) 
                             if os.path.isfile(os.path.join(log_directory, filename)) and log_file_regex.match(filename)]
        files_to_process = []
        for filepath, filename in all_files_on_disk:
            if filename not in processed_filenames_db and os.path.getsize(filepath) > 0:
                files_to_process.append(filepath)
            # Check for empty files
            elif os.path.getsize(filepath) == 0:
                logger.warning(f"Skipping empty log file: '{filename}'")
                # FIX: Only insert the filename if it is NOT already in the set of processed files
                if filename not in processed_filenames_db:
                    cursor.execute("INSERT INTO processed_files (filename) VALUES (?)", (filename,))
                    connection.commit()
                else:
                    logger.debug(f"Empty log file '{filename}' already recorded as processed.")

    if not files_to_process:
        logger.warning("No new valid log files found to process. System is up to date.")
        connection.close()
        return False  # No updates

    logger.info(f"Found {len(files_to_process)} new, valid log files to process.")
    files_to_process.sort()

    updates_made = False
    for filepath in files_to_process:
        try:
            success = process_log_file(connection, filepath, None, log_directory)
            filename_only = os.path.basename(filepath)
            if success:
                cursor.execute("INSERT INTO processed_files (filename) VALUES (?)", (filename_only,))
                connection.commit()
                updates_made = True
                logger.info(f"Successfully processed and recorded '{filename_only}'.")
            else:
                logger.error(f"Failed to process '{filename_only}'")
                connection.rollback()
        except Exception as e:
            logger.error(f"ERROR processing file {os.path.basename(filepath)}: {e}")
            connection.rollback()

    if not updates_made:
        logger.warning("No successful updates made despite files found.")
        connection.close()
        return False
    else:
        connection.close()
        logger.info("Database processing complete.")
        return True
    

if __name__ == "__main__":
    if sys.argv[1:]:  # If args provided, treat as single files
        success = False
        for arg in sys.argv[1:]:
            if main(arg):  # Process each as single file
                success = True
        sys.exit(0 if success else 1)
    else:
        sys.exit(0 if main() else 1)  # Directory mode