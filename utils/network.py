# network.py (FIXED: Added log_filename tracking for results display)

import asyncio
import logging
import json
import os
import time # Added for possible future use, but not used in final fix
from concurrent.futures import ThreadPoolExecutor
from netmiko import ConnectHandler, NetMikoTimeoutException, NetMikoAuthenticationException
from paramiko.ssh_exception import SSHException
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# Assuming these are available from your project structure
import mainconfig
import utils.analysis_sqlite as analysis_sqlite
from utils.fastapi_mymodule import core_check, send_command 
from utils.task_db_manager import task_db_manager
# from utils.analysis_sqlite import setup_database, process_log_file

# --- Global Status Store ---
# TASK_STATUS_DB: Dict[str, Dict] = {}
LOG_OUTPUT_DIR = mainconfig.LOGS_DIR / "core_logs"

logger = mainconfig.setup_module_logger(__name__)


class NetworkDeviceManager:
    """Manages the network device checking process."""
    def __init__(
        self,
        task_id: str,
        iplist_with_os: List[str],  # Format: ['os_type:ip_address', ...]
        username: str,
        password: str,
        check_type: str,
    ):
        self.task_id = task_id
        self.iplist_with_os = iplist_with_os
        self.username = username
        self.password = password
        self.check_type = check_type
        self.results: List[Dict] = []
        self.total = len(iplist_with_os)
        self.completed = 0
        self.executor = ThreadPoolExecutor(max_workers=max(1, min(self.total, 10))) 
        LOG_OUTPUT_DIR.mkdir(exist_ok=True)


    def _update_progress(self, status: str, progress: int, message: str = "", current_ip: str = "", log_filename: str = ""):
        """
        Updates the global task status for the FastAPI polling endpoint.
        Added optional log_filename argument.
        """
        data = {
            "task_id": self.task_id,
            "status": status,
            "progress": progress,
            "completed": self.completed,
            "total": self.total,
            "message": message,
            "current_ip": current_ip,
            "log_filename": log_filename, # <-- NEW FIELD
            "timestamp": datetime.now().isoformat()
        }
        # CRITICAL: Use the DB manager to save the status
        task_db_manager.save_task_status(data)
        logger.info(f"Task {self.task_id} status: {status}, Progress: {progress}% (DB updated)")


    def _get_cmds(self, os_type: str) -> List[str]:
        """Maps check_type and os_type to command list, based on your logic."""
        cmd_core = []
        if self.check_type == "core":
            if os_type == "cisco_ios":
                cmd_core = mainconfig.CMD_CISCO
            elif os_type == "arista_eos":
                cmd_core = mainconfig.CMD_ARISTA
            elif os_type == "hp_comware":
                cmd_core = mainconfig.CMD_HPE
        return cmd_core

    
    def _run_single_check(self, os_type: str, ip: str , nodeid: str) -> Dict:
        """Synchronous (blocking) function to execute commands and analysis."""
        log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{log_time}_{ip}_{self.username}.txt"
        session_log_file = LOG_OUTPUT_DIR / fname
        
        device_setting = {
            'device_type': os_type, 'ip': ip, 'username': self.username,
            'password': self.password, 'session_log': str(session_log_file), 
            'timeout': 90, 'global_delay_factor': 2, 'fast_cli': False,
        }
        
        cmds = self._get_cmds(os_type)
        # Initial status is failed until both phases succeed
        result = {"ip": ip, "status": "failed", "output_file": str(session_log_file.name), "analysis_html": "", "error": ""}
        
        if not self.username or not self.password:
            result["error"] = "Missing username or password."
            return result
            
        # --- PHASE 1: CONNECT AND CREATE LOG FILE ---
        command_success = False
        try:
            output_placeholder = None 
            command_success = send_command(
                device_setting, 
                cmds, 
                logger=logger, 
                output=output_placeholder
            ) 

        # --- PHASE 1.3: LOG ANALYSIS to sqlite --- 20251220

            if command_success:
                try:
                    self._analysis_sqlite(session_log_file)
                except Exception as e:
                    logger.error(f"anaylsis to sqlite fail: {session_log_file}")
            else:
                result["error"] = f"Command execution failed or utility returned False for {ip}."
                return result 
                
        except (NetMikoAuthenticationException, SSHException, NetMikoTimeoutException) as e:
            result["error"] = f"Connection error: {type(e).__name__} - {str(e)}" 
            return result 
        except Exception as e:
            result["error"] = f"Unexpected error during command phase: {type(e).__name__} - {str(e)}" 
            logger.error(f"Error for {ip} (Command Phase): {e}", exc_info=True) 
            return result 

        # --- PHASE 2: LOG ANALYSIS ---
        try:
            analysis_html = core_check(str(LOG_OUTPUT_DIR), session_log_file.name, ip, nodeid) 
            
            # Update status only if analysis succeeds
            result.update({
                "status": "success", 
                "analysis_html": analysis_html
            })
            
        except Exception as e:
            result["error"] = f"Error in output analysis (core_check): {type(e).__name__} - {str(e)}"
            logger.error(f"Error for {ip} (Analysis Phase): {e}", exc_info=True) 
            
        return result

    async def execute_checks(self):
        """The main asynchronous entry point to run all checks concurrently."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
            
        futures = []
        first_successful_log_filename = "" # Initialize tracker

        self._update_progress("in_progress", 0, f"Starting checks on {self.total} devices.")

        check_args = []
        for item in self.iplist_with_os:
            try:
                # os_type, ip , nodeid = item.split(':', 1)
                os_type, ip , nodeid = item.split(':')
                check_args.append((os_type, ip, nodeid))
            except ValueError:
                self.completed += 1
                error_msg = f"Skipped invalid IP format: {item}."
                self.results.append({"ip_string": item, "status": "failed", "error": error_msg})          
        
        for os_type, ip , nodeid  in check_args:
            future = loop.run_in_executor(self.executor, self._run_single_check, os_type, ip , nodeid )
            futures.append(future)

        # Process results as they complete
        for future in asyncio.as_completed(futures):
            result = await future
            self.results.append(result)
            self.completed += 1
            progress = int((self.completed / self.total) * 100)
            
            # CRITICAL: Track the first successful log file name
            if not first_successful_log_filename and result.get("status") == "success":
                first_successful_log_filename = result.get("output_file", "")
            
            # Update status, now including the IP just processed and the log file name
            self._update_progress(
                "in_progress", 
                progress, 
                f"Processed {self.completed}/{self.total} devices.",
                result.get("ip", "Unknown"),
                first_successful_log_filename # Pass the currently tracked file name
            )

        # Final result collection (File is saved synchronously BEFORE status update)
        final_results_path = LOG_OUTPUT_DIR / f"final_results_{self.task_id}.json"
        # CRITICAL: Store the actual results list in the DB for persistence
        # This is a good way to ensure the data for the results page is always available
        task_db_manager.save_task_status({
            "task_id": self.task_id,
            "status": "completed", # Temporarily update status to include results
            "results": self.results # <-- Store the full list of results here
        })

        with open(final_results_path, "w") as f:
            json.dump(self.results, f, indent=2)

        # Retrieve the final log_filename from the DB to ensure all fields are passed
        final_status = task_db_manager.get_task_status(self.task_id)
        final_log_filename = final_status.get("log_filename", "") if final_status else ""

        # CRITICAL: Ensure the final 'completed' status update contains the file name
        self._update_progress(
            "completed", 
            100, 
            f"All checks completed. {self.total} devices checked.",
            "",
            final_log_filename
        )
        self.executor.shutdown(wait=False)

    # 20251220 """Trigger SQLite update after log is written."""
    def _analysis_sqlite(self, log_file_path):
            try:
                conn = analysis_sqlite.setup_database(mainconfig.DB_PATH) #
                # process_log_file expects (connection, path, file_id, base_dir)
                success = analysis_sqlite.process_log_file(conn, log_file_path, None, mainconfig.LOGS_DIR)
                if success:
                    logger.info(f"Log {log_file_path} synced to SQLite database.")
                conn.close()
            except Exception as e:
                logger.error(f"Failed to sync to database: {e}")

# Utility for file listing (moved from mymodule to be accessible)
def get_file_list_fastapi() -> List[Dict]:
    """Retrieves log files for display in the frontend."""
    log_files = []
    
    for p in mainconfig.LOGS_DIR.rglob("*"): 
        if p.is_file() and not p.name.startswith('.'):
            # The 'link_path' must match the URL path used by FastAPI's StaticFiles mount
            # Assuming you mount your mainconfig.LOGS_DIR at '/logs'
            link_path = f"/logs/{p.relative_to(mainconfig.BASE_DIR)}" 
            
            log_files.append({
                "filename": p.name,
                "link_path": link_path, 
                "size": f"{(p.stat().st_size / 1024):.2f} KB",
                "timestamp": datetime.fromtimestamp(p.stat().st_ctime).isoformat()
            })
    return log_files