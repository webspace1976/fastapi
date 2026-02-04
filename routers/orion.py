import re,requests,urllib3,urllib.parse,os,json,sys, uuid, pickle, atexit, logging, html, sqlite3, pickle
# from logging.handlers import RotatingFileHandler
from time import perf_counter,time,ctime
from datetime import datetime
from orionsdk import SwisClient
from fastapi.responses import HTMLResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Form, Request, Response
from pydantic import ValidationError
from typing import Any
import pandas as pd

# Local imports
import utils.fastapi_mymodule as mymodule
import mainconfig as mainconfig
from mainpydantic import OrionCheckRequest, OrionResponse
from utils.session_manager import OrionSession, get_deterministic_session_id
from utils.orion_db_manager import sync_orion_data
from utils.orion_db_manager import OrionDatabaseManager

# --- Setup ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = mainconfig.setup_module_logger(__name__)

router  = APIRouter()
# start   = perf_counter()

# --- Directories ---
curr_dir= os.path.dirname(__file__)
log_dir=os.path.abspath(os.path.join(curr_dir, '..', 'logs'))
data_dir=os.path.abspath(os.path.join(curr_dir, '..', 'data'))
icon_dir = mainconfig.ICONS_DIR
# session_dir = os.path.abspath(os.path.join(data_dir, 'orion_sessions'))  # Directory to store session files
session_dir = mainconfig.SESSION_DIR  # Directory to store session files
SESSION_LOG_FILE = os.path.join(session_dir, "orion_session_log.json")

DB_ORION_PATH = mainconfig.DB_ORION_PATH


for directory in [log_dir, data_dir, session_dir]:
    if not os.path.exists(directory):
        os.makedirs(directory)


#   golbal var    
sitedown_list=[]    
dict_query = {}     
detailsurl=""
orion_prefix = str(mainconfig.orion_prefix)
swis_site = mainconfig.swis_site
swis_sitedown = mainconfig.swis_sitedown
swis_nodedown2 = mainconfig.swis_nodedown2
swis_interfacdown = mainconfig.swis_interfacdown
swis_bgp = mainconfig.swis_bgp
swis_ospf = mainconfig.swis_ospf
swis_nodestatistic = mainconfig.swis_nodestatistic
swis_ncp = mainconfig.swis_ncp
swis_alert = mainconfig.swis_alert
swis_event = mainconfig.swis_event
swis_apipoller = mainconfig.swis_apipoller
swis_netpath = mainconfig.swis_netpath
swis_endpoint = mainconfig.swis_endpoint
swis_nodesevent = mainconfig.swis_nodesevent
swis_nodes_eventhistory = mainconfig.swis_nodes_eventhistory
swis_nodeduration = mainconfig.swis_nodeduration

def cleanup_session(session_file):
    if os.path.exists(session_file):
        os.remove(session_file)
        logger.debug(f"Debug: Removed session file: {session_file}")


# Register cleanup function to run on script exit
# atexit.register(cleanup_session, session_file=os.path.join(session_dir, "your_session_id"))

def close_log_handler():
    for h in logger.handlers:
        h.close()

atexit.register(close_log_handler)

def cleanup_old_sessions(session_dir, max_age=3600):
    now = time()
    for file in os.listdir(session_dir):
        file_path = os.path.join(session_dir, file)
        if os.path.isfile(file_path) and (now - os.path.getmtime(file_path)) > max_age:
            os.remove(file_path)
            # logger.debug(f"Debug: Removed expired session file: {file_path}")

# Call this function at the start of the script
cleanup_old_sessions(session_dir)

def get_session_id_from_cookie():
    """Retrieve session ID from cookies."""
    from http.cookies import SimpleCookie

    cookie = SimpleCookie(os.environ.get("HTTP_COOKIE", ""))
    session_id = cookie.get("session_id")
    if session_id:
        logger.debug(f"Retrieved session_id from cookie: {session_id.value}")
        return session_id.value
    logger.error("No session_id found in cookie")
    return None

