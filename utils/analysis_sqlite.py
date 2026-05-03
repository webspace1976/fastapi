import os, sys, json, re, logging, sqlite3, traceback
from datetime import datetime
from multiprocessing.pool import ThreadPool as Pool
from functools import lru_cache
from logging.handlers import RotatingFileHandler
# Import mainconfig from parent directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
import mainconfig as mainconfig
from database.db_manager import DatabaseManager
logger = mainconfig.setup_module_logger(__name__)

def cleanup_bgp_peer_status(db): #(One-time Run)
    """
    Cleans up the bgp_peer_status table, keeping only the record 
    with the latest last_updated_ts for each unique peer 
    (host_ip, vpn_instance, neighbor_address).
    """
    # conn = sqlite3.connect(db_path)
    # cursor = conn.cursor()
    logger.info("Starting BGP peer status cleanup for historical duplicates...")

    # Robust SQL to find the single rowid with the latest last_updated_ts (MAX(last_updated_ts)) 
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
                    neighbor_address, 
                    MAX(last_updated_ts) AS max_ts
                FROM bgp_peer_status
                GROUP BY host_ip, vpn_instance, neighbor_address
            ) AS latest_data
            ON t.host_ip = latest_data.host_ip
               AND t.vpn_instance = latest_data.vpn_instance
               AND t.neighbor_address = latest_data.neighbor_address
               AND t.last_updated_ts = latest_data.max_ts
        );
    '''
    
    try:
        # cursor.execute(cleanup_sql)
        # deleted_rows = cursor.rowcount
        # conn.commit()
        db.execute_write(cleanup_sql, debug=True)
        # logger.info(f"Cleanup complete. Deleted {deleted_rows} older duplicate BGP peer records.")
        # return deleted_rows
    except sqlite3.Error as e:
        logger.error(f"SQLite error during cleanup: {e}")
        # conn.rollback()
        return -1
    
def cleanup_ospf_peer_status(db): #(One-time Run)
    """
    Cleans up the ospf_peer_status table, keeping only the record 
    with the latest last_updated_ts for each unique peer 
    (host_ip, vpn_instance, neighbor_address).
    """
    # cursor = conn.cursor()
    logger.info("Starting ospf peer status cleanup for historical duplicates...")

    # Robust SQL to find the single rowid with the latest last_updated_ts (MAX(last_updated_ts)) 
    # for each unique peer key, and delete all other rows.
    cleanup_sql = '''
        DELETE FROM ospf_state_changes 
        WHERE rowid NOT IN (
            SELECT MIN(rowid) 
            FROM ospf_state_changes 
            GROUP BY hostname, neighbor_address, last_updated_ts, to_state
        );
    '''
    update_sql = '''
        UPDATE ospf_peer_status
        SET 
            state = (
                SELECT to_state 
                FROM ospf_state_changes h
                WHERE h.neighbor_address = ospf_peer_status.neighbor_address
                AND h.hostname = ospf_peer_status.hostname
                ORDER BY last_updated_ts DESC, ROWID DESC LIMIT 1
            ),
            last_updated_ts = (
                SELECT last_updated_ts 
                FROM ospf_state_changes h
                WHERE h.neighbor_address = ospf_peer_status.neighbor_address
                AND h.hostname = ospf_peer_status.hostname
                ORDER BY last_updated_ts DESC, ROWID DESC LIMIT 1
            )
        WHERE EXISTS (
            SELECT 1 
            FROM ospf_state_changes h 
            WHERE h.neighbor_address = ospf_peer_status.neighbor_address 
            AND h.hostname = ospf_peer_status.hostname
            -- CRITICAL: Only update if the history record is newer than current DB
            AND h.last_updated_ts >= ospf_peer_status.last_updated_ts
        );
        '''
    
    try:
        # cursor.execute(cleanup_sql)
        # cursor.execute(update_sql)
        # deleted_rows = cursor.rowcount
        # conn.commit()
        db.execute_write(cleanup_sql, debug=True)
        db.execute_write(update_sql, debug=True)
        # logger.info(f"Cleanup complete. Deleted {deleted_rows} older duplicate BGP peer records.")
        # return deleted_rows
    except sqlite3.Error as e:
        logger.error(f"SQLite error during cleanup: {e}")
        # conn.rollback()
        return -1


@lru_cache(maxsize=128)    # Cache results of this function to speed up repeated calls with the same input
def parse_last_updated_ts(raw_ts_str, log_year):
    """
    Standardizes all timestamps to the 'T' ISO format: 2026-04-11T02:15:16
    This ensures lexicographical string comparison works perfectly in SQLite.
    """
    if not raw_ts_str or str(raw_ts_str).lower() == 'none':
        return "1970-01-01T00:00:00"

    # Normalize: Convert spaces to 'T' and clean string
    clean_ts = str(raw_ts_str).strip().replace(' ', 'T')
    # Remove any existing milliseconds if present in the source
    if '.' in clean_ts:
        clean_ts = clean_ts.split('.')[0]
    if ':' in clean_ts and clean_ts.count(':') > 2: # Handle HH:MM:SS:mmm
        clean_ts = clean_ts.rsplit(':', 1)[0]

    try:
        # 1. Already Year-First: 2026-04-11T02:15:16 or 2026-01-25 09:17:11
        if clean_ts.startswith('20'):
            # Re-verify format via datetime to ensure it's valid
            dt_obj = datetime.strptime(clean_ts, "%Y-%m-%dT%H:%M:%S")
            return dt_obj.strftime("%Y-%m-%dT%H:%M:%S")

        # 2. HPE/Log Format: Jan 21 23.16.23:439 2026
        if re.search(r'\d{4}$', clean_ts):
            # Convert dots/colons to standard for parsing
            temp = clean_ts.replace('.', ':').replace('T', ' ')
            dt_obj = datetime.strptime(temp, "%b %d %H:%M:%S:%f %Y")
            return dt_obj.strftime("%Y-%m-%dT%H:%M:%S")

        # 3. Cisco/HPE Syslog Format: Apr 10 22:49:18
        # We replace the 'T' back to space temporarily for strptime
        dt_obj = datetime.strptime(f"{clean_ts.replace('T', ' ')} {log_year}", "%b %d %H:%M:%S %Y")
        return dt_obj.strftime("%Y-%m-%dT%H:%M:%S")

    except Exception:
        # If specific parsing fails, try to return a normalized string at least
        return clean_ts if len(clean_ts) >= 19 else "1970-01-01T00:00:00"

def parse_routing_info(temp_file_path, lines, vendor, json_file=None):
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
    cisco_vpn_name = "Global"
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

        try:
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
                                "neighbor_address": parts[0],
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

                            # Use re.IGNORECASE and allow for flexible whitespace (\s+)
                            router_id_match = re.search(r"Router\s*ID:\s*([\d\.]+)", next_line, re.I)
                            local_match = re.search(r"Local\s*Address:\s*([\d\.]+)", next_line, re.I)
                            remote_match = re.search(r"(?:Remote|Neighbor)\s*Address:\s*([\d\.]+)", next_line, re.I)
                            time_match = re.search(r"Time:\s*(.*)", next_line, re.I)
                            reason_match = re.search(r"Reason:\s*(.*)", next_line, re.I)

                            # Capture the values safely
                            last_down_event["router_id"] = router_id_match.group(1) if router_id_match else None
                            last_down_event["last_local"] = local_match.group(1) if local_match else None
                            last_down_event["last_remote"] = remote_match.group(1) if remote_match else None
                            last_down_event["last_time"] = time_match.group(1).strip() if time_match else None
                            last_down_event["last_reason"] = reason_match.group(1).strip() if reason_match else None

                            j += 1

                        if last_down_event.get("last_remote"):
                            current_ospf_process["lastevents"][last_down_event["last_remote"]] = last_down_event.copy()
                            logger.debug(f"Set last down event for remote {last_down_event['last_remote']} in process {current_process}: {last_down_event}")
                        else:
                            logger.info(f"No valid last_remote found for last down event in process {current_process} : {temp_file_path} {line}")

            if vendor in ('cisco','arista'):

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
                        neighbor_address = bgp_ipv4_match.group(1)
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
                        neighbor_address = bgp_vpnv4_match.group(1)
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
                        logger.debug(temp_file_path,routing_info,neighbor_address)
                        continue

                    if line.startswith("BGP version"):
                    # elif line.startswith("BGP version") and bgp_peer:
                        #   BGP version 4, remote router ID 10.26.101.1
                        remote_router_id_match = re.search(r"remote router ID (\d+\.\d+\.\d+\.\d+)", line)
                        remote_router_id = remote_router_id_match.group(1)
                        logger.debug(temp_file_path, routing_info, remote_router_id)

                    # Extract state and uptime
                    elif line.startswith("BGP state"):
                    # The (?:, (up|down) for (.*))? makes the comma and everything after it optional
                        state_match = re.search(r"BGP state (?:is|=) (\w+)(?:, (up|down) for (.*))?", line, re.IGNORECASE)
                        
                        if state_match:
                            current_neighbor = {
                                "neighbor_address": neighbor_address, 
                                "remote_router_id": remote_router_id, 
                                "remote_as": remote_as, 
                                "peer_uptime": state_match.group(3) if state_match.group(3) else "N/A", 
                                "peer_status": state_match.group(1)
                            }
                        else:
                            # This handles the 'BGP state = Idle' case specifically if the regex above still misses it
                            status_only = re.search(r"BGP state (?:is|=) (\w+)", line, re.IGNORECASE)
                            current_neighbor = {
                                "neighbor_address": neighbor_address,
                                "peer_status": status_only.group(1) if status_only else "Unknown",
                                "peer_uptime": "N/A"
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

        except AttributeError as e:
            # This catches the 'NoneType' has no attribute 'group' specifically
            print(f"Regex match failed on line: '{line}' in file: {temp_file_path} for vendor: {vendor}. Error: {e}")
            raise Exception(f"Protocol: {vendor} | Failed on Line: '{line}' | Error: {e}")                                       

    # if json_file and isinstance(json_file, (str, os.PathLike)):
    #     try:
    #         with open(json_file, 'w') as f:
    #             json.dump(routing_info, f, indent=4)
    #     except Exception as e:
    #         logger.error(f"Failed to write JSON file {json_file}: {e}")

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

def sync_syslog_to_routing_db(orion_db_path, core_db_path):
    # 1. Connect to both databases
    orion_db = DatabaseManager(orion_db_path)
    core_db = DatabaseManager(core_db_path)

    # 2. Fetch recent Syslogs (e.g., last 200 or by a specific ID)
    logs = orion_db.execute_query("SELECT * FROM [Orion.SyslogTracking] ORDER BY LogEntryID DESC")

    # Patterns for HPE/Cisco Syslogs
    RE_BGP = re.compile(
    r"BGP.*?(?:BGP\.(?P<vpn>\S+):\s+)?(?P<nbr>[\d\.]+)\s+.*?from\s+(?P<from>\w+)\s+to\s+(?P<to>\w+)", 
    re.I
    )
    # RE_BGP = re.compile(r"BGP.+(?:Neighbor|peer)\s+([\d\.]+).+changed\s+from\s+(\w+)\s+to\s+(\w+)", re.I)
    RE_OSPF = re.compile(r"OSPF\s+(\d+)\s+Neighbor\s+([\d\.]+)\((.+)\)\s+changed\s+from\s+(\w+)\s+to\s+(\w+)", re.I)


    for log in logs:
        msg = log['Message']
        node_name = log['NodeName']
        host_ip = log['IPAddress']
        # Standardize DateTime to ISO "T" format: 2026-04-11T02:15:16
        raw_dt = log['DateTime'].replace('Z', '').split('.')[0]
        # raw_dt = utc_convert(log['DateTime'])
        syslog_ts = raw_dt.replace(' ', 'T')

        # --- PROCESS BGP ---
        bgp_match = RE_BGP.search(msg)
        if bgp_match:
            # neighbor, from_st, to_st = bgp_match.group(1), bgp_match.group(2), bgp_match.group(3)
            neighbor = bgp_match.group('nbr')
            from_st  = bgp_match.group('from').upper()
            to_st    = bgp_match.group('to').upper()
            vpn      = bgp_match.group('vpn') or 'Global'            
            # Step A: Update Status Table (Latest Wins)
            core_db.execute_write('''
                INSERT INTO bgp_peer_status (hostname, host_ip, neighbor_address, state, last_updated_ts, vpn_instance, log_file)
                VALUES (:hostname, :host_ip, :neighbor_address, :state, :last_updated_ts, :vpn_instance, :log_file)
                ON CONFLICT(host_ip, vpn_instance, neighbor_address) DO UPDATE SET
                    state = excluded.state,
                    last_updated_ts = excluded.last_updated_ts,
                    log_file = 'SyslogDB'
                WHERE excluded.last_updated_ts > bgp_peer_status.last_updated_ts
            ''', {
                'hostname': node_name,
                'host_ip': host_ip,
                'neighbor_address': neighbor,
                'state': to_st,
                'last_updated_ts': syslog_ts,
                'vpn_instance': vpn,
                'log_file': 'SyslogDB'
            })

            # Step B: Record in History  
            core_db.execute_write('''
                INSERT INTO bgp_state_changes (hostname, host_ip, vpn_instance, neighbor_address, from_state, to_state, last_updated_ts, message, log_file)
                VALUES (:hostname, :host_ip, :vpn_instance, :neighbor_address, :from_state, :to_state, :last_updated_ts, :message, :log_file)
                ON CONFLICT(host_ip, vpn_instance, neighbor_address, last_updated_ts) DO UPDATE SET
                    from_state = excluded.from_state,
                    to_state = excluded.to_state
                WHERE excluded.last_updated_ts >= bgp_state_changes.last_updated_ts                               
            ''', {
                'hostname': node_name,
                'host_ip': host_ip,
                'vpn_instance': vpn,
                'neighbor_address': neighbor,
                'from_state': from_st,
                'to_state': to_st,
                'last_updated_ts': syslog_ts,
                'message': msg,
                'log_file': 'SyslogDB'
            })

        # --- PROCESS OSPF ---
        ospf_match = RE_OSPF.search(msg)
        if ospf_match:
            process, neighbor, interface, from_st, to_st = ospf_match.groups()
            
            # Step A: Update Status Table
            core_db.execute_write('''
                INSERT INTO ospf_peer_status (hostname, host_ip, neighbor_address, state, last_updated_ts, process, interface, log_file)
                VALUES (:hostname, :host_ip, :neighbor_address, :state, :last_updated_ts, :process, :interface, :log_file)
                ON CONFLICT(host_ip, process, neighbor_address) DO UPDATE SET
                    state = excluded.state,
                    last_updated_ts = excluded.last_updated_ts
                WHERE excluded.last_updated_ts > ospf_peer_status.last_updated_ts
            ''', {
                'hostname': node_name,
                'host_ip': host_ip,
                'neighbor_address': neighbor,
                'state': to_st,
                'last_updated_ts': syslog_ts,
                'process': process,
                'interface': interface,
                'log_file': 'SyslogDB'
            })

            # Step B: Record in History
            core_db.execute_write('''
                INSERT INTO ospf_state_changes (
                    hostname, host_ip, process, neighbor_address, 
                    interface, from_state, to_state, last_updated_ts, message, log_file
                )
                VALUES (:hostname, :host_ip, :process, :neighbor_address, :interface, :from_state, :to_state, :last_updated_ts, :message, :log_file)
                ON CONFLICT(host_ip, process, neighbor_address, last_updated_ts) -- MUST MATCH INDEX
                DO UPDATE SET to_state = excluded.to_state
            ''', {
                'hostname': node_name,
                'host_ip': host_ip,
                'process': process,
                'neighbor_address': neighbor,
                'interface': interface,
                'from_state': from_st,
                'to_state': to_st,
                'last_updated_ts': syslog_ts,
                'message': msg,
                'log_file': 'SyslogDB'
            })

def process_log_file(db, log_file_path, file_id, log_dir_base):
    """Process a single log file and insert into database."""
    # cursor = conn.cursor()
    filename_only = os.path.basename(log_file_path)
    relative_log_path = os.path.relpath(log_file_path, log_dir_base).replace('\\', '/')
    logger.info(f"Processing file: {log_file_path}")
    hostname,host_ip, vendor = (None,  None, None)
    vpn_instance = "Global"  # Initialize with a default value
    process_info = { "bgp_changes_list": [], "bgp_status_list": [], "ospf_changes_list": [],  "ospf_status_list": [], "bgp_data": [], "ospf_data": [] }

    # Use log file last_updated_ts as last_updated and snapshot_id
    try:
        file_ts_str = '_'.join(filename_only.split('_')[0:2])
        file_dt = datetime.strptime(file_ts_str, '%Y%m%d_%H%M%S')
        last_updated_ts = file_dt.isoformat()
        last_snapshot_id = file_ts_str
    except (ValueError, IndexError):
        last_updated_ts = datetime.now().isoformat()
        last_snapshot_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        logger.warning(f"Could not parse last_updated_ts from filename '{filename_only}', using current time")

    log_year = filename_only.split('_')[0][:4]
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_content = f.read()
            # Remove "---- More ----" and trailing whitespace
            content = re.sub(r'-+ More -+\s*', '', raw_content)
            # Remove empty lines
            lines = [line for line in content.splitlines() if line.strip()]
            # lines = content.splitlines()  # Split content into lines
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
        routing_info = parse_routing_info(log_file_path, lines, vendor, None)  # Pass None for json_file to avoid writing
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error parse_routing from '{log_file_path}':\n{error_details}")
        return False
    
    print(f"Parsed routing info for {log_file_path}: OSPF {len(routing_info['OSPF'])} processes, BGP {len(routing_info['BGP'])} entries", routing_info['BGP'])
    
    # print(f"Parsed routing info for {log_file_path}: BGP {routing_info['BGP']}")
    if not hostname: hostname = routing_info.get("hostname", None)
    
    if not host_ip: host_ip = routing_info.get("host_ip", None)

    # --- Historical Log Parsing ---
    bgp_changes_list = []
    bgp_status_list = []
    ospf_changes_list = []
    ospf_status_list = []    
    execute_list = []
    hpe_bgp_log_regex = re.compile(r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?BGP/5/BGP_STATE_CHANGED:(?: BGP\.([^:]*?):)?\s+([\d\.]+) \s+state has changed from ([\w\/]+) to ([\w\/]+)")
    hpe_ospf_log_regex = re.compile(
        r"%(\w{3}\s+\d+\s+[\d:]+:\d{3}).*?OSPF/5/OSPF_NBR_CHG:.*?OSPF\s+(?P<proc>\d+).*?Neighbor\s+(?P<nbr>[\d\.]+)\((?P<iface>[\w\-\/]+)\)\s+changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)"
    )    
    hpe_ospf_last_down_regex = re.compile(
        r"%(\w{3}\s+\d+\s+[\d:]+:\d{3}).*?OSPF/6/OSPF_LAST_NBR_DOWN: OSPF (?P<proc>\d+) Last neighbor down event: Router ID: (?P<rid>[\d\.]+) Local address: (?P<loc>[\d\.]+) Remote address: (?P<rem>[\d\.]+) Reason: (?P<reason>[^.]+)"
    )
    arista_ospf_log_regex = mainconfig.OSPF_ADJ_SPECIAL_RE
    # cisco_bgp_adjchg_regex = mainconfig.CISCO_BGP_ADJCHG

    if vendor == 'hpe':

        for match in hpe_bgp_log_regex.finditer(content):
            message = match.group(0)  # Capture the entire log line
            vpn = match.group(2).strip() if match.group(2) else 'Global'
            neighbor = match.group(3)
            from_state = match.group(4)
            to_state = match.group(5)
            last_updated_ts = parse_last_updated_ts(match.group(1), log_year)

            bgp_changes_list.append({
                'hostname': hostname,
                'host_ip': host_ip,
                'vpn_instance': vpn,
                'neighbor_address': neighbor,
                'from_state': from_state,
                'to_state': to_state,
                'last_updated_ts': last_updated_ts,
                'log_file': filename_only,
                'message': message
            })

                # 3. Update the main dashboard table ONLY if this log is the newest truth
            res = db.execute_query('''
                SELECT MAX(last_updated_ts) as max_ts FROM bgp_peer_status
                WHERE host_ip = :host_ip AND neighbor_address = :neighbor_address
            ''', {
                'host_ip': host_ip,
                'neighbor_address': neighbor
            })
            latest_ts_in_db = res[0]['max_ts'] if res and res[0] else ""

            if not latest_ts_in_db or last_updated_ts >= latest_ts_in_db:
                bgp_status_list.append({
                    'hostname': hostname,
                    'host_ip': host_ip,
                    'vpn_instance': vpn,
                    'neighbor_address': neighbor,
                    'state': to_state,
                    'last_updated_ts': last_updated_ts,
                    'log_file': filename_only
                })

        for match in hpe_ospf_log_regex.finditer(content):
            message = match.group(0)  # Capture the entire log line
            g = match.groupdict()
            last_updated_ts = parse_last_updated_ts(match.group(1), log_year)
            ospf_changes_list.append({
                'hostname': hostname,
                'host_ip': host_ip,
                'process': g['proc'],
                'neighbor_address': g['nbr'],
                'interface': g['iface'],
                'from_state': g['old'],
                'to_state': g['new'],
                'last_updated_ts': last_updated_ts,
                'log_file': filename_only,
                'message': message
            })

        for match in hpe_ospf_last_down_regex.finditer(content):
            g = match.groupdict()
            ts = parse_last_updated_ts(match.group(1), log_year)
            
            # Corrected Update: Use the groups captured by THIS regex
            ospf_status_list.append({
                    'last_down_time': ts,
                    'last_routerid': g['rid'],
                    'last_local': g['loc'],
                    'last_remote': g['rem'],
                    'last_reason': g['reason'].strip(),
                    'hostname': hostname,
                    'process': g['proc'],
                    'neighbor_address': g['rem']
                })

    elif vendor in ('cisco', 'arista'):
        
        for match in mainconfig.CISCO_BGP_ADJ_SPECIFIC_RE.finditer(content):
            message = match.group(0)  # Capture the entire log line
            g = match.groupdict()
            neighbor = g['neighbor']
            from_state = g['mode']
            to_state = g['action']
            last_updated_ts = parse_last_updated_ts(g['timestamp'], log_year)

            bgp_changes_list.append({
                'hostname': hostname,
                'host_ip': host_ip,
                'neighbor_address': neighbor,
                'from_state': from_state,
                'to_state': to_state,
                'last_updated_ts': last_updated_ts,
                'log_file': filename_only,
                'message': message
            })

                # 3. Update the main dashboard table ONLY if this log is the newest truth
            res = db.execute_query('''
                SELECT MAX(last_updated_ts) as max_ts FROM bgp_peer_status
                WHERE host_ip = :host_ip AND neighbor_address = :neighbor_address
            ''', {
                'host_ip': host_ip,
                'neighbor_address': neighbor
            })
            latest_ts_in_db = res[0]['max_ts'] if res and res[0] else ""

            if not latest_ts_in_db or last_updated_ts >= latest_ts_in_db:
                bgp_status_list.append({
                    'hostname': hostname,
                    'host_ip': host_ip,
                    'neighbor_address': neighbor,
                    'state': to_state,
                    'last_updated_ts': last_updated_ts,
                    'log_file': filename_only
                })

        for match in arista_ospf_log_regex.finditer(content):
            # 2. SAFETY CHECK: Only proceed if match is NOT None
            if match:
                try:
                    message = match.group(0)  # Capture the entire log line
                    g = match.groupdict()
                    last_updated_ts = parse_last_updated_ts(g['timestamp'], log_year)
                    if "ESTABLISHED" in match.group('action').upper():
                        g['new_state'] = "established"
                    elif "DROPPED" in match.group('action').upper():
                        g['new_state'] = "DOWN"
                    else:
                        g['new_state'] = "UNKNOWN"

                    ospf_changes_list.append({
                            'hostname': hostname,
                            'host_ip': host_ip,
                            'process': g['process'],
                            'neighbor_address': g['neighbor'],
                            'interface': g['iface'],
                            'from_state': g['old_state'],
                            'to_state': g['new_state'],
                            'last_updated_ts': last_updated_ts,
                            'log_file': filename_only,
                            'message': message
                        }
                    )
                except Exception as e:
                    logger.error(f"Error inserting OSPF row from {filename_only}: {message}, {e}")

    # Process BGP peers
    bgp_data = []
    if isinstance(routing_info.get("BGP"), list):
        for bgp_instance in routing_info["BGP"]:
            vpn_instance = bgp_instance.get("VPN_instance", "Global")
            local_router_id = bgp_instance.get("local_router_id")
            local_as_number = bgp_instance.get("local_as_number")            
            for peer in bgp_instance.get("Peer", []):
                # Create a dictionary for each peer
                peer_dict = {
                    "host": hostname,
                    "ip": host_ip,
                    "vpn": vpn_instance,
                    "l_rid": local_router_id,
                    "l_as": local_as_number,
                    "n_addr": peer.get("neighbor_address"),
                    "r_rid": peer.get("remote_router_id"),
                    "r_as": peer.get("remote_as"),
                    "uptime": peer.get("peer_uptime"),
                    "state": peer.get("peer_status"),
                    "ts": last_updated_ts,
                    "snap_id": last_snapshot_id,
                    "file": filename_only
                }
                bgp_data.append(peer_dict)

    ospf_data = []   
    if isinstance(routing_info.get("OSPF"), list):
        for ospf_process in routing_info.get("OSPF", []):
            process = ospf_process.get("process", "0")
            process_routerid = ospf_process.get("process_routerid")
            vrf = ospf_process.get("vrf")
            last_events = ospf_process.get("lastevents", {})

            for neighbor in ospf_process.get("neighbors", []):
                address = neighbor.get("neighbor_address")
                event_data = last_events.get(address) if address else None
                
                peer_entry = {
                    "hn": hostname,
                    "hip": host_ip,
                    "proc": process,
                    "prid": process_routerid,
                    "vrf": vrf,
                    "area": neighbor.get("Area"),
                    "iface": neighbor.get("Interface"),
                    "nrid": neighbor.get("neighbor_routerid"),
                    "naddr": address,
                    "state": neighbor.get("state"),
                    "mode": neighbor.get("mode"),
                    "v_uptime": neighbor.get("uptime"),
                    "s_count": neighbor.get("state_count"),
                    "ldt": event_data.get("last_time") if event_data else None,
                    "lrid": event_data.get("router_id") if event_data else None,
                    "lloc": event_data.get("last_local") if event_data else None,
                    "lrem": event_data.get("last_remote") if event_data else None,
                    "lreas": event_data.get("last_reason") if event_data else None,
                    "ts": last_updated_ts,
                    "snap": last_snapshot_id,
                    "file": filename_only
                }
                ospf_data.append(peer_entry)


    if bgp_changes_list:
        process_info["bgp_changes_list"] = bgp_changes_list
    if bgp_status_list:
        process_info["bgp_status_list"] = bgp_status_list
    if ospf_changes_list:
        process_info["ospf_changes_list"] = ospf_changes_list   
    if ospf_status_list:
        process_info["ospf_status_list"] = ospf_status_list
    if ospf_data:
        process_info["ospf_data"] = ospf_data
    if bgp_data:
        process_info["bgp_data"] = bgp_data    

    # print(f"Finished processing {log_file_path}: {len(bgp_changes_list)} BGP changes, {len(bgp_status_list)} BGP status updates, {len(ospf_changes_list)} OSPF changes, {len(ospf_status_list)} OSPF status updates, {len(bgp_data)} BGP peers, {len(ospf_data)} OSPF peers")
    return process_info

def process_db_updates(db, db_info):

    bgp_changes_stmt =   '''
        INSERT OR IGNORE INTO bgp_state_changes 
        (hostname, host_ip, vpn_instance, neighbor_address, from_state, to_state, last_updated_ts, log_file, message) 
        VALUES ( :hostname, :host_ip, :vpn_instance, :neighbor_address, :from_state, :to_state, :last_updated_ts, :log_file, :message )
        ON CONFLICT(host_ip, vpn_instance, neighbor_address, last_updated_ts) DO UPDATE SET
            from_state = excluded.from_state,
            to_state = excluded.to_state,
            last_updated_ts = excluded.last_updated_ts,
            log_file = excluded.log_file
        WHERE excluded.last_updated_ts >= bgp_state_changes.last_updated_ts
    ''' 
    bgp_status_stmt = '''
        INSERT INTO bgp_peer_status (hostname, host_ip, vpn_instance, neighbor_address, state, last_updated_ts, log_file)
        VALUES (:hostname, :host_ip, :vpn_instance, :neighbor_address, :state, :last_updated_ts, :log_file)
        ON CONFLICT(host_ip, vpn_instance, neighbor_address) DO UPDATE SET
            state = excluded.state,
            last_updated_ts = excluded.last_updated_ts,
            log_file = excluded.log_file
        WHERE excluded.last_updated_ts > bgp_peer_status.last_updated_ts
    '''
    ospf_changes_stmt = '''
        INSERT OR IGNORE INTO ospf_state_changes 
        (hostname, host_ip, process, neighbor_address, interface, from_state, to_state, last_updated_ts, log_file, message) 
        VALUES (:hostname, :host_ip, :process, :neighbor_address, :interface, :from_state, :to_state, :last_updated_ts, :log_file, :message)
    '''
    ospf_status_stmt = '''
        UPDATE ospf_peer_status 
        SET last_down_time = :last_down_time, last_routerid = :last_routerid, last_local = :last_local, last_remote = :last_remote, last_reason = :last_reason
        WHERE hostname = :hostname AND (process = :process OR neighbor_address = :neighbor_address)
    '''
    bgp_upsert_query = '''
        INSERT INTO bgp_peer_status (hostname, host_ip, vpn_instance, local_router_id, local_as_number, neighbor_address, remote_router_id, remote_as, up_down_time, state, last_updated_ts, last_snapshot_id, log_file) 
        VALUES (
            :host, :ip, :vpn, :l_rid, :l_as, :n_addr, 
            :r_rid, :r_as, :uptime, :state, :ts, :snap_id, :file
        )
        ON CONFLICT(host_ip, vpn_instance, neighbor_address) 
        DO UPDATE SET
            state = excluded.state,
            up_down_time = excluded.up_down_time,
            remote_router_id = excluded.remote_router_id,
            remote_as = excluded.remote_as,
            last_updated_ts = excluded.last_updated_ts,
            last_snapshot_id = excluded.last_snapshot_id,
            log_file = excluded.log_file
        WHERE excluded.last_updated_ts > bgp_peer_status.last_updated_ts
    '''
    ospf_upsert_query = '''
        INSERT INTO ospf_peer_status (
            hostname, host_ip, process, process_routerid, vrf, area, interface, 
            neighbor_routerid, neighbor_address, state, mode, verbose_uptime, 
            state_count, last_down_time, last_routerid, last_local, 
            last_remote, last_reason, last_updated_ts, last_snapshot_id, log_file
        ) 
        VALUES (
            :hn, :hip, :proc, :prid, :vrf, :area, :iface, 
            :nrid, :naddr, :state, :mode, :v_uptime, 
            :s_count, :ldt, :lrid, :lloc, 
            :lrem, :lreas, :ts, :snap, :file
        )
        ON CONFLICT(host_ip, process, neighbor_address) 
        DO UPDATE SET
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
            log_file = excluded.log_file,
            hostname = CASE WHEN excluded.hostname IS NOT NULL AND excluded.hostname != '' THEN excluded.hostname ELSE hostname END,
            vrf = CASE WHEN excluded.vrf IS NOT NULL AND excluded.vrf != '' THEN excluded.vrf ELSE vrf END,
            last_down_time = COALESCE(excluded.last_down_time, last_down_time),
            last_routerid = COALESCE(excluded.last_routerid, last_routerid),
            last_local = COALESCE(excluded.last_local, last_local),
            last_remote = COALESCE(excluded.last_remote, last_remote),
            last_reason = COALESCE(excluded.last_reason, last_reason)
        WHERE excluded.last_updated_ts >= ospf_peer_status.last_updated_ts
    '''        

    if db_info.get("filename_list"):
        # Mark the file as processed in the database
        filename_dicts = [{"filename": f} for f in db_info["filename_list"]]
        db.execute_many(
            "INSERT OR IGNORE INTO processed_files (filename) VALUES (:filename)", 
            filename_dicts
        )

    """Execute the database updates for BGP and OSPF based on the process_info."""
    # 1. Apply log-based status updates first (less detailed)
    if db_info.get("all_bgp_data"):
        db.execute_many(bgp_upsert_query, db_info["all_bgp_data"])

    if db_info.get("all_bgp_status_list"):
        db.execute_many(bgp_status_stmt, db_info["all_bgp_status_list"])
    if db_info.get("all_bgp_changes_list"):
        db.execute_many(bgp_changes_stmt, db_info["all_bgp_changes_list"])

    if db_info.get("all_ospf_changes_list"):
        db.execute_many(ospf_changes_stmt, db_info["all_ospf_changes_list"])
    if db_info.get("all_ospf_status_list"):
        db.execute_many(ospf_status_stmt, db_info["all_ospf_status_list"])
    # 2. Apply snapshot-based updates second (more detailed)
    # This will fill in the missing AS numbers and Router IDs

    if db_info.get("all_ospf_data"):
        db.execute_many(ospf_upsert_query, db_info["all_ospf_data"])

    cleanup_bgp_peer_status(db)  
    cleanup_ospf_peer_status(db) 
    sync_syslog_to_routing_db(mainconfig.DB_ORION_PATH, mainconfig.DB_PATH) 

def main(log_file_path=None, json_file=None):
    """Main entry point: Process all logs in directory (default) or a single file (if provided)."""

    log_directory = mainconfig.CORE_LOGS_DIR_LOCAL
    database_path = mainconfig.DB_PATH
    db = DatabaseManager(database_path)

    if not os.path.exists(mainconfig.DB_PATH):
        logger.info("Database path ", database_path, " not configured. Initializing...")

    db.setup_core_tables()
        
    logger.info("Starting network log analysis...")

    if not os.path.isdir(log_directory):
        logger.error(f"Error: Log directory '{log_directory}' not found.")
        sys.exit(1)  # Or raise an exception if imported

    stmt = "SELECT filename FROM processed_files"
    processed_filenames_db = {row['filename'] for row in db.execute_query(stmt)}
    logging.info(f"Found {len(processed_filenames_db)} files already processed in the database.")

    log_file_regex = re.compile(r"^\d{8}_\d{6}_[\d\.]+_[\w-]+_sa\.txt$")
    files_to_process = []
    
    if log_file_path:  # Single-file mode (when called with a path)
        if not os.path.isfile(log_file_path):
            logger.error(f"Single file not found: {log_file_path}")
            # connection.close()
            return False  # Or raise ValueError
        
        filename_only = os.path.basename(log_file_path)
        if os.path.getsize(log_file_path) == 0:
            logger.warning(f"Skipping empty single file: '{filename_only}'")
            return False
        files_to_process = [log_file_path]
    else:  # Directory mode (all new files)
        all_files_on_disk = [(os.path.join(log_directory, filename), filename) for filename in os.listdir(log_directory) 
                             if os.path.isfile(os.path.join(log_directory, filename)) and log_file_regex.match(filename)]
        for filepath, filename in all_files_on_disk:
            if filename not in processed_filenames_db and os.path.getsize(filepath) > 0:
                files_to_process.append(filepath)

    if not files_to_process:
        logger.warning("No new valid log files found to process. System is doing the cleanup.")
        cleanup_bgp_peer_status(db)  
        cleanup_ospf_peer_status(db) 
        sync_syslog_to_routing_db(mainconfig.DB_ORION_PATH, mainconfig.DB_PATH) 
        exit(0)  # Or return False if imported
    else:
        logger.info(f"Found {len(files_to_process)} new, valid log files to process.")
        files_to_process.sort()

    updates_made = False
    
    pool = Pool(processes=20)  # Adjust the number of processes as needed
    all_results = pool.map(lambda fp: process_log_file(db, fp, None, log_directory), files_to_process)

    db_info = {
        "filename_list": [],
        "all_bgp_changes_list": [],
        "all_bgp_status_list": [],
        "all_ospf_changes_list": [],
        "all_ospf_status_list": [],
        "all_bgp_data": [], 
        "all_ospf_data": []
    }

    for i, res in enumerate(all_results):
        if res:
            db_info["filename_list"].append(os.path.basename(files_to_process[i]))
            db_info["all_bgp_changes_list"].extend(res.get("bgp_changes_list", []))
            db_info["all_bgp_status_list"].extend(res.get("bgp_status_list", []))
            db_info["all_ospf_changes_list"].extend(res.get("ospf_changes_list", []))
            db_info["all_ospf_status_list"].extend(res.get("ospf_status_list", []))
            
            if res.get("bgp_data"):
                db_info["all_bgp_data"].extend(res.get("bgp_data"))
            if res.get("ospf_data"):
                db_info["all_ospf_data"].extend(res.get("ospf_data"))
            updates_made = True
      
    # print(f"Total BGP changes: {len(db_info['all_bgp_changes_list'])}, BGP status updates: {len(db_info['all_bgp_status_list'])}, OSPF changes: {len(db_info['all_ospf_changes_list'])}, OSPF status updates: {len(db_info['all_ospf_status_list'])}, BGP data entries: {len(db_info['all_bgp_data'])}, OSPF data entries: {len(db_info['all_ospf_data'])}")
    process_db_updates(db, db_info)  # This will handle both BGP and OSPF updates and the cleanup/sync

    if json_file and isinstance(json_file, (str, os.PathLike)):
        try:
            with open(json_file, 'w') as f:
                json.dump(db_info, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to write JSON file {json_file}: {e}")

    if not updates_made:
        logger.warning("No successful updates made despite files found.")
        # connection.close()
        return False
    else:
        # connection.close()
        logger.info("Database processing complete.")
        return True
    

# for count the profile : (venv) PS C:\inetpub\fastapi> .\venv\Scripts\python -m cProfile -s tottime .\utils\analysis_sqlite.py | findstr "analysis_sqlite.py log_parser.py mainconfig.py"
if __name__ == "__main__":
    if sys.argv[1:]:  # If args provided (manual file processing)
        success = False
        for arg in sys.argv[1:]:
            if main(arg):
                success = True
        
        # Optionally sync even for manual files, or just exit
        sys.exit(0 if success else 1)
        
    else:  # Directory mode (Automatic scan)
        # 1. Run the main log folder scan
        main_success = main()
        
        # 2. Run the Syslog DB sync
        # We run this regardless, or you can wrap it in 'if main_success:'
        try:
            # sync_syslog_to_routing_db(mainconfig.DB_ORION_PATH, mainconfig.DB_PATH)
            logger.info("Syslog to Routing DB sync completed.")
        except Exception as e:
            logger.error(f"Syslog sync failed: {e}")

        # 3. Exit based on the main process result
        sys.exit(0 if main_success else 1)    
