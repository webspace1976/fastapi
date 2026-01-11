# utils/collector.py
import logging, time
from typing import List, Dict
from netmiko import ConnectHandler
from pathlib import Path
import mainconfig as config
from core.database import DatabaseManager  # ← shared

logger = logging.getLogger(__name__)
db = DatabaseManager(str(config.DB_PATH))

def collect_and_save_device(ip: str, os_type: str, username: str, password: str) -> Dict:
    """Connect → collect → save to DB → return summary"""
    log_path = Path(config.LOGS_DIR) / "core_logs" / f"session_{ip}_{int(time.time())}.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    device = {
        "device_type": os_type,
        "host": ip,
        "username": username,
        "password": password,
        "session_log": str(log_path),
        "global_delay_factor": 3,
        "timeout": 90,
    }

    try:
        with ConnectHandler(**device) as conn:
            hostname = conn.find_prompt()[1:-1].split("#")[0]
            output = {
                cmd: conn.send_command(cmd)
                for cmd in [
                    "display bgp peer ipv4",
                    "display bgp peer ipv4 vpn-instance-all",
                    "display ospf peer verbose",
                ]
            }

        # Parse and save
        from utils.parser import parse_bgp_peers, parse_ospf_peers
        bgp_peers = parse_bgp_peers(output, hostname)
        ospf_peers = parse_ospf_peers(output, hostname)

        for p in bgp_peers: p["hostname"] = hostname
        for p in ospf_peers: p["hostname"] = hostname

        for p in bgp_peers: db.upsert_bgp_peer(p)
        for p in ospf_peers: db.upsert_ospf_peer(p)

        return {
            "hostname": hostname,
            "ip": ip,
            "bgp_up": sum(1 for p in bgp_peers if p["state"] == "Established"),
            "bgp_total": len(bgp_peers),
            "ospf_full": sum(1 for p in ospf_peers if "FULL" in p["state"]),
            "ospf_total": len(ospf_peers),
        }
    except Exception as e:
        logger.error(f"Failed {ip}: {e}")
        return {"ip": ip, "error": str(e)}