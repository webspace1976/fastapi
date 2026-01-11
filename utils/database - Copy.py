import sqlite3, logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = "data/network_monitoring.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS bgp_peer_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT NOT NULL,
                    neighbor_ip TEXT NOT NULL,
                    vpn_instance TEXT,
                    state TEXT,
                    uptime TEXT,
                    prefix_received INTEGER,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(hostname, neighbor_ip, vpn_instance)
                );

                CREATE TABLE IF NOT EXISTS ospf_peer_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT NOT NULL,
                    process INTEGER,
                    neighbor_address TEXT NOT NULL,
                    interface TEXT,
                    state TEXT,
                    uptime TEXT,
                    dead_time TEXT,
                    area TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(hostname, process, neighbor_address)
                );

                CREATE TABLE IF NOT EXISTS bgp_state_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT NOT NULL,
                    neighbor_ip TEXT NOT NULL,
                    old_state TEXT,
                    new_state TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ospf_state_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT NOT NULL,
                    process INTEGER,
                    neighbor_address TEXT NOT NULL,
                    interface TEXT,
                    old_state TEXT,
                    new_state TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_bgp_host ON bgp_peer_status(hostname);
                CREATE INDEX IF NOT EXISTS idx_ospf_host ON ospf_peer_status(hostname);
                CREATE INDEX IF NOT EXISTS idx_bgp_changes_time ON bgp_state_changes(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_ospf_changes_time ON ospf_state_changes(timestamp DESC);
            """)
            conn.commit()

    def upsert_bgp_peer(self, data: Dict):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO bgp_peer_status 
                (hostname, neighbor_ip, vpn_instance, state, uptime, prefix_received)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(hostname, neighbor_ip, vpn_instance) DO UPDATE SET
                    state=excluded.state,
                    uptime=excluded.uptime,
                    prefix_received=excluded.prefix_received,
                    last_updated=CURRENT_TIMESTAMP
            """, (data['hostname'], data['neighbor_ip'], data.get('vpn_instance', ''), 
                  data['state'], data.get('uptime', ''), data.get('prefix_received', 0)))

            # Log state change if changed
            cursor = conn.execute("""
                SELECT state FROM bgp_peer_status 
                WHERE hostname=? AND neighbor_ip=? AND vpn_instance=?
            """, (data['hostname'], data['neighbor_ip'], data.get('vpn_instance', '')))
            row = cursor.fetchone()
            if row:
                old_state = row['state'] if row['state'] != data['state'] else None
                if old_state and old_state != data['state']:
                    conn.execute("""
                        INSERT INTO bgp_state_changes (hostname, neighbor_ip, old_state, new_state)
                        VALUES (?, ?, ?, ?)
                    """, (data['hostname'], data['neighbor_ip'], old_state, data['state']))
            conn.commit()

    def upsert_ospf_peer(self, data: Dict):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO ospf_peer_status 
                (hostname, process, neighbor_address, interface, state, uptime, dead_time, area)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hostname, process, neighbor_address) DO UPDATE SET
                    state=excluded.state,
                    interface=excluded.interface,
                    uptime=excluded.uptime,
                    dead_time=excluded.dead_time,
                    area=excluded.area,
                    last_updated=CURRENT_TIMESTAMP
            """, (data['hostname'], data.get('process', 1), data['neighbor_address'],
                  data.get('interface', ''), data['state'], data.get('uptime', ''),
                  data.get('dead_time', ''), data.get('area', '')))

            # Log state change
            cursor = conn.execute("""
                SELECT state FROM ospf_peer_status 
                WHERE hostname=? AND neighbor_address=?
            """, (data['hostname'], data['neighbor_address']))
            row = cursor.fetchone()
            if row and row['state'] != data['state']:
                conn.execute("""
                    INSERT INTO ospf_state_changes (hostname, process, neighbor_address, interface, old_state, new_state)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (data['hostname'], data.get('process', 1), data['neighbor_address'],
                      data.get('interface', ''), row['state'], data['state']))
            conn.commit()

    def get_problem_peers(self):
        with self.get_connection() as conn:
            bgp_down = conn.execute("""
                SELECT hostname, neighbor_ip, state, last_updated 
                FROM bgp_peer_status WHERE state != 'Established'
            """).fetchall()
            ospf_down = conn.execute("""
                SELECT hostname, neighbor_address, state, interface 
                FROM ospf_peer_status WHERE state NOT LIKE 'FULL%'
            """).fetchall()
            return [dict(row) for row in bgp_down], [dict(row) for row in ospf_down]

    def get_current_status(self, protocol: str = "all"):
        with self.get_connection() as conn:
            if protocol in ("bgp", "all"):
                bgp = conn.execute("SELECT * FROM bgp_peer_status ORDER BY hostname, neighbor_ip").fetchall()
            else:
                bgp = []
            if protocol in ("ospf", "all"):
                ospf = conn.execute("SELECT * FROM ospf_peer_status ORDER BY hostname, neighbor_address").fetchall()
            else:
                ospf = []
            return [dict(row) for row in bgp], [dict(row) for row in ospf]


    # def get_problem_peers(self, conn: sqlite3.Connection):
    #     """Get problem BGP and OSPF peers"""
    #     # Implement logic from monitor.py get_problem_peers
    #     problem_ips = set()
    #     problem_bgp = []
    #     problem_ospf = []
        
    #     # BGP peers not established
    #     cursor = conn.cursor()
    #     cursor.execute("SELECT * FROM bgp_peer_status WHERE state != 'Established'")
    #     problem_bgp = [dict(row) for row in cursor.fetchall()]
        
    #     # OSPF peers not full
    #     cursor.execute("SELECT * FROM ospf_peer_status WHERE UPPER(state) NOT LIKE 'FULL%'")
    #     problem_ospf = [dict(row) for row in cursor.fetchall()]
        
    #     for row in problem_bgp:
    #         problem_ips.add(row['neighbor_ip'])
    #     for row in problem_ospf:
    #         problem_ips.add(row['neighbor_address'])
            
    #     return problem_ips, problem_bgp, problem_ospf
        
    # def get_recently_changed_peers(self, conn: sqlite3.Connection):
    #     """Get recently changed BGP and OSPF peers"""
    #     cursor = conn.cursor()
        
    #     # BGP state changes
    #     cursor.execute("SELECT * FROM bgp_state_changes ORDER BY timestamp DESC LIMIT 200")
    #     recent_bgp = [dict(row) for row in cursor.fetchall()]
        
    #     # OSPF state changes
    #     cursor.execute("SELECT * FROM ospf_state_changes ORDER BY timestamp DESC LIMIT 200")
    #     recent_ospf = [dict(row) for row in cursor.fetchall()]
        
    #     return recent_bgp, recent_ospf
        
    # def get_bgp_current_status(self, conn: sqlite3.Connection) -> List[Dict]:
    #     """Get current BGP peer status"""
    #     cursor = conn.cursor()
    #     cursor.execute("SELECT * FROM bgp_peer_status ORDER BY hostname, vpn_instance, neighbor_ip")
    #     return [dict(row) for row in cursor.fetchall()]
        
    # def get_ospf_current_status(self, conn: sqlite3.Connection) -> List[Dict]:
    #     """Get current OSPF peer status"""
    #     cursor = conn.cursor()
    #     cursor.execute("SELECT * FROM ospf_peer_status ORDER BY hostname, process, neighbor_address, verbose_uptime DESC")
    #     return [dict(row) for row in cursor.fetchall()]
        
    # def get_peer_history(self, hostname: str, protocol: str, neighbor: str) -> List[Dict]:
        # """Get history for a specific peer"""
        # conn = self.get_connection()
        # cursor = conn.cursor()
        
        # if protocol == 'bgp':
        #     cursor.execute(
        #         "SELECT * FROM bgp_state_changes WHERE neighbor_ip = ? AND hostname = ? ORDER BY timestamp DESC",
        #         (neighbor, hostname)
        #     )
        # else:  # ospf
        #     cursor.execute(
        #         "SELECT * FROM ospf_state_changes WHERE neighbor_address = ? AND hostname = ? ORDER BY timestamp DESC",
        #         (neighbor, hostname)
        #     )
            
        # history = [dict(row) for row in cursor.fetchall()]
        # conn.close()
        # return history


