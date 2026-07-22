# scripts/config.py

import logging, os, re
from pathlib import Path
# 202512 Import the concurrent handler instead of the standard one, fix RotatingFileHandler on Windows, rename to  to .log.1 falls issue
# # from logging.handlers import RotatingFileHandler 

# Base paths
# BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).parent.parent # "inetpub" / "fastapi"  # Adjusted for the new file structure
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


# Cookie settings
COOKIE_NAME = "session_id"
COOKIE_PATH = "/"
COOKIE_HTTPONLY = True
COOKIE_MAX_AGE_SECONDS = 86400  # 1 day


# Optional: other environment configs
DEBUG_MODE = True

# orion settings
orion_prefix = "https://orion.net.mgmt"
OrionRCS_prefix = "https://samsw.phsa.ca"

swis_test='SELECT TOP 3 NodeID, DisplayName FROM Orion.Nodes'
# swis_sitedown= 'SELECT SUM(1) as value, Site FROM (SELECT nodeid,DisplayName,CP.CustomProperties.Site,CP.CustomProperties.SiteType FROM Orion.Nodes CP WHERE CP.Status=2 ) GROUP by site order by value'
swis_nodedown1='SELECT TOP 1000 nodeid,DisplayName,IPAddress,C.CustomProperties.Site,C.CustomProperties.SiteType,C.CustomProperties.DeviceType,location, C.CustomProperties.address, StatusDescription,DetailsUrl, LastBoot FROM Orion.Nodes C WHERE StatusDescription like \'%Node status is Down%\' AND not C.CustomProperties.Site=\'PPN\' ORDER BY C.CustomProperties.Site '
# swis_nodedown2='SELECT N.DetailsUrl,N.NodeName,N.IPAddress,NCP.Site,NCP.SiteType, tolocal(MAX(E.EventTime)) AS DownTime, ToString(DayDiff(0,GETUTCDATE() - MAX(E.EventTime))) + \'d \'  + ToString(Ceiling((HourDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 24.0 - Floor(HourDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 24.0)) * 24 )) + \'h \'+ ToString(Ceiling((MinuteDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 60.0 - Floor(MinuteDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 60.0) ) * 60 )) + \'m \' AS Duration, SecondDiff(0,GETUTCDATE() - MAX(E.EventTime)) as Seconds FROM orion.Nodes N  INNER JOIN orion.Events E ON E.NetworkNode = N.NodeID  INNER JOIN orion.NodesCustomProperties NCP ON NCP.NodeID = N.NodeID  where N.status = 2 and eventtype = 1 and N.IP not like \'%10.200%\' and N.IP not like \'%10.202%\'GROUP BY NCP.Site,N.Caption,NCP.Site,NCP.SiteType,N.DetailsUrl,N.IPAddress order BY Seconds'

# 202509 node/site down list for all node not in up/unmanage/external
swis_sitedown= 'SELECT SUM(1) as value, Site FROM (SELECT nodeid,DisplayName,CP.CustomProperties.Site,CP.CustomProperties.SiteType FROM Orion.Nodes CP WHERE CP.Status NOT IN (1,9,11) ) GROUP by site order by value' 
#20251226 site summary with down and total count
swis_site='''
SELECT 
    ISNULL(CP.CustomProperties.Site, 'Unknown') AS Site, 
    ISNULL(CP.CustomProperties.HA, 'Unknown') AS HA,
    ISNULL(CP.CustomProperties.Address, 'None') AS Address,
    MAX(ISNULL(CP.CustomProperties.City, 'None')) AS City,
    COUNT(nodeid) AS TotalNodes,
    SUM(CASE WHEN CP.Status NOT IN (1, 9, 11) THEN 1 ELSE 0 END) AS DownCount
FROM Orion.Nodes CP
GROUP BY 
    ISNULL(CP.CustomProperties.Site, 'Unknown'), 
    ISNULL(CP.CustomProperties.HA, 'Unknown'),
    ISNULL(CP.CustomProperties.Address, 'None')
ORDER BY DownCount DESC
'''
# 20251023 Add N.NodeID to the swis_nodedown2 query so we can reference NodeID in the node down table (for linking to UDT details).
swis_nodedown2='''
SELECT 
    N.NodeID,N.DetailsUrl,N.NodeName,N.Status,N.StatusDescription,N.IPAddress,NCP.Site,NCP.SiteType, tolocal(MAX(E.EventTime)) AS DownTime, ToString(DayDiff(0,GETUTCDATE() - MAX(E.EventTime))) + \'d \'  + ToString(Ceiling((HourDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 24.0 - Floor(HourDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 24.0)) * 24 )) + \'h \'+ ToString(Ceiling((MinuteDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 60.0 - Floor(MinuteDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 60.0) ) * 60 )) + \'m \' AS Duration, SecondDiff(0,GETUTCDATE() - MAX(E.EventTime)) as Seconds 
FROM orion.Nodes N  
INNER JOIN orion.Events E ON E.NetworkNode = N.NodeID  
INNER JOIN orion.NodesCustomProperties NCP ON NCP.NodeID = N.NodeID  
where N.status NOT IN (1,9) and eventtype = 1 and N.IP not like \'%10.200%\' and N.IP not like \'%10.202%\'
GROUP BY N.NodeID, N.Status,N.StatusDescription, NCP.Site,N.Caption,NCP.Site,NCP.SiteType,N.DetailsUrl,N.IPAddress 
ORDER BY NCP.Site ASC, Seconds 
'''

