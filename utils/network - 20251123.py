import asyncio, logging, re, json, time, os
from netmiko import ConnectHandler
from netmiko import NetMikoTimeoutException, NetMikoAuthenticationException
from paramiko.ssh_exception import SSHException
from multiprocessing.pool import ThreadPool as Pool
from datetime import datetime
from time import ctime
from typing import List, Dict, Any, Optional
from pathlib import Path
import mainconfig as mainconfig

# Import database manager if needed
from utils.database import DatabaseManager
# Initialize DB once at module level
db = DatabaseManager(mainconfig.DB_PATH)

logger = logging.getLogger(__name__)

class NetworkDeviceManager:
    def __init__(
        self,
        check_type: str,
        device_type: str,
        iplist: str,
        interface: str,
        username: str,
        password: str,
        options: Dict[str, bool],
        bgp_event: bool = False,
        log_file: Optional[Path] = None,
        progress_file: Optional[Path] = None
    ):
        self.check_type = check_type
        self.device_type = device_type
        self.iplist = iplist
        self.interface = interface
        self.username = username
        self.password = password
        self.options = options
        self.bgp_event = bgp_event
        self.log_file = log_file
        self.results: List[Dict[str, Any]] = []
        self.progress_status: Dict[str, str] = {}
        self.completed = 0
        self.total = 0
        self.progress_file = progress_file

    def parse_iplist(self, iplist: str) -> List[Dict[str, str]]:
        ips = []
        for item in iplist.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                os_type, ip = item.split(":", 1)
            else:
                os_type = self.device_type or "hp_comware"
                ip = item
            ips.append({"os": os_type.strip(), "ip": ip.strip()})
        return ips

    async def execute_checks(self) -> List[Dict[str, Any]]:
        if not self.iplist:
            raise ValueError("IP list required")

        ips = self.parse_iplist(self.iplist)
        self.total = len(ips)
        self.completed = 0
        self.results = []

        tasks = [asyncio.create_task(self.check_single_device(ip_info)) for ip_info in ips]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in raw_results:
            if isinstance(result, dict):
                self.results.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Device check failed: {result}")
            self.completed += 1

        return self.results

    async def check_single_device(self, ip_info: Dict[str, str]) -> Dict[str, Any]:
        ip = ip_info["ip"]
        os_type = ip_info["os"]
        self.progress_status[ip] = "connecting"

        session_log_path = self.log_file or Path(f"logs/core_logs/session_{ip}.txt")
        session_log_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            device_params = {
                "device_type": os_type,
                "host": ip,
                "username": self.username,
                "password": self.password,
                "timeout": 60,
                "session_log": str(session_log_path),
                "global_delay_factor": 3,
                "fast_cli": False,
            }

            conn = ConnectHandler(**device_params)
            prompt = conn.find_prompt()
            logger.info(f"Connected to {ip}, prompt: {prompt}")

            # Do NOT disable paging - rely on low-level handling for "--More--"

            commands = self.get_commands(os_type)
            if not commands:
                raise ValueError("No commands defined")

            output = self._raw_send_commands(conn, commands, prompt, ip)

            result = self.process_output(ip, os_type, output)
            self.progress_status[ip] = "completed"
            self.completed += 1
            return result

        except (NetMikoTimeoutException, NetMikoAuthenticationException, SSHException) as e:
            error_msg = f"Connection failed: {str(e)}"
            logger.error(error_msg)
            self.progress_status[ip] = "failed"
            self.completed += 1
            return {
                "ip": ip,
                "os_type": os_type,
                "status": "failed",
                "error": error_msg,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            self.progress_status[ip] = "failed"
            self.completed += 1
            return {
                "ip": ip,
                "os_type": os_type,
                "status": "failed",
                "error": error_msg,
                "timestamp": datetime.now().isoformat(),
            }

        finally:
            try:
                conn.disconnect()
            except Exception:
                pass

    def _raw_send_commands(
        self,
        conn: ConnectHandler,
        commands: List[str],
        prompt: str,
        ip: str,
    ) -> Dict[str, str]:
        output_dict: Dict[str, str] = {}
        for idx, cmd in enumerate(commands, 1):
            cmd_output = ""
            try:
                conn.write_channel(f"{cmd}\n")
                while True:
                    try:
                        # Use more specific pattern for HP Comware paging (from logs/tests)
                        page = conn.read_until_pattern(
                            pattern=f"--More--|{re.escape(prompt)}",
                            read_timeout=60,
                        )
                        cmd_output += page
                        if "--More--" in page:  # Specific match for HP Comware
                            conn.write_channel(" ")
                        elif prompt in page:
                            break
                    except NetMikoTimeoutException:
                        logger.warning(f"Timeout reading {ip} cmd: {cmd}")
                        break
                    except (NetMikoAuthenticationException, SSHException) as exc:
                        logger.error(f"SSH error on {ip} cmd: {cmd} → {exc}")
                        cmd_output += f"\nERROR: {exc}"
                        break
            except Exception as exc:
                logger.error(f"Error sending {cmd} to {ip}: {exc}")
                cmd_output += f"\nERROR: {exc}"

            output_dict[cmd] = cmd_output.strip()

            # Progress update
            if self.progress_file:
                progress = int((idx / len(commands)) * 100)
                self.progress_file.write_text(json.dumps({
                    "progress": progress,
                    "status": "running",
                    "updated_at": datetime.now().isoformat()
                }))

        return output_dict

    def get_commands(self, os_type: str) -> List[str]:
        if self.check_type == "core":
            if os_type == "hp_comware":
                return [
                    "display logbuffer | include BGP|OSPF",
                    "display bgp peer ipv4",
                    "display bgp peer ipv4 vpn-instance-all",
                    "display ospf peer",
                    "display ospf peer verbose | include Router|State|Neighbor|Area|Address|Time|Reason",
                ]
            # Add cisco_ios/arista_eos if needed
        return []

    def process_output(self, ip: str, os_type: str, output: Dict[str, str]) -> Dict[str, Any]:
        return {
            "ip": ip,
            "os_type": os_type,
            "status": "success",
            "output": output,
            "timestamp": datetime.now().isoformat(),
        }

class OrionSessionManager:
    def __init__(self, npm_server: str, username: str, password: str):
        self.npm_server = npm_server
        self.username = username
        self.password = password
        
    async def execute_checks(self, check_options: Dict[str, bool]) -> Dict[str, Any]:
        """Execute Orion checks based on options"""
        results = {}
        
        if check_options.get("check_down"):
            results["down_nodes"] = await self.get_down_nodes()
            results["down_interfaces"] = await self.get_down_interfaces()
            
        if check_options.get("check_alert"):
            results["alerts"] = await self.get_alerts()
            
        if check_options.get("check_netpath"):
            results["netpath"] = await self.get_netpath_status()
            
        if check_options.get("check_udt") and check_options.get("udt_ip"):
            results["udt"] = await self.get_udt_info(check_options["udt_ip"])
            
        return results
        
    async def get_down_nodes(self) -> List[Dict]:
        """Get down nodes from Orion"""
        # Implement Orion query logic
        return []
        
    async def get_down_interfaces(self) -> List[Dict]:
        """Get down interfaces from Orion"""
        # Implement Orion query logic
        return []
        
    async def get_alerts(self) -> List[Dict]:
        """Get current alerts from Orion"""
        # Implement Orion query logic
        return []
        
    async def get_netpath_status(self) -> List[Dict]:
        """Get NetPath status from Orion"""
        # Implement Orion query logic
        return []
        
    async def get_udt_info(self, ip_address: str) -> Dict[str, Any]:
        """Get User Device Tracker information"""
        # Implement UDT query logic
        return {}

async def trigger_analysis_update():
    """Trigger analysis_sqlite update"""
    try:
        # This would run the analysis in a subprocess or directly
        from routers.analysis import update_analysis
        success = await update_analysis()
        return success, "Analysis completed successfully"
    except Exception as e:
        return False, f"Analysis failed: {str(e)}"
    
def send_command(device_setting,cmds,output, logger=None):
    print(f"Starting send_command for IP: {device_setting['ip']} {cmds}")

    output = ""

    try:
        device = ConnectHandler(**device_setting)
        prompt = device.find_prompt()
        # print("login:",device_setting['ip'], " success")
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
                    except (NetMikoAuthenticationException, SSHException) as error:
                        logger.error(f"Connection Error {device_setting['ip']} : {error}")
                        break
        device.disconnect()
        # # Write to log file : log was saved in the device_setting['session_log']
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    
    return output    

# 20251110 - 
def run_getweboutput(form_data: dict) -> str:
    html_output = []

    def html_print(*args):
        html_output.append(' '.join(str(a) for a in args))

    check_type = form_data.get('check_type', 'core') # Regular or Core
    device_type = form_data.get('vendor', '')
    iplist = form_data.get('ipaddress', '') #for multiple IPs
    interface = form_data.get('interface', '')
    bgp_event = form_data.get('core2_bgp', '')

    option1 = form_data.get('check_option1')
    option2 = form_data.get('check_option2')
    option3 = form_data.get('check_option3')
    option4 = form_data.get('check_option4')
    option5 = form_data.get('check_option5')

    # Core IP address
    if check_type == "core":
        uname = form_data.get('core_uname', '')
        passwd = form_data.get('core_passwd', '')
        # log_dir = os.path.abspath(os.path.join(mainconfig.BASE_DIR, 'logs\core_logs'))
        log_dir = mainconfig.LOGS_DIR / "core_logs"
        core_ipaddress = form_data.get('core_ipaddress', '')
        if core_ipaddress : 
            for loop in core_ipaddress:
                os_type = loop.split(':')[0]
                ip = loop.split(':')[1]    
    else:
        uname = form_data.get('uname', '')
        passwd = form_data.get('passwd', '')
        log_dir = mainconfig.LOGS_DIR
        html_print(f"<html><body><h2>Get Web Output - {ip} {ctime(time.time())}</h2>")

    os.makedirs(log_dir, exist_ok=True)


    def getoutput(os_type, ip, retries=2, timeout=30):
        cmds = []
        log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_log_file = os.path.join(log_dir, f"{log_time}_{ip}_{uname}.txt")
        device_setting = {
            'device_type': os_type,
            'ip': ip,
            'username': uname,
            'password': passwd,
            'fast_cli': False,
            'session_log': session_log_file,
            'timeout': 60,           # Default is 100 seconds, increase if needed
            'global_delay_factor': 3 # Try increasing to 3–5 if device is slow
        }

        if os_type == "cisco_ios" or os_type == "arista_eos" and check_type == "regular":
            if option1 == "enable": cmds.append("show version")
            if option2 == "enable": cmds.append("show env all")
            if option3 == "enable": cmds.append("show log")
            if option4 == "enable" and interface:
                cmds.append(f"show interface {interface}")
            if option5 == "enable":
                cmd5 = form_data.get('defined_cmd', '')
                cmds.extend([c.strip() for c in cmd5.split(',')])

        if check_type == "core":
            # core_os = os_type
            if os_type == "cisco_ios":
                cmd_core = mainconfig.CMD_CISCO
            if os_type == "arista_eos":
                cmd_core = mainconfig.CMD_ARISTA
            if os_type == "hp_comware":
                cmd_core = mainconfig.CMD_HPE
        cmds.extend(cmd_core)

        if cmds:
            # print(device_setting, cmds )
            if not uname or not passwd:
                html_print(f"<p>Missing username or password for device {ip}</p>")
                return
            try:
                #start login and sending commands
                success = send_command(device_setting, cmds, session_log_file, logger=None)
                if success:
                    print(f"login success {ip}, log")
                    if check_type == "core":
                        try:
                            analysis = core_check(log_dir, os.path.basename(session_log_file), ip)
                            html_print(analysis)
                        except Exception as e:
                            html_print(f"<p>Error in output analysis core_check {ip} : {e}</p>")
                else:
                    html_print(f"<p>Failed to connect or run commands on {ip}</p>")
            except (NetMikoAuthenticationException, SSHException, NetMikoTimeoutException) as e:
                html_print(f"<p>Error connecting to {ip}: {str(e)}</p>")

    if iplist and check_type == "regular":
        ips = [ip.strip() for ip in iplist.split(',')]
        pool = Pool(min(len(ips), 10))
        for ip in ips:
            pool.apply_async(getoutput, args=(device_type, ip))
        pool.close()
        pool.join()
    elif check_type == "core":
        if core_ipaddress:
            pool = Pool(max(1, min(len(core_ipaddress), 10)))
            for loop in core_ipaddress:
                os_type, ip = loop.split(':', 1)
                pool.apply_async(getoutput, args=(os_type, ip))
            pool.close()
            pool.join()
    else:
        html_print("<p>No Core IP address provided.</p>")

    return '\n'.join(html_output)


def core_check(log_dir, fname, ip, logger=None):
    html_output = []
    fname = os.path.split(fname)[1]

    if not log_dir.endswith("arch"):
        log_arch_dir = os.path.join(log_dir, "arch")
    else:
        log_arch_dir = log_dir
    log_file_path = os.path.join(log_dir, fname)
    ip_pattern = "(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
    ip_match = re.search(ip_pattern, fname)
    ip = ip_match[0] if ip_match else "unknown"
    arch_file_tag = "off"

    def html_print(*args):
        html_output.append(' '.join(str(a) for a in args))

    # Check log file existence
    if not os.path.exists(log_file_path):
        return "<p>Error: Log file does not exist.</p>"
    elif os.path.getsize(log_file_path) == 0:
        return "<p>Error: Log file is empty.</p>"
    else:
        print(f"Starting core_check for IP: {ip}, File: {log_file_path}")

    # Process log file
    result_log = log_check(log_file_path, logger=None, label="Current Log file")
    if result_log:
        # logger.info(f"Log check result: {result}")
        try:
            # Compose HTML output
            hostname = result_log.get("hostname",[])  # Extract the hostname
            label = result_log.get("label", "Current Log file")
            log_content = result_log.get("log_content", [])
            summary_content = result_log.get("summary_content", "")
            ipv4_peers = result_log.get("ipv4_peers", [])
            count_ipv4 = result_log.get("count_ipv4", 0)
            vpnv4_peers = result_log.get("vpnv4_peers", [])
            count_vpnv4 = result_log.get("count_vpnv4", 0)
            ospf_peers = result_log.get("ospf_peers", [])
            count_ospf = result_log.get("count_ospf", 0)

            html_output.append(f"""
            <br>
            <table id="{ip}" style="width:100%;">
                <tr style="display:flex;">
                    <td style="width:50%;"><b>{hostname}</b></td>
                    <td style=\"width:50%\">{label}: <a href=\"\\logs\\core_logs\\{fname}\" target=\"_blank\">{fname}</a>
                </tr>
            """) 

            if log_content :
                html_output.append(
                    "<tr><td><p style=background-color:Orange;font-size:12px>{}</p></td></tr>".format(log_content)
                )
            if summary_content :            
                html_output.append(
                    "<tr><td><p style=font-size:12px>{}</p></td></tr>".format(summary_content)
                ) 

            #20251121 no need 
            # html_output.append(
            #     "<tr style=\"display:flex;\"><td style=\"width:50%\">{}: <a href=\"\\logs\\core_logs\\{}\" target=\"_blank\">{}</a> <br>BGP Global peers:{}, established:{} <br>BGP VPN peers:{}, established:{}<br>OSPF peers:{}, Full:{}</td>"
            # .format(
            #     label, fname, fname, 
            #     len(ipv4_peers), count_ipv4, 
            #     len(vpnv4_peers), count_vpnv4, 
            #     len(ospf_peers), count_ospf
            # ))  

        except Exception as e:
            html_print(f"<p>Error in log analysis {log_file_path}: {e}</p>")        

    # # Process archived log file
    # for arch_filename in os.listdir(log_arch_dir):
    #     # only check the file name end with .txt
    #     if re.search(ip, arch_filename) and arch_filename.endswith('.txt'): 
    #         arch_file_tag = "on"
    #         arch_file_path=os.path.join(log_arch_dir, arch_filename) 
    #         print(f"Found archived file for IP: {ip}  : {arch_file_path}")
    #         result_arch = log_check(arch_file_path, logger=None, label="Archived Log file")
    #         if result_arch:
    #             # logger.info(f"Log check result: {result}")
    #             try:
    #                 icon_green="/icons/Event-5.gif"
    #                 icon_red="/icons/Event-10.gif"
    #                 icon_plus="/icons/Event-16.gif"

    #                 arch_count_ipv4 = result_arch.get("count_ipv4", 0)
    #                 arch_count_vpnv4 = result_arch.get("count_vpnv4", 0)
    #                 arch_count_ospf = result_arch.get("count_ospf", 0)
    #                 arch_ipv4_peers = result_arch.get("ipv4_peers", [])
    #                 arch_vpnv4_peers = result_arch.get("vpnv4_peers", [])
    #                 arch_ospf_peers = result_arch.get("ospf_peers", [])
    #                 label = result_arch.get("label", "Archived Log file")

    #                 if arch_count_ipv4 == count_ipv4:
    #                     arch_icon_ipv4 = icon_green
    #                 elif arch_count_ipv4 > count_ipv4:
    #                     arch_icon_ipv4 = icon_red
    #                 else:
    #                     arch_icon_ipv4 = icon_plus

    #                 if arch_count_vpnv4 == count_vpnv4:
    #                     arch_icon_vpnv4 = icon_green
    #                 elif arch_count_vpnv4 > count_vpnv4:
    #                     arch_icon_vpnv4 = icon_red
    #                 else:
    #                     arch_icon_vpnv4 = icon_plus

    #                 if arch_count_ospf == count_ospf:
    #                     arch_icon_ospf = icon_green
    #                 elif arch_count_ospf > count_ospf:
    #                     arch_icon_ospf = icon_red
    #                 else:
    #                     arch_icon_ospf = icon_plus                        

    #                 html_output.append(
    #                     "<td style=\"width:50%\">{}: <a href=\"\\logs\\core_logs\\arch\\{}\" target=\"_blank\">{}</a><br>" \
    #                     "<img src=\"{}\" alt=\"\"/> BGP Global peers:{}, established:{} <br>" \
    #                     "<img src=\"{}\" alt=\"\"/> BGP VPN peers:{}, established:{} <br>" \
    #                     "<img src=\"{}\" alt=\"\"/> OSPF peers:{}, Full:{} </td> "
    #                 .format(
    #                     label, arch_filename, arch_filename, 
    #                     arch_icon_ipv4, len(arch_ipv4_peers), arch_count_ipv4,  
    #                     arch_icon_vpnv4, len(arch_vpnv4_peers), arch_count_vpnv4, 
    #                     arch_icon_ospf, len(arch_ospf_peers), arch_count_ospf, 
    #                 ))  

    #             except Exception as e:
    #                 html_print(f"<p>Error in archived log analysis {arch_file_path}: {e}</p>")

    #         break  # <--- Add this to avoid duplicates

    # if arch_file_tag == "off": #no archived file found
    #     html_output.append(f"<td style=\"width:50%\"> No archived log file for {ip} compare.</td>")

    #render HTML table
    html_output.append(f"        </tr></table>")

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

    # Check log file existence
    if not os.path.exists(log_file_path):   
        print(f"Error: Log file '{log_file_path}' does not exist.")
        return None
    else:
        print("starting log_check for IP:", ip, "File:", log_file_path)
     
    output_json_path = os.path.join(log_dir, f"{ip}_log_analysis.json")
    if os.path.basename(os.path.dirname(log_file_path)) != "arch" or not os.path.exists(output_json_path):     # for normal log file, save for report every time; or the first time for archived log file
        with open(log_file_path, 'r') as file:
            log_match_texts = []  # Collect stripped lines
            log_entries = []
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
                            current_os = 'cisco_iso'
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
                    current_os = 'cisco_iso'
                    continue

                if hostname_prompt + 'show logger ' in stripped:
                    current_section = 'log'
                    current_os = 'arista_eos'
                    continue

                # Collect log entries
                if current_section == "log" and re.search(log_regex, line):
                    if current_entry:
                        log_entries.append(current_entry)
                    current_entry = line.rstrip()
                    continue
                
                # if current_section == 'log':
                #     if current_os == 'hpe':
                #         if line.startswith("%"):
                #             if current_entry:
                #                 log_entries.append(current_entry)
                #             current_entry = line.rstrip()
                #         elif line.startswith(" "):
                #             if current_entry is not None:
                #                 current_entry += "\n" + line.rstrip()
                #     else:  # Cisco / Arista
                #         if re.match(r"^\d+:", line.strip()) or "%" in line:  # seq: or %
                #             if current_entry:
                #                 log_entries.append(current_entry)
                #             current_entry = line.rstrip()
                #         elif line.startswith(" "):
                #             if current_entry is not None:
                #                 current_entry += "\n" + line.rstrip()

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
                
                # Check for cisco_iso status
                if current_os == 'cisco_iso':
                    if "For address family: IPv4 Unicast" in stripped:
                        current_section = "ipv4"
                        continue
                    elif "For address family: VPNv4 Unicast" in stripped:
                        current_section = "vpnv4"
                        continue
                    elif "show ip ospf" in stripped:
                        current_section = "ospf"
                        continue
                    if re.search(ip_pattern, stripped):
                        fields = stripped.split()
                        if current_section == "ipv4" and len(fields) >= 9:
                            ipv4_peers.append(stripped)
                        elif current_section == "vpnv4" and  len(fields) in (10, 11):
                            vpnv4_peers.append(stripped)
                        elif current_section == "ospf" and len(fields) >= 7:
                            ospf_peers.append(stripped)
                                            
                # Check for arista_eos status
                if current_os == 'arista_eos':
                    if "BGP summary information for VRF default" == stripped:
                        current_section = "ipv4"
                        continue
                    elif "BGP summary information for VRF" in stripped:
                        current_section = "vpnv4"
                        continue
                    elif "show ip ospf" in stripped:
                        current_section = "ospf"
                        continue
                    if re.search(ip_pattern, stripped):
                        fields = stripped.split()
                        ipv4_parrern = r'(?:\d{1,3}\.){3}\d{1,3}\s+\d+'
                        if current_section == "ipv4" and re.search(ipv4_parrern, stripped):
                            ipv4_peers.append(stripped)
                        elif current_section == "vpnv4" and len(fields) in (10, 11):
                            vpnv4_peers.append(stripped)
                        elif current_section == "ospf" and len(fields) >= 8:
                            ospf_peers.append(stripped)

        # the last log entry
        if current_entry:
            log_entries.append(current_entry)

        # Now filter by your log_regex
        filtered_entries = [entry for entry in log_entries if re.search(log_regex, entry)]
        if filtered_entries:
            log_content = "<br>".join(filtered_entries)
            print_match.append(
                "<tr><td><p style=background-color:Orange;font-size:12px>{}</p></td></tr>".format(log_content)
            )        

            summary_content = log_summary("\n".join(filtered_entries))

        # log_content = "<br>".join(filtered_entries)
        # print_match.append(
        #     "<tr><td><p style=background-color:Orange;font-size:12px>{}</p></td></tr>".format(log_content)
        # )

        # if log_match_texts:
        #     log_content = "<br>".join(log_match_texts)
        #     print_match.append(
        #         "<tr><td><p style=background-color:Orange;font-size:12px>{}</p></td></tr>".format(log_content)
        #     )     

        if current_os == 'arista_eos' or current_os == 'cisco_iso':
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
        print(f"Found archived json file for IP: {ip}  : {output_json_path}")
        with open(output_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Access fields with defaults
        current_os = data.get("current_os", "unknown")
        ipv4_peers = data.get("ipv4_peers", [])
        vpnv4_peers = data.get("vpnv4_peers", [])
        ospf_peers = data.get("ospf_peers", [])

        # Count based on conditions (modify if needed)
        if current_os == 'arista_eos' or current_os == 'cisco_iso':
            count_ipv4 = sum(1 for line in ipv4_peers if not "Idle" in line)
            count_vpnv4 = sum(1 for line in vpnv4_peers if not "Idle" in line)
            count_ospf = sum(1 for line in ospf_peers if "FULL" in line)
        elif current_os == 'hpe':
            count_ipv4 = sum(1 for line in ipv4_peers if "Established" in line)
            count_vpnv4 = sum(1 for line in vpnv4_peers if "Established" in line)
            count_ospf = sum(1 for line in ospf_peers if "Full" in line)
        
    # print(print_match)

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

def log_summary(log):
    import re
    from collections import defaultdict

    if isinstance(log, list):
        log = "\n".join(log)

    log_analysis = []

    # Structures: {process: {neighbor: [(timestamp, interface, state)]}}
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

    ospf_reason_re = re.compile(
        r'(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?OSPF_NBR_CHG_REASON:.*?OSPF\s+(?P<process>\d+).*?Neighbor address: (?P<neighbor>\d+\.\d+\.\d+\.\d+).*?\((?P<iface>[^)]+)\).*?changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
        re.IGNORECASE
    )

    # Parse log lines


    # Preprocess: Join lines that are part of the same log entry
    lines = []
    buffer = ""
    for line in log.splitlines():
        line = line.strip()
        if re.match(r"^%\w+\s+\d+\s[\d:.]+\s+\d{4}", line): # New log entry starts
            if buffer:
                lines.append(buffer)
            buffer = line
        else:
            buffer += " " + line # Continuation of previous line
    if buffer:
        lines.append(buffer)


    for line in lines:
        line = line.strip()

        # BGP
        bgp_match = bgp_re.search(line)
        # print(f"Processing BGP line: {line}")
        if bgp_match:
            # print(f"Processing BGP line: {line}")
            g = bgp_match.groupdict()
            timestamp = f"{g['timestamp']} {g['year']}"
            instance = g['instance'].rstrip('.:') or "BGP"
            bgp_states[instance][g['neighbor']].append((timestamp, "-", g['old'].upper()))
            bgp_states[instance][g['neighbor']].append((timestamp, "-", g['new'].upper()))
            continue

        # OSPF standard
        ospf_match = ospf_re.search(line)
        if ospf_match:
            g = ospf_match.groupdict()
            timestamp = f"{g['timestamp']} {g['year']}"
            ospf_states[g['process']][g['neighbor']].append((timestamp, g['iface'], g['new'].upper()))
            continue

        # OSPF CHG_REASON
        ospf_reason_match = ospf_reason_re.search(line)
        if ospf_reason_match:
            g = ospf_reason_match.groupdict()
            timestamp = f"{g['timestamp']} {g['year']}"
            ospf_states[g['process']][g['neighbor']].append((timestamp, g['iface'], g['new'].upper()))
            continue

    # === BGP Summary ===
    if bgp_states:
        log_analysis.append("<h>BGP Current Summary</h>")
        bgp_all_states = set()
        for neighbors in bgp_states.values():
            for entries in neighbors.values():
                bgp_all_states.update(state for _, _, state in entries)

        header = (
            "<tr><th style='width:10%'>Instance</th><th style='width:10%'>Neighbor</th><th style='width:20%'>Interface</th><th style='width:10%'>Current State</th><th>LastChange</th>"
            + "".join(f"<th>{state}</th>" for state in sorted(bgp_all_states))
            + "</tr>"
        )
        log_analysis.append("<table id='bgp_log_summary' border='1' style='font-size:12px;width:100%;table-layout:auto'>" + header)

        for instance, neighbors in bgp_states.items():
            for neighbor, entries in neighbors.items():
                current_ts, current_if, current_state = entries[-1]
                state_counts = {state: 0 for state in bgp_all_states}
                for _, _, state in entries:
                    state_counts[state] += 1
                row_style = " style='background-color:Yellow'" if current_state != "ESTABLISHED" else "style='background-color:lightgreen;'"
                row = (
                    f"<tr {row_style}><td>{instance}</td><td>{neighbor}</td><td>{current_if}</td><td>{current_state}</td><td>{current_ts}</td>"
                    + "".join(f"<td>{state_counts[state]}</td>" for state in sorted(bgp_all_states))
                    + "</tr>"
                )
                log_analysis.append(row)

        log_analysis.append("</table>")

    # === OSPF Summary ===
    if ospf_states:
        log_analysis.append("<h>OSPF Current Summary</h>")
        ospf_all_states = set()
        for neighbors in ospf_states.values():
            for entries in neighbors.values():
                ospf_all_states.update(state for _, _, state in entries)

        header = (
            "<tr><th style='width:10%'>Process</th><th style='width:10%'>Neighbor</th><th style='width:20%'>Interface</th><th style='width:10%'>Current State</th><th>LastChange</th>"
            + "".join(f"<th>{state}</th>" for state in sorted(ospf_all_states))
            + "</tr>"
        )
        log_analysis.append("<table id='ospf_log_summary' border='1' style='font-size:12px;width:100%;table-layout:auto'>" + header)

        for process, neighbors in ospf_states.items():
            for neighbor, entries in neighbors.items():
                current_ts, current_iface, current_state = entries[-1]
                state_counts = {state: 0 for state in ospf_all_states}
                for _, _, state in entries:
                    state_counts[state] += 1

                #20251120 use current_state as ospf peer state 
                ospf_peer_state = current_state

                row_style = "style='background-color:Yellow'" if ospf_peer_state not in ["FULL", "ESTABLISHED"] else "style='background-color:lightgreen;'"
                row = (
                    f"<tr {row_style}><td>{process}</td><td>{neighbor}</td><td>{current_iface}</td><td>{ospf_peer_state}</td><td>{current_ts}</td>"
                    + "".join(f"<td>{state_counts[state]}</td>" for state in sorted(ospf_all_states))
                    + "</tr>"
                )
                log_analysis.append(row)

        log_analysis.append("</table>")

    # print(log_analysis)
    return "".join(log_analysis)

# # 20251121 save to database
def save_to_database(hostname: str, bgp_peers: List[Dict], ospf_peers: List[Dict]):
    for peer in bgp_peers:
        peer['hostname'] = hostname
        db.upsert_bgp_peer(peer)

    for peer in ospf_peers:
        peer['hostname'] = hostname
        db.upsert_ospf_peer(peer)
