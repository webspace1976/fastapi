
import sqlite3, os
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
import mainconfig

logger = mainconfig.setup_module_logger(__name__)

# Configuration for the pool
_engines = {}

def get_db_engine(db_path: str):
    """
    Creates/Retrieves a pooled engine for the given path and returns 
    a connection with sqlite3.Row factory enabled.
    """
    global _engines
    
    # 1. Initialize the engine if it doesn't exist for this path
    if db_path not in _engines:
        if not os.path.exists(db_path):
            logger.warning(f"Database file not found at {db_path}. It will be created on first write.")
            
        logger.info(f"Creating new SQLAlchemy QueuePool for: {db_path}")
        
        # We apply your pool settings here
        _engines[db_path] = create_engine(
            f"sqlite:///{db_path}",
            poolclass=QueuePool,
            pool_size=10,          # Connections kept open in the pool
            max_overflow=20,       # Max additional connections if pool is full
            pool_timeout=30,       # Seconds to wait for a free connection
            # connect_args are passed directly to the sqlite3 driver
            connect_args={
                "check_same_thread": False, 
                "timeout": 30      # SQLite internal busy timeout (prevents 'database is locked')
            }
        )

    # 2. Get a raw connection from the pool
    conn = _engines[db_path].raw_connection()
    
    # 3. Apply the Row factory so you can use row['column_name']
    conn.row_factory = sqlite3.Row 
    
    return conn

def get_db_conn(DB_PATH: str):
    try:
        if not os.path.exists(DB_PATH):
            logger.warning(f"Database file not found at {DB_PATH}. Initialization may be required.")
            return None
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        return None
