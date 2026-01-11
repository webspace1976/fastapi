# scripts/config.py

import logging, os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Base paths
# BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"
ICONS_DIR = STATIC_DIR / "icons"
TEMPLATES_DIR = BASE_DIR / "templates"
SESSION_DIR = DATA_DIR / "orion_sessions"
ALERT_LOG_PATH = os.path.join(LOGS_DIR, "alert_center.log")

# Database settings
DB_PATH = DATA_DIR / "network_analysis.db"

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


# Core devices
CORE_DEVICES = [
    {"os": "hp_comware", "ip": "10.102.102.80", "name": "LAB-eNG-KEL-Core"},
    {"os": "hp_comware", "ip": "10.102.102.79", "name": "LAB-eNG-KAM-Core"},
    {"os": "hp_comware", "ip": "10.8.8.15", "name": "LAB-eNG-CC-Core"},
    {"os": "hp_comware", "ip": "10.8.8.16", "name": "LAB-eNG-CW-Core"},
    {"os": "hp_comware", "ip": "10.251.0.75", "name": "KDC-R4.7-Core-1"},
    {"os": "hp_comware", "ip": "10.251.0.76", "name": "KDC-R4.23-Core-2"},
    {"os": "hp_comware", "ip": "10.251.18.216", "name": "KDC-DMZ-KAM"},
    {"os": "hp_comware", "ip": "10.251.18.217", "name": "KDC-DMZ-KEL"},
    {"os": "cisco_ios", "ip": "10.26.101.127", "name": "NS-LGH-LGAC-01A-C9600-Core1"},
    {"os": "cisco_ios", "ip": "10.26.101.128", "name": "NS-LGH-LGAC-PIMS-C9600-Core2"},
    {"os": "arista_eos", "ip": "10.26.101.7", "name": "VGH-JPS3730-Core1"},
    {"os": "arista_eos", "ip": "10.26.101.8", "name": "VGH-JPNB9-Core-2"},
]


# === Logging Setup ===
def setup_module_logger(name: str = "default") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler = RotatingFileHandler(ALERT_LOG_PATH, maxBytes=5*1024*1024, backupCount=3,encoding="utf-8" )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

# Optional: other environment configs
DEBUG_MODE = True

# orion settings
orion_prefix = "https://orion.net.mgmt"

swis_test='SELECT TOP 3 NodeID, DisplayName FROM Orion.Nodes'
# swis_sitedown= 'SELECT SUM(1) as value, Site FROM (SELECT nodeid,DisplayName,CP.CustomProperties.Site,CP.CustomProperties.SiteType FROM Orion.Nodes CP WHERE CP.Status=2 ) GROUP by site order by value'
swis_nodedown1='SELECT TOP 1000 nodeid,DisplayName,IPAddress,C.CustomProperties.Site,C.CustomProperties.SiteType,C.CustomProperties.DeviceType,location, C.CustomProperties.address, StatusDescription,DetailsUrl, LastBoot FROM Orion.Nodes C WHERE StatusDescription like \'%Node status is Down%\' AND not C.CustomProperties.Site=\'PPN\' ORDER BY C.CustomProperties.Site '
# swis_nodedown2='SELECT N.DetailsUrl,N.NodeName,N.IPAddress,NCP.Site,NCP.SiteType, tolocal(MAX(E.EventTime)) AS DownTime, ToString(DayDiff(0,GETUTCDATE() - MAX(E.EventTime))) + \'d \'  + ToString(Ceiling((HourDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 24.0 - Floor(HourDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 24.0)) * 24 )) + \'h \'+ ToString(Ceiling((MinuteDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 60.0 - Floor(MinuteDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 60.0) ) * 60 )) + \'m \' AS Duration, SecondDiff(0,GETUTCDATE() - MAX(E.EventTime)) as Seconds FROM orion.Nodes N  INNER JOIN orion.Events E ON E.NetworkNode = N.NodeID  INNER JOIN orion.NodesCustomProperties NCP ON NCP.NodeID = N.NodeID  where N.status = 2 and eventtype = 1 and N.IP not like \'%10.200%\' and N.IP not like \'%10.202%\'GROUP BY NCP.Site,N.Caption,NCP.Site,NCP.SiteType,N.DetailsUrl,N.IPAddress order BY Seconds'

