import sqlite3
from collections.abc import Iterator

from app.config import DATABASE_PATH


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        DATABASE_PATH, timeout=10, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    connection = connect()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                evidence_ref TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                collection_conditions TEXT NOT NULL,
                ppe_compliant INTEGER NOT NULL CHECK (ppe_compliant IN (0, 1)),
                tool_condition TEXT NOT NULL,
                packaging_condition TEXT NOT NULL,
                storage_condition TEXT NOT NULL,
                separately_packaged INTEGER NOT NULL CHECK (separately_packaged IN (0, 1)),
                chain_of_custody_documented INTEGER NOT NULL CHECK (
                    chain_of_custody_documented IN (0, 1)
                ),
                risk_category TEXT NOT NULL CHECK (
                    risk_category IN ('low', 'medium', 'high')
                ),
                risk_score INTEGER NOT NULL,
                risk_factors TEXT NOT NULL,
                recommendations TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, evidence_ref)
            );

            CREATE INDEX IF NOT EXISTS idx_assessments_user_date
                ON assessments(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_assessments_user_risk
                ON assessments(user_id, risk_category);
            """
        )
    finally:
        connection.close()
