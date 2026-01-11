# task_db_manager.py

import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Union
from pathlib import Path
import mainconfig # Assumed to contain BASE_DIR

# Define the database file path
DB_FILE = mainconfig.DATA_DIR / "task_status.db"

class TaskDBManager:
# Define all non-PK columns for easy merging/saving
    COLUMNS = [
        "status", "progress", "completed", "total", "message", 
        "current_ip", "log_filename", "timestamp", "results_json"
    ]
    
    # Define a default structure for new tasks
    DEFAULT_STATUS = {
        "status": "pending",
        "progress": 0,
        "completed": 0,
        "total": 0,
        "message": "Initializing task.",
        "current_ip": "",
        "log_filename": "",
        "results_json": "null",
        "timestamp": datetime.now().isoformat()
    }

    def __init__(self, db_file: Path = DB_FILE):
        self.db_file = db_file
        self._initialize_db()

    def _get_connection(self):
        """Returns a connection object."""
        return sqlite3.connect(self.db_file)

    def _initialize_db(self):
        """Creates the task_status table if it doesn't exist."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_status (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    completed INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    message TEXT,
                    current_ip TEXT,
                    log_filename TEXT,
                    timestamp TEXT NOT NULL,
                    results_json TEXT  -- Store simplified results or status data as JSON
                );
            """)
            conn.commit()

    def save_task_status(self, data: Dict[str, Any]):
        """Merges new data with existing status and saves the complete record."""
        
        # CRITICAL FIX: Explicitly check for 'task_id' before proceeding.
        task_id = data.get('task_id')
        if not task_id:
            # Raise a specific error if task_id is not found
            raise KeyError("Cannot save task status: 'task_id' must be provided in the data dictionary.")

        # 1. Get existing data (or use defaults for a new task)
        existing_status = self.get_task_status(task_id)
        
        merged_data = self.DEFAULT_STATUS.copy()
        
        # If the record exists, use its data as the starting point for the merge
        if existing_status:
            # Prepare existing_status for merging by removing unnecessary keys
            existing_status.pop('task_id', None)
            existing_status.pop('results', None) 
            # Update merged_data with all existing fields
            merged_data.update(existing_status)

        # 2. Overwrite with new data (remove 'task_id' and 'results' first)
        data.pop('task_id', None)
        new_results = data.pop('results', None) # Get new results if present
        
        # Update the merged dictionary with the new status/progress fields
        merged_data.update(data)
        merged_data['timestamp'] = datetime.now().isoformat()
        
        # 3. Handle results_json specifically
        if new_results is not None:
            # If new results were provided, use them
            results_json_to_save = json.dumps(new_results)
        elif merged_data.get('results_json'):
             # Retain existing results_json from the database
            results_json_to_save = merged_data['results_json']
        else:
            results_json_to_save = "null"

        merged_data['results_json'] = results_json_to_save
        
        # 4. Save the complete record to DB using INSERT OR REPLACE
        with self._get_connection() as conn:
            
            # Values must be in the order: task_id, status, progress, ..., results_json
            values = [task_id] + [merged_data.get(col, self.DEFAULT_STATUS.get(col)) for col in self.COLUMNS]

            columns_sql = ', '.join(['task_id'] + self.COLUMNS)
            placeholders_sql = ', '.join('?' * len(values))
            
            conn.execute(f"""
                INSERT OR REPLACE INTO task_status ({columns_sql})
                VALUES ({placeholders_sql})
            """, values)
            conn.commit()

    def get_task_status(self, task_id: str) -> Union[Dict[str, Any], None]:
        """Retrieves a single task status by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_status WHERE task_id = ?", 
                (task_id,)
            )
            row = cursor.fetchone()
            if row:
                # Convert row tuple to dictionary
                columns = [desc[0] for desc in cursor.description]
                data = dict(zip(columns, row))
                
                # Optionally load the results_json, though it might be empty
                if data.get('results_json'):
                    data['results'] = json.loads(data.pop('results_json'))
                return data
            return None
        
    def get_completed_tasks(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all completed tasks, formatted for the reports dropdown."""
        completed_tasks = []
        with self._get_connection() as conn:
            # Select relevant fields for display, ordered by most recent (timestamp DESC)
            cursor = conn.execute("""
                SELECT task_id, log_filename, timestamp 
                FROM task_status 
                WHERE status = 'completed'
                ORDER BY timestamp DESC
            """)
            
            for row in cursor.fetchall():
                task_id, log_filename, timestamp = row
                
                # 1. Create a display name (use log_filename if available, otherwise use a UUID snippet)
                display_name = log_filename or f"Task ID: {task_id[:8]}"
                
                # 2. Format the timestamp to be a readable date/time string
                try:
                    display_time = datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    display_time = "Unknown Date"
                
                completed_tasks.append({
                    # 'task_id' is used to construct the link
                    'task_id': task_id, 
                    # 'display_name' is the main option text
                    'display_name': display_name, 
                    # 'size' is repurposed to show the completion date/time
                    'time': display_time,
                })
        return completed_tasks        

# Initialize the manager for use in other modules
task_db_manager = TaskDBManager()