# 202509 node/site down list for all node not in up/unmanage/external
swis_sitedown= 'SELECT SUM(1) as value, Site FROM (SELECT nodeid,DisplayName,CP.CustomProperties.Site,CP.CustomProperties.SiteType FROM Orion.Nodes CP WHERE CP.Status NOT IN (1,9,11) ) GROUP by site order by value' 
# 20251023 Add N.NodeID to the swis_nodedown2 query so we can reference NodeID in the node down table (for linking to UDT details).
swis_nodedown2='SELECT N.NodeID,N.DetailsUrl,N.NodeName,N.Status,N.StatusDescription,N.IPAddress,NCP.Site,NCP.SiteType, tolocal(MAX(E.EventTime)) AS DownTime, ToString(DayDiff(0,GETUTCDATE() - MAX(E.EventTime))) + \'d \'  + ToString(Ceiling((HourDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 24.0 - Floor(HourDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 24.0)) * 24 )) + \'h \'+ ToString(Ceiling((MinuteDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 60.0 - Floor(MinuteDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 60.0) ) * 60 )) + \'m \' AS Duration, SecondDiff(0,GETUTCDATE() - MAX(E.EventTime)) as Seconds FROM orion.Nodes N  INNER JOIN orion.Events E ON E.NetworkNode = N.NodeID  INNER JOIN orion.NodesCustomProperties NCP ON NCP.NodeID = N.NodeID  where N.status NOT IN (1,9) and eventtype = 1 and N.IP not like \'%10.200%\' and N.IP not like \'%10.202%\'GROUP BY N.NodeID, N.Status,N.StatusDescription, NCP.Site,N.Caption,NCP.Site,NCP.SiteType,N.DetailsUrl,N.IPAddress order BY Seconds'

