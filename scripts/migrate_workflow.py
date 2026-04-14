"""
Database Migration Script — Add workflow columns to existing tables.

Adds new columns to video_jobs table:
  - person_image_url (TEXT)
  - background_image_url (TEXT)
  - workflow_id (VARCHAR(100), default='default')
  - workflow_context (JSON)
  - current_step (VARCHAR(100))

Safe to run multiple times — checks if columns exist before adding.
"""

import sqlite3
import os
import sys

DB_PATH = os.environ.get("DATABASE_PATH", "ai_video_factory.db")

MIGRATIONS = [
    ("video_jobs", "person_image_url", "TEXT"),
    ("video_jobs", "background_image_url", "TEXT"),
    ("video_jobs", "workflow_id", "VARCHAR(100) DEFAULT 'default' NOT NULL"),
    ("video_jobs", "workflow_context", "TEXT"),  # JSON stored as TEXT in SQLite
    ("video_jobs", "current_step", "VARCHAR(100)"),
]


def get_existing_columns(cursor, table_name):
    """Get list of existing column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH} — will be created on app startup.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print(f"Migrating database: {DB_PATH}")

    for table, column, col_type in MIGRATIONS:
        existing = get_existing_columns(cursor, table)

        if column in existing:
            print(f"  [SKIP] {table}.{column} — already exists")
            continue

        sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        try:
            cursor.execute(sql)
            print(f"  [ADD]  {table}.{column} ({col_type})")
        except Exception as e:
            print(f"  [ERR]  {table}.{column} — {e}")

    conn.commit()
    conn.close()
    print("Migration complete!")


if __name__ == "__main__":
    migrate()
