import json
import sqlite3
import sys
import os
import re
import logging

# Ensure your local project paths are accessible
sys.path.append(os.getcwd())
import mainconfig
from utils.orion_db_manager import OrionDatabaseManager

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger('import_tool')

def extract_json_objects(text):
    """Finds all JSON objects {} within a string, even if the file is malformed."""
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        match = re.search(r'\{', text[pos:])
        if not match:
            break
        start = pos + match.start()
        try:
            obj, index = decoder.raw_decode(text[start:])
            yield obj
            pos = start + index
        except json.JSONDecodeError:
            pos = start + 1

def manual_migrate(json_path, db_path):
    db_manager = OrionDatabaseManager(db_path)
    db_manager.setup_tables() 
    
    if not os.path.exists(json_path):
        logger.error(f"File not found: {json_path}")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            content = f.read()

        logger.info("Scanning file for syslog objects...")
        
        new_records = []
        count = 0
        
        for log in extract_json_objects(content):
            count += 1
            node_id = str(log.get('NodeID'))
            
            # Enrich from CORE_DEVICES
            device = next((item for item in mainconfig.CORE_DEVICES if str(item["nodeid"]) == node_id), None)
            host_name = device['name'] if device else log.get('NodeName', 'Unknown')
            host_ip = device['ip'] if device else log.get('IPAddress', '0.0.0.0')

            new_records.append((
                log.get('LogEntryID'),
                log.get('NodeID'),
                host_name,
                host_ip,
                log.get('DateTime'),
                log.get('Message')
            ))

        if not new_records:
            logger.warning("No valid log objects found.")
            return

        logger.info(f"Found {count} logs. Starting DB import...")

        db_manager.connect()
        # INSERT OR IGNORE handles the duplicates caused by your 'appended' file structure
        db_manager.cursor.executemany(
            "INSERT OR IGNORE INTO [Orion.SyslogTracking] VALUES (?, ?, ?, ?, ?, ?)", 
            new_records
        )
        db_manager.conn.commit()
        
        logger.info(f"Success! Imported {db_manager.cursor.rowcount} NEW unique records into {db_path}")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
    finally:
        if db_manager.conn:
            db_manager.conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        # Adding 'r' before the quote tells Python to ignore backslashes
        print(r"Usage: python .\utils\import_json_db.py <json_path> <db_path>")
        print(r"Example: python .\utils\import_json_db.py .\data\syslog_tracking.json .\data\orion_data.db")
    else:
        manual_migrate(sys.argv[1], sys.argv[2])