def remove_non_ascii(data):
    if isinstance(data, dict):
        return {remove_non_ascii(key): remove_non_ascii(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [remove_non_ascii(item) for item in data]
    elif isinstance(data, str):
        return data.encode('ascii', 'ignore').decode('ascii')
    else:
        return data

def check_orion_status(session):
    try:
        # Try a lightweight query
        session.refresh_session()
        session.query("SELECT TOP 1 NodeID FROM Orion.Nodes")
        return True
    except Exception as e:
        logger.error(f"Orion server check failed: {e}")
        return False

############## generate tables
def safe_escape(value: Any) -> str:
    return html.escape(str(value or ""))

def generate_node_table(session):
    sitedown_list = []
    table_rows = ""

    query_site = swis_site
    results_site = session.query(query_site)
    site_data = results_site.get("results", [])
    for row_site in results_site['results']:
        if row_site.get('DownCount') and row_site.get('DownCount') == row_site.get('TotalNodes'):
            # Store as a dictionary for precise matching later
            sitedown_list.append({
                'Site': row_site.get('Site'),
                'Address': row_site.get('Address'),
                'FullDisplay': f"{row_site.get('Site')}, {row_site.get('Address')}, {row_site.get('City')}, {row_site.get('DownCount')}/{row_site.get('TotalNodes')}"
            })        
        # if row_site.get('DownCount') and row_site.get('DownCount') == row_site.get('TotalNodes'):
        #     # sitedown_list.append(row_site.get('Site',''))
        #     sitedown_list.append(f"{row_site.get('Site')}, {row_site.get('Address')}, {row_site.get('City')}, {row_site.get('DownCount')}/{row_site.get('TotalNodes')}")
    logger.debug(f"Debug: sitedown_list: {sitedown_list}")
    # 20250106 update site down logic to check from site table

    query_sitetopology = mainconfig.swis_sitetopology
    results_sitetopology = session.query(query_sitetopology)
    results_sitetopology_data = results_sitetopology.get("results", [])

    query = swis_nodeduration
    results = session.query(query)
    results_data = results.get("results", [])

    for row in results_data:
        if row.get("Status") in [2,12]: # Only process nodes that are down 2 or unreachable 12
            seccond = int(row.get("Seconds", 0))  # Default to 0 if 'Seconds' is missing
            if seccond < 43200 : 
                class_tag = "highLight"
            elif seccond >= 43200 and seccond < 345600 : 
                class_tag = "rowRecent"
            elif seccond >= 345600 and seccond < 604800 : 
                class_tag = "rowOld"
            else:
                class_tag = "rowOther"

            # url="{DetailsUrl}".format(**row)
            # url_link=orion_prefix+url            
            url = row.get("DetailsUrl", "") # Use .get with a default
            if url and orion_prefix:
                url_link = orion_prefix + url
            else:
                url_link = url # Fallback to raw url or empty string        

            #20250106 update site url link to orion search via "urllib"
            site_searchurl = "https://orion.net.mgmt/apps/search/?q="
            node_name = str(row.get('NodeName') or '')
            node_address = str(row.get('Address') or 'None')
            node_city = str(row.get('City') or 'None')
            raw_site_name = row.get('Site', 'Unknown')
            
            # 1. Find the match in the sitedown_list using a prefix match
            # We check if the item in the list starts with the specific site name
            # site_down_match = next((item for item in sitedown_list if item.startswith(f"{raw_site_name},")), None)
            # 20260121. Match by BOTH Site Name and Address to distinguish campus buildings
            site_down_match = next((
                item for item in sitedown_list 
                if item['Site'] == raw_site_name and item['Address'] == node_address
            ), None)

            if site_down_match:
                # Use the specific display string we built earlier
                display_site_name = site_down_match['FullDisplay']
                is_down = True
            else:
                display_site_name = raw_site_name + ", " + node_address + ", " + node_city
                is_down = False

            # if site_down_match:
            #     # If matched, use the detailed string for display and add the tag
            #     display_site_name = site_down_match
            #     is_down = True
            # else:
            #     # If not matched, use the standard site name
            #     display_site_name = raw_site_name + ", " + node_address + ", " + node_city
            #     is_down = False
                
            escaped_node_name = html.escape(node_name)
            escaped_site_display = html.escape(display_site_name)
            encoded_site_search = urllib.parse.quote(raw_site_name) # Search by raw name for better results

            table_rows += (
                "<tr class=\"{}\"><td>{}</td><td><a href=\"{}\" target=\"_blank\">{}</a></td>"
                "<td><a href=\"{}\" target=\"_blank\">{}</a></td><td>{}</td>"
                "<td id=\"IPAddress\" style=\"display:none\">{}</td></tr>"
            ).format(
                class_tag,
                row.get('Duration', ""),
                url_link if url_link is not None else "",
                escaped_node_name,
                f"{site_searchurl}{encoded_site_search}",
                f"<b>{escaped_site_display} **Site Down** </b>" if is_down else escaped_site_display,
                row.get('SiteType', ""),
                row.get('IPAddress', "")
            )  

    results_html = f"""
    <table id="nodedownTable" style="visibility:'hidden';font-size:11px; width:100%">
        <thead>
            <tr>
                <th style="width:14%">Duration</th> 
                <th >
                    <div>Node Link-Toggle:
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_nodedownTable" value="Orion" checked>Orion Node</label>
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_nodedownTable" value="SNOW">SNOW</label>
                        <label><input type="radio" name="link_type_nodedownTable" value="Orion_UDT">Orion UDT</label>
                    </div>
                </th> 
                <th style="width:20%">Type</th>
                <th style="display:none">IPAddress</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """

    return results_html, results_data, site_data, results_sitetopology_data

def generate_interface_table(session):
    query = swis_interfacdown
    results = session.query(query)
    table_rows = ""
    for row in results.get("results", []):
        seccond = int(row.get("Seconds", 0))  # Default to 0 if 'Seconds' is missing
        if seccond < 43200 : 
            class_tag = "highLight"
        elif seccond >= 43200 and seccond < 345600 : 
            class_tag = "rowRecent"
        elif seccond >= 345600 and seccond < 604800 : 
            class_tag = "rowOld"
        else:
            class_tag = "rowOther"
            
        url = row.get("DetailsUrl", "") # Use .get with a default
        if url and orion_prefix:
            url_link = orion_prefix + url
        else:
            url_link = url # Fallback to raw url or empty string          

        table_rows += (            
                "<tr class=\"{}\"><td>{}</td><td id=\"node_info\" value=\"{}\"><a href=\"{}\" target=\"_blank\">{}</a></td>"
                "<td>{}</td></tr>"
            ).format(
                class_tag,
                row.get('Duration', ""),  # Use .get() to handle missing keys
                row.get('IPAddress', ""),                
                url_link if url_link is not None else "",
                row.get('NodeName', ""),
                row.get('SiteType', "")
            )

    results_data = results.get("results", [])
    results_html = f"""
    <table id="interfacedownTable" style="font-size:11px">
        <thead>
            <tr>
                <th style="width:14%">Duration</th> 
                <th>
                    <div>
                        <strong>Interface Link-Toggle:</strong>
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_interfacedownTable" value="Orion" checked>Orion Node</label>
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_interfacedownTable" value="SNOW">SNOW</label>
                        <label><input type="radio" name="link_type_interfacedownTable" value="webssh">WebSSH</label>
                    </div>
                </th> 
                <th style="width:12%">Type</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """
    return results_html, results_data

def generate_event_table(session):
    query = swis_event
    results = session.query(query)
    table_rows = ""
    for row in results.get("results", []):

        # event time:
        timestamp=row['EventTime']
        date=re.split("T",timestamp)[0]
        time_utc=re.search("[0-9][0-9]\:[0-9][0-9]\:[0-9][0-9]",timestamp)[0]
        t=re.split(":",time_utc)
        utc_offset=datetime.utcnow().hour-datetime.now().hour
        if utc_offset < 0 :
            utc_offset=24 + datetime.utcnow().hour-datetime.now().hour
        t[0]=int(t[0])-utc_offset
        i=0 # for time debug
        if t[0] < 0 :
            t[0]=str(t[0] + 24)
            i=1
        elif t[0] < 10 :
            t[0]="0"+str(t[0])
            i=2
        else:
            i=3
            t[0]=str(t[0])
        time_cur=t[0]+":"+t[1]+":"+t[2]    

        vendor=row['Vendor']
        nodeip=row['IPAddress']
        icon_gif = "/icons/Event-5.gif"
        interface_name=row['InterfaceName']

        if "rebooted" in row['Message']:
            row['Message']=str(re.split(" at",row['Message'])[0])
        if "Node: " in row['Message']:
            row['Message']=str(re.split("Node: ",row['Message'])[1])
        if ":Node" in row['Message']:
            row['Message']=str(re.split(":Node ",row['Message'])[1])
		# check if the message contains any non-ASCII characters.
        if re.search(r'[^\x00-\x7F]', row['Message']) :
            row['Message']=re.sub(r'[^\x00-\x7F]','',row['Message'])

        #filter option for "sanity check"   
        if re.match("Windows|Eaton|Merlin|Northern",row['Vendor']) :
            url="/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:"+str(row['NetworkNode'])
            url_link=orion_prefix+url


            if "Down" in row['NodeStatus']:
                icon_gif = "/icons/Event-10.gif"
            table_rows += (            
                    "<tr><td>{}</td><td></td><td><img src=\"{}\" alt=\"\"/><a href=\"{}\" target=\"_blank\" >{}</a></td></tr>"
                ).format(
                    time_cur, icon_gif, url_link if url_link is not None else "", row['Message']
                )                
            # table_rows +=("<tr><td>",time_cur,"</td><td></td><td><img src=\"",icon_gif,"\" alt=\"\"/><a href=\"",url_link,"\" target=\"_blank\" >"+row['Message'],"</a></td></tr>")
			
        elif row['NetObjectType'] == "I" :
            url="/Orion/NetPerfMon/NodeDetails.aspx?NetObject=I:"+str(row['NetObjectID'])
            url_link=orion_prefix+url
                
            if row['InterfaceStatus'] is None:
                table_rows += (
                        f"<tr><td>{time_cur}</td><td></td><td><img src=\"{icon_gif}\" alt=\"\"/><a href=\"{url_link}\" target=\"_blank\">{row['Message']}</a></td></tr>"
                )
            elif "own" in row['InterfaceStatus']:
                icon_gif = "/icons/Event-10.gif"
                table_rows += (
                    f"<tr><td>{time_cur}</td>"
                    f"<td><input type=\"radio\" name=\"interface_info\" value=\"{vendor},{nodeip},{interface_name}\"></td>"
                    f"<td><img src=\"{icon_gif}\" alt=\"\"/><a href=\"{url_link}\" target=\"_blank\">{row['Message']}</a></td></tr>"
                )
            elif "Up" in row['InterfaceStatus']:
                icon_gif = "/icons/Event-5.gif"
                table_rows += (f"<tr><td>{time_cur}</td><td><input type=\"radio\" name=\"interface_info\" value=\"{vendor,nodeip,interface_name}\"></td><td><img src=\"{icon_gif}\" alt=\"\"/><a href=\"{url_link}\" target=\"_blank\">{row['Message']}</a></td></tr>")
        else : # radio option for sanith check
            url="/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:"+str(row['NetworkNode'])
            url_link=orion_prefix+url
            if "Down" in row['NodeStatus']:
                icon_gif = "/icons/Event-10.gif"
            table_rows += (
                f"<tr><td>{time_cur}</td><td><input type=\"radio\" name=\"node_info\" value=\"{vendor,nodeip}\"></td><td><img src=\"{icon_gif}\" alt=\"\"/><a href=\"{url_link}\" target=\"_blank\" >{row['Message']}</a></td></tr>")     

        # table_rows += f"<tr><td>{row['EventID']}</td><td>{row['Message']}</td></tr>"

    return f"""
    <table id="eventTable" style="font-size:11px">
        <thead>
            <tr>
            <th>Time</th><th></th>
            <th><div style="display:flex;justify-content:space-around;">
                <div>Event</div>
                    <label class="switch">
                        <input id="linkToggleEvent" type="checkbox">
                        <span class="slider round"></span>
                    </label>
                <span id="toggleStateEvent"><span style="background-color:lightgreen">Orion</span> <span style="background-color:lightblue">SNOW</span> </span>
                <div style="padding:0;font-size:10px;"><spam><a id="sshLink" href="../xterm.html" target="_blank">Login via Web SSH</a></spam></div>
            </div></th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """

def generate_alert_table(session):
    query = swis_alert
    results = session.query(query)
    table_rows = ""

    # 20260203 --- : Keep track of seen events ---
    seen_alerts = set()

    try:
        for row in results.get("results", []):


            # event time:
            timestamp=row['TriggerTimeStamp']
            date=re.split("T",timestamp)[0]
            time_utc=re.search("[0-9][0-9]\:[0-9][0-9]\:[0-9][0-9]",timestamp)[0]
            t=re.split(":",time_utc)
            utc_offset=datetime.utcnow().hour-datetime.now().hour
            if utc_offset < 0 :
                utc_offset=24 + datetime.utcnow().hour-datetime.now().hour
            t[0]=int(t[0])-utc_offset
            i=0 # for time debug
            if t[0] < 0 :
                t[0]=str(t[0] + 24)
                i=1
            elif t[0] < 10 :
                t[0]="0"+str(t[0])
                i=2
            else:
                i=3
                t[0]=str(t[0])
            time_cur=t[0]+":"+t[1]+":"+t[2]    

            vendor = str(row.get('Vendor') or "Unknown")
            nodeip = str(row.get('IPAddress') or "0.0.0.0")
            object_type=str(row['ObjectType'] or "Unknown")
            TriggerCount=str(row['TriggerCount'] or "0")
            hostname = str(row['RelatedNodeCaption'] or "Unknown")
            Message = str(row['AlertMessage'] or "No Message")
            TriggerCount = str(row['TriggerCount'] or "0")


            # Create a unique identifier for the row (e.g., Time + Message)
            alert_id = f"{nodeip}_{Message}"
            
            # Check for duplicates
            if alert_id in seen_alerts:
                continue
            seen_alerts.add(alert_id)

            # url_link = orion_prefix + (row.get('EntityDetailsUrl') or "")
            url = row.get("EntityDetailsUrl", "") # Use .get with a default
            if url:
                url_link = orion_prefix + url
            else:
                url_link = url # Fallback to raw url or empty string                

            # if "Down" in row['StatusDescription']:
            if row.get('Status') in [2,12] or "Failure" in row.get('AlertMessage', ''):
                status_gif = "/icons/Event-10.gif"
            else :
                status_gif = "/icons/Event-5.gif"

            raw_severity = row.get('Severity')
            if raw_severity == 0:
                severity = 0
                severity_png   = "/icons/Event_Information.png" 
            elif raw_severity == 1:
                severity = 1
                severity_png = "/icons/Event_Warning.png"
            elif raw_severity == 2:
                severity = 2
                severity_png = "/icons/Event_Critical.png"            
            elif raw_severity == 3:
                severity = 3
                severity_png = "/icons/Event_Serious.png"
            else:
                severity = 4
                severity_png = "/icons/Event_Unknown.png"

            if object_type == "Interface":
                interface_name = row['ObjectName']
                Message = hostname + " " + interface_name + " " + row['AlertMessage']
            else:
                Message = hostname + " " + row['AlertMessage']


            table_rows += (
                    "<tr><td id=\"severity\" value=\"{}\"><img src=\"{}\" alt=\"\"/></td><td style=\"text-align:center\" id=\"node_info\" value=\"{},{}\">{}</td><td><img src=\"{}\" alt=\"\"/><a href=\"{}\" target=\"_blank\">{}</a></td></tr>"
            ).format(
                    severity, severity_png,vendor, nodeip, TriggerCount,status_gif, url_link if url_link is not None else "", Message if Message is not None else ""
            ) 
            # table_rows += (
            #         "<tr><td>{}</td><td style=\"text-align:center\" id=\"node_info\" value=\"{},{}\">{}</td><td><img src=\"{}\" alt=\"\"/><a href=\"{}\" target=\"_blank\">{}</a></td></tr>"
            # ).format(
            #         time_cur,vendor, nodeip, TriggerCount,status_gif, url_link if url_link is not None else "", Message if Message is not None else ""
            # ) 

        results_data = results.get("results", [])
        results_len = len(results_data)
        results_html = f"""
        <table id="alertTable" style="font-size:11px;">
            <thead>
                <tr>
                <th>Severity</th><th>Count</th>
                <th>
                    <div style="display:flex;justify-content: space-around;align-items: flex-end;">
                        <div>Link-Toggle:
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_alertTable" value="Orion" checked>Orion Node</label>
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_alertTable" value="SNOW"> SNOW</label>
                        <label><input type="radio" name="link_type_alertTable" value="webssh">WebSSH</label>
                        </div>
                    </div>
                </th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        """
        return results_html, results_data
    except Exception as e:
        logger.error(f"Error generating alert table: {e} {row}")
        return "<p>Error generating alert table. {row} </p>", []

def generate_netpath_table(session):
    query = swis_netpath
    results = session.query(query)

    table_rows = ""
    for row in results.get("results", []):
        status=row['Status']
        last_status=row['LastStatus']
        probetime=mymodule.utc_convert(row['LastProbeTime'])
        if status == 1 and last_status == 1:
            icon_gif = "/icons/Event-5.gif"
        else :
            icon_gif = "/icons/Event-10.gif"

        path_id=row['EndpointServiceID']
        if path_id == 208 :
            table_rows += (f"<tr><td style='text-align:center'><img src=\"{icon_gif}\" alt=\"\"/></td><td style='text-align:center'>{probetime}</td><td><a href=\"https://orion.net.mgmt/ui/netpath/routeinspector/208/9/0/0/0/0/0/0/\" target=\"_blank\"> NetPath From KDC SPAPPORIKPE1 to CST-PHSACDCLDCVCH4 </a></td></tr>")
        elif path_id == 216 :
            table_rows += (f"<tr><td style='text-align:center'><img src=\"{icon_gif}\" alt=\"\"/></td><td style='text-align:center'>{probetime}</td><td style='text-align:left'><a href=\"https://orion.net.mgmt/ui/netpath/routeinspector/216/13/0/0/0/0/0/0\" target=\"_blank\"> NetPath From CW SPAPPORICWPE1 to CST-PHSACDCLDCPHSA3 </a></td></tr>")        

    results_data = results.get("results", [])
    results_html = f"""
    <table id="netpathTable" style="font-size:11px; width:100%">
        <thead>
            <tr>
                <th style='width:10%'>Status</th><th style='width:20%'>LastProbeTime</th><th>CST NetPath </th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """
    return results_html, results_data

def generate_apipoller_table(session):
    query = swis_apipoller
    results = session.query(query)

    table_rows = ""
    for row in results.get("results", []):
        status=row['Status']
        pollername=row['Name']
        pollertime=mymodule.utc_convert(row['LastPollTimestamp'])
        if status == 1:
            icon_gif = "/icons/Event-5.gif"
        else :
            icon_gif = "/icons/Event-10.gif"

        apipoller_id=row['ID']
        if apipoller_id == 6 :
            table_rows +=(f"<tr><td style='text-align:center'><img src=\"{icon_gif}\" alt=\"\"/></td><td style='text-align:center'>{pollertime}</td><td><a href=\"https://orion.net.mgmt//Orion/View.aspx?NetObject=OAPI:6\" target=\"_blank\">{pollername}</a></td></tr>")
        elif apipoller_id == 7 :
            table_rows += (f"<tr><td style='text-align:center'><img src=\"{icon_gif}\" alt=\"\"/></td><td style='text-align:center'>{pollertime}</td><td style='text-align:left'><a href=\"https://orion.net.mgmt//Orion/View.aspx?NetObject=OAPI:7\" target=\"_blank\">{pollername}</a></td></tr>")       

    results_data = results.get("results", [])
    results_html = f"""
    <table id="apipollerTable" style="font-size:11px; width:100%">
        <thead>
            <tr>
                <th style='width:10%'>Status</th><th style='width:20%'>LastPollTime</th><th>API Poller</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """
    return results_html, results_data  

def get_orion_dashboard_html(request, npm_server, username, password, session_id):
    try:
        logger.debug("Debug: Starting main_all function")
        session_path = os.path.join(session_dir, f"{session_id}.json")

        # Initialize and attempt to connect
        session = OrionSession(npm_server, username, password)
        # connect() MUST throw an error if UN/PW is wrong or IP is down
        session.connect(session_id)

        # Try to reuse OrionSession from file
        if os.path.exists(session_path):
            with open(session_path, "r") as f:
                session_data = json.load(f)
                if session_data.get("npm_server") == npm_server and session_data.get("username") == username:
                    session = OrionSession(npm_server, username, password)
                    session.session_id = session_id  # Reuse ID
                    session.reuse = True
                    logger.debug(f"Reusing session: {session_id}")
                else:
                    logger.warning("Mismatch in session, starting fresh")
                    session = OrionSession(npm_server, username, password)
                    session.connect(session_id=session_id)
        else:
            session = OrionSession(npm_server, username, password)
            # session.connect(session_id=session_id)

        # Save session metadata (once)
        if not os.path.exists(session_path):
            session_meta = {
                "session_id": session_id,
                "username": username,
                "npm_server": npm_server,
                "ip": request.client.host,
                "timestamp": datetime.now().isoformat()
            }
            with open(session_path, "w") as f:
                json.dump(session_meta, f)    


        # Get the current time as the last execution time
        orion_status = check_orion_status(session)
        last_execution_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Generate dynamic tables
        node_table = generate_node_table(session)
        interface_table = generate_interface_table(session)
        # event_table = generate_event_table(session)
        alert_table = generate_alert_table(session)
        netpath_table = generate_netpath_table(session)
        apipoller_table = generate_apipoller_table(session)

        rendered_html = templates.get_template("orion_dashboard.html").render({
            "request": request,
            "last_execution_time": last_execution_time,
            "orion_status": orion_status,
            "npm_server": npm_server,
            "npm_username": username,
            "stale": False,  # <--- Not stale
            "node_table": node_table[0],
            "interface_table": interface_table[0],
            # "event_table": event_table,
            "alert_table": alert_table[0],
            "netpath_table": netpath_table[0],
            "apipoller_table": apipoller_table[0],
        })
        # Save the last good page
        with open("data/last_orion_dashboard.html", "w", encoding="utf-8") as f:
            f.write(rendered_html)

    # 20251226 Create a dictionary of data for the DB manager

        db_manager = OrionDatabaseManager(mainconfig.DB_ORION_PATH)
        db_manager.setup_tables()

        conn = sqlite3.connect(mainconfig.DB_ORION_PATH)
        curr = conn.cursor()

        # Check if we have data
        db_manager.setup_tables()

        data_for_db = {
            "node_table": node_table[1],  # pass the data part
            "custom_properties_table": node_table[2], 
            "interface_table": interface_table[1],  
            "alert_table": alert_table[1],  
            "netpath_table": netpath_table[1], 
            "apipoller_table": apipoller_table[1],  
            "sites_topology": node_table[3],
            # add others if needed
        }

        curr.execute("SELECT COUNT(*) FROM [Orion.NodesCustomProperties]")
        count = curr.fetchone()[0]
        if count == 0:
            logger.debug("Performing Initial Full Load...")
            query = mainconfig.swis_ncp
            swis_result = session.query(query)
            # Safety Check for NoneType
            if swis_result and swis_result.get("results"):
                results = swis_result.get("results")
                # Ensure you are grabbing the correct index (usually results[0] or the whole list)
                data_for_db["NodesCustomProperties"] = results
        
        # Pass the dictionary to the sync function
        sync_orion_data(data_for_db)
        # sync_historical_tracing(session)
    # 20251226 Create a dictionary of data for the DB manager

        # Return both content and session_id (so FastAPI route can attach it)
        return rendered_html, session_id
    
    except Exception as e: # 20251110 Fix: Safe html.escape() with Default
        logger.error(f"Dashboard generation failed: {type(e).__name__}: {e}")
        # Do NOT return cached_html here. Raise the error to the router.
        raise ConnectionError(str(e))
    
        # try:
        #     with open("data/last_orion_dashboard.html", "r", encoding="utf-8") as f:
        #         cached_html = f.read()
        #     if cached_html and "<body>" in cached_html:
        #         if "Connection" in str(e) or "timeout" in str(e).lower():
        #             stale_popup = f"""
        #             <div id="orionDownModal" style="display:block;position:fixed;z-index:9999;left:0;top:0;width:100vw;height:100vh;background:rgba(0,0,0,0.4);">
        #                 <div style="background:#fff;color:#b00;max-width:400px;margin:10% auto;padding:30px 10px;border-radius:8px;box-shadow:0 2px 10px #000;">
        #                     <h2 style="background:#b00;"><a href="https://{ npm_server }" target="_blank">Orion Status  </a><br><button onclick="document.getElementById('orionDownModal').style.display='none';" style="margin-top:20px;margin-bottom:10px;padding:8px;">Unreachable or {html.escape(str(e))} </button></h2>
        #                 </div>
        #             </div>
        #             """
        #         return cached_html, session_id
        # except Exception as cache_err:
        #     logger.error(f"Cache load failed: {cache_err}")
        # return f"<h2>Dashboard Error</h2><p>{html.escape(str(e))}</p>", session_id


############## data sync functions

#202601
def sync_historical_tracing(session):
    query = swis_nodesevent
    results = session.query(query)
    db_conn = OrionDatabaseManager(mainconfig.DB_ORION_PATH)
    db_conn.connect()

    nodes_history = {}
    # db_manager = OrionDatabaseManager(mainconfig.DB_ORION_PATH)    
    for row in results.get("results", []): 
        node_id = row['NodeID']
        event_type = row['EventType']
        event_time = parse_swis_date(row['EventTime'])

        if node_id not in nodes_history:
            nodes_history[node_id] = []

        # If it's a 'Down' event, store it as the start of an outage
        if event_type == 1:
            nodes_history[node_id].append({'down': event_time, 'desc': row['Message']})
        
        # If it's an 'Up' event, find the last 'Down' and calculate duration
        elif event_type == 5 and nodes_history[node_id]:
            last_outage = nodes_history[node_id][-1]
            if 'up' not in last_outage:
                last_outage['up'] = event_time
                duration = (event_time - last_outage['down']).total_seconds()
                
                # # Import to local DB, db more than 50 MB, disable for now  
                # db_conn.import_history_record(
                #     node_id, 
                #     last_outage['down'], 
                #     event_time, 
                #     int(duration),
                #     last_outage['desc'],
                #     row.get('StatusDescription', "")
                # )

def parse_swis_date(date_str):
    if not date_str:
        return None
    try:
        # 1. Remove 'Z' if present
        date_str = date_str.replace('Z', '')
        
        # 2. Handle the precision issue (7 decimals -> 6 decimals)
        if '.' in date_str:
            base, fraction = date_str.split('.')
            date_str = f"{base}.{fraction[:6]}" # Truncate to microseconds
            
        return datetime.fromisoformat(date_str)
    except ValueError:
        # Fallback for very weird strings
        return datetime.strptime(date_str[:19], '%Y-%m-%dT%H:%M:%S')
    

############## main
templates = Jinja2Templates(directory="templates")
import asyncio

@router.get("/check_form", response_class=HTMLResponse)
async def get_device_output_form(request: Request):
    return templates.TemplateResponse("orion_login.html", {"request": request})

# @router.post("/check_output", response_class=HTMLResponse)
# async def run_orioncheck_route(
#     request: Request,
#     npm_server: str = Form(...),
#     npm_uname: str = Form(...),
#     npm_passwd: str = Form(...),
# ):
#     try:
#         # This enforces the "one session per user" rule
#         session_id = get_deterministic_session_id(npm_server, npm_uname)

#         # session_id = get_or_create_session_id_hash(request, npm_server, npm_uname)

#         loop = asyncio.get_running_loop()

#         rendered_html, final_session_id = await loop.run_in_executor(
#             None,
#             get_orion_dashboard_html,
#             request,
#             npm_server,
#             npm_uname,
#             npm_passwd,
#             session_id,
#         )

#         # Now attach session_id cookie to actual response
#         response = HTMLResponse(content=rendered_html)
#         response.set_cookie(key="session_id", value=final_session_id, httponly=True, path="/")
#         return response
#     except ConnectionError as ce:
#         # Return a popup error if the server is down
#         return HTMLResponse(content=f"""
#             <script>
#                 alert("ACCESS DENIED / SERVER DOWN\\n\\nError: {str(ce)}");
#                 window.location.href = "/orion/login_page"; 
#             </script>
#         """, status_code=503)
#     except Exception as e:
#         logger.error(f"Unexpected error: {e}")
#         return HTMLResponse(content="<h2>An unexpected error occurred.</h2>", status_code=500)


# orion.py

@router.post("/check_output", response_class=HTMLResponse)
async def run_orioncheck_route(
    request: Request,
    npm_server: str = Form(...),
    npm_uname: str = Form(...),
    npm_passwd: str = Form(...),
):
    try:
        # 1. Generate the deterministic ID immediately from credentials
        # This enforces the "one session per user" rule
        session_id = get_deterministic_session_id(npm_server, npm_uname)

        loop = asyncio.get_running_loop()

        # 2. Execute the heavy lifting in a thread pool
        # get_orion_dashboard_html will now find/create the pickle based on this hash
        rendered_html, final_session_id = await loop.run_in_executor(
            None,
            get_orion_dashboard_html,
            request,
            npm_server,
            npm_uname,
            npm_passwd,
            session_id,
        )

        # 3. Attach the hash-based session_id to the cookie
        # Setting httponly=True and samesite='lax' for security
        response = HTMLResponse(content=rendered_html)
        response.set_cookie(
            key="session_id", 
            value=final_session_id, 
            httponly=True, 
            path="/",
            samesite="lax"
        )
        
        return response

    except ConnectionError as ce:
        # Handle failed logins or unreachable servers
        logger.error(f"Login failed for {npm_uname}: {ce}")
        return HTMLResponse(content=f"""
            <script>
                alert("ACCESS DENIED / SERVER DOWN\\n\\nError: {html.escape(str(ce))}");
                window.location.href = "/check_form"; 
            </script>
        """, status_code=401)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return HTMLResponse(content="<h2>An unexpected error occurred.</h2>", status_code=500)

@router.get("/map_data")
async def get_map_data(site: str = None):

    if not site:
        return {"nodes": [], "edges": []}
    
    db = OrionDatabaseManager(mainconfig.DB_ORION_PATH)
    db.connect()
    
    # 1. Fetch Topology Links
    query = "SELECT SourceNodeID, SourceNodeName, TargetNodeID, TargetNodeName, SourceInterface FROM [Orion.Topology]"
    query += f" WHERE SourceSite LIKE '%{site}%' OR TargetSite LIKE '%{site}%'"

    df = pd.read_sql_query(query, db.conn)
    db.conn.close()

    # 2. Build vis.js format
    nodes = []
    edges = []
    seen_nodes = set()

    for _, row in df.iterrows():
        # Add Source Node
        if row['SourceNodeID'] not in seen_nodes:
            # Example logic: If name contains 'CORE', put at level 0
            level = 0 if 'CORE' in row['SourceNodeName'].upper() else 1
            nodes.append({
                "id": row['SourceNodeID'], 
                "label": row['SourceNodeName'], 
                "level": level,  # Enforces vertical position
                "shape": "box", 
                "color": "#007bff"
            })
            seen_nodes.add(row['SourceNodeID'])

            # nodes.append({"id": row['SourceNodeID'], "label": row['SourceNodeName'], "shape": "dot", "color": "#007bff"})
            # seen_nodes.add(row['SourceNodeID'])
        
        # Add Target Node
        if row['TargetNodeID'] not in seen_nodes:
            nodes.append({
                "id": row['TargetNodeID'], 
                "label": row['TargetNodeName'], 
                "shape": "box", 
                "level": 2 if 'CORE' not in row['TargetNodeName'].upper() else 0
            })
            seen_nodes.add(row['TargetNodeID'])

        # Add Edge (The Connection)
        edges.append({
            "from": row['SourceNodeID'], 
            "to": row['TargetNodeID'], 
            "label": row['SourceInterface'],
            "font": {"size": 10, "align": "middle"},
            "arrows": 'to' # Shows direction of connectivity
        })

    return {"nodes": nodes, "edges": edges}


@router.get("/orion_analysis", response_class=HTMLResponse)
async def get_analysis_page(request: Request):
    # This renders your orion_custom_properties.html file
    return templates.TemplateResponse("orion_custom_properties.html", {"request": request})

@router.get("/get_custom_properties_data")
async def get_custom_properties_data():
    db_manager = OrionDatabaseManager(mainconfig.DB_ORION_PATH)
    try:
        conn = sqlite3.connect(mainconfig.DB_ORION_PATH)
        db_manager.setup_tables()
        query = "SELECT  * FROM [Orion.Nodes]"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Replace NaN/None with empty strings for clean display
        df = df.fillna("")
        
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        logger.error(f"Failed to fetch table data: {e}")
        return {"data": [], "error": str(e)}

@router.get("/topology")
async def get_topology_data(site: str = None):
    db = OrionDatabaseManager(mainconfig.DB_ORION_PATH)
    db.connect()
    # Filter by site if provided, otherwise return all
    query = "SELECT * FROM [Orion.Topology]"
    if site:
        query += f" WHERE Site = '{site}'"
    df = pd.read_sql_query(query, db.conn)
    db.conn.close()
    return {"data": df.to_dict(orient="records")}