swis_bgp="SELECT  rn.NodeID,rr.Caption, rn.NeighborID, ln.Caption as RemoteRouter, rn.NeighborIP, orrp.DisplayName,rn.AutonomousSystem AS RemoteAS, rpsm.DisplayName AS Status, rn.LastChange FROM Orion.Routing.Neighbors rn  left JOIN orion.Nodes n on rn.NodeID=n.NodeID LEFT JOIN orion.Nodes ln on rn.NeighborIP=ln.IPAddress JOIN Orion.Routing.Router rr ON rn.NodeID=rr.NodeID JOIN Orion.Routing.RoutingProtocol orrp on rn.ProtocolID=orrp.ProtocolID JOIN Orion.Routing.RoutingProtocolStateMapping rpsm  ON rn.ProtocolID=rpsm.ProtocolID AND rn.ProtocolStatus=rpsm.ProtocolStatus WHERE orrp.ProtocolID=14 ORDER BY n.Caption"
swis_ospf="SELECT NodeID,n.Caption, NeighborID, NeighborIP, ln.Caption AS RemoteRouter, orrp.DisplayName,   rpsm.DisplayName AS Status   FROM Orion.Routing.Neighbors rn JOIN orion.Nodes n on n.NodeID=rn.NodeID LEFT JOIN orion.Nodes ln on rn.NeighborIP=ln.IPAddress JOIN Orion.Routing.RoutingProtocol orrp on rn.ProtocolID=orrp.ProtocolID LEFT JOIN Orion.Routing.RoutingProtocolStateMapping rpsm  ON rn.ProtocolID=rpsm.ProtocolID AND rn.ProtocolStatus=rpsm.ProtocolStatus WHERE orrp.ProtocolID=13 ORDER BY n.Caption"
swis_nodestatistic="SELECT COUNT(1) as value, Status, CASE WHEN Status = 1 THEN \'Up\' WHEN Status =2 THEN \'Down\' WHEN Status =3 THEN \'warning\' WHEN Status=9 THEN \'Unmanaged\' WHEN Status=11 THEN \'External\' WHEN Status=14 THEN\'Critical\' ELSE \'unknown\' END as NodeStatus FROM Orion.Nodes GROUP BY status ORDER BY value"
swis_ncp="SELECT Site, ONS.DisplayName ,NodeID, Address, Architecture, AssetTag, Building, City, Closest_Poller, Closet, Comments, Configuration, ControlUpEventID, DeviceType, Floor, GAddress, HA, HardwareIncidentStatus, Imported_From_NCM, IncidentStatus, Layer3, LdapTestFailureMessage, Make, New_Poller_Home, NodeOwner, Not_Migrated, OutOfBand, PDIntegrationKey, PONumber, ProgramApplication, ProgramApplicationType, Provider, ProviderSiteID, Rack, Region, ServiceType, SiteContactName, SiteHours, SitePhone, SiteType, Technology, Topology, Unmanaged_, WANbandwidth, WANnode, WANProvider, WANProviderCSID, WANProviderDeviceID FROM Orion.NodesCustomProperties ONCP INNER JOIN Orion.Nodes ONS ON ONCP.NodeID = ONS.NodeID ORDER BY Site"
swis_alert="SELECT TOP 150 OAO.EntityDetailsUrl,OND.Status,OAS.TriggerCount,StatusDescription,ObjectType,ObjectName, AlertMessage,OAO.RelatedNodeCaption,OND.Vendor, OND.ObjectSubType,OND.IPAddress,TriggerTimeStamp FROM Orion.AlertStatus OAS INNER JOIN Orion.AlertObjects OAO ON OAO.AlertObjectID=OAS.AlertObjectID INNER JOIN orion.Nodes OND ON OND.Caption=OAO.RelatedNodeCaption WHERE AlertMessage NOT LIKE '%Hardware Sensor Unknown%' AND AlertMessage NOT LIKE '%TESTING%' AND AlertMessage NOT LIKE '%OrionNCMVCHA logged in%' AND AlertMessage NOT LIKE '%system logged in%' ORDER BY triggertimestamp DESC"
swis_event="SELECT TOP 200 N.StatusLED AS NodeStatus, ONI.StatusLED AS InterfaceStatus,EventID, EventTime, NetworkNode, N.IPAddress,N.Vendor,ONI.InterfaceName, NetObjectID, NetObjectValue,  EventType, Message, Acknowledged, NetObjectType, TimeStamp FROM Orion.Events OE LEFT JOIN Orion.Nodes N on N.NodeID=OE.NetworkNode LEFT JOIN Orion.NPM.Interfaces ONI ON ONI.InterfaceID=OE.NetObjectID WHERE OE.EventType=5000 or OE.EventType=10 or OE.EventType=1 or OE.EventType=530 ORDER BY TimeStamp DESC"
swis_apipoller='''SELECT ID, Name, DisplayName, TemplateId, LastPollTimestamp, RelatedEntityId, RelatedEntityType, DetailsUrl, Status, StatusDescription, StatusLED, Image, Description
FROM Orion.APIPoller.ApiPoller '''
swis_netpath='''SELECT ProbeID, EndpointServiceID, Enabled, LastStatus, Status, LastProbeTime FROM Orion.NetPath.EndpointServiceAssignments where EndpointServiceID='208' OR EndpointServiceID='216' '''
swis_interfacdown='''
SELECT
    I.DetailsUrl, n.IPAddress,
    n.NodeName + ' ' + i.InterfaceCaption AS NodeName,
    NCP.SiteType,
    ToString(DayDiff(0, GETUTCDATE() - MAX(e.EventTime))) + 'd ' +
    ToString(Ceiling((HourDiff(0, GETUTCDATE() - MAX(e.EventTime)) / 24.0 - Floor(HourDiff(0, GETUTCDATE() - MAX(e.EventTime)) / 24.0)) * 24)) + 'h ' +
    ToString(Ceiling((MinuteDiff(0, GETUTCDATE() - MAX(e.EventTime)) / 60.0 - Floor(MinuteDiff(0, GETUTCDATE() - MAX(e.EventTime)) / 60.0)) * 60)) + 'm ' AS Duration,
    SecondDiff(0, GETUTCDATE() - MAX(e.EventTime)) AS Seconds,
    tolocal(MAX(e.EventTime)) AS DownTime
FROM
    Orion.NPM.Interfaces AS i
INNER JOIN
    Orion.Events AS e ON e.NetObjectID = i.InterfaceID
INNER JOIN
    Orion.Nodes AS n ON n.NodeID = i.NodeID
INNER JOIN
    Orion.NodesCustomProperties AS NCP ON NCP.NodeID = N.NodeID
WHERE
    i.Status = 2
    OR not i.StatusIcon LIKE '%Up%'
    AND e.EventTime > GETDATE() - 1000
    AND e.EventType = 10
GROUP BY
    n.NodeName + ' ' + i.InterfaceCaption,
    NCP.SiteType,
    n.IPAddress,
    I.DetailsUrl
ORDER BY
    Seconds
'''

