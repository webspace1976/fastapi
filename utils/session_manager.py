# utils/session_manager.py
import os, json, uuid, hashlib, requests
from cryptography.fernet import Fernet
import pickle
from datetime import datetime
from fastapi import Request
import mainconfig as mainconfig
from orionsdk import SwisClient
from time import time

# Set up folder paths and mount 
os.makedirs(mainconfig.SESSION_DIR, exist_ok=True)

# --- Logging ---
logger = mainconfig.setup_module_logger(__name__)

session_dir = mainconfig.SESSION_DIR

class OrionSession:
    SESSION_DIR = session_dir  # Directory to store session files
    if not os.path.exists(SESSION_DIR):
        os.mkdir(SESSION_DIR)

    def __init__(self, npm_server, username, password, timeout=3600):
        self.npm_server = npm_server
        self.username = username
        self.password = password
        self.timeout = timeout  # Session timeout in seconds
        self.swis = None
        self.session = None
        self.last_activity = None  # Track the last activity time
        self.session_id = None

    def connect(self, session_id=None):
        # FORCE the use of the session_id passed from the router
        self.session_id = session_id        
        
        # Use a consistent naming convention
        session_file = os.path.join(self.SESSION_DIR, f"{self.session_id}.pickle")

        try:
            # Check if server is reachable first (for the popup error)
            check_client = SwisClient(self.npm_server, self.username, self.password)
            check_client.query("SELECT TOP 1 NodeID FROM Orion.Nodes")
            
            # If validation passed, check if we can reuse the session file
            if os.path.exists(session_file):
                with open(session_file, "rb") as f:
                    self.session, self.last_activity = pickle.load(f)
                self.swis = SwisClient(self.npm_server, self.username, self.password, session=self.session)
            else:
                # Create a fresh session and save it
                self.swis = check_client # Reuse the validated client
                self._create_new_session(session_file)

        except Exception as e:
            # If login fails (wrong UN/PW), delete the pickle so it can't be used again
            if os.path.exists(session_file):
                os.remove(session_file)
            # RAISE ConnectionError so the router displays the alert popup
            raise ConnectionError(f"Login Failed: {str(e)}")

    # def connect(self, session_id=None):
    #     logger.debug(f"Connecting to Orion server: {self.npm_server}")
    #     try:
    #         is_new_session = False

    #         # Generate a new session ID if not provided
    #         if session_id is None:
    #             self.session_id = str(uuid.uuid4())
    #             is_new_session = True
    #             logger.debug(f"Debug: Generated new session_id: {self.session_id}")
    #         else:
    #             self.session_id = session_id
    #             logger.debug(f"Debug: Using existing session_id: {self.session_id}")

    #         # session_file = os.path.join(self.SESSION_DIR, self.session_id)
    #         session_file = os.path.join(str(session_dir), f"{session_id}.pickle")

    #         # Before loading or creating, verify the server is actually reachable
    #         try:
    #             self.swis = SwisClient(self.npm_server, self.username, self.password)
    #             # Test credentials
    #             self.swis.query("SELECT TOP 1 NodeID FROM Orion.Nodes")
    #         except requests.exceptions.RequestException as e:
    #             # If connection fails, delete the old session file so it doesn't get reused
    #             if os.path.exists(session_file):
    #                 os.remove(session_file)
    #             # This error message will appear in your browser popup
    #             raise ConnectionError(f"Cannot reach {self.npm_server}. Please check IP/Credentials. Error: {str(e)}")

    #         if os.path.exists(session_file):
    #             try:
    #                 with open(session_file, "rb") as f:
    #                     self.session, self.last_activity = pickle.load(f)
    #                 logger.debug(f"Debug: Loaded session from file: {session_file}")
                    
    #                 # Create SwisClient with the stored session
    #                 # Use the instance's npm_server, username, password
    #                 self.swis = SwisClient(
    #                     self.npm_server, 
    #                     self.username, 
    #                     self.password, 
    #                     session=self.session
    #                 )
    #                 logger.debug("Debug: SwisClient created with stored session")
                    
    #             except (pickle.UnpicklingError, EOFError) as e:
    #                 logger.warning(f"Debug: Corrupted session file: {session_file}. Error: {e}")
    #                 os.remove(session_file)
    #                 self._create_new_session(session_file)
    #                 is_new_session = True
    #             except Exception as e:
    #                 logger.error(f"Debug: Failed to create SwisClient: {e}")
    #                 self._create_new_session(session_file)
    #                 is_new_session = True
    #         else:
    #             logger.error(f"Debug: Session file not found: {session_file}. Creating new session.")
    #             self._create_new_session(session_file)
    #             is_new_session = True

    #         # Log session activity
    #         self._log_session_activity(is_new_session)

    #     except ConnectionError:
    #         # Re-raise our custom connection error to trigger the UI popup
    #         raise
    #     except Exception as ex:
    #         logger.error(f"Error connecting to Orion server: {str(ex)}")
    #         # Raise generic error as a ConnectionError for the UI
    #         raise ConnectionError(f"System Error: {str(ex)}")

    def _create_new_session(self, session_file):
        """Helper to create a new session"""
        self.session = requests.Session()
        self.session.verify = False
        self.swis = SwisClient(self.npm_server, self.username, self.password, session=self.session)
        self.last_activity = time()
        
        # Save the new session
        with open(session_file, "wb") as f:
            pickle.dump((self.session, self.last_activity), f)
        logger.debug(f"Debug: Saved new session to file: {session_file}")

    def _log_session_activity(self, is_new_session):
        """Helper to log session activity"""
        session_metadata = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "npm_server": self.npm_server,
            "username": self.username,
            "is_new_session": is_new_session
        }

        # Append to persistent log
        log_file = os.path.join(session_dir, "orion_session_log.json")
        try:
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    history = json.load(f)
            else:
                history = []

            history.append(session_metadata)

            with open(log_file, "w") as f:
                json.dump(history, f, indent=2)

        except Exception as e:
            logger.error(f"[SESSION LOGGING ERROR] {e}")
            
    def is_session_expired(self):
        """Check if the session has expired based on the timeout."""
        if self.last_activity is None:
            logger.debug("Debug: Session expired because last_activity is None")
            return True
        elapsed_time = time() - self.last_activity
        expired = elapsed_time > self.timeout
        # logger.debug(f"Debug: Elapsed time since last activity: {elapsed_time} seconds. Expired: {expired}")
        return expired

    def refresh_session(self):
        """Refresh the session if it has expired."""
        if self.is_session_expired():
            logger.debug("Debug: Session expired. Reconnecting...")
            self.connect()
        else:
            if self.swis is not None:
                logger.debug("Debug: Session is still valid.")

    def query(self, query):
        if self.swis is not None:
            try:
                result = self.swis.query(query)
                self.last_activity = time()  # Update the last activity time
                # Save the updated session to the file
                # session_file = os.path.join(self.SESSION_DIR, self.session_id)
                session_file = os.path.join(self.SESSION_DIR, f"{self.session_id}.pickle")
                with open(session_file, "wb") as f:
                    pickle.dump((self.session, self.last_activity), f)
                return result
            except requests.exceptions.RequestException as ex:
                logger.debug(f"Error executing query: {str(ex)}")
        else:
            logger.error("Not connected to Orion server.")

    def create(self, entity, properties):
        if self.swis is not None:
            try:
                self.last_activity = time()  # Update the last activity time
                return self.swis.create(entity, properties)
            except requests.exceptions.RequestException as ex:
                logger.error(f"Error creating entity: {str(ex)}")
        else:
            logger.error("Not connected to Orion server.")

