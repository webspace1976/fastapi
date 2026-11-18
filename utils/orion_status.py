# utils/orion_status.py
"""Public Orion server availability checks (no login required).

Each configured Orion server is checked with a plain HTTPS GET to its
SWIS JSON endpoint WITHOUT credentials. A port counts as up ONLY when
the endpoint answers HTTP 401 (auth required) -- that is the signature
of a live SWIS endpoint demanding credentials. Any other status means
no SWIS here: 17778 answers 405 on all three servers (a different
service that rejects GET), and a missing endpoint 404s. Connection
errors and timeouts count as down. Results are cached briefly so the
login page never waits on a dead server.

Rule settled 2026-11-18 from the live server_status JSON: healthy
SWIS on 17774 -> 401; 17778 -> 405 on every server.

20261118: built for the login-page status dots next to the three Orion
servers (see templates/orion_login.html and the /server_status route).
"""
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

import config.orion_config as orion_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CHECK_TIMEOUT = 3          # seconds per check
CACHE_TTL = 120             # seconds; the login page polls at the same cadence
SWIS_PATH = "/SolarWinds/InformationService/v3/Json/"
DEFAULT_SWIS_PORT = 17774  # same default as session_manager
# Ports probed for every server that does not name its own port: 17774
# is the SWIS port (healthy servers answer 401 there). 17778 is probed
# too, but it is NOT SWIS on any server -- it answers 405 everywhere
# (2026-11-18) -- so it will show down in the per-port detail. Keeping
# it in the probe list makes that visible instead of assumed.
CHECK_PORTS = (17774, 17778)
DEFAULT_SERVERS = ("10.248.217.101", "142.71.111.67", "142.71.111.72")

_cache = {"at": 0.0, "data": None}


def _servers():
    return getattr(orion_config, "ORION_FAILOVER_SERVERS", None) or DEFAULT_SERVERS


def _split_entry(entry):
    """'host' -> (host, None); 'host:port' -> (host, port)."""
    s = (entry or "").strip().lower()
    s = s.replace("https://", "").replace("http://", "")
    s = s.split("/")[0]
    if ":" in s:
        host, port = s.split(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return host, None
    return s, None


def _check_port(host, port):
    """Returns (up, latency_ms, detail). Only HTTP 401 counts as up."""
    url = f"https://{host}:{port}{SWIS_PATH}"
    start = time.monotonic()
    try:
        resp = requests.get(url, timeout=CHECK_TIMEOUT, verify=False)
        if resp.status_code == 401:
            # Auth required: a live SWIS endpoint is here.
            return True, int((time.monotonic() - start) * 1000), "HTTP 401"
        # Anything else is NOT a SWIS endpoint: 405 is what the unrelated
        # service on 17778 answers on every server, 404 means the path is
        # not there at all. Either way the dashboard cannot use this port.
        return False, int((time.monotonic() - start) * 1000), f"HTTP {resp.status_code} (not SWIS)"
    except requests.exceptions.RequestException as e:
        return False, int((time.monotonic() - start) * 1000), type(e).__name__


def get_server_status(force=False):
    """Cached availability for every configured Orion server.

    Returns {"checked_at": ..., "servers": [{"server", "status",
    "ports": {"17774": {"up", "latency_ms", "detail"}, ...}, "port",
    "latency_ms"}]}. "port" is the port to use for this server: the one
    that answered (the app default 17774 is preferred when both answer),
    or None when the server is down on every probed port.
    """
    now = time.monotonic()
    if not force and _cache["data"] is not None and now - _cache["at"] < CACHE_TTL:
        return _cache["data"]

    targets = {}  # host -> [ports]
    for entry in _servers():
        host, port = _split_entry(entry)
        if host:
            targets.setdefault(host, [port] if port else list(CHECK_PORTS))

    jobs = [(host, port) for host, ports in targets.items() for port in ports]
    results = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            for host, port, outcome in pool.map(
                lambda jp: (jp[0], jp[1], _check_port(jp[0], jp[1])), jobs
            ):
                results.setdefault(host, {})[port] = outcome

    servers = []
    for host, ports in targets.items():
        port_info = {}
        up_ports = []
        best_ms = None
        for port in ports:
            up, ms, detail = results.get(host, {}).get(port, (False, None, "not checked"))
            port_info[str(port)] = {"up": up, "latency_ms": ms, "detail": detail}
            if up:
                up_ports.append(port)
                best_ms = ms if best_ms is None else min(best_ms, ms)
        if DEFAULT_SWIS_PORT in up_ports:
            use_port = DEFAULT_SWIS_PORT
        elif up_ports:
            use_port = up_ports[0]
        else:
            use_port = None
        servers.append({
            "server": host,
            "status": "up" if up_ports else "down",
            "ports": port_info,
            "port": use_port,
            "latency_ms": best_ms,
        })

    data = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "servers": servers}
    _cache["at"] = now
    _cache["data"] = data
    return data
