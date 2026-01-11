from http.client import CONFLICT
import sqlite3
import logging
import os, time
from datetime import datetime
import mainconfig as mainconfig
# from routers.orion import OrionSession
logger = mainconfig.setup_module_logger(__name__)

class OrionDatabaseManager:
    def __init__(self, db_path):
        """Initialize the manager with the path to the Orion SQLite database."""
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.logger = logging.getLogger('analysis.orion')

    def connect(self):
        """Establish a connection to the SQLite database."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
        except sqlite3.Error as e:
            self.logger.error(f"Failed to connect to Orion DB: {e}")

    def setup_tables(self):
        """Creates all necessary Orion tables if they do not exist."""
        self.connect()
        
        # 1. Orion.Nodes Table - Realtime Table (Current State)
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS [Orion.Nodes] 
            (NodeID TEXT PRIMARY KEY, IPAddress TEXT, Site TEXT, SiteType TEXT, DetailsUrl TEXT, NodeName TEXT, Status TEXT, StatusDescription TEXT, DownTime TEXT, Duration TEXT, Seconds INTEGER)''')
        
        # 1.1 Create Index on Orion.NodesCustomProperties for faster lookups
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS [Orion.NodesCustomProperties] 
            (Site TEXT, NodeName TEXT, IPaddress TEXT, DetailsUrl TEXT, NodeID TEXT, Status TEXT, StatusDescription TEXT, Address TEXT, Architecture TEXT, AssetTag TEXT, Building TEXT, City TEXT, Closest_Poller TEXT, Closet TEXT, Comments TEXT, Configuration TEXT, ControlUpEventID TEXT, DeviceType TEXT, Floor TEXT, HA TEXT, HardwareIncidentStatus TEXT, Imported_From_NCM TEXT, IncidentStatus TEXT, Layer3 TEXT, LdapTestFailureMessage TEXT, Make TEXT, New_Poller_Home TEXT, NodeOwner TEXT,  OutOfBand TEXT, PDIntegrationKey TEXT, PONumber TEXT, ProgramApplication TEXT, ProgramApplicationType TEXT, Provider TEXT, ProviderSiteID TEXT, Rack TEXT, Region TEXT, ServiceType TEXT, SiteContactName TEXT, SiteHours TEXT, SitePhone TEXT, SiteType TEXT, Technology TEXT, Topology TEXT, Unmanaged_ TEXT, WANbandwidth TEXT, WANnode TEXT, WANProvider TEXT, WANProviderCSID TEXT, WANProviderDeviceID TEXT,
            PRIMARY KEY (NodeID))''')

        # 1.3. Create Index - FIX: Ensure spaces around the parenthesis
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_nodeid ON [Orion.Nodes] (NodeID)')

        # 1.4  Trigger to update NodesCustomProperties when Nodes table is updated
        # self.cursor.execute('''DROP TRIGGER IF EXISTS update_cp_status;''')
        # self.cursor.execute('''
        #     CREATE TRIGGER update_cp_status
        #     AFTER INSERT ON [Orion.Nodes]
        #     BEGIN
        #         UPDATE [Orion.NodesCustomProperties]
        #         SET Status = NEW.Status,
        #             StatusDescription = NEW.StatusDescription
        #         WHERE NodeID = NEW.NodeID;
        #         END;
        # ''')

        # 1.4 Create View for Node Full Status
        self.cursor.execute("PRAGMA foreign_keys = ON")
        self.cursor.execute(''' 
            CREATE VIEW IF NOT EXISTS NodeFullStatus AS
            SELECT 
                cp.NodeID, cp.Site, cp.City, 
                n.Status, n.StatusDescription, n.Duration
            FROM [Orion.NodesCustomProperties] cp
            JOIN [Orion.Nodes] n ON cp.NodeID = n.NodeID;
        ''')

        # 1.5 202601 History Table Tracing Table with start/end logic
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS [Orion.StatusHistory] 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
            NodeID TEXT, 
            Status TEXT, 
            StatusDescription TEXT,
            StartTime DATETIME,
            EndTime DATETIME,
            DurationSeconds INTEGER)''')

        # 2. Orion.SitesCustomProperties Table
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS [Orion.SitesCustomProperties]
            (Site TEXT, Address TEXT, City Text,
            TotalNodes TEXT, DownCount TEXT,
            PRIMARY KEY (Site, Address))''') # Use both to define a unique row
                                         
        # 3. Orion.NPM.Interfaces Table
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS [Orion.NPM.Interfaces]
            (DetailsUrl TEXT, IPAddress TEXT, NodeName TEXT, SiteType TEXT, Duration TEXT, DownTime TEXT, 
             PRIMARY KEY (NodeName))''')

        # 4. Orion.AlertObjects Table
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS [Orion.AlertObjects]
            (EntityDetailsUrl TEXT, Status TEXT, TriggerCount TEXT, StatusDescription TEXT, ObjectType TEXT, ObjectName TEXT, 
            AlertMessage TEXT, RelatedNodeCaption TEXT,  Vendor TEXT, ObjectSubType TEXT, IPAddress TEXT,TriggerTimeStamp TEXT,
             PRIMARY KEY (EntityDetailsUrl))''')
        
        self.conn.commit()

    def upsert_node(self, node_data):
        """Inserts or updates a record in Orion.Nodes."""
        # 1. Clear the table first to ensure only fresh data exists
        self.cursor.execute("DELETE FROM [Orion.Nodes]")
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S') # Define current time for tracing
                
        data_rows = "NodeID, IPAddress, Site, SiteType, DetailsUrl, NodeName, Status, StatusDescription, Duration, DownTime, Seconds"
        placeholders = ', '.join(['?'] * len(data_rows.split(', ')))    

        query = f'''INSERT INTO [Orion.Nodes] ({data_rows}) 
                 VALUES ({placeholders})
                 ON CONFLICT(NodeID) DO UPDATE SET 
                Status=excluded.Status, 
                StatusDescription=excluded.StatusDescription,
                Duration=excluded.Duration, 
                DownTime=excluded.DownTime, 
                Seconds=excluded.Seconds'''

        # New Sync Query (Using OR IGNORE in case CP record doesn't exist yet)
        sync_status_query = '''UPDATE [Orion.NodesCustomProperties] 
                SET Status = ?, StatusDescription = ? 
                WHERE NodeID = ?'''

        try:
            for row in node_data:

                node_id = str(row.get('NodeID', ''))
                new_status = str(row.get('Status', ''))
                status_desc = str(row.get('StatusDescription', ''))

                # 1. Get OLD status to see if it changed
                self.cursor.execute("SELECT Status, StatusDescription FROM [Orion.Nodes] WHERE NodeID = ?", (node_id,))
                old_result = self.cursor.fetchone()
                old_status = old_result[0] if old_result else None

                # B. Update Realtime Table

                status_desc = str(row.get('StatusDescription', ''))
                values = (
                    node_id,
                    str(row.get('IPAddress', '')),
                    str(row.get('Site', '')),
                    str(row.get('SiteType', '')),
                    str(row.get('DetailsUrl', '')),
                    str(row.get('NodeName', row.get('Caption', ''))),
                    new_status,
                    status_desc,
                    str(row.get('Duration', '')),
                    str(row.get('DownTime', '')),
                    str(row.get('Seconds', ''))
                )

                self.cursor.execute(query, values)
                self.cursor.execute(sync_status_query, (new_status, status_desc, node_id))

                # if old_status is not None and new_status != old_status:
                #     # Close the previous state and record the new one
                #     # First, we check if there's an open record in history to set an EndTime
                #     self.cursor.execute('''UPDATE [Orion.StatusHistory] 
                #                         SET EndTime = ? 
                #                         WHERE NodeID = ? AND EndTime IS NULL''', (now, node_id))
                    
                #     # Then, insert the new status change record
                #     self.cursor.execute('''INSERT INTO [Orion.StatusHistory] 
                #                         (NodeID, Status, StatusDescription, StartTime) 
                #                         VALUES (?, ?, ?, ?)''', 
                #                         (node_id, new_status, status_desc, now))
                
                # elif old_status is None:
                #     # First time seeing this node, start its history
                #     self.cursor.execute('''INSERT INTO [Orion.StatusHistory] 
                #                         (NodeID, Status, StatusDescription, StartTime) 
                #                         VALUES (?, ?, ?, ?)''', 
                #                         (node_id, new_status, status_desc, now))

            self.conn.commit()
            logger.debug(f"Successfully: upsert_node synced {len(node_data)} nodes.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"SQL Upsert Failed: {e} | Query: {query} | nodes Data: {row}")

    def upsert_interface(self, interface_data):
        """Inserts or updates a record in Orion.NPM.Interfaces."""
        data_rows = "NodeName, IPAddress ,  DetailsUrl , SiteType , Duration, DownTime "
        placeholders = ', '.join(['?'] * len(data_rows.split(', ')))        
        query = f'''INSERT INTO [Orion.NPM.Interfaces] ({data_rows}) 
                 VALUES ({placeholders})
                 ON CONFLICT(NodeName) DO UPDATE SET 
                    IPAddress=excluded.IPAddress, DetailsUrl=excluded.DetailsUrl, Duration=excluded.Duration, DownTime=excluded.DownTime
                 '''

        try:
            for row in interface_data:
                values = (
                    str(row.get('NodeName', '')),
                    str(row.get('IPAddress', '')),
                    str(row.get('DetailsUrl', '')),
                    str(row.get('SiteType', '')),
                    str(row.get('Duration', '')),
                    str(row.get('DownTime', ''))
                )
                self.cursor.execute(query, values)
            self.conn.commit()
            logger.debug(f"Successfully: upsert_interface synced {len(interface_data)} interfaces.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"SQL Upsert Failed: {e} | Query: {query} | interface Data: {row}")

    def upsert_alert(self, alert_data):
        """Inserts or updates a record in Orion.AlertObjects."""
        data_rows = "EntityDetailsUrl, Status, TriggerCount, StatusDescription, ObjectType, ObjectName, AlertMessage, RelatedNodeCaption, Vendor, ObjectSubType, IPAddress, TriggerTimeStamp"
        placeholders = ', '.join(['?'] * len(data_rows.split(', ')))        
        query = f'''INSERT INTO [Orion.AlertObjects] ({data_rows}) 
                 VALUES ({placeholders})
                 ON CONFLICT(EntityDetailsUrl) DO UPDATE SET 
                    Status=excluded.Status, TriggerCount=excluded.TriggerCount, StatusDescription=excluded.StatusDescription,
                    ObjectType=excluded.ObjectType, ObjectName=excluded.ObjectName,
                    AlertMessage=excluded.AlertMessage, RelatedNodeCaption=excluded.RelatedNodeCaption,
                    Vendor=excluded.Vendor, ObjectSubType=excluded.ObjectSubType,
                    IPAddress=excluded.IPAddress, TriggerTimeStamp=excluded.TriggerTimeStamp
                 '''

        try:
            for row in alert_data:
                values = (
                    str(row.get('EntityDetailsUrl', '')),
                    str(row.get('Status', '')),
                    str(row.get('TriggerCount', '')),
                    str(row.get('StatusDescription', '')),
                    str(row.get('ObjectType', '')),
                    str(row.get('ObjectName', '')),
                    str(row.get('AlertMessage', '')),
                    str(row.get('RelatedNodeCaption', '')),
                    str(row.get('Vendor', '')),
                    str(row.get('ObjectSubType', '')),
                    str(row.get('IPAddress', '')),
                    str(row.get('TriggerTimeStamp', ''))
                )
                self.cursor.execute(query, values)
            self.conn.commit()
            logger.debug(f"Successfully: upsert_alert synced {len(alert_data)} alerts.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"SQL Upsert Failed: {e} | Query: {query} | alert Data: {row}")

    def upsert_sites_properties(self, prop_data):
        data_rows = "Site , Address, City, TotalNodes , DownCount "
        placeholders = ', '.join(['?'] * len(data_rows.split(', ')))        
    # Updated to handle composite conflict on (Site, Address)
        query = f'''INSERT INTO [Orion.SitesCustomProperties] ({data_rows}) 
             VALUES ({placeholders})
             ON CONFLICT(Site, Address) DO UPDATE SET 
                City=excluded.City,
                TotalNodes=excluded.TotalNodes, 
                DownCount=excluded.DownCount''' # Updates City if Site/Address matches
        
        try:
            for row in prop_data:
                values = (
                    str(row.get('Site', '')),
                    str(row.get('Address', '')),
                    str(row.get('City', '')),
                    str(row.get('TotalNodes', '')),
                    str(row.get('DownCount', '')),
                )
                self.cursor.execute(query, values)
            self.conn.commit()
            logger.debug(f"Successfully: upsert_custom_properties synced {len(prop_data)} Site custom properties.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"SQL upsert_custom_properties Failed: {e} | Query: {query} | nodes Data: {row}")

    def upsert_nodes_properties(self, nodes_data):
        if not nodes_data:
            return

        # Handle single dictionary or list of dictionaries
        if isinstance(nodes_data, dict):
            nodes_data = [nodes_data]

        # 1. Dynamically get column names from the data keys
        columns = list(nodes_data[0].keys())
        
        # 2. Build the query parts dynamically
        # Wraps each column in [] to handle special characters like 'Unmanaged_'
        col_names = ", ".join([f"[{c}]" for c in columns])
        
        # Creates exactly the right number of ?
        placeholders = ", ".join(["?"] * len(columns))
        
        # Builds the update part: [Site]=EXCLUDED.[Site], [City]=EXCLUDED.[City]...
        update_parts = [f"[{c}] = EXCLUDED.[{c}]" for c in columns if c != 'NodeID']
        update_set = ", ".join(update_parts)

        sql_NodesCustomProperties = f"""
            INSERT INTO [Orion.NodesCustomProperties] ({col_names})
            VALUES ({placeholders})
            ON CONFLICT(NodeID) DO UPDATE SET {update_set}
        """

        try:
            self.connect()
            # Ensure values are extracted in the exact same order as the column names list
            params = [tuple(node[c] for c in columns) for node in nodes_data]

            self.cursor.executemany(sql_NodesCustomProperties, params)
            self.conn.commit()
            self.logger.debug(f"Successfully upserted {len(nodes_data)} NodesCustomProperties.")
        except sqlite3.Error as e:
            self.logger.error(f"SQL Dynamic Upsert NodesCustomProperties Failed: {e}")
            # Log the first data point to help debug column mismatches
            self.logger.debug(f"Sample Data: {nodes_data[0]}")

   
    def import_history_record(self, node_id, start_time, end_time, duration, StatusDescription):
        """Now correctly part of the class, so 'self' refers to the DB instance."""
        query = '''INSERT INTO [Orion.StatusHistory] 
                (NodeID, StartTime, EndTime, DurationSeconds, StatusDescription)
                VALUES (?, ?, ?, ?, ?)'''
        try:
            # Check for existing record to prevent duplicates
            check_query = "SELECT id FROM [Orion.StatusHistory] WHERE NodeID = ? AND StartTime = ?"
            self.cursor.execute(check_query, (node_id, start_time))
            if not self.cursor.fetchone():
                self.cursor.execute(query, (node_id, start_time, end_time, duration, StatusDescription))
                self.conn.commit()
        except Exception as e:
            self.logger.error(f"History Import Error: {e}")

    def close(self):
        """Close the database connection safely."""
        if self.conn:
            self.conn.close()

def sync_orion_data(rendered_data):
    if isinstance(rendered_data, str):
        logger.warning("Received HTML string instead of Data Dictionary. Skipping DB sync.")    
        return
    # from utils.orion_db_manager import OrionDatabaseManager
    database_path = mainconfig.DB_ORION_PATH

    # 1. Create the instance
    db_conn = OrionDatabaseManager(database_path)

    # 2. Connect to the database
    try:
        db_conn.connect()
        db_conn.setup_tables()
    except Exception as e:
        logger.error(f"Error setting up Orion DB: {e}")
        return

    try:
        node_data = rendered_data["node_table"]
        if node_data:
            db_conn.upsert_node(node_data)

        interface_data = rendered_data["interface_table"]
        db_conn.upsert_interface(interface_data)

        alert_data = rendered_data["alert_table"]
        db_conn.upsert_alert(alert_data)

        custom_properties_data = rendered_data["custom_properties_table"]
        db_conn.upsert_sites_properties(custom_properties_data)

        NodesCustomPropertiess_data = rendered_data.get("NodesCustomProperties")
        if NodesCustomPropertiess_data:
            db_conn.upsert_nodes_properties(NodesCustomPropertiess_data)

    except Exception as e:
        logger.error(f"Error syncing Orion data: {e}")

    # 4. Always close the connection to prevent database locks
    db_conn.close()                

def cleanup_expired_sessions(max_age_hours=24):
    """Deletes session files older than the specified age."""
    session_dir = (mainconfig.SESSION_DIR)
    
    if not session_dir.exists():
        logger.warning(f"Session directory {session_dir} does not exist. Skipping cleanup.")
        return

    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    deleted_count = 0

    try:
        # Scan for .pickle and .json files in the session directory
        for file_path in session_dir.glob("*"):
            if file_path.suffix in ['.pickle', '.json']:
                file_time = file_path.stat().st_mtime
                
                if file_time < cutoff:
                    os.remove(file_path)
                    deleted_count += 1
                    logger.debug(f"Deleted expired session: {file_path.name}")

        if deleted_count > 0:
            logger.info(f"Session cleanup complete. Removed {deleted_count} expired files.")
    except Exception as e:
        logger.error(f"Error during session cleanup: {e}")        


def main(rendered_data):
    """Main entry point: Process all logs in directory (default) or a single file (if provided)."""

    if rendered_data:
        sync_orion_data(rendered_data)


if __name__ == "__main__":
    main()