def get_or_create_session_id(request: Request, username: str = None) -> str:
    # First try to reuse session_id from cookie
    session_id = request.cookies.get("session_id")
    if session_id:
        print(f"[SessionManager] Reusing session_id from cookie: {session_id}")
        return session_id

    client_ip = request.client.host
    print(f"[SessionManager] No cookie session_id, checking for reuse by IP: {client_ip}")

    # Reuse session based on IP and username (if available)
    try:
        for filename in os.listdir(mainconfig.SESSION_DIR):
            if filename.endswith(".json"):
                path = os.path.join(mainconfig.SESSION_DIR, filename)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("ip") == client_ip:
                        if username:
                            if data.get("username") == username:
                                print(f"[SessionManager] Reusing session_id from file: {data['session_id']} for user: {username}")
                                return data["session_id"]
                        else:
                            print(f"[SessionManager] Reusing session_id by IP: {data['session_id']}")
                            return data["session_id"]
    except Exception as e:
        print(f"[SessionManager] Warning: failed to check session files: {e}")

    # If none found, create new session
    new_session_id = str(uuid.uuid4())
    print(f"[SessionManager] Creating new session_id: {new_session_id}")
    return new_session_id

def get_or_create_session_id_hash(request: Request, npm_server: str = None, username: str = None) -> str:
    # 1. PRIORITY: If we have credentials, ALWAYS generate the Hash.
    # This prevents the "random UUID cookie" from taking over.
    if username and npm_server:
        raw_str = f"{username.lower()}_{npm_server.lower()}"
        target_id = hashlib.md5(raw_str.encode()).hexdigest()
        return target_id

    # 2. FALLBACK: Only use the cookie if we aren't logging in (e.g. refreshing a page)
    session_id = request.cookies.get("session_id")
    if session_id:
        return session_id
    
    # 3. Last resort
    return str(uuid.uuid4())
