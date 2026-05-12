# scripts/config.py

import logging, os, re
from pathlib import Path
# 202512 Import the concurrent handler instead of the standard one, fix RotatingFileHandler on Windows, rename to  to .log.1 falls issue
# # from logging.handlers import RotatingFileHandler 

# Base paths
# BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
CORE_MAIN_DIR = BASE_DIR / ".." / ".." / "logs" / "core"
CORE_LOGS_DIR_LOCAL = BASE_DIR / "logs" / "core_logs"
CORE_LOGS_DIR = "/logs/core_logs"  # relative path for log links

STATIC_DIR = BASE_DIR / "static"
ICONS_DIR = STATIC_DIR / "icons"
TEMPLATES_DIR = BASE_DIR / "templates"
SESSION_DIR = DATA_DIR / "orion_sessions"
ALERT_LOG_PATH = LOGS_DIR / "alert_center.log"

# Database settings
DB_PATH = DATA_DIR / "network_core.db"
DB_ORION_PATH = DATA_DIR / "orion_data.db"

# files settings
SESSION_LOG_JSON = SESSION_DIR / "orion_session_log.json"
SESSION_LOG_TSV = DATA_DIR / "orion_session_log.tsv"
LAST_ORION_DASHBOARD = DATA_DIR / "last_orion_dashboard.html"

# WebSocket settings
WEBSOCKET_PORT = 8765
WEBSOCKET_HOST = "0.0.0.0"

# Cookie settings
COOKIE_NAME = "session_id"
COOKIE_PATH = "/"
COOKIE_HTTPONLY = True
COOKIE_MAX_AGE_SECONDS = 86400  # 1 day

# 20251113 regre pattern
LOG_REGEX = r"(BGP|BFD|OSPF)(-|\/)\d+[-|\/]\w+|(BGP|BFD|OSPF)_\w+(-|\/)\d+"  # general log pattern for BGP/OSPF/BFD
# IP_PATTERN = "(?:[0-9]{1,3}\.){3}[0-9]{1,3}"                # 10.26.101.8
IP_PATTERN = r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}"

# HOSTNAME_REGEX = r"(?:<)?([A-Za-z0-9._-]+(?:\([A-Za-z0-9._-]+\))?)(?:>|#)"<ENG-KEL-HUT8-5945-Core>
HOSTNAME_REGEX = r"(<|)(.*?)(>|#)"  #  generic hostname pattern
LOG_FILE_REGEX = r"^\d{8}_\d{6}_[\d\.]+_[\w-]+_sa\.txt$"    # 20251123_100149_10.26.101.8_tl2492_sa.txt
BGP_REGEX = (r'(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?'
    r'BGP/\d+/BGP_STATE_CHANGED:\s+(?P<instance>BGP[.\w]*):?\s+'
    r'(?P<neighbor>\d+\.\d+\.\d+\.\d+)\s+'
    r'(?:state|State)\s+(?:is|has)\s+changed\s+from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
    re.IGNORECASE)
OSPF_REGEX = (
    r'(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?OSPF_NBR_CHG:\s+OSPF\s+(?P<process>\d+)\s+Neighbor\s+(?P<neighbor>\d+\.\d+\.\d+\.\d+)\((?P<iface>[^)]+)\)\s+changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
    re.IGNORECASE
    )
OSPF_REASON_REGEX = (
    r'(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?OSPF_NBR_CHG_REASON:.*?OSPF\s+(?P<process>\d+).*?Neighbor address: (?P<neighbor>\d+\.\d+\.\d+\.\d+).*?\((?P<iface>[^)]+)\).*?changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)',
    re.IGNORECASE
    )
HPE_BGP_LOG_REGEX = r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?BGP/5/BGP_STATE_CHANGED:(?: BGP\.([^:]*?):)?\s+([\d\.]+) \s+state has changed from ([\w\/]+) to ([\w\/]+)"
HPE_OSPF_LOG_REGEX = r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?OSPF\/5\/OSPF_NBR_CHG:.*?OSPF\s+(\d+).*?Neighbor\s+([\d\.]+)\(([\w\-\/]+)\)\s+changed from\s+([\w\/]+)\s+to\s+([\w\/]+)"
HPE_OSPF_LAST_DOWN_REGEX = r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?OSPF/6/OSPF_LAST_NBR_DOWN: OSPF (\d+) Last neighbor down event: Router ID: ([\d\.]+) Local address: ([\d\.]+) Remote address: ([\d\.]+) Reason: ([^\.]+)"
CISCO_OSPF_LOG_REGEX = r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}).*?Ospf.*?: Instance (\d+):.*?NGB ([\d\.]+), interface ([\d\.]+) adjacency (dropped|established).*?(?:state was: (\w+))?"