# 20260412 update only show NOT suppressed/muted
swis_nodeduration='''
SELECT N.NodeID,N.DetailsUrl,N.NodeName,N.Status,N.StatusDescription,N.IPAddress,NCP.Site,NCP.Address, NCP.City, NCP.SiteType, tolocal(MAX(E.EventTime)) AS DownTime, ToString(DayDiff(0,GETUTCDATE() - MAX(E.EventTime))) + \'d \'  + ToString(Ceiling((HourDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 24.0 - Floor(HourDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 24.0)) * 24 )) + \'h \'+ ToString(Ceiling((MinuteDiff(0, GETUTCDATE() - MAX(E.EventTime)) / 60.0 - Floor(MinuteDiff(0,GETUTCDATE() - MAX(E.EventTime)) / 60.0) ) * 60 )) + \'m \' AS Duration, SecondDiff(0,GETUTCDATE() - MAX(E.EventTime)) as Seconds 
FROM orion.Nodes N  
INNER JOIN orion.Events E ON E.NetworkNode = N.NodeID  
INNER JOIN orion.NodesCustomProperties NCP ON NCP.NodeID = N.NodeID  
LEFT JOIN Orion.AlertSuppression AS asup ON n.Uri = asup.EntityUri
where N.status NOT IN (1,9,11) -- 1 up , 9 unmanager, 11 external, 12 Unreachable.
    AND e.eventtype IN (1,5,9,14)  --1 Down, 5 Up, added, reboot
    AND asup.EntityUri IS NULL -- EXCLUSION LOGIC: Only show if NOT suppressed/muted
GROUP BY N.NodeID, N.Status,N.StatusDescription, NCP.Site,NCP.Address, NCP.City, N.Caption,NCP.Site,NCP.SiteType,N.DetailsUrl,N.IPAddress
ORDER BY Seconds 
'''

