from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class DeviceCheckRequest(BaseModel):
    check_type: str = Field(default="core")
    device_type: Optional[str] = None
    iplist: Optional[str] = None
    interface: Optional[str] = None
    username: str
    password: str
    options: Dict[str, bool] = Field(default_factory=dict)
    bgp_event: Optional[bool] = False

class OrionCheckRequest(BaseModel):
    npm_server: str
    username: str
    password: str
    check_options: Dict[str, bool] = Field(default_factory=dict)
    udt_ip: Optional[str] = None

class MonitorRequest(BaseModel):
    protocol: Optional[str] = None
    hostname: Optional[str] = None
    neighbor: Optional[str] = None
    flush: Optional[bool] = False

class DeviceResponse(BaseModel):
    success: bool
    message: str
    log_file: Optional[str] = None
    results: Optional[List[Dict]] = None

class OrionResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None