import re,urllib3,urllib.parse,os,json,atexit, html, traceback

from time import perf_counter,time,ctime
from datetime import datetime
from typing import Any
from fastapi.templating import Jinja2Templates

# Local imports
import utils.fastapi_mymodule as mymodule
import mainconfig as mainconfig
from utils.session_manager import OrionSession, update_session_audit
from utils.orion_db_manager import sync_orion_data
from utils.orion_db_manager import OrionDatabaseManager
from utils.analysis_sqlite import sync_syslog_to_routing_db

# --- Setup ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = mainconfig.setup_module_logger(__name__)


# --- Directories ---
curr_dir= os.path.dirname(__file__)
log_dir=os.path.abspath(os.path.join(curr_dir, '..', 'logs'))
data_dir=os.path.abspath(os.path.join(curr_dir, '..', 'data'))
icon_dir = mainconfig.ICONS_DIR
session_dir = mainconfig.SESSION_DIR  # Directory to store session files
SESSION_LOG_FILE = os.path.join(session_dir, "orion_session_log.json")

DB_ORION_PATH = mainconfig.DB_ORION_PATH

templates = Jinja2Templates(directory="templates")

from sqlalchemy import create_engine as _create_engine
_orion_read_engine = _create_engine(
    f"sqlite:///{mainconfig.DB_ORION_PATH}",
    connect_args={"check_same_thread": False}
)


for directory in [log_dir, data_dir, session_dir]:
    if not os.path.exists(directory):
        os.makedirs(directory)


#   golbal var    
sitedown_list=[]    
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