swis_nodeduration_2026='''
SELECT 
    ISNULL(Summary.TotalNodes, 0) AS TotalNodes,
    ISNULL(Summary.DownCount, 0) AS DownCount,
    N.NodeID, -- Added NodeID
    N.NodeName,
    N.IPAddress,
    N.StatusDescription,
    NCP.Site,
    NCP.Address,
    NCP.City,
    NCP.SiteType,
    N.DetailsUrl,
    tolocal(MAX(E.EventTime)) AS DownTime, 
    ToString(DayDiff(0,GETUTCDATE() - MAX(E.EventTime))) + 'd ' + 
    ToString(Floor(HourDiff(0, GETUTCDATE() - MAX(E.EventTime)) % 24)) + 'h ' + 
    ToString(Floor(MinuteDiff(0, GETUTCDATE() - MAX(E.EventTime)) % 60)) + 'm ' AS Duration, 
    SecondDiff(0,GETUTCDATE() - MAX(E.EventTime)) as Seconds 
FROM Orion.Nodes N
INNER JOIN Orion.NodesCustomProperties NCP ON NCP.NodeID = N.NodeID
INNER JOIN Orion.Events E ON E.NetworkNode = N.NodeID

-- Summary Subquery to get Site Totals
LEFT JOIN (
    SELECT 
        ISNULL(NCP_Sub.Site, '') AS Site,
        ISNULL(NCP_Sub.Address, '') AS Address,
        COUNT(N_Sub.NodeID) AS TotalNodes,
        SUM(CASE WHEN N_Sub.Status NOT IN (1, 9, 11) THEN 1 ELSE 0 END) AS DownCount
    FROM Orion.Nodes N_Sub
    INNER JOIN Orion.NodesCustomProperties NCP_Sub ON NCP_Sub.NodeID = N_Sub.NodeID
    GROUP BY ISNULL(NCP_Sub.Site, ''), ISNULL(NCP_Sub.Address, '')
) AS Summary ON ISNULL(Summary.Site, '') = ISNULL(NCP.Site, '') 
             AND ISNULL(Summary.Address, '') = ISNULL(NCP.Address, '')

WHERE N.Status NOT IN (1, 9, 11)
  AND E.EventType IN (1, 5, 9, 14)
GROUP BY 
    N.NodeID, -- Added to Group By
    Summary.TotalNodes, 
    Summary.DownCount, 
    N.NodeName, 
    N.IPAddress, 
    N.Status, 
    N.StatusDescription, 
    N.DetailsUrl, 
    NCP.Site, 
    NCP.Address, 
    NCP.City, 
    NCP.SiteType
ORDER BY Seconds ASC
'''

swis_bgp="SELECT  rn.NodeID,rr.Caption, rn.NeighborID, ln.Caption as RemoteRouter, rn.NeighborIP, orrp.DisplayName,rn.AutonomousSystem AS RemoteAS, rpsm.DisplayName AS Status, rn.LastChange FROM Orion.Routing.Neighbors rn  left JOIN orion.Nodes n on rn.NodeID=n.NodeID LEFT JOIN orion.Nodes ln on rn.NeighborIP=ln.IPAddress JOIN Orion.Routing.Router rr ON rn.NodeID=rr.NodeID JOIN Orion.Routing.RoutingProtocol orrp on rn.ProtocolID=orrp.ProtocolID JOIN Orion.Routing.RoutingProtocolStateMapping rpsm  ON rn.ProtocolID=rpsm.ProtocolID AND rn.ProtocolStatus=rpsm.ProtocolStatus WHERE orrp.ProtocolID=14 ORDER BY n.Caption"
swis_ospf="SELECT NodeID,n.Caption, NeighborID, NeighborIP, ln.Caption AS RemoteRouter, orrp.DisplayName,   rpsm.DisplayName AS Status   FROM Orion.Routing.Neighbors rn JOIN orion.Nodes n on n.NodeID=rn.NodeID LEFT JOIN orion.Nodes ln on rn.NeighborIP=ln.IPAddress JOIN Orion.Routing.RoutingProtocol orrp on rn.ProtocolID=orrp.ProtocolID LEFT JOIN Orion.Routing.RoutingProtocolStateMapping rpsm  ON rn.ProtocolID=rpsm.ProtocolID AND rn.ProtocolStatus=rpsm.ProtocolStatus WHERE orrp.ProtocolID=13 ORDER BY n.Caption"
swis_nodestatistic="SELECT COUNT(1) as value, Status, CASE WHEN Status = 1 THEN \'Up\' WHEN Status =2 THEN \'Down\' WHEN Status =3 THEN \'warning\' WHEN Status=9 THEN \'Unmanaged\' WHEN Status=11 THEN \'External\' WHEN Status=14 THEN\'Critical\' ELSE \'unknown\' END as NodeStatus FROM Orion.Nodes GROUP BY status ORDER BY value"

# 20251011 Full Node Custom Properties Query
# 20251230 update ONS.NodeName, ONS.IPaddress, ONS.DetailsUrl
# swis_ncp="SELECT Site, ONS.NodeName, ONS.IPaddress, ONS.DetailsUrl, NodeID, ONS.Status, ONS.StatusDescription, Address, Architecture, AssetTag, Building, City, Closest_Poller, Closet, Comments, Configuration, ControlUpEventID, DeviceType, Floor, HA, HardwareIncidentStatus, Imported_From_NCM, IncidentStatus, Layer3, LdapTestFailureMessage, Make, New_Poller_Home, NodeOwner,  OutOfBand, PDIntegrationKey, PONumber, ProgramApplication, ProgramApplicationType, Provider, ProviderSiteID, Rack, Region, ServiceType, SiteContactName, SiteHours, SitePhone, SiteType, Technology, Topology, Unmanaged_, WANbandwidth, WANnode, WANProvider,WANProviderCSID,WANProviderDeviceID FROM Orion.NodesCustomProperties ONCP INNER JOIN Orion.Nodes ONS ON ONCP.NodeID = ONS.NodeID ORDER BY Site"