swis_netpath_tmp='''
SELECT [SA].ProbeName AS [Source]
     , [SA].ServiceName AS [Destination]
     , [SA].DetailsUrl AS [_LinkFor_Source]
     , CONCAT('/Orion/images/StatusIcons/Small-', [SI].IconPostfix, '.gif') AS [_IconFor_Source] -- This is the status for the most recent poll only
--     , ROUND([Tests].MinLatency, 2) AS [Min Latency (ms)]
--     , ROUND([Tests].AvgLatency, 2) AS [Avg Latency (ms)]
--     , ROUND([Tests].MaxLatency, 2) AS [Max Latency (ms)]
     , CONCAT(ROUND([Tests].MinLatency, 2), ' / ', ROUND([Tests].AvgLatency, 2), ' / ', ROUND([Tests].MaxLatency, 2) ) AS [Min/Avg/Max Latency (ms)]
--     , ROUND([Tests].MinPacketLoss, 2) AS [Min Packet Loss (%)]
--     , ROUND([Tests].AvgPacketLoss, 2) AS [Avg Packet Loss (%)]
--     , ROUND([Tests].MaxPacketLoss, 2) AS [Max Packet Loss (%)]
     , CONCAT(ROUND([Tests].MinPacketLoss, 2), ' / ', ROUND([Tests].AvgPacketLoss, 2), ' / ', ROUND([Tests].MaxPacketLoss, 2) ) AS [Min/Avg/Max Packet Loss (%)]
FROM Orion.NetPath.ServiceAssignments AS [SA]
INNER JOIN Orion.StatusInfo AS [SI]
   ON [SA].Status = [SI].StatusID
INNER JOIN (
    SELECT EndpointServiceID
         , ProbeID
         , MIN(Rtt) AS MinLatency
         , AVG(Rtt) AS AvgLatency
         , MAX(Rtt) AS MaxLatency
         , MIN(PacketLoss) AS MinPacketLoss
         , AVG(PacketLoss) AS AvgPacketLoss
         , MAX(PacketLoss) AS MaxPacketLoss
    FROM Orion.NetPath.Tests
    WHERE ExecutedAt >= GETUTCDATE() - 1 -- ExecutedAt is stored in UTC, so we use 'GETUTCDATE() - 1' to get last 24 hours only
    GROUP BY EndpointServiceID, ProbeID
) AS [Tests]
ON  [Tests].ProbeID = [SA].ProbeID
AND [Tests].EndpointServiceID = [SA].EndpointServiceID
where EndpointServiceID='208' OR EndpointServiceID='216'
ORDER BY [SA].ProbeName
'''
swis_endpoint='''
SELECT UDT.EndpointID, UDT.IPAddress, CMI.NodeName, CMI.PortID, CMI.PortNumber, CMI.PortName,UDT.FirstSeen, UDT.LastSeen, UDT.RouterPortID, UDT.ID
FROM Orion.UDT.IPAddress UDT
JOIN Orion.UDT.ConnectedMACsAndIPs CMI on UDT.RouterPortID = CMI.PortID
'''
# 20251023 UDT Queries for Endpoint Details including Device Inventory
def swis_udt_all_query(node_id: int) -> str:
    swis_udt_all='''
    SELECT DISTINCT
        -- CONNECTION DETAILS (AllEndpoints)
        ae.ConnectedTo,
        ae.PortNumber,
        ae.VLAN,
        ae.PortName,
        ae.IPAddress,
        ae.HostName,
        ae.MACAddress,
        ae.MACVendor,
        ae.ConnectionTypeName,
        
        -- DEVICE DETAILS (DeviceInventory)  
        di.Vendor,
        di.EndpointType,
        di.FirstName,
        di.LastName,
        di.UserName

    FROM Orion.UDT.AllEndpoints ae

    -- JOIN DeviceInventory
    LEFT JOIN Orion.UDT.DeviceInventory di
        ON di.NodeID = ae.NodeID 
        AND di.MacAddress = ae.MACAddress

    WHERE ae.NodeID = {node_id}

    ORDER BY ae.PortNumber, ae.MACAddress
'''
    return swis_udt_all.format(node_id=node_id)

# 20251023 orion node connection details 
def swis_udt_node_query(node_id: int) -> str:
    swis_udt_node_query='''
    SELECT DISTINCT
        -- CONNECTION DETAILS (AllEndpoints)
        ae.ConnectedTo,
        ae.PortNumber,
        ae.PortName,
        ae.IPAddress,
        -- NODE DETAILS (Nodes)  
        n.Caption,n.Status, n.StatusLED, n.DetailsUrl,

        ae.HostName,
        ae.MACAddress,
        ae.MACVendor,

        ae.ConnectionTypeName,

        -- DEVICE DETAILS (DeviceInventory)  
        di.Vendor,
        di.EndpointType,
        di.FirstName,
        di.LastName,
        di.UserName

    FROM Orion.UDT.AllEndpoints ae

    -- JOIN DeviceInventory
    LEFT JOIN Orion.UDT.DeviceInventory di
        ON di.NodeID = ae.NodeID 
        AND di.MacAddress = ae.MACAddress

    inner JOIN Orion.Nodes n ON ae.IPAddress = n.IPAddress

    WHERE ae.NodeID = {node_id} 

    ORDER BY ae.PortNumber, ae.MACAddress
    '''
    return swis_udt_node_query.format(node_id=node_id)