def cleanup_old_sessions(session_dir, max_age=3600*12):  # Default max age: 12 hours
    now = time()
    for file in os.listdir(session_dir):
        # 20260219 ignore 'orion_session_log.json'
        if file == "orion_session_log.json":
            continue
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
    nodedown_list = []
    table_rows = ""

    # --- UPDATED: Load Active Power Outages with URLs ---
    power_lookup = {} # Use a dictionary to store SiteName: SourceURL
    debug_path = os.path.join(mainconfig.DATA_DIR, "debug_active_poweroutages.json")
    
    if os.path.exists(debug_path):
        try:
            with open(debug_path, "r", encoding="utf-8") as f:
                power_data = json.load(f)
                for case in power_data:
                    url = case.get('SourceURL', '#')
                    # Map every site in this case to the same SourceURL
                    for site in case.get('all_sites', []):
                        power_lookup[site] = url
        except Exception as e:
            logger.error(f"Error loading power data for tags: {e}")
    # ----------------------------------------------------

    query_site = swis_site
    results_site = session.query(query_site)
    site_data = results_site.get("results", [])
    for row_site in site_data:  # FIX: reuse .get() result, don't double-fetch with ['results']
        site_name = row_site.get('Site', '').strip()
        site_ha = row_site.get('HA', '').strip()
        site_address = row_site.get('Address', '').strip()
        site_city = row_site.get('City', '').strip()
        nodedown_list.append({
            'Site': site_name,
            'HA': site_ha,
            'Address': site_address,
            'City': site_city,
            'DownCount': row_site.get('DownCount'),
            'TotalNodes': row_site.get('TotalNodes'),
            'FullDisplay': f"{site_ha} - {site_name}, {site_address}, {site_city}, {row_site.get('DownCount')}/{row_site.get('TotalNodes')}"
        })
        if row_site.get('DownCount') and row_site.get('DownCount') == row_site.get('TotalNodes'):
            # Store as a dictionary for precise matching later
            sitedown_list.append({
                'Site': site_name,
                'Address': site_address,
                'City': site_city,
                'FullDisplay': f"{site_ha} - {site_name}, {site_address}, {site_city}, {row_site.get('DownCount')}/{row_site.get('TotalNodes')}"
            })
        # 20260224 
            

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

            # event time: Calculate the '25d 13h 45m' string
            # Ensure we have a valid positive integer
            total_sec = abs(int(row.get('Seconds') or 0))

            # Convert seconds to minutes and remaining seconds
            # (total_sec // 60) gives minutes, (total_sec % 60) gives remaining seconds
            total_minutes, _ = divmod(total_sec, 60)
            total_hours, minutes = divmod(total_minutes, 60)
            days, hours = divmod(total_hours, 24)
            duration_str = f"{days}d {hours:02d}h {minutes:02d}m"

            # url="{DetailsUrl}".format(**row)
            # url_link=orion_prefix+url            
            url = row.get("DetailsUrl", "") # Use .get with a default
            if url and orion_prefix:
                url_link = orion_prefix + url
            else:
                url_link = url # Fallback to raw url or empty string        

            #20250106 update site url link to orion search via "urllib"
            site_searchurl = "https://orion.net.mgmt/apps/search/?q="
            node_name = str(row.get('NodeName') or '').strip()
            node_address = str(row.get('Address') or 'None').strip()
            raw_site_name = str(row.get('Site') or 'Unknown').strip()
            site_ha = str(row.get('HA') or 'Unknown').strip()
            # 1. Find the match in the sitedown_list using a prefix match
            # We check if the item in the list starts with the specific site name
            # site_down_match = next((item for item in sitedown_list if item.startswith(f"{raw_site_name},")), None)
            # 20260121. Match by BOTH Site Name and Address to distinguish campus buildings
            site_down_match = next((
                item for item in sitedown_list 
                if item['Site'].lower() == raw_site_name.lower() and item['Address'].lower() == node_address.lower()
            ), None)

            nodedown_match = next((
                item for item in nodedown_list 
                if item['Site'].lower() == raw_site_name.lower() and item['Address'].lower() == node_address.lower()
            ), None)

            if site_down_match:
                # Use the specific display string we built earlier
                display_site_name = site_down_match['FullDisplay']
                is_down = True
            else:
                # display_site_name = raw_site_name + ", " + node_address + ", " + node_city
                display_site_name = nodedown_match['FullDisplay'] if nodedown_match else raw_site_name
                is_down = False

            # --- NEW: Check for Power Outage Tag ---
            power_tag = ""
            if raw_site_name in power_lookup:
                target_url = power_lookup[raw_site_name]
                power_tag = (
                    f'<a href="{target_url}" target="_blank" style="text-decoration: none;">'
                    f'<span style="background-color: #ffc107; color: #000;border-radius: 3px; font-weight: bold; margin-left: 5px; '
                    f'cursor: pointer;" title="View Outage Map">⚡OUTAGE</span></a>'
                )
            # else:
            #     power_tag = '<span style="background-color: lightgreen; color: #000; padding: 2px 5px; font-size: 8px; border-radius: 3px; font-weight: bold; margin-left: 5px;">POWER</span>'
            # ---------------------------------------


            escaped_node_name = html.escape(node_name)
            # escaped_site_display = html.escape(display_site_name)
            escaped_site_display = html.escape(display_site_name)
            encoded_site_search = urllib.parse.quote(raw_site_name) # Search by raw name for better results

            table_rows += (
                "<tr class=\"{}\"><td style=\"text-align:right;padding-right:5px\">{}</td><td><a href=\"{}\" target=\"_blank\">{}</a></td>"
                "<td><div style=\"display: flex;justify-content: space-between;\"><div><a href=\"{}\" target=\"_blank\">{}</a></div><div>{}</div></div></td>"
                "<td>{}</td>"
                "<td id=\"IPAddress\" style=\"display:none\">{}</td></tr>\n"
            ).format(
                class_tag,
                # row.get('Duration', ""),
                duration_str,
                url_link if url_link is not None else "",
                escaped_node_name,
                f"{site_searchurl}{encoded_site_search}",
                f"<b>{escaped_site_display} **Site Down** </b>" if is_down else escaped_site_display, power_tag,
                row.get('SiteType', ""),
                row.get('IPAddress', "")
            )  

    results_html = f"""
    <div style="max-height: 50vh; overflow-y: auto;">
    <table id="nodedownTable" style="display:none; width:100%">
        <thead>
            <tr>
                <th style="width:14%">Duration</th> 
                <th >
                    <div>Link:
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_nodedownTable" value="Orion" checked>OrionNode</label>
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_nodedownTable" value="SNOW">SNOW</label>
                        <label><input type="radio" name="link_type_nodedownTable" value="Orion_UDT">OrionUDT</label>
                        <label><input type="radio" name="link_type_nodedownTable" value="Ringer">RingerOPS</label>
                    </div>
                </th> 
                <th style="width:12%">Type</th>
                <th style="display:none">IPAddress</th>
            </tr>
        </thead>
        <tbody style="font-size:11px;">
            {table_rows}
        </tbody>
    </table>
    </div>
    """

    return table_rows, results_data, site_data, results_sitetopology_data

