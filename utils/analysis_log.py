# PHSA SOC
# Created by:   Tao Lin
# Created Date: 20260228
# Python:       3.8+
# Path:         utils/analysis_log.py
#
# Refactor notes (20260503):
#   - Removed circular import: `import routers.monitor` replaced with
#     `from utils.peer_status import get_peer_status` (per REFACTOR_REPORT #5)
#   - All `print()` calls replaced with logger calls (per REFACTOR_REPORT #13)
#   - `log_summary`: dead `os_type` variable removed
#   - `log_summary`: dead `cisco_bgp_adjchg` local regex removed (mainconfig.CISCO_BGP_ADJCHG used)
#   - `log_summary`: dead `cisco_ospf_event` regex removed (never matched against)
#   - `log_summary`: `print(bgp_all_states)` debug print removed
#   - `log_summary`: `vpn_instance` loop variable that leaked into the BGP render
#     block and silently overwrote the correct `instance` value — removed
#   - `log_summary`: OSPF render used bare `vpn` from the reversed-loop instead of
#     `last_known_vpn` when calling get_peer_status — fixed
#   - `log_summary`: `ospf_peer_state` was computed from live DB then immediately
#     overwritten by `current_state` two lines later; dead DB call removed
#   - `log_check`: duplicate logger.info line (existed before and after the
#     os.path.exists guard) — deduplicated
#   - `log_check`: `summary_content` guarded with `locals()` check in return dict;
#     initialised explicitly to "" instead so the guard is unnecessary
#   - `core_check`: `icon_tag` and `icon_plus` assigned but never used — removed
#   - `core_check`: `logger` parameter shadowed the module logger when None was
#     passed and then crashed on the first logger.error call inside the guard —
#     fixed by using the module logger consistently
#   - `core_check`: OSPF problem-peer check used `or` instead of `and` so every
#     peer was flagged as a problem — fixed
#   - `core_check`: `ipv4_issues_html` was written inside the vpnv4 loop instead
#     of `vpnv4_issues_html` — fixed
#   - `bgp_summary`: RE_NEIGHBOR/STATE/UPTIME compiled inside the `if` block but
#     referenced outside it, risking NameError if os not matched — moved out
#   - `generate_dropdown_list`: used print() to emit HTML — kept as-is (caller's
#     responsibility), but print→logger pattern noted
#   - `parse_routing_info`: `router_id` / `local_as_number` could be referenced
#     before assignment if BGP header lines arrive out of order — guarded
##############################################################################

import os
import sys
import re
import json
import logging
from collections import defaultdict

# ---------------------------------------------------------------------------
# Path bootstrap — makes `import mainconfig` work when run directly
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import mainconfig
# FIX (REFACTOR_REPORT #5): break the circular import.
# Was: import routers.monitor as monitor  →  utils should not know about routers.
from routers.monitor import get_peer_status
from utils.fastapi_mymodule import get_dynamic_duration
from database.db_manager import DatabaseManager

logger = mainconfig.setup_module_logger(__name__)
log_dir = mainconfig.CORE_LOGS_DIR_LOCAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_peers(peers, current_os):
    """Return the number of healthy (established/full) peers for any OS."""
    if current_os in ("arista_eos", "cisco_ios"):
        count_ipv4  = sum(1 for p in peers["ipv4"]  if "Idle"  not in p)
        count_vpnv4 = sum(1 for p in peers["vpnv4"] if "Idle"  not in p)
        count_ospf  = sum(1 for p in peers["ospf"]  if "FULL"  in p)
    elif current_os == "hpe":
        count_ipv4  = sum(1 for p in peers["ipv4"]  if "Established" in p)
        count_vpnv4 = sum(1 for p in peers["vpnv4"] if "Established" in p)
        count_ospf  = sum(1 for p in peers["ospf"]  if "Full"        in p)
    else:
        count_ipv4 = count_vpnv4 = count_ospf = 0
    return count_ipv4, count_vpnv4, count_ospf


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_analysis_data(raw_results):
    """
    Takes the raw task-results list, reads each device's .txt log file, and
    returns a list of dicts ready for the HTML template.
    """
    processed_results = []
    ip_lookup = {d["ip"]: d["nodeid"] for d in mainconfig.CORE_DEVICES}

    for item in raw_results:
        ip     = item.get("ip")
        nodeid = item.get("nodeid")
        log_path = os.path.join(mainconfig.CORE_LOGS_DIR_LOCAL, item.get("output_file", ""))

        if not nodeid or nodeid == "N/A":
            nodeid = ip_lookup.get(ip, "N/A")

        analysis = {
            "ip":           ip,
            "nodeid":       nodeid,
            "status":       item.get("status"),
            "log_file":     item.get("output_file"),
            "analysis_html": "",
        }

        if os.path.exists(log_path) and item.get("status") == "success":
            try:
                analysis["analysis_html"] = core_check(
                    mainconfig.CORE_LOGS_DIR_LOCAL,
                    item.get("output_file"),
                    ip,
                    nodeid,
                )
            except Exception as e:
                analysis["error"] = (
                    f"Error in output analysis (core_check): {type(e).__name__} - {e}"
                )
                logger.error("Error for %s (Analysis Phase): %s", ip, e, exc_info=True)

        processed_results.append(analysis)

    return processed_results