hpe_bgp_log_regex = re.compile(r"%(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}:\d{3}).*?BGP/5/BGP_STATE_CHANGED:(?: BGP\.([^:]*?):)?\s+([\d\.]+) \s+state has changed from ([\w\/]+) to ([\w\/]+)")

hpe_ospf_log_regex = re.compile(
    r"%(\w{3}\s+\d+\s+[\d:]+:\d{3}).*?OSPF/5/OSPF_NBR_CHG:.*?OSPF\s+(?P<proc>\d+).*?Neighbor\s+(?P<nbr>[\d\.]+)\((?P<iface>[\w\-\/]+)\)\s+changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)"
)

   #  New pattern for Arista/Cisco Adjacency Logs
# Apr 19 20:43:07 VH-VGH-JPNB9-7508R-Core2 Ospf-vrf-vrf-vch-guest[10200]: Instance 300: %OSPF-4-OSPF_ADJACENCY_TEARDOWN: NGB 10.26.107.24, interface 10.26.63.233 adjacency dropped: interface went down, state was: FULL
# Apr 19 20:43:07 VH-VGH-JPNB9-7508R-Core2 Ospf: Instance 200: %OSPF-4-OSPF_ADJACENCY_TEARDOWN: NGB 10.26.101.26, interface 10.26.249.33 adjacency dropped: interface went down, state was: FULL
OSPF_ADJ_SPECIAL_RE = re.compile(
    r'(?P<timestamp>\w{3}\s+\d+\s+[\d:]+)\s+'           # Date and Time
    r'(?P<hostname>\S+)\s+'                             # Device Name
    r'Ospf(?:-vrf-(?P<vrf>[\w-]+))?(?:\[\d+\])?:\s+'    # Flexible Ospf/VRF/PID
    r'Instance\s+(?P<process>\d+):\s+'                  # Instance/Process ID
    r'%OSPF-4-OSPF_ADJACENCY_(?P<state>\w+):\s+'        # Event Type: TEARDOWN or ESTABLISHED
    r'NGB\s+(?P<neighbor>[\d.]+),\s+'                   # Neighbor IP
    r'interface\s+(?P<iface>[\d.]+)\s+'                 # Interface IP/Name
    r'adjacency\s+(?P<action>\w+)'                      # dropped or established
    r'(?::\s+.*state\s+was:\s+(?P<old_state>\w+))?',    # Optional: previous state
    re.IGNORECASE
)
# cisco BGP adjacency change logs
# 047981: Apr 30 18:46:30 PST: %BGP-3-NOTIFICATION: sent to neighbor 10.26.101.2 active 6/2 (Administrative Shutdown) 0 bytes

# 047982: Apr 30 18:46:30 PST: %BGP-5-NBR_RESET: Neighbor 10.26.101.2 active reset (Admin. shutdown)

# 047983: Apr 30 18:46:30 PST: %BGP-5-ADJCHANGE: neighbor 10.26.101.2 active Down Admin. shutdown
#  120538: Apr 30 19:41:57 PDT: %BGP-5-ADJCHANGE: neighbor 10.253.83.2 active vpn vrf VCHA-TC2 Down Admin. shutdown
CISCO_BGP_ADJCHG = re.compile(
    r'(?P<seq>\d+)?:\s*'                                 # Optional Sequence Number
    r'(?P<timestamp>\w{3}\s+\d+\s+[\d:]+(?:\s+\w+)?):\s+' # Date, Time, and optional TZ
    r'(?:(?P<hostname>\S+)\s+)?'                        # Optional Hostname
    r'%BGP-\d+-(?P<event_type>\w+):\s+'                 # BGP Event
    r'neighbor\s+(?P<neighbor>[\d.]+)\s+'               # Neighbor IP
    r'(?P<status_mode>\S+\s+)?'                         # Matches 'active'
    r'(?:vpn\s+vrf\s+(?P<vrf>\S+)\s+)?'                 # NEW: Specifically captures the VRF name
    r'(?P<action>Up|Down|reset)'                        # The actual state change
    r'(?:\s+(?P<reason>.*))?',                          # Optional reason
    re.IGNORECASE
)