def generate_interface_table(session):
    query = swis_interfacdown
    results = session.query(query)
    table_row = ""
    rows_list = []
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

        # event time: Calculate the '25d 13h 45m' string
        total_sec = abs(int(row.get('Seconds') or 0))
        total_minutes, _ = divmod(total_sec, 60)
        total_hours, minutes = divmod(total_minutes, 60)
        days, hours = divmod(total_hours, 24)
        # Formatted output: "25d 13h 45m"
        duration_str = f"{days}d {hours:02d}h {minutes:02d}m"

        url = row.get("DetailsUrl", "") # Use .get with a default
        if url and orion_prefix:
            url_link = orion_prefix + url
        else:
            url_link = url # Fallback to raw url or empty string          

        table_row = (            
                "<tr class=\"{}\"><td style=\"text-align:right;padding-right:5px\">{}</td><td style=\"padding-left:5px;\" id=\"node_info\" value=\"{}\"><a href=\"{}\" target=\"_blank\">{}</a></td>"
                "<td style=\"text-align:left;padding-left:3px\">{}</td></tr>\n"
            ).format(
                class_tag,
                duration_str,
                row.get('IPAddress', ""),                
                url_link if url_link is not None else "",
                row.get('NodeName', ""),
                row.get('StatusDescription', "")
            )
        rows_list.append(table_row)
    results_html = "\n".join(rows_list)

    results_data = results.get("results", [])
    # results_html = table_rows_joined
    # results_html = f"""
    # <table id="interfacedownTable" style="font-size:11px;width:100%">
    #     <thead>
    #         <tr>
    #             <th style="width:14%">Duration</th> 
    #             <th>
    #                 <div>
    #                     <strong>Link-Toggle:</strong>
    #                     <label style="margin-right: 10px;"><input type="radio" name="link_type_interfacedownTable" value="Orion" checked>OrionNode</label>
    #                     <label style="margin-right: 10px;"><input type="radio" name="link_type_interfacedownTable" value="SNOW">SNOW</label>
    #                     <label><input type="radio" name="link_type_interfacedownTable" value="webssh">WebSSH</label>
    #                     <label><input type="radio" name="link_type_interfacedownTable" value="Ringer">RingerOPS</label>

    #                 </div>
    #             </th> 
    #             <th style="width:12%">Status</th>
    #         </tr>
    #     </thead>
    #     <tbody>
    #         {table_rows_joined}
    #     </tbody>
    # </table>
    # """
    return results_html, results_data

