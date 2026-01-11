# utils/parser.py
import re
from typing import Dict, List

def parse_bgp_peers(raw_output: Dict[str, str], hostname: str) -> List[Dict]:
    """Parse 'display bgp peer' output from HPE Comware"""
    peers = []
    text = "\n".join(raw_output.values())

    # Public peers
    public_pattern = re.compile(
        r"^\s*(\d+\.\d+\.\d+\.\d+)\s+\d+\s+\d+\s+\d+\s+\w+\s+\w+\s+(\w+)"
    )
    for line in text.splitlines():
        m = public_pattern.match(line.strip())
        if m:
            state = "Established" if "Established" in line else m.group(2)
            peers.append({
                "hostname": hostname,
                "neighbor_ip": m.group(1),
                "vpn_instance": "",
                "state": state,
                "uptime": _extract_bgp_uptime(line),
                "prefix_received": 0,
            })

    # VPN-Instance peers
    vpn_pattern = re.compile(
        r"VPN-Instance\s+([^\s,]+),.*?^\s*(\d+\.\d+\.\d+\.\d+).*?(\w+).*?(\d+)\s+prefixes",
        re.DOTALL | re.MULTILINE
    )
    for match in vpn_pattern.finditer(text):
        peers.append({
            "hostname": hostname,
            "neighbor_ip": match.group(2),
            "vpn_instance": match.group(1),
            "state": match.group(3),
            "uptime": "",
            "prefix_received": int(match.group(4) or 0),
        })

    return peers


def parse_ospf_peers(raw_output: Dict[str, str], hostname: str) -> List[Dict]:
    """Parse 'display ospf peer verbose' from HPE Comware"""
    peers = []
    text = raw_output.get("display ospf peer verbose", "")

    blocks = re.split(r"Neighbor Address", text, flags=re.IGNORECASE)[1:]

    for block in blocks:
        peer = {
            "hostname": hostname,
            "process": 1,
            "neighbor_address": "",
            "interface": "",
            "state": "",
            "uptime": "",
            "dead_time": "",
            "area": "",
        }

        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", block)
        if not ip_match:
            continue
        peer["neighbor_address"] = ip_match.group(1)

        state_match = re.search(r"State:\s*([^\s\r\n]+)", block)
        if state_match:
            peer["state"] = state_match.group(1).split("/")[0]

        iface_match = re.search(r"Interface:\s*([^\s\(]+)", block)
        if iface_match:
            peer["interface"] = iface_match.group(1)

        area_match = re.search(r"Area:\s*[^\d]*([\d\.]+)", block)
        if area_match:
            peer["area"] = area_match.group(1)

        up_match = re.search(r"Neighbor is up for\s+([\w\d:]+)", block)
        if up_match:
            peer["uptime"] = up_match.group(1)

        dead_match = re.search(r"Dead timer due in\s+([\w\d:]+)", block)
        if dead_match:
            peer["dead_time"] = dead_match.group(1)

        peers.append(peer)

    return peers


def _extract_bgp_uptime(line: str) -> str:
    m = re.search(r"Up for\s+([\w\d:]+)", line, re.IGNORECASE)
    return m.group(1) if m else ""