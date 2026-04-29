# SOC Network-Tools Portal — Full Codebase Review

**Reviewed:** April 2026  
**Stack:** FastAPI 0.115 · Python 3.9 · SQLite · Jinja2 · Netmiko · orionsdk  
**Scope:** `main.py`, `mainconfig.py`, `mainpydantic.py`, `models.py`, all routers, all utils, templates, Docker config

---

## Executive Summary

This is a genuinely useful internal network operations tool — the domain logic (BGP/OSPF parsing, Orion integration, device polling) is solid and clearly evolved through real operational experience. The main issues are concentrated in three areas: **security vulnerabilities** that need immediate fixes, **architectural drift** that makes the codebase hard to maintain, and **quality issues** (dead code, blocking I/O in async routes) that introduce risk as the app grows.

---

## 1. Critical Security Issues

### 1.1 Path Traversal — `/edit` and `/save` endpoints (`main.py`)

**Severity: HIGH**

```python
# VULNERABLE — no containment check
async def edit_tab(filename: str):
    file_path = os.path.join(os.path.dirname(__file__), "data", filename)
    with open(file_path, "r") as f: ...

async def save_tab(request: Request):
    filename = form_data.get("filename", "")
    file_path = os.path.join(os.path.dirname(__file__), "data", filename)
    with open(file_path, "w") as f:
        f.write(content)  # arbitrary write to arbitrary path
```

`os.path.join("data", "../../main.py")` resolves to `main.py`. The `/save` endpoint can **overwrite any file the process has write access to**, including `main.py`, `mainconfig.py`, the database, or system files. The `/edit` endpoint can read any file.

**Fix:**

```python
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ALLOWED_EXTENSIONS = {".txt", ".json", ".html"}

async def edit_tab(filename: str):
    # Resolve and contain
    target = (DATA_DIR / filename).resolve()
    if not str(target).startswith(str(DATA_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if target.suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")
    ...

async def save_tab(request: Request):
    # Same containment + no path separators allowed in filename
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    target = (DATA_DIR / filename).resolve()
    if not str(target).startswith(str(DATA_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    ...
```

Also consider: these endpoints have **no authentication**. Anyone who can reach the app can read/write data files.

### 1.2 Path Traversal — `/logs/{subpath:path}` (`main.py`)

**Severity: MEDIUM-HIGH**

```python
base_dir = os.path.join(os.path.dirname(__file__), "logs")
full_path = os.path.join(base_dir, subpath)
# No check that full_path is still inside base_dir
elif os.path.isfile(full_path):
    return FileResponse(full_path)  # serves any file if path resolves out
```

A request to `/logs/../main.py` or `/logs/../data/network_core.db` serves those files.

**Fix:** Add the same containment check used in `/edit`.

```python
base_dir = Path(__file__).parent / "logs"
full_path = (base_dir / subpath).resolve()
if not str(full_path).startswith(str(base_dir.resolve())):
    raise HTTPException(status_code=403, detail="Access denied")
```

### 1.3 `requests.get(..., verify=False)` in `ringer.py`

**Severity: MEDIUM**

All outbound calls to `ringer.healthbc.org` disable TLS verification. This is fine for development but should use a proper CA bundle or at minimum only be silenced in dev/test environments, not production.

### 1.4 No Authentication on Admin Endpoints

`/admin/alerts`, `/admin/session-log`, `/edit`, `/save`, and `/webssh` are all publicly accessible with no auth guard. For an internal tool on a network this may be acceptable, but it should be a deliberate decision. Consider adding at minimum an IP-allowlist middleware or HTTP Basic Auth.

---

## 2. Architecture Issues

### 2.1 Duplicate Model Definitions (`models.py` vs `mainpydantic.py`)

`DeviceCheckRequest`, `OrionCheckRequest`, `MonitorRequest`, `DeviceResponse`, and `OrionResponse` are all defined twice — once in `models.py` (plain, no validation) and once in `mainpydantic.py` (with validators, patterns, field constraints). The routers import from neither — they use `Form(...)` directly. `models.py` is a zombie file.