def generate_event_table(session):
    query = swis_event
    results = session.query(query)
    table_rows = ""
    for row in results.get("results", []):

        # event time:
        timestamp=row['EventTime']
        date=re.split("T",timestamp)[0]
        time_utc=re.search(r"[0-9][0-9]\:[0-9][0-9]\:[0-9][0-9]",timestamp)[0]
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
        if re.match(r"Windows|Eaton|Merlin|Northern",row['Vendor']) :
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

            # event time: Calculate the '25d 13h 45m' string
            total_min = int(row.get('DurationMinutes') or 0)
            days = total_min // 1440
            hours = (total_min % 1440) // 60
            minutes = total_min % 60
            # Use :02d to force 2 digits with leading zeros
            duration_str = f"{days}d {hours:02d}h {minutes:02d}m"

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

            # 20260212 --- FIXED CODE ---
            url = row.get("EntityDetailsUrl")
            node_id = row.get("RelatedNodeID")

            if url:
                # Use the specific entity link if it exists
                url_link = orion_prefix + url
            elif node_id:
                # FALLBACK: Link to the Node Details page if it's a Stack alert with no specific URL
                url_link = f"{orion_prefix}/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:{node_id}"
            else:
                # FINAL FALLBACK: Link to the general Orion Alerts page
                url_link = "https://orion.net.mgmt/orion/netperfmon/alerts.aspx"         

            # if "Down" in row['StatusDescription']:
            if row.get('Status') in [2,12] or any(keyword in row.get('AlertMessage', '') for keyword in ["Failure","down", "broken"]):
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
                "<tr>"
                f"<td style='text-align:right;padding-right:5px;white-space:nowrap;'>{duration_str}</td>"
                "<td style='text-align:center' class='node_info_cell' value='{},{}'>{}</td>"
                "<td><img src='{}' alt=''/><a href='{}' target='_blank'>{}</a></td>"
                "</tr>"
            ).format(
                vendor, nodeip, TriggerCount, status_gif, url_link, Message
            )

        results_data = results.get("results", [])
        results_html = f"""
        <table id="alertTable" style="font-size:11px;">
            <thead>
                <tr>
                    <th style="width:13%;">Duration</th><th>Count</th>
                    <th style="width:80%" >
                        <div style="display:flex;justify-content: space-around;align-items: flex-end;">
                            <div>Link-Toggle:
                            <label style="margin-right: 10px;"><input type="radio" name="link_type_alertTable" value="Orion" checked>OrionNode</label>
                            <label style="margin-right: 10px;"><input type="radio" name="link_type_alertTable" value="SNOW"> SNOW</label>
                            <label><input type="radio" name="link_type_alertTable" value="webssh">WebSSH</label>
                            <label><input type="radio" name="link_type_alertTable" value="Ringer">RingerOPS</label>
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

# 20260318 move to api module: no need to save syslog to file anymore, directly save to DB in generate_syslog function and display through table, also added link toggle for syslog table
def generate_syslog(session):
    query = mainconfig.swis_syslog
    results = session.query(query)

    # Debug: log the raw SWIS response type and first item so we can see
    # exactly what's being returned when non-dict rows appear.
    _raw = results.get("results", [])
    if _raw and not isinstance(_raw[0], dict):
        logger.warning("generate_syslog: SWIS returned non-dict first item: %r", type(_raw[0]))

    table_rows = ""
    for row in results.get("results", []):
        # message_id = int(row.get('LogEntryID', 0))
        # if message_id > temp_max_id:
        #     temp_max_id = message_id
        message_syslog = row['Message']
        # FIX: convert once and store in local var — row['DateTime'] was being
        # converted then passed to utc_convert() a second time (double-conversion)
        message_syslog_time = mymodule.utc_convert(row['DateTime'])
        row['DateTime'] = message_syslog_time   # update row for DB upsert
        message_syslog_link = f"{orion_prefix}/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N:{row['NodeID']}&ViewID=2453"

        node_id_to_find = str(row['NodeID'])
        # Find the device dictionary that matches the nodeid
        device = next((item for item in mainconfig.CORE_DEVICES if item["nodeid"] == node_id_to_find), None)
        if device:
            host_name = device['name']
            host_ip = device['ip']
        else:
            host_name = "Unknown Node"
            host_ip = "0.0.0.0"

        # Add these to the dictionary so they are available for the DB upsert
        row['NodeName'] = host_name
        row['IPAddress'] = host_ip

        if any(word in message_syslog for word in ["to UP", "to FULL", "to ESTABLISHED"]):
            change_stauts = "UP"
            icon_gif = "/icons/Event-5.gif"
        elif any(word in message_syslog for word in ["to DOWN", "to IDLE", "to INIT"]):
            change_stauts = "DOWN"
            icon_gif = "/icons/Event-10.gif"
        else:
            change_stauts = "Unknown"
            icon_gif = "/icons/Event-504.gif"  # question mark icon for unknown status

        table_rows += (f"""
            <tr>
                <td style='text-align:center'>{message_syslog_time}</td>
                <td style='text-align:left'><img src="{icon_gif}" alt=""><a href="{message_syslog_link}" data-hostip="{host_ip}" data-hostname="{host_name}" target="_blank">{message_syslog}</a></td>
            </tr>
        """)       

    # Filter to dicts only — SWIS OLM can return error strings mixed into results
    results_data = [r for r in results.get("results", []) if isinstance(r, dict)]
    results_html = f"""
    <table id="syslogTable" style="font-size:11px; width:100%">
        <thead>
            <tr>
                <th style='width:10%'>DateTime</th>
                <th>
                    <div style="display:flex;justify-content: space-around;align-items: flex-end;">
                        <div>Link-Toggle:
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_syslogTable" value="Orion" checked>OrionNode</label>
                        <label style="margin-right: 10px;"><input type="radio" name="link_type_syslogTable" value="SNOW"> SNOW</label>
                        <label><input type="radio" name="link_type_syslogTable" value="webssh">WebSSH</label>
                        <label><input type="radio" name="link_type_syslogTable" value="Ringer">RingerOPS</label>
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

    # 20260318 --- saved to DB now; file backup removed (was appending forever with mode "a")

    return results_html, results_data  



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

