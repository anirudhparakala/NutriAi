"""
One-time database cleanup script.

Deletes broken sessions and tags baseline runs as validated.
Run this once after Migration 4 completes.
"""

import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from integrations import db

DB_PATH = "nutri_ai.db"


def cleanup_database():
    """Run one-time cleanup operations."""
    print("=" * 60)
    print("DATABASE CLEANUP SCRIPT")
    print("=" * 60)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # 1. Delete broken sessions (IDs 37, 38)
    print("\n1. Deleting broken sessions (37, 38)...")
    cur.execute("DELETE FROM sessions WHERE id IN (37, 38)")
    deleted_sessions = cur.rowcount
    print(f"   Deleted {deleted_sessions} broken sessions")

    cur.execute("DELETE FROM assumptions WHERE session_id IN (37, 38)")
    deleted_assumptions = cur.rowcount
    print(f"   Deleted {deleted_assumptions} related assumptions")

    # 2. Tag baseline sessions as validated
    print("\n2. Tagging baseline sessions (prompt=94636b1, id>=40)...")
    cur.execute("""
        UPDATE sessions
        SET validated = 1,
            notes = 'Post-Stage2 baseline'
        WHERE prompt_version = '94636b1'
          AND id >= 40
    """)
    tagged_count = cur.rowcount
    print(f"   Tagged {tagged_count} sessions as validated")

    # 3. Show summary
    print("\n3. Database summary:")
    cur.execute("SELECT COUNT(*) FROM sessions")
    total_sessions = cur.fetchone()[0]
    print(f"   Total sessions: {total_sessions}")

    cur.execute("SELECT COUNT(*) FROM sessions WHERE validated = 1")
    validated_sessions = cur.fetchone()[0]
    print(f"   Validated sessions: {validated_sessions}")

    cur.execute("SELECT COUNT(DISTINCT prompt_version) FROM sessions WHERE prompt_version IS NOT NULL")
    prompt_versions = cur.fetchone()[0]
    print(f"   Unique prompt versions: {prompt_versions}")

    # 4. Show validation by prompt version
    print("\n4. Sessions by prompt version:")
    cur.execute("""
        SELECT prompt_version,
               COUNT(*) as total,
               SUM(CASE WHEN validated = 1 THEN 1 ELSE 0 END) as validated
        FROM sessions
        WHERE prompt_version IS NOT NULL
        GROUP BY prompt_version
        ORDER BY total DESC
    """)
    for row in cur.fetchall():
        print(f"   {row[0]}: {row[1]} sessions ({row[2]} validated)")

    con.commit()
    con.close()

    print("\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Run the app to verify migration worked")
    print("2. Use the analytics queries in db.py to explore data")
    print("3. Mark more sessions as validated after manual review")


if __name__ == "__main__":
    cleanup_database()