**Action:** Delete `models.py`. Use `mainpydantic.py` as the single source. Wire the pydantic models into the router endpoints that accept JSON bodies.

### 2.2 `routers/analysis.py` References Non-Existent `myconfig`

```python
import myconfig as myconfig  # No such module — should be mainconfig
```

This router is also **not registered in `main.py`** (`app.include_router` is never called for it). It is dead code that would crash at import if it were ever included.

**Action:** Either fix the import (`mainconfig`) and register it, or delete `analysis.py` if `analysis_sqlite.py` covers the same ground.

### 2.3 Circular Import: `fastapi_mymodule.py` → `routers/monitor.py`

```python
# utils/fastapi_mymodule.py line 22
import routers.monitor as monitor
```

A utility module importing from a router is an inversion of the dependency graph. Utils should have no knowledge of routers. If `fastapi_mymodule` needs something from `monitor`, extract that logic into a shared util or move it into `fastapi_mymodule` directly.

### 2.4 `Jinja2Templates` Instantiated 6 Times

Every router creates its own `Jinja2Templates` instance, some using relative strings and some using `mainconfig.TEMPLATES_DIR`. This wastes memory and creates inconsistency.

```python
# orion.py:974
templates = Jinja2Templates(directory="templates")  # relative — fragile
# devices.py:22
templates = Jinja2Templates(directory=mainconfig.TEMPLATES_DIR)  # absolute — correct
```

**Fix:** Create one shared instance in a `deps.py` or `state.py` module and import it everywhere:

```python
# app/deps.py
from fastapi.templating import Jinja2Templates
import mainconfig
templates = Jinja2Templates(directory=str(mainconfig.TEMPLATES_DIR))
```

### 2.5 `@app.on_event("startup")` Is Deprecated in FastAPI 0.93+

```python
@app.on_event("startup")  # deprecated since 0.93
async def startup_event(): ...

@app.on_event("startup")  # second startup handler — also fragile ordering
async def start_scheduler(): ...
```

The `on_event` decorator was deprecated in FastAPI 0.93 and should be replaced with the lifespan context manager. Having two separate `startup` handlers also makes the startup order implicit.

**Fix:**

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    start_websocket_server_in_background()
    scheduler.add_job(cleanup_expired_sessions, 'cron', hour='7,19', minute=0, args=[24])
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(title="SOC Network-Tools Portal", lifespan=lifespan)
```

### 2.6 Global Mutable State in `orion.py`

```python
# Module-level mutable globals — shared across all requests
sitedown_list = []
dict_query = {}
```

These are mutated during request handling. In a multi-worker deployment (multiple uvicorn workers or gunicorn) these will be stale or inconsistent across processes. Even with one worker, concurrent requests can race.

**Fix:** Remove module-level state. Pass data through return values, request state (`request.state`), or a proper cache (Redis/lru_cache with TTL).

### 2.7 `orion.py` Is 1,199 Lines — Needs Decomposition

The Orion router mixes: session management, SWIS query execution, HTML rendering, data transformation, DB writes, and file I/O. This makes it very difficult to test or change any single concern without risk.

**Suggested split:**
- `routers/orion_auth.py` — login, session handling
- `routers/orion_dashboard.py` — node down, site down, alerts
- `routers/orion_routing.py` — BGP/OSPF query views
- `utils/swis.py` — all SWIS query execution helpers

### 2.8 `ACTIVE_SESSIONS` Dict Is Process-Local

```python
# session_manager.py
ACTIVE_SESSIONS = {}  # in-memory, not shared across workers
```

If you run more than one uvicorn worker (`--workers 2`), each has its own `ACTIVE_SESSIONS`. A login request hitting worker 1 won't be seen by worker 2. This is fine with `--workers 1` but is a silent bug at scale.

---

## 3. Code Quality Issues

### 3.1 Dead / Backup Files Committed to Repo

| File | Status |
|---|---|
| `routers/analysis - Copy.py` | Exact copy of `analysis.py`, committed by accident |
| `routers/monitor - Copy.py` | Old version of `monitor.py` |
| `utils/network - 20251123.py` | Date-versioned backup |

These should be removed. Version control (git) already does this job.

### 3.2 Blocking I/O in `async` Route Handlers

Multiple `async` route functions call blocking operations directly on the event loop thread:

```python
# ringer.py — blocks the entire event loop during HTTP call
async def get_ops_tracking(...):
    response = requests.get(base_url, ...)  # BLOCKING

