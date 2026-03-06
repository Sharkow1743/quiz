import sqlite3
import json
import time

class DatabaseStore:
    def __init__(self, db_path="sessions.db"):
        """
        :param db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        # Cache to store references to active session dictionaries
        self._session_cache = {} 
        self._initialize_db()

    def _initialize_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_store (
                    session_id TEXT PRIMARY KEY,
                    created_at INTEGER,
                    data TEXT
                )
            """)

    def has_session_id(self, session_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM session_store WHERE session_id = ?", (session_id,))
            return cursor.fetchone() is not None

    def has_no_session_id(self, session_id):
        return not self.has_session_id(session_id)

    def create_store(self, session_id, *args, **kwargs):
        """
        Fixed signature with *args to prevent 'missing argument' errors.
        """
        created_at = int(time.time())
        initial_data = {}
        
        # Store in cache so save_store can find it later
        self._session_cache[session_id] = initial_data
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO session_store (session_id, created_at, data) VALUES (?, ?, ?)",
                (session_id, created_at, json.dumps(initial_data))
            )
        return initial_data

    def get_store(self, session_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT data FROM session_store WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                # Keep reference in cache
                self._session_cache[session_id] = data
                return data
            return None

    def save_store(self, session_id, store_data=None):
        """
        Easier Use: 
        If store_data is NOT passed (which is how the library calls it),
        we pull the data from our internal cache.
        """
        # If the library passed data, update our cache
        if store_data is not None:
            self._session_cache[session_id] = store_data
        
        # Retrieve the data we need to save
        data_to_persist = self._session_cache.get(session_id)

        if data_to_persist is not None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE session_store SET data = ? WHERE session_id = ?",
                    (json.dumps(data_to_persist), session_id)
                )

    def gc(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM session_store")
            count = cursor.fetchone()[0]
            if count >= 100:
                self.cleanup_old_sessions()
        
        # Clean up memory cache for sessions no longer in the DB
        if len(self._session_cache) > 200:
            self._session_cache.clear()

    def cleanup_old_sessions(self):
        current_time = int(time.time())
        expiry_timestamp = current_time - (3600 * 12)  # 12 hours ago
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM session_store WHERE created_at < ?", (expiry_timestamp,))