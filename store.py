# store.py
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

class Store:
    def __init__(self, db_path: str = "rpa.db"):
        self.db_path = db_path

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, col: str, col_type: str):
        """Add column if missing (SQLite safe migration)."""
        cur = conn.cursor()
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")] 
        if col not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            conn.commit()

    def init_db(self):
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              exe_path TEXT NOT NULL,
              args TEXT DEFAULT '',
              workdir TEXT DEFAULT '',
              trigger_type TEXT NOT NULL,      -- 'interval' | 'daily'
              interval_sec INTEGER DEFAULT NULL,
              daily_time TEXT DEFAULT NULL,    -- 'HH:MM'
              cond_type TEXT DEFAULT NULL,     -- NULL | 'file_exists' | 'process_not_running'
              cond_value TEXT DEFAULT NULL,    -- file path or process name
              timeout_sec INTEGER NOT NULL DEFAULT 60,
              retry_count INTEGER NOT NULL DEFAULT 0,
              retry_delay_sec INTEGER NOT NULL DEFAULT 5,
              prevent_overlap INTEGER NOT NULL DEFAULT 1,
              updated_at TEXT NOT NULL
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id INTEGER NOT NULL,
              started_at TEXT NOT NULL,
              ended_at TEXT,
              status TEXT NOT NULL,            -- 'RUNNING'|'SUCCESS'|'FAIL'|'TIMEOUT'|'KILLED'|'SKIPPED'
              exit_code INTEGER,
              message TEXT,
              stdout_tail TEXT,
              stderr_tail TEXT,
              stdout_full TEXT,
              stderr_full TEXT,
              FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            """)
                        # ---- schema migrations (safe if columns already exist)
            self._ensure_column(conn, 'jobs', 'day_of_week', 'TEXT')
            self._ensure_column(conn, 'jobs', 'day_of_month', 'INTEGER')
            self._ensure_column(conn, 'jobs', 'cron_expr', 'TEXT')
            self._ensure_column(conn, 'runs', 'stdout_full', 'TEXT')
            self._ensure_column(conn, 'runs', 'stderr_full', 'TEXT')
            self._ensure_column(conn, 'runs', 'stdout_tail', 'TEXT')
            self._ensure_column(conn, 'runs', 'stderr_tail', 'TEXT')
            conn.commit()


    def list_jobs(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        q = "SELECT * FROM jobs"
        if enabled_only:
            q += " WHERE enabled=1"
        q += " ORDER BY id DESC"
        with self._conn() as conn:
            rows = conn.execute(q).fetchall()
            return [dict(r) for r in rows]

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def upsert_job(self, job: Dict[str, Any]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        fields = [
            "name","enabled","exe_path","args","workdir",
            "trigger_type","interval_sec","daily_time",
            "cond_type","cond_value",
            "timeout_sec","retry_count","retry_delay_sec",
            "prevent_overlap","updated_at",
            "day_of_week","day_of_month","cron_expr"
        ]
        data = {k: job.get(k) for k in fields}
        data["updated_at"] = now

        with self._conn() as conn:
            cur = conn.cursor()
            if job.get("id"):
                sets = ",".join([f"{k}=?" for k in fields])
                values = [data[k] for k in fields] + [job["id"]]
                cur.execute(f"UPDATE jobs SET {sets} WHERE id=?", values)
                conn.commit()
                return int(job["id"])
            else:
                cols = ",".join(fields)
                qs = ",".join(["?"] * len(fields))
                values = [data[k] for k in fields]
                cur.execute(f"INSERT INTO jobs ({cols}) VALUES ({qs})", values)
                conn.commit()
                return int(cur.lastrowid)

    def delete_job(self, job_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            conn.commit()

    def insert_run(self, job_id: int, status: str, message: str = "") -> int:
        started = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO runs(job_id, started_at, status, message)
                VALUES(?,?,?,?)
            """, (job_id, started, status, message))
            conn.commit()
            return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        exit_code: Optional[int] = None,
        message: str = "",
        stdout_tail: str = "",
        stderr_tail: str = "",
        stdout_full: Optional[str] = None,
        stderr_full: Optional[str] = None
    ):
        ended = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute("""
                UPDATE runs
                SET ended_at=?,
                    status=?,
                    exit_code=?,
                    message=?,
                    stdout_tail=?,
                    stderr_tail=?,
                    stdout_full=?,
                    stderr_full=?
                WHERE id=?
            """, (ended, status, exit_code, message, stdout_tail, stderr_tail, stdout_full, stderr_full, run_id))
            conn.commit()

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    r.*,
                    j.name AS job_name,
                    j.exe_path AS exe_path,
                    j.args AS args
                FROM runs r
                JOIN jobs j ON j.id = r.job_id
                WHERE r.id=?
            """, (run_id,)).fetchone()
            return dict(row) if row else None

    def list_runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT
                    r.*,
                    j.name AS job_name,
                    j.exe_path AS exe_path,
                    j.args AS args
                FROM runs r
                JOIN jobs j ON j.id = r.job_id
                ORDER BY r.id DESC
                LIMIT {int(limit)}
            """).fetchall()
            return [dict(r) for r in rows]