# orion.py — SwisClient uses requests internally
async def get_orion_dashboard(...):
    result = swis.query(swis_nodedown2)  # BLOCKING
```

**Fix:** Wrap CPU/IO-bound calls in `asyncio.to_thread()` (Python 3.9+):

```python
import asyncio

async def get_ops_tracking(...):
    response = await asyncio.to_thread(
        requests.get, base_url, params=params, verify=False, timeout=10
    )
```

Or switch to `httpx` with its native async client:

```python
import httpx

async def get_ops_tracking(...):
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(base_url, params=params, timeout=10)
```

### 3.3 `print()` Used in Production Code

14 `print()` calls exist in router and util files. These bypass the logging system and won't appear in `alert_center.log` or be filterable by level.

**Fix:** Replace all with `logger.debug(...)` or `logger.info(...)`.

```python
# Before
print(f"Error: File not found - {file_path}")

# After
logger.warning("File not found: %s", file_path)
```

### 3.4 `base.html` Has XLSX Parser Code Prepended Before `<!DOCTYPE html>`

```html
<script type="text/javascript">
    var gk_isXlsx = false;
    ...
</script><!DOCTYPE html>
```

The `<!DOCTYPE html>` declaration appears after a `<script>` block, which triggers quirks mode in all browsers. The script also appears to be auto-generated boilerplate. The base template should start with `<!DOCTYPE html>` on line 1.

### 3.5 `base.html` Navigation Has Dead Links

```html
<li><a href="#">Log file</a></li>
<li><a href="#">BookMark</a></li>
<li><a href="#">Notes</a></li>
```

These `href="#"` links have never been wired up. Either implement them or remove them.

### 3.6 `mainconfig.py` Is Doing Too Many Things

`mainconfig.py` currently contains:
- Path definitions (appropriate)
- Logger factory (appropriate)
- 15+ raw SWIS SQL queries (should live in `utils/swis_queries.py`)
- `CORE_DEVICES` device list (should live in `config/devices.json` or a separate `devices_config.py`)
- 8 compiled regex patterns (fine, but could be in `utils/patterns.py`)

This makes every module that needs even one constant import 300+ lines of unrelated SQL.

### 3.7 `OrionDatabaseManager` Uses `self.conn` as Instance State

```python
class OrionDatabaseManager:
    def connect(self):
        self.conn = sqlite3.connect(self.db_path)  # Not thread-safe
```

SQLite connections cannot safely be shared across threads. If this object is instantiated once at module load and used across requests, this is a latent concurrency bug. The `DatabaseManager` in `database/db_manager.py` already uses SQLAlchemy's connection pool correctly — `OrionDatabaseManager` should follow the same pattern.

### 3.8 `requirements.txt` Has Windows-Only Packages

```
pywin32==311
wfastcgi==3.0.0
```

These will fail `pip install` on Linux (including the Docker container built from `Dockerfile.dockerfile`). Separate into `requirements.txt` (cross-platform) and `requirements_win.txt`.

### 3.9 `netmiko==3.1.1` Is Significantly Outdated

Current stable is 4.4.x. v3.x has known issues with newer Comware and Arista EOS versions. The `NetMikoTimeoutException` import path also changed between v3 and v4.

---

## 4. Minor / Improvement Items

### 4.1 `DEBUG_MODE = True` in `mainconfig.py`

This flag is defined but never checked anywhere in the codebase. Either wire it up (e.g., `if mainconfig.DEBUG_MODE: logger.setLevel(logging.DEBUG)`) or remove it.

### 4.2 Docker `CMD` Has No Worker Count

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5050"]
```

Single worker, no reload guard, no access log. Recommended:

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5050", \
     "--workers", "1", "--access-log", "--log-level", "warning"]