# Helper to safely call submodules
def safe_generate(func, session, default_val="<p class='text-danger'>Error loading data</p>"):
    try:
        return func(session)
    except Exception as e:
        logger.error(f"Module Error in {func.__name__}: {e}")
        # FIX: return a tuple matching the function's expected shape so callers
        # like syslog_table[1] and node_table[1] don't raise TypeError.
        # generate_node_table returns (html, data, site_data, topo_data) — 4 items
        # generate_syslog / others return (html, data) — 2 items
        # We return (error_html, [], [], []) which is safe for all callers.
        error_html = f"<div class='alert alert-danger'>Failed to load {func.__name__} data.</div>"
        return (error_html, [], [], [])



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


        # Wrap each call so one failure doesn't stop the others
        node_table = safe_generate(generate_node_table, session)
        interface_table = safe_generate(generate_interface_table, session)
        alert_table = safe_generate(generate_alert_table, session)
        netpath_table = safe_generate(generate_netpath_table, session)
        apipoller_table = safe_generate(generate_apipoller_table, session)
        syslog_table = safe_generate(generate_syslog, session)    

        rendered_html = templates.get_template("orion_dashboard.html").render({
            "request": request,
            "last_execution_time": last_execution_time,
            "orion_status": orion_status,
            "npm_server": npm_server,
            "npm_username": username,
            "stale": False,  # <--- Not stale
            "node_table": node_table[0],
            "interface_table": interface_table[0],
            # "syslog_table": syslog_table[0],  #-- html load from db
            "alert_table": alert_table[0],
            "netpath_table": netpath_table[0],
            "apipoller_table": apipoller_table[0],
        })
        # Save the last good page
        with open("data/last_orion_dashboard.html", "w", encoding="utf-8") as f:
            f.write(rendered_html)

    # 20251226 Create a dictionary of data for the DB manager

        db_manager = OrionDatabaseManager(mainconfig.DB_ORION_PATH)
        db_manager.connect()       # FIX: must connect before setup_tables or cursor use
        db_manager.setup_tables()  # idempotent — safe to call every refresh

        data_for_db = {
            "node_table": node_table[1],
            "custom_properties_table": node_table[2],
            "interface_table": interface_table[1],
            "alert_table": alert_table[1],
            "netpath_table": netpath_table[1],
            "apipoller_table": apipoller_table[1],
            "sites_topology": node_table[3],
            "syslog_table": syslog_table[1]  # upsert_syslog filters new-only internally
        }

        from sqlalchemy import text as _sa_text
        with _orion_read_engine.connect() as _tmp_conn:
            count = _tmp_conn.execute(_sa_text(
                "SELECT COUNT(*) FROM [Orion.NodesCustomProperties]"
            )).scalar()
        if count == 0:
            logger.debug("Performing Initial Full Load...")
            swis_result = session.query(mainconfig.swis_ncp)
            if swis_result and swis_result.get("results"):
                data_for_db["NodesCustomProperties"] = swis_result.get("results")

        sync_orion_data(data_for_db)
        db_manager.close()  # FIX: always close the write connection
    # 20251226 Create a dictionary of data for the DB manager

        # Return both content and session_id (so FastAPI route can attach it)
        return rendered_html, session_id
    
    except Exception as e: # 20251110 Fix: Safe html.escape() with Default
# This will give you the exact "filename:line_number : function_name"
        error_details = traceback.format_exc()
        print(f"Dashboard generation failed: {e}")
        print(f"DEBUG TRACE:\n{error_details}")
        logger.error(f"Dashboard generation failed: {e} DEBUG TRACE:\n{error_details}")
        raise ConnectionError(str(e))