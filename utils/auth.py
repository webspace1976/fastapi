# utils/auth.py
from ldap3 import Server, Connection, ALL, NTLM
import mainconfig
import time

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException

logger = mainconfig.setup_module_logger(__name__)

# Simple in-memory lockout guard — AD will lock the account after N failed
# attempts (usually 3-5), so we must NOT let the app hammer it.
_failed_attempts = {}  # {username_lower: [timestamps]}
MAX_ATTEMPTS = 3
WINDOW_SECONDS = 300  # 5 min

def _is_locked_out(username: str) -> bool:
    now = time.time()
    attempts = [t for t in _failed_attempts.get(username, []) if now - t < WINDOW_SECONDS]
    _failed_attempts[username] = attempts
    return len(attempts) >= MAX_ATTEMPTS

def _record_failure(username: str):
    _failed_attempts.setdefault(username, []).append(time.time())

def authenticate_domain_user(username: str, password: str) -> bool:
    username = username.strip()

    if _is_locked_out(username):
        logger.warning("Login blocked (app-side rate limit): %s", username)
        return False
    if not password:
        return False

    try:
        server = Server(mainconfig.AD_SERVER, use_ssl=True, get_info=ALL)
        conn = Connection(
            server,
            user=username,          # keep as "phsabc\\tao.lin", not converted to UPN
            password=password,
            authentication=NTLM,    # NTLM understands DOMAIN\user natively
            auto_bind=True,
        )
        conn.unbind()
        logger.info("AD login success: %s", username)
        return True
    except Exception as e:
        logger.warning("AD login failed: %s (%s: %s)", username, type(e).__name__, str(e))
        _record_failure(username)
        return False

_serializer = URLSafeTimedSerializer(mainconfig.APP_SECRET_KEY)
SESSION_MAX_AGE = 8 * 3600  # 8h

def create_session_cookie(username: str) -> str:
    return _serializer.dumps({"username": username})

def get_current_user(request: Request) -> str:
    token = request.cookies.get("app_session")
    if not token:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return data["username"]    