```

Note: Keep `--workers 1` given the in-memory session dict issue above. Fix session sharing before increasing workers.

### 4.3 Docker Doesn't `EXPOSE` Port

```dockerfile
# Missing:
EXPOSE 5050
```

### 4.4 `docker-compose.yml` Uses Deprecated `version:` Key

```yaml
version: '3.8'  # Deprecated in Compose v2, ignored by Docker Desktop 4.x+
```

Remove the `version:` line entirely.

### 4.5 `fastapi_note.txt` and `.bat` Files Should Not Be in Docker Image

`fastapi_startup.bat`, `export_win.bat`, `sync_to_github.bat`, and `setup_new_pc.bat` are development scripts that get `COPY .`-ed into the production container. Add them to `.dockerignore`.

### 4.6 Logging Level Set to `WARNING` — Silences Useful `INFO`

```python
logger.setLevel(logging.WARNING)
```

INFO-level logs (task starts, DB syncs, session creation) are currently suppressed. Consider `INFO` in development and a `LOG_LEVEL` env variable override.

### 4.7 `urllib3==1.25.9` Is End-of-Life

urllib3 1.x is EOL. `requests` 2.31+ supports urllib3 2.x natively and the new version has better connection pooling and security defaults.

---

## 5. What's Well Done

- **`DatabaseManager`** (`database/db_manager.py`) — clean SQLAlchemy implementation with connection pooling, proper session scoping, and consistent error handling. This is the right pattern and the rest of the DB code should converge on it.
- **`TaskDBManager`** — using SQLite for task state instead of an in-memory dict is the correct approach for a background-task system and survives restarts.
- **`parse_uptime`** / `parse_any_ts` — comprehensive handling of multi-vendor timestamp formats. The regex-first approach in the refactored version is much cleaner than the original.
- **`NetworkDeviceManager`** — `ThreadPoolExecutor` with capped workers, proper progress reporting via DB, clean separation between task queuing and result retrieval.
- **`OrionSession.get_client()`** — heartbeat check before reuse, graceful reconnect on stale sessions, and a requests.Session for TCP keep-alive is a solid pattern.
- **`analysis_sqlite.py`** — the `lru_cache` on hot parsing paths and the multiprocessing pool for log file processing show real performance thinking.
- **Pydantic validators in `mainpydantic.py`** — IP validation, pattern constraints, and the `coerce_bools` validator for `check_options` are exactly how these should be done. The models just need to be used by the routers.

---

## 6. Recommended Fix Priority

| Priority | Item | Effort |
|---|---|---|
| 🔴 Immediate | Path traversal on `/edit` and `/save` | 30 min |
| 🔴 Immediate | Path traversal on `/logs/{subpath}` | 15 min |
| 🟠 High | Delete `models.py`, use `mainpydantic.py` everywhere | 1 hr |
| 🟠 High | Fix `analysis.py` (`myconfig` → `mainconfig`), register or delete | 30 min |
| 🟠 High | Remove circular import (`fastapi_mymodule` → `routers.monitor`) | 1 hr |
| 🟠 High | Migrate `on_event` → `lifespan` | 45 min |
| 🟠 High | Fix `base.html` DOCTYPE position | 5 min |
| 🟡 Medium | Wrap blocking `requests.get` calls with `asyncio.to_thread` | 2 hr |
| 🟡 Medium | Delete `*- Copy.py` and `*-20251123.py` backup files | 5 min |
| 🟡 Medium | Single shared `Jinja2Templates` instance | 30 min |
| 🟡 Medium | Split SWIS queries out of `mainconfig.py` | 1 hr |
| 🟡 Medium | Fix `requirements.txt` Windows-only packages | 15 min |
| 🟡 Medium | Upgrade `netmiko` to 4.x | 1–2 hr (test) |
| 🟢 Low | Add `EXPOSE 5050` to Dockerfile | 2 min |
| 🟢 Low | Remove `version:` from docker-compose | 2 min |
| 🟢 Low | Add `.bat` files to `.dockerignore` | 5 min |
| 🟢 Low | Replace `print()` with `logger` | 30 min |
| 🟢 Low | Wire up or remove dead nav links in `base.html` | 15 min |
