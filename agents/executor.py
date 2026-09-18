"""
Executor and Self-Correction Loop module.
Executes generated SQL against the SQLite database with automatic retry on runtime errors.
"""
import sqlite3

from sql_generator import generate_sql


def execute_with_self_correction(question, schema_text, db_path, client=None, max_retries=3):
    """
    Returns a dict:
        success: bool
        sql: the final (working or last-attempted) query
        columns: list of column names (if successful)
        rows: list of row tuples (if successful)
        attempts: [{sql, error_or_None}, ...] full trace of every attempt
    """
    conn = sqlite3.connect(db_path)
    attempts = []
    sql = None
    error = None

    for attempt_num in range(1, max_retries + 1):
        try:
            sql = generate_sql(
                question, schema_text, client=client,
                prior_attempt=sql if attempt_num > 1 else None,
                prior_error=error if attempt_num > 1 else None,
            )
        except ValueError as e:
            # forbidden statement — do not retry, this is a safety stop, not a bug to fix
            attempts.append({"sql": None, "error": str(e)})
            conn.close()
            return {"success": False, "sql": None, "columns": [], "rows": [], "attempts": attempts}

        try:
            cur = conn.cursor()
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            attempts.append({"sql": sql, "error": None})
            conn.close()
            return {"success": True, "sql": sql, "columns": columns, "rows": rows, "attempts": attempts}
        except sqlite3.Error as e:
            error = str(e)
            attempts.append({"sql": sql, "error": error})
            # loop continues -> next attempt passes this error back to the generator

    conn.close()
    return {"success": False, "sql": sql, "columns": [], "rows": [], "attempts": attempts}