#20260709 updated
swis_ncp='''SELECT Site, ONS.NodeName, ONS.IPaddress, ONS.DetailsUrl, NodeID, ONS.Status, ONS.StatusDescription, Address, Architecture, Building, City, Closet, Comments, Configuration, DeviceType, Floor, HA, HardwareIncidentStatus, IncidentStatus, Layer3, Make, New_Poller_Home, NodeOwner,  OutOfBand,  ProgramApplication, ProgramApplicationType, Provider, ProviderSiteID, Rack, Region, ServiceType, SiteContactName, SiteHours, SitePhone, SiteType, Technology, Topology, WANbandwidth, WANnode, WANProvider,WANProviderCSID,WANProviderDeviceID FROM Orion.NodesCustomProperties ONCP INNER JOIN Orion.Nodes ONS ON ONCP.NodeID = ONS.NodeID ORDER BY Site
'''


swis_alert='''
SELECT 
    -- Calculate duration in minutes
    MINUTEDIFF(OAS.TriggerTimeStamp, GETUTCDATE()) AS DurationMinutes,
    -- Fallback URL for Stack objects
    ISNULL(OAO.EntityDetailsUrl, '/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:' + TOSTRING(OAO.RelatedNodeID)) AS EntityDetailsUrl,
    OAO.AlertConfigurations.Severity, 
    OND.Status,
    OAS.TriggerCount,
    StatusDescription,
    ObjectType,
    ObjectName, 
    AlertMessage,
    OAO.RelatedNodeCaption,
    OND.Vendor, 
    OND.ObjectSubType,
    OND.IPAddress,
    TriggerTimeStamp 
FROM Orion.AlertStatus OAS 
LEFT JOIN Orion.AlertObjects OAO ON OAO.AlertObjectID=OAS.AlertObjectID 
LEFT JOIN orion.Nodes OND ON OND.Caption=OAO.RelatedNodeCaption 
WHERE AlertMessage NOT LIKE '%OrionNCMVCHA logged in%' 
  AND AlertMessage NOT LIKE '%system logged in%' 
GROUP BY OND.IPAddress, OAS.AlertMessage 
ORDER BY TriggerTimeStamp DESC
'''

# swis_alert="SELECT OAO.EntityDetailsUrl,OND.Status,OAS.TriggerCount,StatusDescription,ObjectType,ObjectName, AlertMessage,OAO.RelatedNodeCaption,OND.Vendor, OND.ObjectSubType,OND.IPAddress,TriggerTimeStamp FROM Orion.AlertStatus OAS INNER JOIN Orion.AlertObjects OAO ON OAO.AlertObjectID=OAS.AlertObjectID INNER JOIN orion.Nodes OND ON OND.Caption=OAO.RelatedNodeCaption WHERE AlertMessage NOT LIKE '%Hardware Sensor Unknown%' AND AlertMessage NOT LIKE '%TESTING%' AND AlertMessage NOT LIKE '%OrionNCMVCHA logged in%' AND AlertMessage NOT LIKE '%system logged in%' ORDER BY triggertimestamp DESC"
swis_nodes_eventhistory='''
SELECT EventID, n.NodeName, EventTime, NetObjectValue, EventType, Message, Acknowledged, TimeStamp
FROM Orion.Events e 
LEFT JOIN Orion.Nodes n on n.NodeID = e.NetObjectID
WHERE n.Status = 2
ORDER BY NetObjectValue DESC
'''

