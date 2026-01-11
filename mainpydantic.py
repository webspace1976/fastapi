# mainpydantic.py
from pydantic import BaseModel, Field, validator, EmailStr
from typing import List, Optional, Dict, Any
import re

# ----------------------------------------------------------------------
# Helper regexes
# ----------------------------------------------------------------------
IP_REGEX = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)
HOSTNAME_REGEX = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,}$"
)


# ----------------------------------------------------------------------
# Orion request model – GET / POST
# ----------------------------------------------------------------------
class OrionCheckRequest(BaseModel):
    npm_server: str = Field(
        ...,
        min_length=1,
        max_length=253,
        description="Orion server FQDN or IP (port will be stripped)",
        example="orion.net.mgmt"
    )
    username: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Orion login name",
        example="admin"
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Orion password (plain-text, will be sent over HTTPS only)",
        example="s3cr3t"
    )
    check_options: Dict[str, bool] = Field(
        default_factory=dict,
        description="Which checks to run. Keys are strings, values are coerced to bool."
    )
    udt_ip: Optional[str] = Field(
        None,
        pattern=r"^(\d{1,3}\.){3}\d{1,3}$",  # Changed from regex to pattern
        description="Optional UDT lookup IP (must be a valid IPv4 address)",
        example="10.10.5.22"
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @validator("npm_server")
    def clean_server(cls, v: str) -> str:
        """Strip accidental :port and force lower-case."""
        return v.split(":")[0].strip().lower()

    @validator("check_options", pre=True, always=True)
    def coerce_bools(cls, v):
        """Accept anything that can be cast to bool (on/off, true/false, 1/0, etc.)"""
        if v is None:
            return {}
        return {k: bool(v) for k, v in v.items()}

    @validator("udt_ip")
    def validate_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not IP_REGEX.match(v):
            raise ValueError("udt_ip must be a valid IPv4 address")
        return v

class OrionResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ----------------------------------------------------------------------
# Device-check model 
# ----------------------------------------------------------------------
class DeviceCheckRequest(BaseModel):
    check_type: str = Field(
        "core",
        pattern=r"^(core|udt|bgp|ospf|realtime)$",
        description="Type of device check"
    )
    device_type: Optional[str] = Field(
        None,
        max_length=50,
        description="Optional device classification"
    )
    iplist: Optional[str] = Field(
        None,
        description="Comma-separated list of IPs. Each must be valid IPv4."
    )
    interface: Optional[str] = Field(
        None,
        max_length=100,
        description="Interface name (e.g. GigabitEthernet0/1)"
    )
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=200)
    options: Dict[str, bool] = Field(default_factory=dict)
    bgp_event: Optional[bool] = False

    @validator("iplist")
    def split_and_validate_ips(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        ips = [ip.strip() for ip in v.split(",")]
        for ip in ips:
            if not IP_REGEX.match(ip):
                raise ValueError(f"Invalid IP in iplist: {ip}")
        return ",".join(ips)

class DeviceResponse(BaseModel):
    success: bool
    message: str
    log_file: Optional[str] = None
    results: Optional[List[Dict]] = None

# ----------------------------------------------------------------------
# Misc models 
# ----------------------------------------------------------------------
class MonitorRequest(BaseModel):
    protocol: Optional[str] = Field(None, pattern=r"^(bgp|ospf)$")
    hostname: Optional[str] = Field(None, max_length=253)
    neighbor: Optional[str] = Field(None, max_length=253)
    flush: Optional[bool] = False




