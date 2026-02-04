# PHSA SOC
# Created by:		Tao Lin
# Created Date:		May, 2025
# Python version:	3.8
#                       version history:
#################################################################################################

import time, sys, os,re, json, copyreg, requests, warnings
from datetime import datetime
from orionsdk import SwisClient
from netmiko import ConnectHandler, SSHDetect
from paramiko.ssh_exception import SSHException 
from netmiko.ssh_exception import  AuthenticationException
from netmiko.ssh_exception import NetMikoTimeoutException
warnings.filterwarnings("ignore", category=DeprecationWarning)

# This finds the absolute path to the 'fastapi' root folder
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import routers.monitor as monitor
import mainconfig as mainconfig
logger = mainconfig.setup_module_logger(__name__)
log_dir = mainconfig.CORE_LOGS_DIR    
curr_dir= os.path.dirname(__file__)
log_dir = os.path.abspath(os.path.join(curr_dir, '..', 'logs'))

def load_json_file(file_path):
    """Load and return JSON data from a file, with error handling."""
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found - {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {file_path}: {e}")
        return None

def read_file(file_path):
    """
    Reads the content of a log file if it exists and is not empty.

    Args:
        log_file_path (str): Path to the log file.

    Returns:
        str: The content of the file.
        None: If the file does not exist or is empty.
    """
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return None

    if os.path.getsize(file_path) == 0:
        print(f"Error: File '{file_path}' is empty.")
        return None

    try:
        with open(file_path, 'r') as file:
            content = file.read()
            return content
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        return None

def utc_convert(timestamp) :
    date=re.split("T",timestamp)[0]
    time_utc=re.search("[0-9][0-9]\:[0-9][0-9]\:[0-9][0-9]",timestamp)[0]
    t=re.split(":",time_utc)
    utc_offset=datetime.utcnow().hour-datetime.now().hour
    if utc_offset < 0 :
        utc_offset=24 + datetime.utcnow().hour-datetime.now().hour
    t[0]=int(t[0])-utc_offset
    i=0 # for time debug
    if t[0] < 0 :
        t[0]=str(t[0] + 24)
        i=1
    elif t[0] < 10 :
        t[0]="0"+str(t[0])
        i=2
    else:
        i=3
        t[0]=str(t[0])
    time_cur=t[0]+":"+t[1]+":"+t[2]    
    return time_cur

def format_time(timestamp):
    """Format the timestamp with UTC offset handling."""
    try:
        time_obj = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S")
        # Adjust for UTC offset
        local_time = time_obj - (datetime.utcnow() - datetime.now())
        return local_time.strftime('%H:%M:%S'), local_time.strftime('%Y-%m-%d')
    except ValueError:
        print(f"Error parsing timestamp: {timestamp}")
        return None, None

    #comparison for the arch file

def udt_update(src_file,data_file):
    file_dir = os.path.split(src_file)[0] 
    file_name= os.path.split(src_file)[1] 
    ip_regex = r'(?:\d{1,3}\.){3}\d{1,3}'

    match = re.match(ip_regex, file_name)
    if match :
        ip = match.group(0)  # Extract the IP address
    else :
        logger.error("no match file found")

    dst_file = f"../../data/{ip}_routing_udt.json"    
    dst_udt = os.path.join(file_dir,dst_file)
    udt_json = data_file
    logger.info(f"src:{src_file} dst: {dst_udt}")

    src_content = json.load(open(src_file,"r"))
    udt_content = json.load(open(udt_json,"r"))

     # Update a specific BGP peer_IP part of the JSON
    try :
        bgp_count = 0
        for bgp_instance in src_content.get("BGP",[]) :
            #logger.info(f"{bgp_instance} ")
            instance = bgp_instance["VPN_instance"]
            for peer in bgp_instance.get("Peer", []):
                peer_ip = peer.get("peer_IP")
                # Search for the matching peer_IP in UDT data
                if peer_ip:
                    bgp_match = next(
                        (entry for entry in udt_content if entry.get("IPAddress") == peer_ip), None
                    )
                    if bgp_match:
                        bgp_count += 1
                        # Update peer with UDT information
                        logger.info(f"Found BGP {instance} peer {peer_ip} ")
                        peer["peer_NodeName"] = bgp_match.get("NodeName", "")
                        peer["peer_PortNumber"] = bgp_match.get("PortNumber", "")
                        peer["peer_PortName"] = bgp_match.get("PortName", "")
                    else:
                        peer["peer_NodeName"] = "na"
    except Exception as e:
        logger.info(f"No BGP  info found.")

     # Update a specific OSPF peer_IP part of the JSON
    try:
        ospf_count = 0
        for ospf_process in src_content.get("OSPF",[]) :
            process = ospf_process["process"]
            for area in ospf_process.get("area_info", []):
                for neighbor in area.get("neighbor_info", []):
                    # Search for the matching neighbor_address in UDT data
                    address = neighbor.get("Address")
                    address_match = next(
                        (entry for entry in udt_content if entry.get("IPAddress") == address), None
                    )
                    if address_match:
                        ospf_count += 1
                        # Update peer with UDT ospf information
                        logger.info(f"Found OSPF process {process} neighbor address {address} ")
                        neighbor["Address NodeName"] = address_match.get("NodeName", "")
                    
                    # Search for the matching neighbor router in UDT data
                    router = neighbor.get("Router IP")
                    router_match = next(
                        (entry for entry in udt_content if entry.get("IPAddress") == router), None
                    )
                    if router_match:
                        # Update peer with UDT ospf information
                        logger.info(f"Found OSPF neighbor RouterIP {router} and update uer endpoint device info")
                        neighbor["Router NodeName"] = router_match.get("NodeName", "")
    except Exception as e:
        logger.error(f"No OSPF info found.")

    # Save to a new JSON file
    with open(dst_udt, "w") as file:
        json.dump(src_content, file, indent=4)

    logger.info(f"Updated {dst_udt}, BGP matched: {bgp_count}, OSPF matched: {ospf_count}")

def format_size(size_bytes):
    """Converts bytes to a human-readable string (KB, MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024**2):.2f} MB"
    
# 20251215 update for fastapi_mymodule : send_command, core_check, log_check, log_summary, compare_peers
def compare_peers(file1_path, file2_path):
    print(f"Starting compare_peers for {file1_path} and {file2_path}")

    """
    Compare BGP and OSPF peer information between two files.

    Args:
        file1_path (str): Path to the first file.
        file2_path (str): Path to the second file.

    Returns:
        list: A list containing the comparison results and differences.
    """
    try:
        # Open and read contents of both files
        with open(file1_path, 'r') as file1, open(file2_path, 'r') as file2:
            content1 = file1.readlines()
            content2 = file2.readlines()

        # Regex patterns for BGP and OSPF peers
        bgp_peer_regex = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s.*(Established|Connect)'
        ospf_peer_regex = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s.*(Full|2-Way|Down|Init|Attempt|Exstart|Exchange|Loading)'

        # Extract BGP and OSPF peers from both files
        bgp_peers1 = set(re.findall(bgp_peer_regex, ''.join(content1)))
        bgp_peers2 = set(re.findall(bgp_peer_regex, ''.join(content2)))

        ospf_peers1 = set(re.findall(ospf_peer_regex, ''.join(content1)))
        ospf_peers2 = set(re.findall(ospf_peer_regex, ''.join(content2)))

        # Calculate differences
        bgp_diff_file1_missing = bgp_peers2 - bgp_peers1  # Peers in file2 but not in file1
        bgp_diff_file2_missing = bgp_peers1 - bgp_peers2  # Peers in file1 but not in file2

        ospf_diff_file1_missing = ospf_peers2 - ospf_peers1  # Peers in file2 but not in file1
        ospf_diff_file2_missing = ospf_peers1 - ospf_peers2  # Peers in file1 but not in file2

        # Prepare results
        result = {
            "File1 Summary": f"{file1_path} -- BGP Peers: {len(bgp_peers1)}, OSPF Peers: {len(ospf_peers1)}",
            "File2 Summary": f"{file2_path} -- BGP Peers: {len(bgp_peers2)}, OSPF Peers: {len(ospf_peers2)}",
            "BGP Differences": {
                "In File1 Only": list(bgp_diff_file2_missing),
                "In File2 Only": list(bgp_diff_file1_missing),
            },
            "OSPF Differences": {
                "In File1 Only": list(ospf_diff_file2_missing),
                "In File2 Only": list(ospf_diff_file1_missing),
            },
        }

        # print(result)
        # Log and return results
        log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        curr_dir = os.path.dirname(__file__)
        log_dir = os.path.abspath(os.path.join(curr_dir, '..', 'logs/core_logs'))
        compare_log_path = os.path.join(log_dir, "arch", "compare_log.txt")

        with open(compare_log_path, "a") as logfile:
            logfile.write(f"\nComparing time: {log_time}\n")
            logfile.write(f"{result['File1 Summary']}\n")
            logfile.write(f"{result['File2 Summary']}\n")
            logfile.write(f"Differences:\n{json.dumps(result, indent=4)}\n")
        print(result["BGP Differences"],result["OSPF Differences"])
        return result

    except FileNotFoundError as e:
        print(f"Error: One or both files not found: {e}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def send_command(device_setting,cmds,output, logger=None):
    logger.info(f"Starting send_command for IP: {device_setting['ip']} {cmds}")

    output = ""

    try:
        device = ConnectHandler(**device_setting)
        prompt = device.find_prompt()
        logger.info("login:",device_setting['ip'], " success")
        start_time = datetime.now()
        output += ">>>>>>>> Start Time: {start_time}\n"

        with device:
            for cmd in cmds:
                # logger.info(f"Executing command: {cmd}")
                device.write_channel(f"{cmd}\n")
                while True:
                    try:
                        page = device.read_until_pattern(f"More|{prompt}")
                        output += page
                        if "More" in page:
                            device.write_channel(" ")
                        elif prompt in output:
                            break
                    except (AuthenticationException, SSHException) as error:
                        logger.error(f"Connection Error {device_setting['ip']} : {error}")
                        break
        device.disconnect()
        # # Write to log file : log was saved in the device_setting['session_log']
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    
    return output

def core_check(log_dir, fname, ip, nodeid, logger=None):
    html_output = []
    fname = os.path.split(fname)[1]
    icon_tag = ""
    icon_green="/icons/Event-5.gif"
    icon_red="/icons/Event-10.gif"
    icon_plus="/icons/Event-16.gif"

    log_dir = mainconfig.CORE_LOGS_DIR
    log_file_path = os.path.join(log_dir, fname)
    ip_pattern = "(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
    ip_match = re.search(ip_pattern, fname)
    ip = ip_match[0] if ip_match else "unknown"

    def html_print(*args):
        html_output.append(' '.join(str(a) for a in args))

    # Check log file existence
    if not os.path.exists(log_file_path):
        logger.error(f"No file exists: {ip}, File: {log_file_path}")
        return "<p>Error: Log file does not exist.</p>"
    elif os.path.getsize(log_file_path) == 0:
        return "<p>Error: Log file is empty.</p>"
    # else:
    #     logger.info(f"Starting core_check for IP: {ip}, File: {log_file_path}")

    # Process log file
    result_log = log_check(log_file_path, logger=None, label="Current Log file: ")
    if result_log:
        # print(f"Log check result: {result_log}")
        try:
            # Compose HTML output
            hostname = result_log.get("hostname",[])  # Extract the hostname
            current_os = result_log.get("current_os","unknown")
            label = result_log.get("label", "Current Log file: ")
            log_content = result_log.get("log_content", [])
            summary_content = result_log.get("summary_content", "")
            ipv4_peers = result_log.get("ipv4_peers", [])
            count_ipv4 = result_log.get("count_ipv4", 0)
            vpnv4_peers = result_log.get("vpnv4_peers", [])
            count_vpnv4 = result_log.get("count_vpnv4", 0)
            ospf_peers = result_log.get("ospf_peers", [])
            count_ospf = result_log.get("count_ospf", 0)

            peers_ospf_problem = []
            peers_bgp_ipv4_problem = []
            peers_bgp_vpnv4_problem = []
            vpnv4_issues_html = ""
            ipv4_issues_html = ""
            ospf_issues_html = ""

            if len(ipv4_peers) == count_ipv4 :
                icon_bgp_ipv4 = icon_green
            else:
                for peer in ipv4_peers:
                    if "Established" not in peer:
                        peers_bgp_ipv4_problem.append(peer)
                    ipv4_issues_html = "<br>".join(peers_bgp_ipv4_problem)
                icon_bgp_ipv4 = icon_red
                # print("BGP problem IPv4 peer:",peers_bgp_ipv4_problem)
            
            if len(vpnv4_peers) == count_vpnv4 :
                icon_bgp_vpnv4 = icon_green
            else:
                # print("vpnv4_peers:",vpnv4_peers)
                for peer in vpnv4_peers:
                    if "Established" not in peer:
                        peers_bgp_vpnv4_problem.append(peer)        
                        ipv4_issues_html = "<br>".join(peers_bgp_vpnv4_problem)                
                icon_bgp_vpnv4 = icon_red
                # print("BGP problem VPNv4 peer:", peers_bgp_vpnv4_problem)

            if len(ospf_peers) == count_ospf:
                icon_ospf = icon_green
            else:
                for peer in ospf_peers:
                    if "Full" not in peer or "FULL" not in peer:
                        peers_ospf_problem.append(peer)
                    ospf_issues_html = "<br>".join(peers_ospf_problem)
                # print("OSPF problem peer:", peers_ospf_problem)
                icon_ospf = icon_red                

            html_output.append(f"""
            <br>
            <table id="{ip}" style="width:100%;">
                <tr>
                    <th style="width:50%;">
                        <div style="display:flex;justify-content: space-around;">
                            <div style="width:60%;margin-left:5px"><b>{hostname}</b></div>
                            <div style="width:20%;margin-left:5px"><a href="https://orion.net.mgmt/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:{nodeid}" target="_blank">Orion</a></div>
                            <div style="margin-left:5px"><a href="/webssh?ip={ip}" target="_blank">webssh</a></div>
                        </div>
                    </th>
                    <th >{label}<a href=\"\\logs\\core_logs\\{fname}\" target=\"_blank\">{fname}</a></th>
                </tr>
            """) 

            if log_content :
                html_output.append(f"""
                    <tr><td colspan="2"><p style="background-color:Orange;">{log_content}</p></td></tr>
                """)
            if summary_content :            
                html_output.append(f"""
                    <tr><td colspan="2"><p>{summary_content}</p></td></tr>
                """) 

            html_output.append(
                "<tr><td ><img src=\"{}\" alt=\"\"/>BGP Global peers:{}, established:{}</td> <td>{}</td></tr>"
                "<tr><td ><img src=\"{}\" alt=\"\"/>BGP VPN peers:{}, established:{}</td>    <td>{}</td></tr>"
                "<tr><td ><img src=\"{}\" alt=\"\"/>OSPF peers:{}, Full:{}</td>              <td>{}</td></tr>"
                "</table>"
            .format(
                icon_bgp_ipv4, len(ipv4_peers), count_ipv4, vpnv4_issues_html,
                icon_bgp_vpnv4, len(vpnv4_peers), count_vpnv4, ipv4_issues_html,
                icon_ospf, len(ospf_peers), count_ospf, ospf_issues_html
            ))  

            # print(current_os, html_output)

        except Exception as e:
            html_print(f"<p>Error in log analysis {log_file_path}: {e}</p>")        


    return "\n".join(html_output)

def log_check(log_file_path, logger=None, label="Log file"):
    log_dir = os.path.dirname(log_file_path)
    fname = os.path.split(log_file_path)[1]  # Get filename from the file path
    print_match = []
    current_section = None
    current_os = None
    hostname = None
    log_content = ""
    ipv4_peers = []
    vpnv4_peers = []
    ospf_peers = []  
    count_ipv4 = 0         # <-- Add this
    count_vpnv4 = 0        # <-- Add this
    count_ospf = 0         # <-- Add this
    log_regex = mainconfig.LOG_REGEX
    hostname_regex = mainconfig.HOSTNAME_REGEX
    ip_pattern = mainconfig.IP_PATTERN
    ip_match = re.search(ip_pattern, fname)
    ip = ip_match[0] if ip_match else "unknown"

    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
        # If still no handlers, add a simple one for console output
        if not logger.handlers:
            logging.basicConfig(level=logging.INFO)

    # Now this line will work even if you pass None
    logger.info(f"starting log_check for IP: {ip} File: {log_file_path}")

    # Check log file existence
    if not os.path.exists(log_file_path):   
        logger.error(f"Error: Log file '{log_file_path}' does not exist.")
        return None
    else:
        logger.info(f"starting log_check for IP: {ip}, File: {log_file_path}")
     
    output_json_path = os.path.join(log_dir, f"{ip}_log_analysis.json")
    if os.path.basename(os.path.dirname(log_file_path)) != "arch" or not os.path.exists(output_json_path):     # for normal log file, save for report every time; or the first time for archived log file
        with open(log_file_path, 'r') as file:
            log_entries = []
            ospf_block = []
            current_entry = None            

            for line in file:
                stripped = line.strip()

                # Extract hostname
                if hostname is None:
                    hostname_match = re.match(hostname_regex, stripped)
                    if hostname_match:
                        hostname = hostname_match.group(2)  # Extract the hostname
                        hostname_prompt = hostname_match[0]
                        if hostname_prompt + 'display' in stripped:
                            current_os = 'hpe'
                        elif hostname_prompt + 'show' in stripped:
                            current_os = 'cisco_ios'
                    else:
                        continue  # Skip lines without a hostname

                # Start the loop from the line where the content is matched
                if 'exit' in stripped:
                    current_section = 'exit'
                    break   # exit the loop
                if hostname_prompt + 'display log' in stripped:
                    current_section = 'log'
                    current_os = 'hpe'
                if hostname_prompt + 'show log ' in stripped:
                    current_section = 'log'
                    current_os = 'cisco_ios'
                    continue

                if hostname_prompt + 'show logging ' in stripped:
                    current_section = 'log'
                    current_os = 'arista_eos'
                    continue

                if current_section == 'log':
                    if current_os == 'hpe':
                        if line.startswith("%"):
                            if current_entry:
                                log_entries.append(current_entry)
                            current_entry = line.rstrip()
                        elif line.startswith(" "):
                            if current_entry is not None:
                                current_entry += "\n" + line.rstrip()
                    else:  # Cisco / Arista
                        if re.match(r"^\d+:", line.strip()) or "%" in line:  # seq: or %
                            if current_entry:
                                log_entries.append(current_entry)
                            current_entry = line.rstrip()
                        elif line.startswith(" "):
                            if current_entry is not None:
                                current_entry += "\n" + line.rstrip()

                # Check for hpe status
                if current_os == 'hpe':  
                    if hostname_prompt+"display bgp peer ipv4" == stripped:
                        current_section = "ipv4"
                        continue
                    elif hostname_prompt+"display bgp peer ipv4 vpn-instance-all" == stripped:
                        current_section = "vpnv4"
                        continue
                    elif hostname_prompt+"display ospf peer" in stripped:
                        current_section = "ospf"
                        continue                           
                    if re.search(ip_pattern, stripped):
                        fields = stripped.split()
                        if current_section == "ipv4" and len(fields) >= 8:
                            ipv4_peers.append(stripped)
                        if current_section == "vpnv4" and len(fields) >= 8:
                            vpnv4_peers.append(stripped)
                        if current_section == "ospf" :
                            ospf_pattern = r'(?:\d{1,3}\.){3}\d{1,3}\s+(?:\d{1,3}\.){3}\d{1,3}'
                            if re.search(ospf_pattern, stripped):
                                ospf_peers.append(stripped)
                
                # Check for cisco_ios status
                if current_os == 'cisco_ios':
                    if "For address family:" in stripped:
                        # Before switching families, save any block currently in progress
                        if 'temp_bgp_block' in locals() and temp_bgp_block:
                            if current_section == "ipv4": ipv4_peers.append("\n".join(temp_bgp_block))
                            if current_section == "vpnv4": vpnv4_peers.append("\n".join(temp_bgp_block))
                        temp_bgp_block = [] # Reset for new family
                        
                        if "IPv4 Unicast" in stripped:
                            current_section = "ipv4"
                        elif "VPNv4 Unicast" in stripped:
                            current_section = "vpnv4"
                        continue

                    # Logic to catch the BGP Neighbor block
                    if "BGP neighbor is" in stripped:
                        if 'temp_bgp_block' in locals() and temp_bgp_block:
                            # Save the previous neighbor's block before starting a new one
                            block_str = "\n".join(temp_bgp_block)
                            if current_section == "ipv4": ipv4_peers.append(block_str)
                            if current_section == "vpnv4": vpnv4_peers.append(block_str)
                        temp_bgp_block = [stripped]
                    elif 'temp_bgp_block' in locals() and temp_bgp_block:
                        # Append the Description, Version, and State lines
                        temp_bgp_block.append(stripped)

                    elif "show ip ospf" in stripped:
                        current_section = "ospf"
                        continue

                    if current_section == "ospf" :
                        if "Neighbor" in stripped and "interface" in stripped:
                            if 'temp_block' in locals() and temp_block:
                                ospf_block.append("\n".join(temp_block))
                            temp_block = [stripped]
                        elif 'temp_block' in locals():
                            temp_block.append(stripped)
                                            
                # Check for arista_eos status
                if current_os == 'arista_eos':
                    if "BGP summary information for VRF default" == stripped:
                        current_section = "ipv4"
                        continue
                    elif "BGP neighbor" in stripped:
                        current_section = "vpnv4"
                        continue
                    elif "show ip ospf" in stripped:
                        current_section = "ospf"
                        continue

                    if current_section == "ipv4" and "BGP state" in stripped:
                        ipv4_peers.append(stripped)

                    if current_section == "vpnv4" and "BGP state" in stripped:
                        vpnv4_peers.append(stripped)

                    if current_section == "ospf" :
                        if "Neighbor" in stripped and "interface" in stripped:
                            if 'temp_block' in locals() and temp_block:
                                ospf_block.append("\n".join(temp_block))
                            temp_block = [stripped]
                        elif 'temp_block' in locals():
                            temp_block.append(stripped)

            # the last log entry
            if current_entry:
                log_entries.append(current_entry)

            if 'temp_bgp_block' in locals() and temp_bgp_block:
                block_str = "\n".join(temp_bgp_block)
                if current_section == "ipv4": ipv4_peers.append(block_str)
                if current_section == "vpnv4": vpnv4_peers.append(block_str)      
            if current_os == 'cisco_ios':
                ipv4_peers =  bgp_summary(current_os, ipv4_peers)
                vpnv4_peers = bgp_summary(current_os, vpnv4_peers)


            # FIX: Catch the final OSPF neighbor block
            if 'temp_block' in locals() and temp_block:
                ospf_block.append("\n".join(temp_block))

            if ospf_block:
                ospf_peers = ospf_summary(ospf_block)
                

        # Now filter by your log_regex
        filtered_entries = [entry for entry in log_entries if re.search(log_regex, entry)]
        if filtered_entries:
            log_content = "<br>".join(filtered_entries)
            print_match.append(
                "<tr><td><p style=\"background-color:Orange;\">{}</p></td></tr>".format(log_content)
            )        

            # summary_content = log_summary("\n".join(filtered_entries))
            summary_content = log_summary("\n".join(filtered_entries), hostname, ip)

        if current_os == 'arista_eos' or current_os == 'cisco_ios':
            count_ipv4 = sum(1 for line in ipv4_peers if not "Idle" in line)
            count_vpnv4 = sum(1 for line in vpnv4_peers if not "Idle" in line)
            count_ospf = sum(1 for line in ospf_peers if "FULL" in line)
        elif current_os == 'hpe':
            count_ipv4 = sum(1 for line in ipv4_peers if "Established" in line)
            count_vpnv4 = sum(1 for line in vpnv4_peers if "Established" in line)
            count_ospf = sum(1 for line in ospf_peers if "Full" in line)

        # Save the log analysis to a JSON file
        try:
            with open(output_json_path, "w") as json_file:
                json.dump({
                    "hostname"      : hostname, 
                    "current_os"    : current_os,
                    "print_match"   : print_match,
                    "ipv4_peers"    : ipv4_peers,
                    "vpnv4_peers"   : vpnv4_peers,
                    "ospf_peers"    : ospf_peers,
                }, json_file, indent=4)
            if logger:
                logger.info(f"Log analysis saved to {output_json_path}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to save log analysis JSON: {e}")
    else:       # for archived log file, read the json file while it exists
        logger.info(f"Found archived json file for IP: {ip}  : {output_json_path}")
        with open(output_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Access fields with defaults
        current_os = data.get("current_os", "unknown")
        ipv4_peers = data.get("ipv4_peers", [])
        vpnv4_peers = data.get("vpnv4_peers", [])
        ospf_peers = data.get("ospf_peers", [])

        # Count based on conditions (modify if needed)
        if current_os == 'arista_eos' or current_os == 'cisco_ios':
            count_ipv4 = sum(1 for line in ipv4_peers if not "Idle" in line)
            count_vpnv4 = sum(1 for line in vpnv4_peers if not "Idle" in line)
            count_ospf = sum(1 for line in ospf_peers if "FULL" in line)
        elif current_os == 'hpe':
            count_ipv4 = sum(1 for line in ipv4_peers if "Established" in line)
            count_vpnv4 = sum(1 for line in vpnv4_peers if "Established" in line)
            count_ospf = sum(1 for line in ospf_peers if "Full" in line)
        
    # print(ipv4_peers, vpnv4_peers, ospf_peers)

    return {
        "label"         : label,
        "current_os"    : current_os,
        "ip"            : ip,
        "hostname"      : hostname,
        "log_content"   : log_content,
        "summary_content": summary_content if 'summary_content' in locals() else "",
        "print_match"   : print_match,
        "ipv4_peers"    : ipv4_peers,
        "count_ipv4"    : count_ipv4,
        "vpnv4_peers"   : vpnv4_peers,
        "count_vpnv4"   : count_vpnv4,
        "ospf_peers"    : ospf_peers,
        "count_ospf"    : count_ospf,
    }

def bgp_summary(current_os, blocks):
    """Converts a multi-line BGP block into a single line summary. cisco_ios

    For address family: IPv4 Unicast
        BGP neighbor is 10.26.101.1,  remote AS 65500, internal link
        Description: to_OldCore2
        BGP version 4, remote router ID 10.26.101.1
        BGP state = Established, up for 6w4d

    For address family: VPNv4 Unicast
        BGP neighbor is 10.73.119.241,  vrf VCHA-TC2,  remote AS 4255000501,  local AS 4255000101, external link
        Description: to_FW-Outside
        BGP version 4, remote router ID 10.73.119.241
        BGP state = Established, up for 6w2d         or     BGP state = Idle, down for never
    """

    """Converts a multi-line BGP block into a single line summary. arista_eos 
    BGP neighbor is 10.26.101.57, remote AS 65500, internal link
    BGP version 4, remote router ID 10.26.101.57, VRF default
    BGP state is Established, up for 278d01h
    BGP session driven failover for IPv4 Unicast is disabled
    BGP session driven failover for IPv6 Unicast is disabled
        Malformed MPBGP routes: 0
    """
    summary_results = []

# Regex to capture the IP, the State (after '='), and the Uptime (after 'for')
    if current_os in ["cisco_ios", "arista_eos"] :
        RE_NEIGHBOR = re.compile(r'BGP neighbor is (?P<ip>[\d.]+)')
        RE_STATE = re.compile(r'BGP state\s*=\s*(?P<state>\w+)')
        RE_UPTIME = re.compile(r'(?:up|down) for\s+(?P<uptime>[\w\d.]+)')
    

    for block in blocks:
        ip_match = RE_NEIGHBOR.search(block)
        state_match = RE_STATE.search(block)
        uptime_match = RE_UPTIME.search(block)

        if ip_match:
            ip = ip_match.group('ip')
            state = state_match.group('state') if state_match else "Down"
            uptime = uptime_match.group('uptime') if uptime_match else "0s"
            
            summary_results.append(f"{ip} {state} {uptime}")
    return summary_results

def ospf_summary(blocks):
    """Converts a multi-line OSPF block into a single line summary. for cisco_ios and arista_eos
    cisco_ios:
    NS-LGH-LGAC-PIMS-C9600-Core2#show ip ospf neighbor detail | include Neighbor|area
    Neighbor 10.28.102.253, interface address 10.28.102.61
        In the area 0 via interface Vlan4060
        Neighbor priority is 0, State is FULL, 6 state changes
        Neighbor is up for 5w2d        
    arista_eos:
    VH-VGH-3730-7508R-Core1(s1)#show ip ospf neighbor detail | include Neighbor|area|state
    Neighbor 10.26.101.73, instance 200, VRF default, interface address 10.26.254.162
    In area 0.0.0.0 interface Ethernet6/29
    Neighbor priority is 0, State is FULL, 6 state changes
    Current state was established 278d01h ago        
    """
    summary_results = []

    # Regex patterns (Note: Arista uses 'established' instead of 'up for' in some logs)
    RE_NEIGHBOR = re.compile(r'Neighbor\s+(?P<ip>[\d.]+)')
    RE_STATE = re.compile(r'State is\s+(?P<state>\w+)')
    RE_UPTIME = re.compile(r'(?:established|up for)\s+(?P<uptime>[\w\d]+)')

    for block in blocks:
        ip_match = RE_NEIGHBOR.search(block)
        state_match = RE_STATE.search(block)
        uptime_match = RE_UPTIME.search(block)

        if ip_match:
            ip = ip_match.group('ip')
            state = state_match.group('state') if state_match else "Down"
            uptime = uptime_match.group('uptime') if uptime_match else "0s"
            summary_results.append(f"{ip} {state} {uptime}")
            continue
    # print(summary_results)
    return summary_results

def log_summary(log, hostname, ip):
    import re
    from collections import defaultdict

    if isinstance(log, list):
        log = "\n".join(log)

    log_analysis = []
    os_type = "unknown"
    vpn_instance = "Global" 

    # Structures:
    # BGP: {instance: {neighbor: [(timestamp, interface, state)]}}
    # OSPF: {process: {neighbor: [(timestamp, interface, state, vpn_name)]}}
    bgp_states = defaultdict(lambda: defaultdict(list))
    ospf_states = defaultdict(lambda: defaultdict(list))

    # Regex patterns
    bgp_re = re.compile(
        r'(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?'
        r'BGP/\d+/BGP_STATE_CHANGED:\s+(?P<instance>BGP[.\w]*):?\s+'
        r'(?P<neighbor>\d+\.\d+\.\d+\.\d+)\s+'
        r'(?:state|State)\s+(?:is|has)\s+changed\s+from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
        re.IGNORECASE
    )

    ospf_re = re.compile(
        r'(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?OSPF_NBR_CHG:\s+OSPF\s+(?P<process>\d+)\s+Neighbor\s+(?P<neighbor>\d+\.\d+\.\d+\.\d+)\((?P<iface>[^)]+)\)\s+changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
        re.IGNORECASE
    )
    
    # %Dec 3 17:46:54:369 2025 KDC-DMZ-HUT8-5945 OSPF/5/OSPF_NBR_CHG_REASON: OSPF 904 Area 0.0.0.0 Router 139.173.79.241(Vlan904) CPU usage: 18%, VPN name: PHSA-Internet, IfMTU: 1500, Neighbor address: 139.173.78.9, NbrID:139.173.78.1 changed from Full to EXSTART because a SeqNumberMismatch event was triggered by the maste-slave relationship change at 2025-12-03 17:46:54:368.
    # ospf_reason_re = re.compile(
    #     r'(?P<timestamp>%\w+\s+\d+\s+[\d:.]+) \s+ (?P<year>\d{4}) .*? OSPF_NBR_CHG_REASON: .*? OSPF\s+(?P<process>\d+) .*? Router\s+[\d.]+\((?P<iface>[^)]+)\) .*? VPN\sname:\s+(?P<vpn_name>\w+) ,? .*? Neighbor\saddress:\s+(?P<neighbor>[\d.]+) .*? changed\sfrom\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
    #     re.IGNORECASE | re.VERBOSE
    # )
    ospf_reason_re = re.compile(
        r"""
        (?P<timestamp>%\w+\s+\d+\s+[\d:.]+) \s+ (?P<year>\d{4}) .*?
        OSPF_NBR_CHG_REASON: .*? OSPF\s+(?P<process>\d+) .*?
        Router\s+[\d.]+\((?P<iface>[^)]+)\) .*?
        VPN\sname:\s+(?P<vpn_name>[\w-]+) ,? .*?   # VPN\sname:\s+(?P<vpn_name>\w+) ,? .*?
        Neighbor\saddress:\s+(?P<neighbor>[\d.]+) .*?
        changed\sfrom\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)
        """,
        re.IGNORECASE | re.VERBOSE
    )

    # ------------------------------------------------------------------
    # 2. NEW Cisco patterns
    # ------------------------------------------------------------------
    # 2-a  %OSPF-5-ADJCHG  (the most common)
    cisco_ospf_adjchg = re.compile(
        r'(?P<seq>\d+):\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<tz>\w+):\s+%OSPF-\d+-(?P<type>\w+):\s+'
        r'Process\s+(?P<process>\d+),\s+Nbr\s+(?P<neighbor>\d+\.\d+\.\d+\.\d+)\s+on\s+(?P<iface>\S+)\s+'
        r'from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
        re.IGNORECASE
    )

    # 2-b  %BGP-5-ADJCHANGE  (Cisco)
    cisco_bgp_adjchg = re.compile(
        r'(?P<seq>\d+):\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<tz>\w+):\s+%BGP-\d+-(?P<type>\w+):\s+'
        r'neighbor\s+(?P<neighbor>\d+\.\d+\.\d+\.\d+).*?(?P<state>Up|Down)',
        re.IGNORECASE
    )

    # 2-c  “show ip ospf events neighbor reverse generic” lines
    #      687  Nov 15 06:32:52.752: Generic:  ospf_external_route_sync  0x0
    cisco_ospf_event = re.compile(
        r'^\s*(?P<seq>\d+)\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>[\d:.]+):\s+'
        r'Generic:\s+(?P<msg>.*?)',
        re.IGNORECASE
    )

    # ------------------------------------------------------------------
    # 3. other BGP OSPF patterns    


    # Preprocess: Join lines that are part of the same log entry
    lines = []
    buffer = ""
    for line in log.splitlines():
        line = line.strip()
        # Cisco syslog line starts with <seq>:    HPE line starts with %<fac>
        if re.match(r"^%\w+\s+\d+\s[\d:.]+\s+\d{4}", line) or re.match(r"^\d+:\s", line):
            if buffer:
                lines.append(buffer)
            buffer = line
        else:
            buffer += " " + line
    if buffer:
        lines.append(buffer)

    for line in lines:
        line = line.strip()
        # print(f"Processing line: {line}")  # Debug print

        # OSPF CHG_REASON (check this first as it's more specific)
        ospf_reason_match = ospf_reason_re.search(line)
        if ospf_reason_match:
            g = ospf_reason_match.groupdict()
            timestamp = f"{g['timestamp']} {g['year']}"
            vpn = g.get('vpn_name', 'N/A')
            ospf_states[g['process']][g['neighbor']].append((timestamp, g['iface'], g['new'].upper(), vpn))
            continue

        # OSPF standard
        ospf_match = ospf_re.search(line)
        if ospf_match:
            g = ospf_match.groupdict()
            timestamp = f"{g['timestamp']} {g['year']}"
            ospf_states[g['process']][g['neighbor']].append((timestamp, g['iface'], g['new'].upper(), 'N/A'))
            continue
            
        # BGP
        bgp_match = bgp_re.search(line)
        if bgp_match:
            g = bgp_match.groupdict()
            timestamp = f"{g['timestamp']} {g['year']}"
            # if cisco_vpn_re.search(line):
            #     cisco_vpn_match = cisco_vpn_re.search(line)
            #     vpn_instance = cisco_vpn_match.group(2)
            #     instance = vpn_instance
            # else:
            #     instance = g['instance'].rstrip('.:') or "BGP"
            # instance = g['instance'].rstrip('.:') or "BGP"

            # Ensure this variable is always set
            if 'instance' in g:
            # If it's just 'BGP' or 'BGP.', treat it as Global
                parsed = g['instance'].rstrip('.:')
                instance = parsed if parsed and parsed != "BGP" else "Global"
            else:
                instance = "Global"

            # Use a generic name instead of cisco_vpn_name
            vpn_instance = instance

            bgp_states[instance][g['neighbor']].append((timestamp, "-", g['old'].upper()))
            bgp_states[instance][g['neighbor']].append((timestamp, "-", g['new'].upper()))
            continue

        # ---- Cisco ----------------------------------------------------
        # general Cisco patterns
        #  cisco bgp neighbor vpn vrf : 024113: Nov 6 00:48:44 PST: %BGP-5-ADJCHANGE: neighbor 10.73.119.241 vpn vrf VCHA-TC2 Up
        cisco_vpn_re = re.compile(r'neighbor\s+(\d+\.\d+\.\d+\.\d+).*vpn vrf (\w+-\w+)')
        if cisco_vpn_re.search(line):
            cisco_vpn_match = cisco_vpn_re.search(line)
            vpn_instance = cisco_vpn_match.group(2)
            # instance = vpn_instance
            # print(f"Debug: Cisco BGP event found {line}, {vpn_instance}")  # Debug print

        # 1. OSPF ADJCHG
        m = cisco_ospf_adjchg.search(line)
        if m:
            g = m.groupdict()
            ts = f"{g['mon']} {g['day']} {g['time']} {g['tz']}"
            ospf_states[g['process']][g['neighbor']].append((ts, g['iface'], g['new'].upper(), 'N/A'))
            continue

        # 2. BGP ADJCHANGE
        m = cisco_bgp_adjchg.search(line)
        if m:
            g = m.groupdict()
            ts = f"{g['mon']} {g['day']} {g['time']} {g['tz']}"
            state = "ESTABLISHED" if g['state'] == "Up" else "DOWN"
            bgp_states["BGP"][g['neighbor']].append((ts, "-", state))
            continue

    # === BGP Summary ===
    if bgp_states:
        # (No changes to BGP summary)
        log_analysis.append("<h5 style='margin:0'>Log Summary - BGP</h5>")
        bgp_all_states = set()
        for neighbors in bgp_states.values():
            for entries in neighbors.values():
                bgp_all_states.update(state for _, _, state in entries)
        header = (
            "<tr><th style='width:15%'>Instance</th><th style='width:15%'>Neighbor</th><th style='width:10%'>Current</th><th style='width:10%'>Duration</th>"
            + "".join(f"<th>{state}</th>" for state in sorted(bgp_all_states))
            + "<th style='width:20%'>LastChange</th></tr>"
        )
        log_analysis.append("<table id='bgp_log_summary' border='1' style='font-size:12px;width:100%;border:none'>" + header)
        for instance, neighbors in bgp_states.items():
            for neighbor, entries in neighbors.items():
                # if vpn_instance and instance == "BGP":
                if vpn_instance :
                    instance = vpn_instance #20251031 get vpn instance name from cisco log parsing
                else:
                    instance = instance.split('.')[1]  # Get base instance name for HPE BGP.1, BGP.2, etc.
                #20251031 get current state from monitor.peer_uptime function
                current_ts, _, current_state = entries[-1]
                # bgp_live_status = monitor.get_peer_status('bgp', neighbor, log)
                logger.debug(f"Debug: Getting BGP status for Host: {ip}, Instance: {instance}, Neighbor: {neighbor}")  # Debug print
                # bgp_live_status = monitor.get_peer_status('bgp', hostname,instance, neighbor)
                bgp_live_status = monitor.get_peer_status('bgp', ip ,instance, neighbor)
                # bgp_live_status = bgp_states.get('instance')
                if isinstance(bgp_live_status, list):
                    # Expect a single element list; take the first one
                    bgp_live_status = bgp_live_status[0] if bgp_live_status else {}
                # fall back and Always show ESTABLISHED, FULL/DR, etc.
                bgp_peer_state = bgp_live_status.get('state', 'UNKNOWN').upper() if bgp_live_status else 'UNKNOWN'    
                # bgp_vpn_stance = bgp_live_status.get('vpn_instance', 'UNKNOWN').upper() if bgp_live_status else 'UNKNOWN'   
                bgp_vpn_stance = instance   #get instance name from log parsing instead of monitor function
                bgp_peer_duration = bgp_live_status.get('up_down_time', 'UNKNOWN') if bgp_live_status else 'UNKNOWN'           

                state_counts = {state: 0 for state in bgp_all_states}
                for _, _, state in entries:
                    state_counts[state] += 1
                row_style = "style='background-color:Yellow'" if bgp_peer_state != "ESTABLISHED" else "style='background-color:lightgreen;'"
                row = (
                    f"<tr {row_style}><td>{bgp_vpn_stance}</td><td>{neighbor}</td><td>{bgp_peer_state}</td><td>{bgp_peer_duration}</td>"
                    + "".join(f"<td>{state_counts[state]}</td>" for state in sorted(bgp_all_states))
                    + f"<td>{current_ts}</td></tr>"
                )
                log_analysis.append(row)
        log_analysis.append("</table>")


    # === OSPF Summary ===
    if ospf_states:
        log_analysis.append("<h5 style='margin:0'>Log Summary - OSPF</h5>")
        ospf_all_states = set()
        for neighbors in ospf_states.values():
            for entries in neighbors.values():
                ospf_all_states.update(state for _, _, state, _ in entries)
        
        header = (
            "<tr><th style='width:10%'>Process</th><th style='width:10%'>VPN</th><th style='width:10%'>Neighbor</th><th style='width:20%'>Interface</th>"
            "<th style='width:10%'>Current</th><th style='width:10%'>Duration</th>"
            + "".join(f"<th>{state}</th>" for state in sorted(ospf_all_states))
            + "<th style='width:20%'>LastChange</th></tr>"
        )
        log_analysis.append("<table id='ospf_log_summary' border='1' style='font-size:12px;width:100%;border:none'>" + header)

        for process, neighbors in ospf_states.items():
            for neighbor, entries in neighbors.items():
                # --- THIS IS THE CORRECTED LOGIC BLOCK ---
                # Get current status from the last entry
                current_ts, current_iface, current_state, _ = entries[-1]

     

                # Find the most recent valid VPN name by searching backwards
                last_known_vpn = 'N/A'
                for _, _, _, vpn in reversed(entries):
                    if vpn != 'N/A':
                        last_known_vpn = vpn
                        break # Found it, stop searching

                #20251031 get current state from monitor.peer_uptime function
                ospf_live_status = monitor.get_peer_status('ospf', ip, vpn, neighbor)
                ospf_peer_state = ospf_live_status.get('state', 'UNKNOWN').upper() if ospf_live_status else 'UNKNOWN'
                ospf_peer_duration = ospf_live_status.get('verbose_uptime', 'UNKNOWN') if ospf_live_status else 'UNKNOWN'   
                                   
                # Calculate state counts
                state_counts = {state: 0 for state in ospf_all_states}
                for _, _, state, _ in entries:
                    state_counts[state] += 1

                #20251120 use current_state as ospf peer state 
                ospf_peer_state = current_state

                row_style = "style='background-color:Yellow'" if ospf_peer_state not in ["FULL", "ESTABLISHED"] else "style='background-color:lightgreen;'"
                # Use the 'last_known_vpn' variable for the output
                row = (
                    f"<tr {row_style}><td>{process}</td><td>{last_known_vpn}</td><td>{neighbor}</td><td>{current_iface}</td>"
                    f"<td>{ospf_peer_state}</td><td>{ospf_peer_duration}</td>"
                    + "".join(f"<td>{state_counts[state]}</td>" for state in sorted(ospf_all_states))
                    + f"<td>{current_ts}</td></tr>"
                )
                log_analysis.append(row)
        log_analysis.append("</table><br>")

    # print(log,log_analysis)
    return "".join(log_analysis)

# # 20251127 generate clickable html list
def list_reports(report_dir):
    """Scans the directory for HTML reports start in final_results_xxx.json and includes file size."""
    reports_data = []
    
    # Loop through the files in the directory
    for filename in os.listdir(report_dir):
        # Filter for files ending with '_sa.html'
        if filename.startswith('final_results_') and filename.endswith('.json'):
            filepath = os.path.join(report_dir, filename)
            try:
                # Get the size in bytes
                size_bytes = os.path.getsize(filepath)
                size_str = format_size(size_bytes)
                
                # Store the filename and the formatted size
                reports_data.append({
                    'filename': filename,
                    'size': size_str
                })
            except OSError:
                # Handle case where file might be inaccessible or doesn't exist (unlikely here)
                reports_data.append({'filename': filename, 'size': 'N/A'})

    # Sort the files by name (which contains the timestamp)
    reports_data.sort(key=lambda x: x['filename'], reverse=True)
    return reports_data

def parse_routing_info(temp_file_path, json_file):
    routing_info = {"hostname": None, "host_ip": None, "BGP": [], "OSPF": []}
    ip_regex = r'(?:\d{1,3}\.){3}\d{1,3}'
    #hostname_regex = r"<(.*?)>"
    hostname_regex = r"(<|)(.*?)(>|#)"
    
    if not os.path.isfile(temp_file_path):
        print("No files exist:", temp_file_path)
        return

    file_name = os.path.split(temp_file_path)[1]  # Get filename from the file path

    host_ip_match = re.search(ip_regex, file_name)

    if host_ip_match:
        host_ip = host_ip_match.group()  # Host IP is extracted from the second part of the filename
    else:
        print("Host IP not found in filename:", file_name)
        return 

    #print("Converting to routing JSON file...", json_file)
    
    with open(temp_file_path, 'r') as temp_file:
        lines = temp_file.readlines()

    current_hostname = None  # Initialize current hostname
    in_bgp_section = False
    in_ospf_section = False
    current_vpn_instance = "Global"     # Initialize BGP VPN Instance
    current_ospf_area = None            # Initialize outside the loop        

    for line in lines:
        line = line.strip()

        if current_hostname is None:
            hostname_match = re.match(hostname_regex, line)
            if hostname_match:
                current_hostname = hostname_match.group(2)
                routing_info["hostname"] = current_hostname
                routing_info["host_ip"] = host_ip          

        if "BGP is not configured." in line:
            routing_info["BGP"] = "BGP is not configured."
            in_bgp_section = False  # Set BGP section flag to False
            continue  # Move to the next line

        if line.startswith("BGP local router ID:"):
            router_id = line.split(":")[1].strip()
            in_bgp_section = True
            continue

        if line.startswith("Local AS number:"):
            local_as_number = line.split(":")[1].strip()
            continue

        # Detect BGP sections
        if in_bgp_section:
            #print(line)
            if line.startswith("VPN instance:"):
                current_vpn_instance = line.split(":")[1].strip()

            elif line.startswith("Total number of peers:"):
                #peer_total = re.findall(r"\d+",line)[0]
                #peer_est = re.findall(r"\d+",line)[1]

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

            elif re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", line):
                parts = line.split()
                if len(parts) >= 7:
                    peer_info = {
                        "peer_IP": parts[0],
                        "peer_AS": parts[1],
                        "peer_uptime": parts[-2],
                        "peer_status": parts[-1]
                    }
                    routing_info["BGP"][-1]["Peer"].append(peer_info)


        # Detect OSPF sections

        if "OSPF is not configured." in line:
            routing_info["OSPF"] = "OSPF is not configured."
            in_ospf_section = False  # Set OSPF section flag to False
            continue  # Move to the next line

        if line.startswith("OSPF Process"):
            in_bgp_section = False
            in_ospf_section = True
            current_process = re.search(r"Process (\d+)", line).group(1)
            router_id = re.search(r"Router ID ([\d\.]+)", line).group(1)
            routing_info["OSPF"].append({
                "process": current_process,
                "process router ID": router_id,
                "area_info": []
            })
            current_area = None  # Reset area

        if in_ospf_section and line.startswith("Area:"):
            current_area = line.split(":")[1].strip()
            routing_info["OSPF"][-1]["area_info"].append({
                "Area": current_area,
                "neighbor_info": []
            })

        elif in_ospf_section and current_area:
            # Match OSPF neighbor lines
            nei_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+'
            nei_pattern += r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+\d+\s+\d+\s+'
            nei_pattern += r'([\w/]+)\s+(\S+)'
            match = re.match(nei_pattern, line)
            
            if match :
                parts = line.split()
                neighbor_info = {
                    "Router ID": parts[0],
                    "Address": parts[1],
                    "State": parts[4],
                    "Interface": parts[-1]
                }
                routing_info["OSPF"][-1]["area_info"][-1]["neighbor_info"].append(neighbor_info)

    # Write to JSON file
    with open(json_file, 'w') as f:
        json.dump(routing_info, f, indent=4)

# # 20251127 generate clickable html list
def generate_dropdown_list(reports_data):
    """Generates an HTML drop-down list of reports, including file size."""
    
    # 1. Start the select box
    print('<h3 style="margin-top: 20px;text-align: left">Select a Historical Report:</h3>')
    print('<select id="reportSelector" onchange="openReport(this.value)" style="padding: 5px; font-size: 12px; width: 500px;">') # Increased width to accommodate size
    print('<option value="" disabled selected>-- Select an HTML Report (File Size) --</option>') # Default option
    
    # 2. Add options for each report file
    for report in reports_data:
        filename = report['filename']
        size = report['size']
        
        # The value is the relative path to the file
        link_path = f"../logs/{filename}" 
        
        # CRITICAL CHANGE: Display text now includes the file size
        display_text = f"{filename} ({size})"
        
        print(f'<option value="{link_path}">{display_text}</option>')
        
    print('''</select>
    <script>
        function openReport(url) {
            // Check if a file was actually selected (not the default option)
            if (url) {
                window.open(url, '_blank');
            }
        }
    </script>
    ''')


def main():
    fname = ""
    ip = ""
    if sys.argv[1:] :
        module_option=sys.argv[1]
        if module_option == "core" :
            logfile = sys.argv[2]
            fname = os.path.split(logfile)[1]  # Get filename from the file path
            ip_match = re.search(mainconfig.IP_PATTERN, fname)
            ip = ip_match[0] if ip_match else "unknown"

            # core_check(log_dir, fname, ip, logger=None)
            log_check(logfile, logger=None)

        if module_option == "compare" :
            file1=sys.argv[2]
            file2=sys.argv[3]
            compare_peers(file1,file2)

        if module_option == "routing" :
            file1=sys.argv[2]
            file2=sys.argv[3]
            parse_routing_info(file1,file2)
    else:
        print(f"Usage: {sys.argv[0]} core|compare|routing file1 file2")
        exit()

if __name__ == "__main__":
    # This will run only if the script is executed directly.
    main()  