swis_nodesevent= '''
SELECT 
    E.NetworkNode AS NodeID,
    E.EventTime,
    E.EventType,
    N.StatusDescription,
    E.Message,
    N.Caption AS NodeName
FROM Orion.Events E
JOIN Orion.Nodes N ON E.NetworkNode = N.NodeID
WHERE E.EventType IN (1, 5) -- 1 = Down, 5 = Up
  AND E.EventTime > ADDDAY(-7, GETUTCDATE()) -- Last 7 days
ORDER BY E.EventTime ASC
'''
# 20260102 

swis_event="SELECT TOP 200 N.StatusLED AS NodeStatus, ONI.StatusLED AS InterfaceStatus,EventID, EventTime, NetworkNode, N.IPAddress,N.Vendor,ONI.InterfaceName, NetObjectID, NetObjectValue,  EventType, Message, Acknowledged, NetObjectType, TimeStamp FROM Orion.Events OE LEFT JOIN Orion.Nodes N on N.NodeID=OE.NetworkNode LEFT JOIN Orion.NPM.Interfaces ONI ON ONI.InterfaceID=OE.NetObjectID WHERE OE.EventType=5000 or OE.EventType=10 or OE.EventType=1 or OE.EventType=530 ORDER BY TimeStamp DESC"
swis_apipoller='''SELECT ID, Name, DisplayName, TemplateId, LastPollTimestamp, RelatedEntityId, RelatedEntityType, DetailsUrl, Status, StatusDescription, StatusLED, Image, Description
FROM Orion.APIPoller.ApiPoller '''
swis_netpath='''SELECT ProbeID, EndpointServiceID, Enabled, LastStatus, Status, LastProbeTime FROM Orion.NetPath.EndpointServiceAssignments where EndpointServiceID='208' OR EndpointServiceID='216' '''

# 20260412 : add nodes status was not in unmanage/external (interface showing down could be due to node down, so filter out unmanaged/external nodes), and event time filter to 1000 days to cover long duration down case. 
swis_interfacdown='''
SELECT
    i.NodeID, i.InterfaceID,
    I.DetailsUrl, n.IPAddress,i.Status,i.StatusDescription,
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
LEFT JOIN 
    Orion.AlertSuppression AS asup ON n.Uri = asup.EntityUri    
WHERE
    i.Status NOT IN (1,9,11) -- 1 up, 9 unmanager, 11 external
    AND N.status  NOT IN (9,11) -- 9 unmanager, 11 external
    AND e.EventTime > GETDATE() - 1000
    AND asup.EntityUri IS NULL -- EXCLUSION LOGIC: Only show if NOT suppressed/muted

GROUP BY
    n.NodeName + ' ' + i.InterfaceCaption,
    NCP.SiteType,N.status,
    n.IPAddress,
    i.NodeID,i.InterfaceID,i.Status,
    i.StatusDescription,
    I.DetailsUrl
ORDER BY
    Seconds
'''

#20260412 update interface query to include node status filter and event time filter, also add alert suppression join and filter to exclude suppressed/muted interfaces.
swis_interface=  '''
SELECT
    i.NodeID, i.InterfaceID,
    I.DetailsUrl, n.IPAddress,i.Status,i.StatusDescription,
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
LEFT JOIN 
    Orion.AlertSuppression AS asup ON n.Uri = asup.EntityUri    
WHERE
    i.Status NOT IN (9,11) -- 1 up, 9 unmanager, 11 external
    AND N.status  NOT IN (9,11) -- 9 unmanager, 11 external
    AND e.EventTime > GETDATE() - 1000
    AND asup.EntityUri IS NULL -- EXCLUSION LOGIC: Only show if NOT suppressed/muted

GROUP BY
    n.NodeName + ' ' + i.InterfaceCaption,
    NCP.SiteType,N.status,
    n.IPAddress,
    i.NodeID,i.InterfaceID,i.Status,
    i.StatusDescription,
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

swis_sitetopology='''

SELECT DISTINCT
    NCP.Site AS SourceSite,
    SourceNode.Caption AS SourceNodeName,
    SourceNode.DetailsUrl AS SourceNodeURL,
    
    -- Pick the best Interface match: Direct ID > Name Match > IP Match
    ISNULL(SourceInt.Caption, GrepInt.Caption) AS SourceInterface,
    ISNULL(SourceInt.DetailsUrl, GrepInt.DetailsUrl) AS SourceInterfaceURL,

    TargetNode.Caption AS TargetNodeName,
    TargetNode.IPAddress,
    TargetCP.DeviceType AS TargetDeviceType,
    TargetNode.DetailsUrl AS TargetNodeURL,
    
    t.LayerType,
    t.LastUpdateUtc

