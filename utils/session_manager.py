# utils/session_manager.py
import os, hashlib, requests, pickle
import mainconfig as mainconfig
from orionsdk import SwisClient
from time import time

# Set up folder paths and mount 
os.makedirs(mainconfig.SESSION_DIR, exist_ok=True)

# --- Logging ---
logger = mainconfig.setup_module_logger(__name__)

class OrionSession:
    SESSION_DIR = mainconfig.SESSION_DIR 

    def __init__(self, npm_server, username, password, timeout=3600):
        self.npm_server = npm_server
        self.username = username
        self.password = password
        self.timeout = timeout  
        self.swis = None
        self.session = None
        self.last_activity = None  
        self.session_id = None

    def connect(self, session_id=None):
        """Connects to Orion, reusing a secured session file if available."""
        # Use provided ID or generate deterministic hash based on credentials
        self.session_id = session_id or get_deterministic_session_id(self.npm_server, self.username)
        session_file = os.path.join(self.SESSION_DIR, f"{self.session_id}.pickle")

        try:
            # 1. Validation: Check if server is reachable with provided credentials
            check_client = SwisClient(self.npm_server, self.username, self.password)
            check_client.query("SELECT TOP 1 NodeID FROM Orion.Nodes")
            
            # 2. Session Reuse: If validation passed, try to load existing session
            if os.path.exists(session_file):
                try:
                    with open(session_file, "rb") as f:
                        self.session, self.last_activity = pickle.load(f)
                    
                    # Re-attach credentials to the loaded session (they aren't in the file)
                    self.session.auth = (self.username, self.password)
                    self.swis = SwisClient(self.npm_server, self.username, self.password, session=self.session)
                    logger.info(f"Reusing secured session file: {self.session_id}")
                except Exception as e:
                    logger.warning(f"Failed to load session file {self.session_id}: {e}")
                    self._create_new_session(session_file)
            else:
                # 3. Fresh Start: Create new session if no file exists
                self._create_new_session(session_file)

        except Exception as e:
            # If login fails, delete the pickle to prevent reuse of invalid sessions
            if os.path.exists(session_file):
                os.remove(session_file)
            logger.error(f"Connection failed for {self.username}: {str(e)}")
            raise ConnectionError(f"Login Failed: {str(e)}")

    def _create_new_session(self, session_file):
        """Initializes a fresh requests session and saves it securely."""
        self.session = requests.Session()
        self.session.verify = False
        self.session.auth = (self.username, self.password)
        self.swis = SwisClient(self.npm_server, self.username, self.password, session=self.session)
        self.last_activity = time()
        self.save_session()
        logger.debug(f"Created and saved new secured session: {self.session_id}")

    def save_session(self):
        """Strips credentials and saves the session to disk."""
        if not self.session:
            return

        session_file = os.path.join(self.SESSION_DIR, f"{self.session_id}.pickle")
        
        # SECURITY FIX: Temporarily remove auth so the password is NOT pickled
        original_auth = self.session.auth
        self.session.auth = None 
        
        try:
            with open(session_file, "wb") as f:
                # Only cookies, headers, and metadata are saved
                pickle.dump((self.session, self.last_activity), f)
        finally:
            # RESTORE auth so the current running process remains authenticated
            self.session.auth = original_auth

    def is_session_expired(self):
        """Check if the session has expired based on the timeout."""
        if self.last_activity is None:
            return True
        return (time() - self.last_activity) > self.timeout

    def refresh_session(self):
        """Auto-reconnects if the session has timed out."""
        if self.is_session_expired():
            logger.debug("Session expired. Reconnecting...")
            self.connect(session_id=self.session_id)

    def query(self, query_str):
        """Executes a query and updates the session activity."""
        self.refresh_session()
        if self.swis:
            try:
                result = self.swis.query(query_str)
                self.last_activity = time()
                self.save_session() # Securely update the timestamp on disk
                return result
            except Exception as ex:
                logger.error(f"Query error: {str(ex)}")
                raise
        else:
            raise ConnectionError("Not connected to Orion server.")

def get_deterministic_session_id(npm_server: str, username: str) -> str:
    """Always returns a unique SHA-256 hash for a specific user on a specific server."""
    if not username or not npm_server:
        return None
    # Normalizing ensures 'Admin' and 'admin' map to the same session file
    raw_str = f"{username.lower().strip()}_{npm_server.lower().strip()}"
    return hashlib.sha256(raw_str.encode()).hexdigest()