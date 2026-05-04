import sqlite3
import json
from datetime import datetime

DB_PATH = "tenders.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def cleanup_expired_tenders():
    """Removes tenders whose deadline is in the past."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT id, deadline FROM tenders')
    rows = c.fetchall()
    
    deleted_count = 0
    now = datetime.now()
    
    for row in rows:
        raw_date = row['deadline']
        try:
            dt = datetime.strptime(raw_date, '%d %b %Y')
            if dt.date() < now.date():
                c.execute('DELETE FROM tenders WHERE id = ?', (row['id'],))
                deleted_count += 1
        except Exception:
            pass
            
    conn.commit()
    conn.close()
    if deleted_count > 0:
        print(f"[database] Cleaned up {deleted_count} expired tenders.")

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS tenders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id      TEXT UNIQUE,
            title       TEXT NOT NULL,
            buyer       TEXT,
            deadline    TEXT,
            value       TEXT,
            location    TEXT,
            description TEXT,
            link        TEXT,
            keywords    TEXT,
            status      TEXT DEFAULT 'New',
            ai_summary  TEXT,
            fetched_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id       INTEGER NOT NULL,
            amount          REAL,
            submitted_date  TEXT,
            approval_status TEXT DEFAULT 'Pending',
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tender_id) REFERENCES tenders(id)
        )
    """)

    conn.commit()
    conn.close()


# ── Tenders ──────────────────────────────────────────────────────────────────

def upsert_tender(data: dict) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO tenders (api_id, title, buyer, deadline, value, location,
                             description, link, keywords)
        VALUES (:api_id, :title, :buyer, :deadline, :value, :location,
                :description, :link, :keywords)
        ON CONFLICT(api_id) DO UPDATE SET
            title       = excluded.title,
            buyer       = excluded.buyer,
            deadline    = excluded.deadline,
            value       = excluded.value,
            location    = excluded.location,
            description = excluded.description,
            link        = excluded.link,
            keywords    = excluded.keywords
    """, data)
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def get_all_tenders(keyword=None, status=None, min_value=None, max_value=None):
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT * FROM tenders WHERE 1=1"
    params = []
    if keyword:
        query += " AND (title LIKE ? OR description LIKE ? OR keywords LIKE ?)"
        k = f"%{keyword}%"
        params += [k, k, k]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY fetched_at DESC"
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_tender(tender_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_tender_status(tender_id: int, status: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tenders SET status = ? WHERE id = ?", (status, tender_id))
    conn.commit()
    conn.close()


def save_ai_summary(tender_id: int, summary: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tenders SET ai_summary = ? WHERE id = ?", (summary, tender_id))
    conn.commit()
    conn.close()


# ── Quotes ────────────────────────────────────────────────────────────────────

def add_quote(data: dict) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO quotes (tender_id, amount, submitted_date, approval_status, notes)
        VALUES (:tender_id, :amount, :submitted_date, :approval_status, :notes)
    """, data)
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def get_quotes_for_tender(tender_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM quotes WHERE tender_id = ? ORDER BY created_at DESC", (tender_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_all_quotes():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT q.*, t.title AS tender_title
        FROM quotes q
        JOIN tenders t ON t.id = q.tender_id
        ORDER BY q.created_at DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def update_quote_status(quote_id: int, status: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE quotes SET approval_status = ? WHERE id = ?", (status, quote_id))
    conn.commit()
    conn.close()


def delete_quote(quote_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM quotes WHERE id = ?", (quote_id,))
    conn.commit()
    conn.close()