FROM Orion.TopologyConnections t
INNER JOIN Orion.Nodes SourceNode ON t.SrcNodeID = SourceNode.NodeID
INNER JOIN Orion.Nodes TargetNode ON t.DestNodeID = TargetNode.NodeID
INNER JOIN Orion.NodesCustomProperties NCP ON t.SrcNodeID = NCP.NodeID
INNER JOIN Orion.NodesCustomProperties TargetCP ON t.DestNodeID = TargetCP.NodeID

-- 1. Standard Join (Works for Switch-to-Switch)
LEFT JOIN Orion.NPM.Interfaces SourceInt ON t.SrcInterfaceID = SourceInt.InterfaceID

-- 2. IP & Name Aware Grep Join
LEFT JOIN Orion.NPM.Interfaces GrepInt ON (
    GrepInt.NodeID = t.SrcNodeID 
    AND t.SrcInterfaceID IS NULL -- Only grep if topology didn't find the link
    AND (
        -- Match by Name (e.g., UPS01)
        GrepInt.Caption LIKE '%' + TargetNode.Caption + '%' 
        -- Match by IP Address (e.g., 10.27.36.81)
        OR GrepInt.Caption LIKE '%' + TargetNode.IPAddress + '%'
        -- Match by DeviceType keywords if the specific name isn't in the port description
        OR (GrepInt.Caption LIKE '%' + TargetCP.DeviceType + '%' AND TargetCP.DeviceType IN ('UPS', 'PDU', 'Telus CE','Firewall'))
    )
)

-- WHERE NCP.Site = 'Gibsons Sumac Place'
-- Ensure we only show rows where we actually found the interface
--AND (SourceInt.Caption IS NOT NULL OR GrepInt.Caption IS NOT NULL)
'''

swis_topology='''
SELECT DiscoveryProfileID, SrcNodeID, SrcInterfaceID, DestNodeID, DestInterfaceID, SrcType, DestType, SrcOrionNodeID, DestOrionNodeID, DataSourceNodeID, LastUpdateUtc, LayerType, DisplayName, Description, InstanceType, Uri, InstanceSiteId
FROM Orion.TopologyConnections
'''

# swis_sitetopology='''
# SELECT 
#     SourceNode.Caption AS SourceNodeName,
#     SourceNode.NodeID AS SourceNodeID,
#     SourceInt.Caption AS SourceInterface,
#     TargetNode.Caption AS TargetNodeName,
#     TargetNode.NodeID AS TargetNodeID,
#     TargetInt.Caption AS TargetInterface,
#     NCP.Site AS SourceSite,         -- Pulling Site from Custom Properties
#     TargetCP.Site AS TargetSite,    -- Pulling Site for the destination node
#     t.LayerType,
#     t.LastUpdateUtc
# FROM Orion.TopologyConnections t
# INNER JOIN Orion.Nodes SourceNode ON t.SrcNodeID = SourceNode.NodeID
# INNER JOIN Orion.Nodes TargetNode ON t.DestNodeID = TargetNode.NodeID
# INNER JOIN Orion.NodesCustomProperties NCP ON t.SrcNodeID = NCP.NodeID
# INNER JOIN Orion.NodesCustomProperties TargetCP ON t.DestNodeID = TargetCP.NodeID
# LEFT JOIN Orion.NPM.Interfaces SourceInt ON t.SrcInterfaceID = SourceInt.InterfaceID
# LEFT JOIN Orion.NPM.Interfaces TargetInt ON t.DestInterfaceID = TargetInt.InterfaceID
# -- Optional: Filter for a specific site
# -- WHERE NCP.Site = '1190 Hornby (PHC)'
# '''

swis_syslog='''
SELECT top 200  LogEntryID,NodeID, DateTime, Message
FROM Orion.OLM.LogEntry 
WHERE DateTime > AddHour(-1, GETUTCDATE()) 
AND nodeid in ('11127','11128','11130','12682','11434','16110') -- Core devices only
AND (Message LIKE '%OSPF_NBR_CHG:%' OR Message LIKE '%BGP_STATE_CHANGED:%')
ORDER BY DateTime DESC
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


