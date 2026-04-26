
import sqlite3, os
from typing import List, Dict   # "Python version" quirk. The syntax list[dict] is only valid in Python 3.9+. 
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.orm import sessionmaker, scoped_session
import mainconfig

logger = mainconfig.setup_module_logger(__name__)

# Configuration for the pool

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        
        if not os.path.exists(self.db_path):
            logger.warning(f"Database not found at {self.db_path}. Creating on first write.")

        # 1. Create the Engine
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            # echo=True,  # Enable SQL logging for debugging (remove in production)
            connect_args={
                "check_same_thread": False,
                "timeout": 30
            }
        )

        # 2. Create a Session Factory
        self.session_factory = sessionmaker(
            bind=self.engine, 
            autocommit=False, 
            autoflush=False
        )

    def get_session(self):
        """Returns a new session instance from the pool."""
        return self.session_factory()

    def execute_query(self, sql: str, params: dict = None, debug: bool = False) -> List[Dict]:
        """
        Best practice for 'Row' style access: 
        Uses .mappings() to allow row['column_name'] access.
        """
        if params is None:
            params = {}

        if debug:
            # This prints the statement and params to your console/logs
            print(f"--- DEBUG SQL ---\nQuery: {sql}\nParams: {params}\n-----------------")

        with self.get_session() as session:
            try:
                result = session.execute(text(sql), params)
                # If it's a SELECT, return the dictionary-like rows
                if sql.strip().upper().startswith("SELECT"):
                    return result.mappings().all()
                
                session.commit()
                return None
            except Exception as e:
                session.rollback()
                logger.error(f"Database error: {e}")
                raise

    def execute_write(self, sql: str, params: dict = None, debug: bool = False):
        """For INSERT, UPDATE, DELETE (Single or list of params)."""
        if debug:
            # This prints the statement and params to your console/logs
            print(f"--- DEBUG SQL ---\nQuery: {sql}\nParams: {params}\n-----------------")
                    
        with self.get_session() as session:
            try:
                # If params is a list, it performs an 'executemany' automatically
                session.execute(text(sql), params or {})
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Write failed: {e}")
                raise

    def execute_many(self, sql: str, params_list: List[Dict], debug: bool = False):
        """Efficiently insert/update multiple rows at once."""
        if debug:
            print(f"--- DEBUG SQL ---\nQuery: {sql}\nParams: {params_list}\n-----------------")

        with self.get_session() as session:
            try:
                session.execute(text(sql), params_list)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Bulk write failed: {e}")
                raise

    def setup_core_tables(self, debug: bool = False):
        """Initializes the database schema if tables do not exist."""
        queries = [
            # BGP Peer Status
            """CREATE TABLE IF NOT EXISTS bgp_peer_status (
                hostname TEXT, host_ip TEXT, vpn_instance TEXT, local_router_id TEXT, 
                local_as_number TEXT, neighbor_address TEXT, remote_router_id TEXT, 
                remote_as TEXT, up_down_time TEXT, state TEXT, last_updated_ts TEXT, 
                last_snapshot_id TEXT, log_file TEXT,
                PRIMARY KEY (host_ip, vpn_instance, neighbor_address)
            )""",

            # BGP State Changes
            """CREATE TABLE IF NOT EXISTS bgp_state_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                hostname TEXT, host_ip TEXT, vpn_instance TEXT, 
                neighbor_address TEXT, from_state TEXT, to_state TEXT, 
                last_updated_ts TEXT, log_file TEXT, message TEXT,
                UNIQUE(host_ip, vpn_instance, neighbor_address, last_updated_ts),
                FOREIGN KEY (host_ip, neighbor_address) REFERENCES bgp_peer_status (host_ip, neighbor_address)
            )""",

            # OSPF Peer Status
            """CREATE TABLE IF NOT EXISTS ospf_peer_status (
                hostname TEXT, host_ip TEXT, process TEXT, process_routerid TEXT, 
                vrf TEXT, area TEXT, interface TEXT, neighbor_routerid TEXT, 
                neighbor_address TEXT, state TEXT, mode TEXT, verbose_uptime TEXT, 
                state_count TEXT, last_down_time TEXT, last_routerid TEXT, 
                last_local TEXT, last_remote TEXT, last_reason TEXT, 
                last_updated_ts TEXT, last_snapshot_id TEXT, log_file TEXT,
                PRIMARY KEY (host_ip, process, neighbor_address)
            )""",

            # OSPF State Changes
            """CREATE TABLE IF NOT EXISTS ospf_state_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT, host_ip TEXT, process TEXT, 
                neighbor_address TEXT, interface TEXT, from_state TEXT, 
                to_state TEXT, last_updated_ts TEXT, log_file TEXT, message TEXT,
                UNIQUE(host_ip, neighbor_address, last_updated_ts),
                FOREIGN KEY (host_ip, neighbor_address) REFERENCES ospf_peer_status (host_ip, neighbor_address)
            )""",

            # Indexes for performance (especially for the dashboard)
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ospf_unique_event ON ospf_state_changes (host_ip, process, neighbor_address, last_updated_ts)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_bgp_unique_event ON bgp_state_changes (host_ip, vpn_instance, neighbor_address, last_updated_ts)",
            "CREATE TABLE IF NOT EXISTS processed_files (filename TEXT PRIMARY KEY)",
            
            # Pro-tip: Enable WAL mode for better concurrency 
            "PRAGMA journal_mode=WAL"
        ]
        
        # if debug:
        #     # This prints the statement and params to your console/logs
        #     print(f"--- DEBUG SQL ---\nQuery: {sql}\nParams: {params}\n-----------------")

        with self.get_session() as session:
            try:
                for query in queries:
                    session.execute(text(query))
                session.commit()
                logger.info("Database schema validated/created successfully.")
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to setup database: {e}")
                raise

# Legacy function - not used in the new SQLAlchemy-based implementation, but kept here for reference or potential future use.
# def get_db_conn(DB_PATH: str):
#     try:
#         if not os.path.exists(DB_PATH):
#             logger.warning(f"Database file not found at {DB_PATH}. Initialization may be required.")
#             return None
#         conn = sqlite3.connect(DB_PATH)
#         conn.row_factory = sqlite3.Row
#         return conn
#     except sqlite3.Error as e:
#         logger.error(f"Database connection error: {e}")
#         return None