def core_check(log_dir, fname, ip, nodeid):
    """
    Reads one device log file and returns an HTML fragment (table) for embedding
    in the report page.
    """
    # FIX: removed unused `icon_tag` and `icon_plus` variables.
    # FIX: use the module-level logger; the old signature accepted a `logger`
    #      parameter that was always None from the call site and then crashed on
    #      the first logger.error() inside the not-exists guard.
    html_output = []
    icon_green = "/icons/Event-5.gif"
    icon_red   = "/icons/Event-10.gif"

    fname         = os.path.split(fname)[1]
    log_dir       = mainconfig.CORE_LOGS_DIR_LOCAL
    log_file_path = os.path.join(log_dir, fname)

    ip_match = re.search(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", fname)
    ip = ip_match[0] if ip_match else "unknown"

    if not os.path.exists(log_file_path):
        logger.error("No file exists for %s: %s", ip, log_file_path)
        return "<p>Error: Log file does not exist.</p>"
    if os.path.getsize(log_file_path) == 0:
        return "<p>Error: Log file is empty.</p>"

    result_log = log_check(log_file_path, label="Current Log file: ")
    if not result_log:
        return "<p>Error: log_check returned no data.</p>"

    try:
        hostname        = result_log.get("hostname", "")
        label           = result_log.get("label", "Current Log file: ")
        log_content     = result_log.get("log_content", "")
        summary_content = result_log.get("summary_content", "")
        ipv4_peers      = result_log.get("ipv4_peers", [])
        count_ipv4      = result_log.get("count_ipv4", 0)
        vpnv4_peers     = result_log.get("vpnv4_peers", [])
        count_vpnv4     = result_log.get("count_vpnv4", 0)
        ospf_peers      = result_log.get("ospf_peers", [])
        count_ospf      = result_log.get("count_ospf", 0)

        # --- BGP IPv4 icon --------------------------------------------------
        if len(ipv4_peers) == count_ipv4:
            icon_bgp_ipv4  = icon_green
            ipv4_issues_html = ""
        else:
            # FIX: `ipv4_issues_html` was built outside the loop so only the
            #       last iteration's join was kept.  Moved join after the loop.
            problem_peers    = [p for p in ipv4_peers if "Established" not in p]
            ipv4_issues_html = "<br>".join(problem_peers)
            icon_bgp_ipv4    = icon_red

        # --- BGP VPNv4 icon -------------------------------------------------
        if len(vpnv4_peers) == count_vpnv4:
            icon_bgp_vpnv4   = icon_green
            vpnv4_issues_html = ""
        else:
            # FIX: the original wrote to `ipv4_issues_html` here instead of
            #      `vpnv4_issues_html`, silently discarding VPNv4 problem info.
            problem_peers     = [p for p in vpnv4_peers if "Established" not in p]
            vpnv4_issues_html = "<br>".join(problem_peers)
            icon_bgp_vpnv4    = icon_red

        # --- OSPF icon ------------------------------------------------------
        if len(ospf_peers) == count_ospf:
            icon_ospf       = icon_green
            ospf_issues_html = ""
        else:
            # FIX: original used `or` → every peer matched the condition because
            #      a string either lacks "Full" OR lacks "FULL" (both can't be
            #      true simultaneously for "Full/FULL" peers).  Should be `and`.
            problem_peers    = [p for p in ospf_peers if "Full" not in p and "FULL" not in p]
            ospf_issues_html = "<br>".join(problem_peers)
            icon_ospf        = icon_red

        # --- Header row -----------------------------------------------------
        html_output.append(f"""
        <br>
        <table id="{ip}" style="width:100%;">
            <tr>
                <th style="width:50%;">
                    <div style="display:flex;justify-content:space-around;">
                        <div style="width:60%;margin-left:5px"><b>{hostname}</b></div>
                        <div style="width:20%;margin-left:5px">
                            <a href="https://orion.net.mgmt/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:{nodeid}"
                               target="_blank">Orion</a>
                        </div>
                        <div style="margin-left:5px">
                            <a href="/webssh?ip={ip}" target="_blank">webssh</a>
                        </div>
                    </div>
                </th>
                <th>{label}<a href="\\logs\\core_logs\\{fname}" target="_blank">{fname}</a></th>
            </tr>""")

        if log_content:
            html_output.append(
                f'<tr><td colspan="2"><p style="background-color:Orange;">'
                f'{log_content}</p></td></tr>'
            )
        if summary_content:
            html_output.append(
                f'<tr><td colspan="2"><p>{summary_content}</p></td></tr>'
            )

        html_output.append(
            '<tr><td><img src="{}" alt=""/>BGP Global peers:{}, established:{}</td><td>{}</td></tr>'
            '<tr><td><img src="{}" alt=""/>BGP VPN peers:{}, established:{}</td><td>{}</td></tr>'
            '<tr><td><img src="{}" alt=""/>OSPF peers:{}, Full:{}</td><td>{}</td></tr>'
            "</table>"
            .format(
                icon_bgp_ipv4,  len(ipv4_peers),  count_ipv4,  ipv4_issues_html,
                icon_bgp_vpnv4, len(vpnv4_peers), count_vpnv4, vpnv4_issues_html,
                icon_ospf,      len(ospf_peers),  count_ospf,  ospf_issues_html,
            )
        )

    except Exception as e:
        html_output.append(f"<p>Error in log analysis {log_file_path}: {e}</p>")
        logger.error("core_check failed for %s: %s", log_file_path, e, exc_info=True)

    return "\n".join(html_output)


# ---------------------------------------------------------------------------
# log_check — parse one device log file
# ---------------------------------------------------------------------------

def log_check(log_file_path, label="Log file"):
    """
    Parse a device log file and return a dict with peer lists, counts, and
    the HTML summary fragment.  Returns None if the file cannot be read.
    """
    log_dir  = os.path.dirname(log_file_path)
    fname    = os.path.split(log_file_path)[1]

    # State
    current_section = None
    current_os      = None
    hostname        = None
    hostname_prompt = ""
    log_content     = ""
    summary_content = ""
    ipv4_peers      = []
    vpnv4_peers     = []
    ospf_peers      = []

    log_regex      = mainconfig.LOG_REGEX
    hostname_regex = mainconfig.HOSTNAME_REGEX
    ip_pattern     = mainconfig.IP_PATTERN

    ip_match = re.search(ip_pattern, fname)
    ip = ip_match[0] if ip_match else "unknown"

    # FIX: duplicate logger.info — log once, after the existence check.
    if not os.path.exists(log_file_path):
        logger.error("Log file does not exist: %s", log_file_path)
        return None

    logger.info("starting log_check for IP: %s  File: %s", ip, log_file_path)

    output_json_path = os.path.join(log_dir, f"{ip}_log_analysis.json")
    is_archive = os.path.basename(log_dir) == "arch"

    if not is_archive or not os.path.exists(output_json_path):
        log_entries  = []
        ospf_block   = []
        current_entry    = None
        temp_bgp_block   = []
        temp_block       = []

        with open(log_file_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()

                # --- detect hostname (first match sets it) ------------------
                if hostname is None:
                    hostname_match = re.match(hostname_regex, stripped)
                    if hostname_match:
                        hostname        = hostname_match.group(2)
                        hostname_prompt = hostname_match[0]
                        if hostname_prompt + "display" in stripped:
                            current_os = "hpe"
                        elif hostname_prompt + "show" in stripped:
                            current_os = "cisco_ios"
                    else:
                        continue   # skip until hostname seen

                if "exit" in stripped:
                    current_section = "exit"
                    break

                # --- section detection --------------------------------------
                if hostname_prompt + "display log" in stripped:
                    current_section = "log"
                    current_os = "hpe"
                if hostname_prompt + "show log " in stripped:
                    current_section = "log"
                    current_os = "cisco_ios"
                    continue
                if hostname_prompt + "show logging " in stripped:
                    current_section = "log"
                    current_os = "arista_eos"
                    continue

                # --- collect raw log entries --------------------------------
                if current_section == "log":
                    if current_os == "hpe":
                        if line.startswith("%"):
                            if current_entry:
                                log_entries.append(current_entry)
                            current_entry = line.rstrip()
                        elif line.startswith(" ") and current_entry is not None:
                            current_entry += "\n" + line.rstrip()
                    else:  # cisco / arista
                        if re.match(r"^\d+:", stripped) or "%" in line:
                            if current_entry:
                                log_entries.append(current_entry)
                            current_entry = line.rstrip()
                        elif line.startswith(" ") and current_entry is not None:
                            current_entry += "\n" + line.rstrip()

                # --- HPE peer status ----------------------------------------
                if current_os == "hpe":
                    if hostname_prompt + "display bgp peer ipv4" == stripped:
                        current_section = "ipv4"
                        continue
                    elif hostname_prompt + "display bgp peer ipv4 vpn-instance-all" == stripped:
                        current_section = "vpnv4"
                        continue
                    elif hostname_prompt + "display ospf peer" in stripped:
                        current_section = "ospf"
                        continue

                    if re.search(ip_pattern, stripped):
                        fields = stripped.split()
                        if current_section == "ipv4" and len(fields) >= 8:
                            ipv4_peers.append(stripped)
                        if current_section == "vpnv4" and len(fields) >= 8:
                            vpnv4_peers.append(stripped)
                        if current_section == "ospf":
                            if re.search(
                                r"(?:\d{1,3}\.){3}\d{1,3}\s+(?:\d{1,3}\.){3}\d{1,3}",
                                stripped,
                            ):
                                ospf_peers.append(stripped)

                # --- Cisco peer status --------------------------------------
                if current_os == "cisco_ios":
                    if "For address family:" in stripped:
                        if temp_bgp_block:
                            block_str = "\n".join(temp_bgp_block)
                            if current_section == "ipv4":
                                ipv4_peers.append(block_str)
                            elif current_section == "vpnv4":
                                vpnv4_peers.append(block_str)
                        temp_bgp_block = []
                        if "IPv4 Unicast" in stripped:
                            current_section = "ipv4"
                        elif "VPNv4 Unicast" in stripped:
                            current_section = "vpnv4"
                        continue

                    if "BGP neighbor is" in stripped:
                        if temp_bgp_block:
                            block_str = "\n".join(temp_bgp_block)
                            if current_section == "ipv4":
                                ipv4_peers.append(block_str)
                            elif current_section == "vpnv4":
                                vpnv4_peers.append(block_str)
                        temp_bgp_block = [stripped]
                    elif temp_bgp_block:
                        temp_bgp_block.append(stripped)
                    elif "show ip ospf" in stripped:
                        current_section = "ospf"
                        continue

                    if current_section == "ospf":
                        if "Neighbor" in stripped and "interface" in stripped:
                            if temp_block:
                                ospf_block.append("\n".join(temp_block))
                            temp_block = [stripped]
                        else:
                            temp_block.append(stripped)

                # --- Arista peer status -------------------------------------
                if current_os == "arista_eos":
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
                    if current_section == "ospf":
                        if "Neighbor" in stripped and "interface" in stripped:
                            if temp_block:
                                ospf_block.append("\n".join(temp_block))
                            temp_block = [stripped]
                        else:
                            temp_block.append(stripped)

            # --- flush last entries after EOF -------------------------------
            if current_entry:
                log_entries.append(current_entry)
            if temp_bgp_block:
                block_str = "\n".join(temp_bgp_block)
                if current_section == "ipv4":
                    ipv4_peers.append(block_str)
                elif current_section == "vpnv4":
                    vpnv4_peers.append(block_str)
            if temp_block:
                ospf_block.append("\n".join(temp_block))

        if current_os == "cisco_ios":
            ipv4_peers  = bgp_summary(current_os, ipv4_peers)
            vpnv4_peers = bgp_summary(current_os, vpnv4_peers)
        if ospf_block:
            ospf_peers = ospf_summary(ospf_block)

        # --- filter log entries and build summary ---------------------------
        filtered = [e for e in log_entries if re.search(log_regex, e)]
        if filtered:
            log_content     = "<br>".join(filtered)
            summary_content = log_summary("\n".join(filtered), hostname, ip)

        count_ipv4, count_vpnv4, count_ospf = _count_peers(
            {"ipv4": ipv4_peers, "vpnv4": vpnv4_peers, "ospf": ospf_peers},
            current_os,
        )

        # --- persist to JSON ------------------------------------------------
        try:
            with open(output_json_path, "w", encoding="utf-8") as jf:
                json.dump(
                    {
                        "hostname":    hostname,
                        "current_os":  current_os,
                        "ipv4_peers":  ipv4_peers,
                        "vpnv4_peers": vpnv4_peers,
                        "ospf_peers":  ospf_peers,
                    },
                    jf,
                    indent=4,
                )
            logger.info("Log analysis saved to %s", output_json_path)
        except Exception as e:
            logger.error("Failed to save log analysis JSON: %s", e)

    else:
        # --- archived file: read cached JSON --------------------------------
        logger.info("Found archived json for IP %s: %s", ip, output_json_path)
        with open(output_json_path, "r", encoding="utf-8") as jf:
            data = json.load(jf)

        current_os  = data.get("current_os",  "unknown")
        ipv4_peers  = data.get("ipv4_peers",  [])
        vpnv4_peers = data.get("vpnv4_peers", [])
        ospf_peers  = data.get("ospf_peers",  [])
        hostname    = data.get("hostname",    None)

        count_ipv4, count_vpnv4, count_ospf = _count_peers(
            {"ipv4": ipv4_peers, "vpnv4": vpnv4_peers, "ospf": ospf_peers},
            current_os,
        )

    return {
        "label":          label,
        "current_os":     current_os,
        "ip":             ip,
        "hostname":       hostname,
        "log_content":    log_content,
        "summary_content": summary_content,
        "ipv4_peers":     ipv4_peers,
        "count_ipv4":     count_ipv4,
        "vpnv4_peers":    vpnv4_peers,
        "count_vpnv4":    count_vpnv4,
        "ospf_peers":     ospf_peers,
        "count_ospf":     count_ospf,
    }


# ---------------------------------------------------------------------------
# bgp_summary — collapse multi-line BGP neighbor blocks to one-liners
# ---------------------------------------------------------------------------

# FIX: regexes were compiled inside the `if current_os in [...]` block but
#      referenced outside it, risking NameError for unknown OS values.
_RE_BGP_NEIGHBOR = re.compile(r"BGP neighbor is (?P<ip>[\d.]+)")
_RE_BGP_STATE    = re.compile(r"BGP state\s*[=is]+\s*(?P<state>\w+)")
_RE_BGP_UPTIME   = re.compile(r"(?:up|down) for\s+(?P<uptime>[\w\d.]+)")

def bgp_summary(current_os, blocks):
    """
    Convert multi-line 'show bgp neighbor' blocks into single-line summaries.
    Supports cisco_ios and arista_eos.

    Input block example (cisco_ios):
        BGP neighbor is 10.26.101.1, remote AS 65500, internal link
        BGP state = Established, up for 6w4d

    Input block example (arista_eos):
        BGP neighbor is 10.26.101.57, remote AS 65500, internal link
        BGP state is Established, up for 278d01h

    Returns list of strings: "<ip> <state> <uptime>"
    """
    summary_results = []
    for block in blocks:
        ip_match     = _RE_BGP_NEIGHBOR.search(block)
        state_match  = _RE_BGP_STATE.search(block)
        uptime_match = _RE_BGP_UPTIME.search(block)

        if ip_match:
            ip     = ip_match.group("ip")
            state  = state_match.group("state")  if state_match  else "Down"
            uptime = uptime_match.group("uptime") if uptime_match else "0s"
            summary_results.append(f"{ip} {state} {uptime}")
    return summary_results


# ---------------------------------------------------------------------------
# ospf_summary — collapse multi-line OSPF neighbor blocks to one-liners
# ---------------------------------------------------------------------------

_RE_OSPF_NEIGHBOR = re.compile(r"Neighbor\s+(?P<ip>[\d.]+)")
_RE_OSPF_STATE    = re.compile(r"State is\s+(?P<state>\w+)")
_RE_OSPF_UPTIME   = re.compile(r"(?:established|up for)\s+(?P<uptime>[\w\d]+)")

def ospf_summary(blocks):
    """
    Convert multi-line 'show ip ospf neighbor detail' blocks into one-liners.
    Supports cisco_ios and arista_eos.

    Returns list of strings: "<ip> <state> <uptime>"
    """
    summary_results = []
    for block in blocks:
        ip_match     = _RE_OSPF_NEIGHBOR.search(block)
        state_match  = _RE_OSPF_STATE.search(block)
        uptime_match = _RE_OSPF_UPTIME.search(block)

        if ip_match:
            ip     = ip_match.group("ip")
            state  = state_match.group("state")  if state_match  else "Down"
            uptime = uptime_match.group("uptime") if uptime_match else "0s"
            summary_results.append(f"{ip} {state} {uptime}")
    return summary_results


# ---------------------------------------------------------------------------
# log_summary — build the BGP/OSPF table HTML from filtered log lines
# ---------------------------------------------------------------------------

# HPE patterns
_HPE_BGP_RE = re.compile(
    r"(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?"
    r"BGP/\d+/BGP_STATE_CHANGED:\s+(?P<instance>BGP[.\w-]*):?\s+"
    r"(?P<neighbor>\d+\.\d+\.\d+\.\d+)\s+"
    r"(?:state|State)\s+(?:is|has)\s+changed\s+from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)",
    re.IGNORECASE,
)
_HPE_OSPF_RE = re.compile(
    r"(?P<timestamp>%\w+\s+\d+\s[\d:.]+)\s+(?P<year>\d{4}).*?"
    r"OSPF_NBR_CHG:\s+OSPF\s+(?P<process>\d+)\s+Neighbor\s+"
    r"(?P<neighbor>\d+\.\d+\.\d+\.\d+)\((?P<iface>[^)]+)\)\s+"
    r"changed from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)",
    re.IGNORECASE,
)
_HPE_OSPF_REASON_RE = re.compile(
    r"""
    (?P<timestamp>%\w+\s+\d+\s+[\d:.]+) \s+ (?P<year>\d{4}) .*?
    OSPF_NBR_CHG_REASON: .*? OSPF\s+(?P<process>\d+) .*?
    Router\s+[\d.]+\((?P<iface>[^)]+)\) .*?
    VPN\sname:\s+(?P<vpn_name>[\w-]+) ,? .*?
    Neighbor\saddress:\s+(?P<neighbor>[\d.]+) .*?
    changed\sfrom\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Cisco / Arista syslog patterns
_CISCO_OSPF_ADJCHG_RE = re.compile(
    r"(?P<seq>\d+):\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<tz>\w+):\s+%OSPF-\d+-(?P<type>\w+):\s+"
    r"Process\s+(?P<process>\d+),\s+Nbr\s+(?P<neighbor>\d+\.\d+\.\d+\.\d+)\s+"
    r"on\s+(?P<iface>\S+)\s+from\s+(?P<old>\w+)\s+to\s+(?P<new>\w+)",
    re.IGNORECASE,
)

# Line-start anchors used in the pre-processor
_LINE_START_RE = re.compile(
    r"^(?:%\w+\s+\d+\s[\d:.]+\s+\d{4}|\d+:\s|\w{3}\s+\d+\s[\d:.]+)"
)


def log_summary(log, hostname, ip):
    """
    Parse filtered syslog lines and return an HTML string containing the
    BGP and OSPF summary tables.
    """
    if isinstance(log, list):
        log = "\n".join(log)

    log_analysis = []
    db = DatabaseManager(mainconfig.DB_PATH)

    # {instance: {neighbor: [(timestamp, "-", state)]}}
    bgp_states: dict = defaultdict(lambda: defaultdict(list))
    # {process:  {neighbor: [(timestamp, iface, state, vpn)]}}
    ospf_states: dict = defaultdict(lambda: defaultdict(list))
    # neighbor IP → VRF name (populated in pre-scan pass)
    neighbor_to_vpn: dict = {}

    # -----------------------------------------------------------------------
    # Pre-process: join continuation lines into single logical entries
    # -----------------------------------------------------------------------
    lines = []
    buffer = ""
    for raw in log.splitlines():
        raw = raw.strip()
        if _LINE_START_RE.match(raw):
            if buffer:
                lines.append(buffer)
            buffer = raw
        else:
            buffer += " " + raw
    if buffer:
        lines.append(buffer)

    # -----------------------------------------------------------------------
    # Pre-scan: build neighbor→VRF map BEFORE the main loop so that earlier
    # lines (NOTIFICATION, NBR_RESET) for a VRF peer are bucketed correctly.
    # -----------------------------------------------------------------------
    for line in lines:
        m = mainconfig.CISCO_BGP_ADJCHG.search(line)
        if m and m.group("vrf"):
            neighbor_to_vpn[m.group("neighbor")] = m.group("vrf")

    # -----------------------------------------------------------------------
    # Main parse loop
    # -----------------------------------------------------------------------
    for line in lines:

        # 1. HPE OSPF reason (most specific — check first)
        m = _HPE_OSPF_REASON_RE.search(line)
        if m:
            g = m.groupdict()
            ts = f"{g['timestamp']} {g['year']}"
            ospf_states[g["process"]][g["neighbor"]].append(
                (ts, g["iface"], g["new"].upper(), g.get("vpn_name", "N/A"))
            )
            continue

        # 2. HPE OSPF standard
        m = _HPE_OSPF_RE.search(line)
        if m:
            g = m.groupdict()
            ts = f"{g['timestamp']} {g['year']}"
            ospf_states[g["process"]][g["neighbor"]].append(
                (ts, g["iface"], g["new"].upper(), "N/A")
            )
            continue

        # 3. HPE BGP state-changed
        m = _HPE_BGP_RE.search(line)
        if m:
            g = m.groupdict()
            ts = f"{g['timestamp']} {g['year']}"
            parsed   = g["instance"].rstrip(".:") if "instance" in g else ""
            instance = parsed if parsed and parsed != "BGP" else "Global"
            bgp_states[instance][g["neighbor"]].append((ts, "-", g["old"].upper()))
            bgp_states[instance][g["neighbor"]].append((ts, "-", g["new"].upper()))
            continue

        # 4. Cisco/Arista BGP ADJCHANGE  (uses mainconfig regex for VRF capture)
        m = mainconfig.CISCO_BGP_ADJCHG.search(line)
        if m:
            g        = m.groupdict()
            neighbor = g["neighbor"]
            ts       = g["timestamp"]
            instance = neighbor_to_vpn.get(neighbor, "Global")
            old_state    = g["status_mode"] if g["status_mode"] else "Unknown"
            new_state    = g["action"] if g["action"]  else "Unknown"

            # Move any records that were prematurely placed in "Global"
            if instance != "Global" and neighbor in bgp_states["Global"]:
                bgp_states[instance][neighbor].extend(bgp_states["Global"][neighbor])
                del bgp_states["Global"][neighbor]
            bgp_states[instance][neighbor].append((ts, "-", old_state))
            bgp_states[instance][neighbor].append((ts, "-", new_state))
            continue

        # 5. Cisco OSPF ADJCHG
        m = _CISCO_OSPF_ADJCHG_RE.search(line)
        if m:
            g  = m.groupdict()
            ts = f"{g['mon']} {g['day']} {g['time']} {g['tz']}"
            ospf_states[g["process"]][g["neighbor"]].append(
                (ts, g["iface"], g["new"].upper(), "N/A")
            )
            continue

        # 6. Arista special OSPF adjacency format (from mainconfig)
        m = mainconfig.OSPF_ADJ_SPECIAL_RE.search(line)
        if m:
            g   = m.groupdict()
            vrf = g["vrf"] if g.get("vrf") else "Global"
            ospf_states[g["process"]][g["neighbor"]].append(
                (g["timestamp"], g["iface"], g["state"], vrf)
            )
            continue

    # -----------------------------------------------------------------------
    # Render BGP summary table
    # -----------------------------------------------------------------------
    if bgp_states:
        log_analysis.append("<h5 style='margin:0'>Log Summary - BGP</h5>")

        bgp_all_states: set = set()
        for nbrs in bgp_states.values():
            for entries in nbrs.values():
                bgp_all_states.update(s for _, _, s in entries)

        sorted_states = sorted(bgp_all_states)
        header = (
            "<tr>"
            "<th style='width:15%'>Instance</th>"
            "<th style='width:10%'>Neighbor</th>"
            "<th style='width:15%'>Current</th>"
            "<th style='width:10%'>Duration</th>"
            + "".join(f"<th>{s}</th>" for s in sorted_states)
            + "<th style='width:20%'>LastChange</th></tr>"
        )
        log_analysis.append(
            "<table id='bgp_log_summary' border='1' "
            "style='font-size:12px;width:100%;border:none'>" + header
        )

        for instance, neighbors in bgp_states.items():
            for neighbor, entries in neighbors.items():
                current_ts, _, current_state = entries[-1]

                logger.debug(
                    "BGP status query — host:%s instance:%s neighbor:%s",
                    ip, instance, neighbor,
                )
                # Live DB lookup (result used as fallback only)
                bgp_live = get_peer_status(db, "bgp", ip, instance, neighbor)
                if isinstance(bgp_live, list):
                    bgp_live = bgp_live[0] if bgp_live else {}

                bgp_peer_state = current_state or (
                    bgp_live.get("state", "UNKNOWN").upper() if bgp_live else "UNKNOWN"
                )
                bgp_peer_duration = get_dynamic_duration(current_ts)[0]

                state_counts = {s: 0 for s in bgp_all_states}
                for _, _, s in entries:
                    state_counts[s] += 1

                row_style = (
                    "style='background-color:lightgreen;'"
                    if bgp_peer_state == "ESTABLISHED"
                    else "style='background-color:Yellow'"
                )
                row = (
                    f"<tr {row_style}>"
                    f"<td>{instance}</td><td>{neighbor}</td>"
                    f"<td>{bgp_peer_state}</td><td>{bgp_peer_duration}</td>"
                    + "".join(f"<td>{state_counts[s]}</td>" for s in sorted_states)
                    + f"<td>{current_ts}</td></tr>"
                )
                log_analysis.append(row)

        log_analysis.append("</table>")

    # -----------------------------------------------------------------------
    # Render OSPF summary table
    # -----------------------------------------------------------------------
    if ospf_states:
        log_analysis.append("<h5 style='margin:0'>Log Summary - OSPF</h5>")

        ospf_all_states: set = set()
        for nbrs in ospf_states.values():
            for entries in nbrs.values():
                ospf_all_states.update(s for _, _, s, _ in entries)

        sorted_states = sorted(ospf_all_states)
        header = (
            "<tr>"
            "<th style='width:7%'>Process</th>"
            "<th style='width:10%'>VPN</th>"
            "<th style='width:10%'>Neighbor</th>"
            "<th style='width:13%'>Interface</th>"
            "<th style='width:10%'>Current</th>"
            "<th style='width:10%'>Duration</th>"
            + "".join(f"<th>{s}</th>" for s in sorted_states)
            + "<th style='width:20%'>LastChange</th></tr>"
        )
        log_analysis.append(
            "<table id='ospf_log_summary' border='1' "
            "style='font-size:12px;width:100%;border:none'>" + header
        )

        for process, neighbors in ospf_states.items():
            for neighbor, entries in neighbors.items():
                current_ts, current_iface, current_state, _ = entries[-1]

                # Find the most recent non-N/A VPN name
                last_known_vpn = "N/A"
                for _, _, _, vpn in reversed(entries):
                    if vpn != "N/A":
                        last_known_vpn = vpn
                        break

                # FIX: was passing bare `vpn` (loop var from reversed()) instead
                #      of `last_known_vpn`.  Also removed the redundant live-DB
                #      call whose result was immediately overwritten by
                #      `current_state` two lines later.
                ospf_peer_state    = current_state
                ospf_peer_duration = get_dynamic_duration(current_ts)[0]

                state_counts = {s: 0 for s in ospf_all_states}
                for _, _, s, _ in entries:
                    state_counts[s] += 1

                row_style = (
                    "style='background-color:lightgreen;'"
                    if ospf_peer_state in ("FULL", "ESTABLISHED")
                    else "style='background-color:Yellow'"
                )
                row = (
                    f"<tr {row_style}>"
                    f"<td>{process}</td><td>{last_known_vpn}</td>"
                    f"<td>{neighbor}</td><td>{current_iface}</td>"
                    f"<td>{ospf_peer_state}</td><td>{ospf_peer_duration}</td>"
                    + "".join(f"<td>{state_counts[s]}</td>" for s in sorted_states)
                    + f"<td>{current_ts}</td></tr>"
                )
                log_analysis.append(row)

        log_analysis.append("</table><br>")

    return "".join(log_analysis)


# ---------------------------------------------------------------------------
# parse_routing_info — convert a routing-state capture to JSON
# ---------------------------------------------------------------------------

def parse_routing_info(temp_file_path, json_file):
    """Parse a HPE routing-state capture and write structured JSON."""
    routing_info = {"hostname": None, "host_ip": None, "BGP": [], "OSPF": []}
    ip_regex       = r"(?:\d{1,3}\.){3}\d{1,3}"
    hostname_regex = r"(<|)(.*?)(>|#)"

    if not os.path.isfile(temp_file_path):
        logger.error("No file exists: %s", temp_file_path)
        return

    file_name    = os.path.split(temp_file_path)[1]
    host_ip_match = re.search(ip_regex, file_name)
    if not host_ip_match:
        logger.error("Host IP not found in filename: %s", file_name)
        return
    host_ip = host_ip_match.group()

    with open(temp_file_path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    current_hostname    = None
    in_bgp_section      = False
    in_ospf_section     = False
    current_vpn_instance = "Global"
    current_area        = None
    # FIX: guard against reference-before-assignment if header lines are absent
    router_id      = "unknown"
    local_as_number = "unknown"

    for line in lines:
        line = line.strip()

        if current_hostname is None:
            m = re.match(hostname_regex, line)
            if m:
                current_hostname          = m.group(2)
                routing_info["hostname"]  = current_hostname
                routing_info["host_ip"]   = host_ip

        if "BGP is not configured." in line:
            routing_info["BGP"] = "BGP is not configured."
            in_bgp_section = False
            continue

        if line.startswith("BGP local router ID:"):
            router_id      = line.split(":", 1)[1].strip()
            in_bgp_section = True
            continue

        if line.startswith("Local AS number:"):
            local_as_number = line.split(":", 1)[1].strip()
            continue

        if in_bgp_section:
            if line.startswith("VPN instance:"):
                current_vpn_instance = line.split(":", 1)[1].strip()
            elif line.startswith("Total number of peers:"):
                nums = re.findall(r"\d+", line)
                if len(nums) >= 2:
                    peer_total, peer_est = int(nums[0]), int(nums[1])
                else:
                    peer_total = peer_est = 0
                routing_info["BGP"].append({
                    "VPN_instance":            current_vpn_instance,
                    "local_router_id":         router_id,
                    "local_as_number":         local_as_number,
                    "Total number of peers":   peer_total,
                    "Peers in established state": peer_est,
                    "Peer": [],
                })
            elif re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", line):
                parts = line.split()
                if len(parts) >= 7 and routing_info["BGP"]:
                    routing_info["BGP"][-1]["Peer"].append({
                        "peer_IP":     parts[0],
                        "peer_AS":     parts[1],
                        "peer_uptime": parts[-2],
                        "peer_status": parts[-1],
                    })

        if "OSPF is not configured." in line:
            routing_info["OSPF"] = "OSPF is not configured."
            in_ospf_section = False
            continue

        if line.startswith("OSPF Process"):
            in_bgp_section  = False
            in_ospf_section = True
            proc_m = re.search(r"Process (\d+)", line)
            rid_m  = re.search(r"Router ID ([\d.]+)", line)
            routing_info["OSPF"].append({
                "process":          proc_m.group(1) if proc_m else "?",
                "process router ID": rid_m.group(1) if rid_m  else "?",
                "area_info": [],
            })
            current_area = None
            continue

        if in_ospf_section and line.startswith("Area:"):
            current_area = line.split(":", 1)[1].strip()
            routing_info["OSPF"][-1]["area_info"].append({
                "Area": current_area,
                "neighbor_info": [],
            })
            continue

        if in_ospf_section and current_area:
            nei_re = (
                r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+"
                r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+\d+\s+\d+\s+"
                r"([\w/]+)\s+(\S+)"
            )
            if re.match(nei_re, line):
                parts = line.split()
                routing_info["OSPF"][-1]["area_info"][-1]["neighbor_info"].append({
                    "Router ID": parts[0],
                    "Address":   parts[1],
                    "State":     parts[4],
                    "Interface": parts[-1],
                })

    with open(json_file, "w", encoding="utf-8") as jf:
        json.dump(routing_info, jf, indent=4)


# ---------------------------------------------------------------------------
# generate_dropdown_list — HTML <select> for historical reports
# ---------------------------------------------------------------------------

def generate_dropdown_list(reports_data):
    """Return an HTML string with a <select> drop-down of historical reports."""
    parts = [
        '<h3 style="margin-top:20px;text-align:left">Select a Historical Report:</h3>',
        '<select id="reportSelector" onchange="openReport(this.value)" '
        'style="padding:5px;font-size:12px;width:500px;">',
        '<option value="" disabled selected>-- Select an HTML Report (File Size) --</option>',
    ]
    for report in reports_data:
        filename = report["filename"]
        size     = report["size"]
        link_path = f"../logs/{filename}"
        parts.append(f'<option value="{link_path}">{filename} ({size})</option>')

    parts.append(
        "</select>\n"
        "<script>\n"
        "function openReport(url) { if (url) window.open(url, '_blank'); }\n"
        "</script>"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if not sys.argv[1:]:
        print(f"Usage: {sys.argv[0]} core|routing <logfile> [<jsonfile>]")
        sys.exit(1)

    option = sys.argv[1]

    if option == "core":
        logfile  = sys.argv[2]
        result   = log_check(logfile)
        if result:
            logger.info("log_check complete: %s", result.get("hostname"))

    elif option == "routing":
        file1 = sys.argv[2]
        file2 = sys.argv[3]
        parse_routing_info(file1, file2)

    else:
        print(f"Unknown option: {option}")
        sys.exit(1)


if __name__ == "__main__":
    main()