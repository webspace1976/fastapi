from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import sqlite3
import os
import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncio
import subprocess

import myconfig as myconfig

router = APIRouter()
logger = logging.getLogger(__name__)

class LogAnalysis:
    def __init__(self, db_path: str):
        self.db_path = db_path
        
    def setup_database(self):
        """Set up the SQLite database with corrected table schemas."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create BGP peer status table
        cursor.execute('''CREATE TABLE IF NOT EXISTS bgp_peer_status
            (hostname TEXT, host_ip TEXT, vpn_instance TEXT, local_router_id TEXT, 
             local_as_number TEXT, neighbor_ip TEXT, peer_as TEXT, up_down_time TEXT, 
             state TEXT, last_updated_ts TEXT, last_snapshot_id TEXT, source_log_file TEXT,
             PRIMARY KEY (host_ip, neighbor_ip))''')
             
        # Create OSPF peer status table
        cursor.execute('''CREATE TABLE IF NOT EXISTS ospf_peer_status
            (hostname TEXT, host_ip TEXT, process TEXT, process_routerid TEXT, vrf TEXT, 
             area TEXT, interface TEXT, neighbor_routerid TEXT, neighbor_address TEXT, 
             state TEXT, mode TEXT, verbose_uptime TEXT, state_count TEXT, last_down_time TEXT, 
             last_routerid TEXT, last_local TEXT, last_remote TEXT, last_reason TEXT, 
             last_updated_ts TEXT, last_snapshot_id TEXT, source_log_file TEXT,
             PRIMARY KEY (host_ip, neighbor_address, interface))''')
             
        # Create tables for BGP/OSPF state changes
        cursor.execute('''CREATE TABLE IF NOT EXISTS ospf_state_changes 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT, process TEXT, 
                         neighbor_address TEXT, interface TEXT, from_state TEXT, to_state TEXT, 
                         timestamp TEXT, log_file TEXT,
                         UNIQUE (hostname, process, neighbor_address, interface, from_state, to_state, timestamp))''')
                         
        cursor.execute('''CREATE TABLE IF NOT EXISTS bgp_state_changes 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT, vpn_instance TEXT, 
                         neighbor_ip TEXT, from_state TEXT, to_state TEXT, timestamp TEXT, log_file TEXT)''')

        # Create table for processed files
        cursor.execute('CREATE TABLE IF NOT EXISTS processed_files (filename TEXT PRIMARY KEY)')

        conn.commit()
        conn.close()
        
    def parse_timestamp(self, raw_ts_str: str, log_year: str) -> str:
        """Converts various log timestamp formats to a standard ISO 8601 format."""
        try:
            # HPE format: "Jul 10 16:08:00:614"
            if raw_ts_str.count(':') == 3:
                raw_ts_str = raw_ts_str.replace(':', '.', 2)
                dt_obj = datetime.strptime(f"{raw_ts_str} {log_year}", "%b %d %H.%M.%S.%f %Y")
            # Cisco format: "Jul 2 09:10:07"
            else:
                dt_obj = datetime.strptime(f"{raw_ts_str} {log_year}", "%b %d %H:%M:%S %Y")
            return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            return f"{raw_ts_str} {log_year}"
            
    async def process_log_file(self, log_file_path: str) -> bool:
        """Process a single log file and insert into database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        filename_only = os.path.basename(log_file_path)
        
        logger.info(f"Processing file: {log_file_path}")
        
        # Check if file already processed
        cursor.execute("SELECT filename FROM processed_files WHERE filename = ?", (filename_only,))
        if cursor.fetchone():
            logger.info(f"File already processed: {filename_only}")
            conn.close()
            return True
            
        # Implementation of log file processing logic from analysis_sqlite.py
        # This would include parsing BGP/OSPF information and updating the database
        
        try:
            # Extract hostname, IP, and routing information
            routing_info = await self.parse_routing_info(log_file_path)
            
            if routing_info:
                # Update BGP peers
                await self.update_bgp_peers(cursor, routing_info, filename_only)
                
                # Update OSPF peers
                await self.update_ospf_peers(cursor, routing_info, filename_only)
                
                # Mark file as processed
                cursor.execute("INSERT INTO processed_files (filename) VALUES (?)", (filename_only,))
                conn.commit()
                logger.info(f"Successfully processed: {filename_only}")
                return True
            else:
                logger.error(f"Failed to parse routing info from: {filename_only}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing {filename_only}: {str(e)}")
            conn.rollback()
            return False
        finally:
            conn.close()
            
    async def parse_routing_info(self, log_file_path: str) -> Dict[str, Any]:
        """Parse routing information from log file."""
        # Implementation of parse_routing_info from analysis_sqlite.py
        # This is a simplified version - you'll need to adapt the full logic
        
        routing_info = {"hostname": None, "host_ip": None, "BGP": [], "OSPF": []}
        
        try:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.splitlines()
                
            # Extract host IP from filename
            ip_regex = r'(?:\d{1,3}\.){3}\d{1,3}'
            file_name = os.path.basename(log_file_path)
            host_ip_match = re.search(ip_regex, file_name)
            if host_ip_match:
                routing_info["host_ip"] = host_ip_match.group()
                
            # Extract hostname from content
            hostname_regex = r"(<|)(.*?)(>|#)"
            for line in lines:
                hostname_match = re.match(hostname_regex, line)
                if hostname_match:
                    routing_info["hostname"] = hostname_match.group(2)
                    break
                    
            # Parse BGP and OSPF sections based on vendor
            vendor = await self.detect_vendor(content)
            
            if vendor == 'hpe':
                routing_info = await self.parse_hpe_routing(lines, routing_info)
            elif vendor in ('cisco', 'arista'):
                routing_info = await self.parse_cisco_routing(lines, routing_info, vendor)
                
            return routing_info
            
        except Exception as e:
            logger.error(f"Error parsing routing info: {str(e)}")
            return routing_info
            
    async def detect_vendor(self, content: str) -> str:
        """Detect device vendor from log content."""
        if "Hewlett Packard Enterprise" in content or "display" in content:
            return 'hpe'
        elif "show logging" in content:
            return 'arista'
        elif "show log" in content:
            return 'cisco'
        else:
            return 'unknown'
            
    async def parse_hpe_routing(self, lines: List[str], routing_info: Dict) -> Dict:
        """Parse HPE device routing information."""
        # Implement HPE-specific parsing logic from analysis_sqlite.py
        current_section = None
        current_vpn_instance = "Global"
        
        for line in lines:
            line = line.strip()
            
            # BGP section detection
            if line.startswith("BGP local router ID:"):
                current_section = "BGP"
                # Parse BGP information...
                
            # OSPF section detection
            elif "display ospf peer" in line:
                current_section = "OSPF"
                # Parse OSPF information...
                
        return routing_info
        
    async def parse_cisco_routing(self, lines: List[str], routing_info: Dict, vendor: str) -> Dict:
        """Parse Cisco/Arista device routing information."""
        # Implement Cisco/Arista-specific parsing logic from analysis_sqlite.py
        current_section = None
        
        for line in lines:
            line = line.strip()
            
            # BGP section detection
            if "show ip bgp" in line:
                current_section = "BGP"
                # Parse BGP information...
                
            # OSPF section detection
            elif "show ip ospf" in line:
                current_section = "OSPF"
                # Parse OSPF information...
                
        return routing_info
        
    async def update_bgp_peers(self, cursor, routing_info: Dict, filename: str):
        """Update BGP peers in database."""
        if not isinstance(routing_info.get("BGP"), list):
            return
            
        for bgp_instance in routing_info["BGP"]:
            vpn_instance = bgp_instance.get("VPN_instance", "Global")
            local_router_id = bgp_instance.get("local_router_id")
            local_as_number = bgp_instance.get("local_as_number")
            
            for peer in bgp_instance.get("Peer", []):
                # Prepare data for insertion
                values = (
                    routing_info["hostname"],
                    routing_info["host_ip"],
                    vpn_instance,
                    local_router_id,
                    local_as_number,
                    peer.get("neighbor_ip"),
                    peer.get("peer_AS"),
                    peer.get("peer_uptime"),
                    peer.get("peer_status"),
                    datetime.now().isoformat(),  # last_updated_ts
                    datetime.now().strftime("%Y%m%d_%H%M%S"),  # last_snapshot_id
                    filename
                )
                
                # Insert or replace BGP peer
                cursor.execute('''INSERT OR REPLACE INTO bgp_peer_status 
                                (hostname, host_ip, vpn_instance, local_router_id, local_as_number,
                                 neighbor_ip, peer_as, up_down_time, state, last_updated_ts,
                                 last_snapshot_id, source_log_file) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', values)
                                
    async def update_ospf_peers(self, cursor, routing_info: Dict, filename: str):
        """Update OSPF peers in database."""
        if not isinstance(routing_info.get("OSPF"), list):
            return
            
        for ospf_process in routing_info["OSPF"]:
            process = ospf_process.get("process")
            process_routerid = ospf_process.get("process_routerid")
            
            for neighbor in ospf_process.get("neighbors", []):
                # Prepare data for insertion
                values = (
                    routing_info["hostname"],
                    routing_info["host_ip"],
                    process,
                    process_routerid,
                    neighbor.get("vrf", ""),
                    neighbor.get("Area"),
                    neighbor.get("Interface"),
                    neighbor.get("neighbor_routerid"),
                    neighbor.get("neighbor_address"),
                    neighbor.get("state"),
                    neighbor.get("mode", ""),
                    neighbor.get("uptime", ""),
                    neighbor.get("state_count", ""),
                    neighbor.get("last_down_time", ""),
                    neighbor.get("last_routerid", ""),
                    neighbor.get("last_local", ""),
                    neighbor.get("last_remote", ""),
                    neighbor.get("last_reason", ""),
                    datetime.now().isoformat(),  # last_updated_ts
                    datetime.now().strftime("%Y%m%d_%H%M%S"),  # last_snapshot_id
                    filename
                )
                
                # Insert or replace OSPF peer
                cursor.execute('''INSERT OR REPLACE INTO ospf_peer_status 
                                (hostname, host_ip, process, process_routerid, vrf, area,
                                 interface, neighbor_routerid, neighbor_address, state, mode,
                                 verbose_uptime, state_count, last_down_time, last_routerid,
                                 last_local, last_remote, last_reason, last_updated_ts,
                                 last_snapshot_id, source_log_file)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', values)

# Global analysis instance
analysis_engine = LogAnalysis(myconfig.DB_PATH)

@router.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    analysis_engine.setup_database()
    logger.info("Analysis database initialized")

@router.post("/update")
async def update_analysis(background_tasks: BackgroundTasks):
    """Trigger analysis update for all new log files"""
    background_tasks.add_task(run_analysis_update)
    return {"status": "started", "message": "Analysis update started in background"}

@router.post("/update/{log_file}")
async def update_specific_file(log_file: str, background_tasks: BackgroundTasks):
    """Trigger analysis for a specific log file"""
    log_file_path = os.path.join(myconfig.LOGS_DIR, "core", log_file)
    
    if not os.path.exists(log_file_path):
        raise HTTPException(status_code=404, detail="Log file not found")
        
    background_tasks.add_task(run_single_file_analysis, log_file_path)
    return {"status": "started", "message": f"Analysis started for {log_file}"}

@router.get("/status")
async def get_analysis_status():
    """Get analysis status and statistics"""
    conn = sqlite3.connect(myconfig.DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Get counts from database
        cursor.execute("SELECT COUNT(*) FROM bgp_peer_status")
        bgp_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM ospf_peer_status")
        ospf_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM processed_files")
        processed_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM bgp_state_changes")
        bgp_changes = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM ospf_state_changes")
        ospf_changes = cursor.fetchone()[0]
        
        # Get latest processed files
        cursor.execute("SELECT filename FROM processed_files ORDER BY rowid DESC LIMIT 5")
        recent_files = [row[0] for row in cursor.fetchall()]
        
        return {
            "status": "active",
            "statistics": {
                "bgp_peers": bgp_count,
                "ospf_peers": ospf_count,
                "processed_files": processed_count,
                "bgp_state_changes": bgp_changes,
                "ospf_state_changes": ospf_changes
            },
            "recent_files": recent_files
        }
        
    finally:
        conn.close()

@router.get("/problems")
async def get_analysis_problems():
    """Get current problems identified by analysis"""
    conn = sqlite3.connect(myconfig.DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Problem BGP peers (not established)
        cursor.execute("SELECT * FROM bgp_peer_status WHERE state != 'Established'")
        problem_bgp = [dict(row) for row in cursor.fetchall()]
        
        # Problem OSPF peers (not full)
        cursor.execute("SELECT * FROM ospf_peer_status WHERE UPPER(state) NOT LIKE 'FULL%'")
        problem_ospf = [dict(row) for row in cursor.fetchall()]
        
        # Recent state changes
        cursor.execute("SELECT * FROM bgp_state_changes ORDER BY timestamp DESC LIMIT 10")
        recent_bgp_changes = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM ospf_state_changes ORDER BY timestamp DESC LIMIT 10")
        recent_ospf_changes = [dict(row) for row in cursor.fetchall()]
        
        return {
            "problem_bgp_peers": problem_bgp,
            "problem_ospf_peers": problem_ospf,
            "recent_bgp_changes": recent_bgp_changes,
            "recent_ospf_changes": recent_ospf_changes
        }
        
    finally:
        conn.close()

@router.get("/peer/{protocol}/{neighbor_ip}")
async def get_peer_details(protocol: str, neighbor_ip: str):
    """Get detailed information for a specific peer"""
    conn = sqlite3.connect(myconfig.DB_PATH)
    cursor = conn.cursor()
    
    try:
        if protocol.lower() == "bgp":
            # Get current status
            cursor.execute("SELECT * FROM bgp_peer_status WHERE neighbor_ip = ?", (neighbor_ip,))
            current_status = cursor.fetchone()
            
            # Get history
            cursor.execute("SELECT * FROM bgp_state_changes WHERE neighbor_ip = ? ORDER BY timestamp DESC", (neighbor_ip,))
            history = [dict(row) for row in cursor.fetchall()]
            
        elif protocol.lower() == "ospf":
            # Get current status
            cursor.execute("SELECT * FROM ospf_peer_status WHERE neighbor_address = ?", (neighbor_ip,))
            current_status = cursor.fetchone()
            
            # Get history
            cursor.execute("SELECT * FROM ospf_state_changes WHERE neighbor_address = ? ORDER BY timestamp DESC", (neighbor_ip,))
            history = [dict(row) for row in cursor.fetchall()]
            
        else:
            raise HTTPException(status_code=400, detail="Invalid protocol. Use 'bgp' or 'ospf'")
            
        return {
            "current_status": dict(current_status) if current_status else None,
            "history": history
        }
        
    finally:
        conn.close()

async def run_analysis_update():
    """Run analysis update for all new log files"""
    log_directory = os.path.join(myconfig.LOGS_DIR, "core")
    
    if not os.path.exists(log_directory):
        logger.error(f"Log directory not found: {log_directory}")
        return
        
    # Get list of log files
    log_files = []
    for filename in os.listdir(log_directory):
        if filename.endswith(".txt") and re.match(r"^\d{8}_\d{6}_", filename):
            log_files.append(os.path.join(log_directory, filename))
            
    logger.info(f"Found {len(log_files)} log files to process")
    
    # Process files
    processed_count = 0
    for log_file in log_files:
        try:
            success = await analysis_engine.process_log_file(log_file)
            if success:
                processed_count += 1
        except Exception as e:
            logger.error(f"Error processing {log_file}: {str(e)}")
            
    logger.info(f"Analysis update completed. Processed {processed_count} files")

async def run_single_file_analysis(log_file_path: str):
    """Run analysis for a single log file"""
    try:
        success = await analysis_engine.process_log_file(log_file_path)
        if success:
            logger.info(f"Successfully processed: {os.path.basename(log_file_path)}")
        else:
            logger.error(f"Failed to process: {os.path.basename(log_file_path)}")
    except Exception as e:
        logger.error(f"Error processing single file {log_file_path}: {str(e)}")

@router.post("/flush")
async def flush_analysis():
    """Flush analysis data and reprocess all files"""
    conn = sqlite3.connect(myconfig.DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Clear all data
        cursor.execute("DELETE FROM bgp_peer_status")
        cursor.execute("DELETE FROM ospf_peer_status")
        cursor.execute("DELETE FROM bgp_state_changes")
        cursor.execute("DELETE FROM ospf_state_changes")
        cursor.execute("DELETE FROM processed_files")
        
        conn.commit()
        
        # Trigger reprocessing
        background_tasks = BackgroundTasks()
        background_tasks.add_task(run_analysis_update)
        
        return {"status": "success", "message": "Analysis data flushed and reprocessing started"}
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to flush analysis data: {str(e)}")
    finally:
        conn.close()