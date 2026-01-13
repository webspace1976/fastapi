# utils/session_manager.py
import os, json, uuid
from cryptography.fernet import Fernet
import pickle
from datetime import datetime
from fastapi import Request
import mainconfig as mainconfig

# Set up folder paths and mount 
os.makedirs(mainconfig.SESSION_DIR, exist_ok=True)

# --- Logging ---
logger = mainconfig.setup_module_logger(__name__)

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


