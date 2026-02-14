# utils/session_manager.py
import os, hashlib, requests, pickle, json
from datetime import datetime
import mainconfig as mainconfig
from orionsdk import SwisClient
from time import time

# Set up folder paths and mount 
os.makedirs(mainconfig.SESSION_DIR, exist_ok=True)

# --- Logging ---
logger = mainconfig.setup_module_logger(__name__)

# 20260211 This lives in memory as long as the FastAPI app is running
ACTIVE_SESSIONS = {}

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

    # 20260211 Returns a SwisClient, reusing the same HTTP session for performance
    def get_client(self):
        """Returns a persistent SwisClient instance."""
        session_id = get_deterministic_session_id(self.npm_server, self.username)
        
        if session_id in ACTIVE_SESSIONS:
            client = ACTIVE_SESSIONS[session_id]
            try:
                # Quick heartbeat check
                client.query("SELECT TOP 1 NodeID FROM Orion.Nodes")
                return client, session_id
            except Exception:
                logger.info(f"Session {session_id} stale, reconnecting...")
                del ACTIVE_SESSIONS[session_id]

        # Use requests.Session for Keep-Alive TCP pooling
        http_session = requests.Session()
        http_session.verify = False 
        http_session.auth = (self.username, self.password)
        
        client = SwisClient(self.npm_server, self.username, self.password, session=http_session)
        ACTIVE_SESSIONS[session_id] = client
        return client, session_id

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

def log_user_activity(session_id, username, npm_server, ip_address, action="login"):
    new_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": session_id,
        "username": username,
        "npm_server": npm_server,
        "ip": ip_address,
        "action": action
    }
    
    # Update the JSON log used by /admin/session-log
    log_file = mainconfig.SESSION_LOG_JSON
    data = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            data = json.load(f)

    # CHECK: Only add if the session_id + IP combo doesn't exist or is very old
    # This prevents the "too many logs" issue during 1-minute refreshes
    is_duplicate = any(entry['session_id'] == session_id and entry['ip'] == ip_address for entry in data[-20:]) 
    
    if not is_duplicate:
        data.append(new_entry)
        with open(log_file, "w") as f:
            json.dump(data, f, indent=4)

def update_session_audit(session_id, username, npm_server, ip_address):
    log_file = mainconfig.SESSION_LOG_JSON
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 1. Load existing logs
    data = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            data = json.load(f)

    # 2. Find if this session is already being tracked
    # We look for the same session_id and same IP to prevent duplicate entries
    session_entry = next((item for item in data if item["session_id"] == session_id and item["ip"] == ip_address), None)

    if not session_entry:
        # NEW LOGIN: Record start time
        session_entry = {
            "session_id": session_id,
            "username": username,
            "npm_server": npm_server,
            "ip": ip_address,
            "start_time": now_str,
            "last_activity": now_str,
            "duration_minutes": 0
        }
        data.append(session_entry)
    else:
        # REFRESH: Update last activity and calculate duration
        session_entry["last_activity"] = now_str
        
        # Calculate duration
        start_dt = datetime.strptime(session_entry["start_time"], "%Y-%m-%d %H:%M:%S")
        duration = now - start_dt
        session_entry["duration_minutes"] = round(duration.total_seconds() / 60, 1)

    # 3. Save back to JSON (Overwrite to keep file small)
    with open(log_file, "w") as f:
        json.dump(data, f, indent=4)