HPE_OSPF_REASON_REGEX = re.compile(
    r"""
    (?P<timestamp>%\w+\s+\d+\s+[\d:.]+) \s+ (?P<year>\d{4}) .*?
    OSPF_NBR_CHG_REASON: .*? OSPF\s+(?P<process>\d+) .*?
    Router\s+[\d.]+\((?P<iface>[^)]+)\) .*?
    VPN\sname:\s+(?P<vpn_name>[^,]+) ,? .*?   # matches one or more of any character except a comma
    Neighbor\saddress:\s+(?P<neighbor>[\d.]+) .*?
    changed\sfrom\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)
    """,
    re.IGNORECASE | re.VERBOSE
)

# Core devices
CORE_DEVICES = [
    {"os": "hp_comware", "ip": "10.102.102.80", "name": "ENG-KEL-HUT8-5945-Core", "nodeid":"16110"},
    {"os": "hp_comware", "ip": "10.102.102.79", "name": "ENG22-KAM-Core", "nodeid":"11128"},
    {"os": "hp_comware", "ip": "10.8.8.15", "name": "ENG22-CC-Core", "nodeid":"11130"},
    {"os": "hp_comware", "ip": "10.8.8.16", "name": "ENG22-CW-Core", "nodeid":"11127"},
    {"os": "hp_comware", "ip": "10.251.0.75", "name": "KDC-R4.7-Core-1", "nodeid":"12682"},
    {"os": "hp_comware", "ip": "10.251.0.76", "name": "KDC-R4.23-Core-2", "nodeid":"11434"},
    {"os": "hp_comware", "ip": "10.251.18.216", "name": "KDC-DMZ-KAM-New", "nodeid":"16100"},
    {"os": "hp_comware", "ip": "10.251.18.217", "name": "KDC-DMZ-HUT8-5945", "nodeid":"16112"},
    {"os": "arista_eos", "ip": "10.26.101.7", "name": "VH-VGH-3730-7508R-Core1", "nodeid":"3158"},
    {"os": "arista_eos", "ip": "10.26.101.8", "name": "VH-VGH-JPNB9-7508R-Core2", "nodeid":"3287"},
    {"os": "cisco_ios", "ip": "10.26.101.127", "name": "NS-LGH-LGAC-01A-C9600-Core1", "nodeid":"14539"},
    {"os": "cisco_ios", "ip": "10.26.101.128", "name": "NS-LGH-LGAC-PIMS-C9600-Core2", "nodeid":"14540"},
    # {"os": "cisco_ios", "ip": "10.26.101.2", "name": "(NEW) LGH-PIM-Core-1", "nodeid":"282"},
    # {"os": "cisco_ios", "ip": "10.26.101.1", "name": "(NEW) LGH-EVGH-Core-2", "nodeid":"281"},
]

# Core device commands
CMD_CISCO = ['show log | inc BGP|OSPF', 'show ip bgp all neighbors | inc family|BGP|Description', 'show ip ospf neighbor detail | include Neighbor|area', 'show ip ospf events neighbor reverse generic']
CMD_ARISTA = ['show logging | inc BGP|OSPF', 'show ip bgp neighbors | inc BGP', 'show ip ospf neighbor detail | include Neighbor|area|state']
CMD_HPE = ['display log | inc BGP|OSPF', 'display bgp peer ipv4', 'display bgp peer ipv4 vpn-instance-all', 'display ospf peer', 'display ospf peer verbose | inc Router|State|Neighbor|Area|Address|Time|Reason']

# Core check template
TEMPLATE_GETDEVICEOUTPUT_FORM =  "template_getdeviceoutput_form.html"
TEMPLATE_GETDEVICEOUTPUT_HTML =  "template_getdeviceoutput.html"

# === Logging Setup ===
def setup_module_logger(name: str = "default") -> logging.Logger:
    # standard fix for Windows environments where multiple processes log to the same file
    from concurrent_log_handler import ConcurrentRotatingFileHandler
    # from logging.handlers import RotatingFileHandler

    logger = logging.getLogger(name)
    # logger.setLevel(logging.INFO) #logging.INFO is a constant integer (the value is actually 20)
    # Set to   CRITICAL, ERROR, WARNING, INFO, DEBUG 
    logger.setLevel(logging.WARNING)

    if not logger.handlers:
        formatter = logging.Formatter(
            # fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            fmt = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s() - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler = ConcurrentRotatingFileHandler(ALERT_LOG_PATH, "a", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        # handler = RotatingFileHandler(
        #     ALERT_LOG_PATH, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        # )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

# Optional: other environment configs
DEBUG_MODE = True



