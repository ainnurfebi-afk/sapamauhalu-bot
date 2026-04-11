"""
database.py - Pengelolaan database untuk Interactive Story Bot
Mendukung SQLite (lokal/dev) dan PostgreSQL (Neon.tech / Railway production).
Gunakan DATABASE_URL environment variable untuk PostgreSQL.
"""

import os
import sqlite3
from typing import Optional
from config import DATABASE_URL, INITIAL_ADMIN_IDS

USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras


# ─── Connection ───────────────────────────────────────────────────────────────

def get_connection():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        DB_PATH = os.path.join(os.path.dirname(__file__), "story_bot.db")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _ph():
    """Placeholder: %s untuk PostgreSQL, ? untuk SQLite."""
    return "%s" if USE_PG else "?"


# ─── Init DB ──────────────────────────────────────────────────────────────────

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                added_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS stories (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS parts (
                id SERIAL PRIMARY KEY,
                story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                text TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS part_media (
                id SERIAL PRIMARY KEY,
                part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                file_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS choices (
                id SERIAL PRIMARY KEY,
                part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                choice_text TEXT NOT NULL,
                next_part_id INTEGER REFERENCES parts(id)
            );

            CREATE TABLE IF NOT EXISTS user_progress (
                user_id BIGINT NOT NULL,
                story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                current_part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, story_id)
            );

            CREATE TABLE IF NOT EXISTS user_story_messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                story_id INTEGER NOT NULL,
                chat_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL
            );
        """)
    else:
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS part_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_id INTEGER NOT NULL,
                choice_text TEXT NOT NULL,
                next_part_id INTEGER,
                FOREIGN KEY (part_id) REFERENCES parts(id) ON DELETE CASCADE,
                FOREIGN KEY (next_part_id) REFERENCES parts(id)
            );

            CREATE TABLE IF NOT EXISTS user_progress (
                user_id INTEGER NOT NULL,
                story_id INTEGER NOT NULL,
                current_part_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, story_id),
                FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
                FOREIGN KEY (current_part_id) REFERENCES parts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_story_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                story_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            );
        """)

    # Seed initial admins
    ph = _ph()
    for uid in INITIAL_ADMIN_IDS:
        if USE_PG:
            cur.execute(
                f"INSERT INTO admins (user_id, added_by) VALUES ({ph}, {ph}) ON CONFLICT DO NOTHING",
                (uid, uid)
            )
        else:
            cur.execute(
                f"INSERT OR IGNORE INTO admins (user_id, added_by) VALUES ({ph}, {ph})",
                (uid, uid)
            )

    conn.commit()
    conn.close()


# ─── Helper ───────────────────────────────────────────────────────────────────

def _row(row) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


def _rows(rows) -> list:
    return [_row(r) for r in rows]


# ─── Admins ───────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT 1 FROM admins WHERE user_id = {ph}", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None


def add_admin(user_id: int, added_by: int) -> bool:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(
            f"INSERT INTO admins (user_id, added_by) VALUES ({ph}, {ph}) ON CONFLICT DO NOTHING",
            (user_id, added_by)
        )
    else:
        cur.execute(
            f"INSERT OR IGNORE INTO admins (user_id, added_by) VALUES ({ph}, {ph})",
            (user_id, added_by)
        )
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_all_admins() -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, added_by, added_at FROM admins ORDER BY added_at")
    result = _rows(cur.fetchall())
    conn.close()
    return result


# ─── Stories ──────────────────────────────────────────────────────────────────

def create_story(title: str) -> int:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(f"INSERT INTO stories (title) VALUES ({ph}) RETURNING id", (title,))
        story_id = cur.fetchone()['id']
    else:
        cur.execute(f"INSERT INTO stories (title) VALUES ({ph})", (title,))
        story_id = cur.lastrowid
    conn.commit()
    conn.close()
    return story_id


def get_all_stories() -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stories ORDER BY created_at DESC")
    result = _rows(cur.fetchall())
    conn.close()
    return result


def get_story_by_id(story_id: int) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM stories WHERE id = {ph}", (story_id,))
    result = _row(cur.fetchone())
    conn.close()
    return result


def delete_story(story_id: int) -> bool:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM stories WHERE id = {ph}", (story_id,))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


# ─── Parts ────────────────────────────────────────────────────────────────────

def create_part(story_id: int, text: str) -> int:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(
            f"INSERT INTO parts (story_id, text) VALUES ({ph}, {ph}) RETURNING id",
            (story_id, text)
        )
        part_id = cur.fetchone()['id']
    else:
        cur.execute(
            f"INSERT INTO parts (story_id, text) VALUES ({ph}, {ph})",
            (story_id, text)
        )
        part_id = cur.lastrowid
    conn.commit()
    conn.close()
    return part_id


def update_part_text(part_id: int, text: str):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE parts SET text = {ph} WHERE id = {ph}", (text, part_id))
    conn.commit()
    conn.close()


def delete_part(part_id: int) -> bool:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM parts WHERE id = {ph}", (part_id,))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_part_by_id(part_id: int) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM parts WHERE id = {ph}", (part_id,))
    result = _row(cur.fetchone())
    conn.close()
    return result


def get_first_part(story_id: int) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM parts WHERE story_id = {ph} ORDER BY id ASC LIMIT 1",
        (story_id,)
    )
    result = _row(cur.fetchone())
    conn.close()
    return result


def get_parts_by_story(story_id: int) -> list:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM parts WHERE story_id = {ph} ORDER BY id ASC", (story_id,))
    result = _rows(cur.fetchall())
    conn.close()
    return result


# ─── Part Media ───────────────────────────────────────────────────────────────

def add_part_media(part_id: int, file_id: str, media_type: str, sort_order: int) -> int:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(
            f"INSERT INTO part_media (part_id, file_id, media_type, sort_order) VALUES ({ph},{ph},{ph},{ph}) RETURNING id",
            (part_id, file_id, media_type, sort_order)
        )
        media_id = cur.fetchone()['id']
    else:
        cur.execute(
            f"INSERT INTO part_media (part_id, file_id, media_type, sort_order) VALUES ({ph},{ph},{ph},{ph})",
            (part_id, file_id, media_type, sort_order)
        )
        media_id = cur.lastrowid
    conn.commit()
    conn.close()
    return media_id


def get_part_media(part_id: int) -> list:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM part_media WHERE part_id = {ph} ORDER BY sort_order ASC, id ASC",
        (part_id,)
    )
    result = _rows(cur.fetchall())
    conn.close()
    return result


def clear_part_media(part_id: int):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM part_media WHERE part_id = {ph}", (part_id,))
    conn.commit()
    conn.close()


# ─── Choices ──────────────────────────────────────────────────────────────────

def create_choice(part_id: int, choice_text: str, next_part_id: Optional[int] = None) -> int:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(
            f"INSERT INTO choices (part_id, choice_text, next_part_id) VALUES ({ph},{ph},{ph}) RETURNING id",
            (part_id, choice_text, next_part_id)
        )
        choice_id = cur.fetchone()['id']
    else:
        cur.execute(
            f"INSERT INTO choices (part_id, choice_text, next_part_id) VALUES ({ph},{ph},{ph})",
            (part_id, choice_text, next_part_id)
        )
        choice_id = cur.lastrowid
    conn.commit()
    conn.close()
    return choice_id


def update_choice_next_part(choice_id: int, next_part_id: int):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE choices SET next_part_id = {ph} WHERE id = {ph}",
        (next_part_id, choice_id)
    )
    conn.commit()
    conn.close()


def delete_choice(choice_id: int) -> bool:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM choices WHERE id = {ph}", (choice_id,))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_choices_by_part(part_id: int) -> list:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM choices WHERE part_id = {ph} ORDER BY id ASC", (part_id,))
    result = _rows(cur.fetchall())
    conn.close()
    return result


def get_choice_by_id(choice_id: int) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM choices WHERE id = {ph}", (choice_id,))
    result = _row(cur.fetchone())
    conn.close()
    return result


def get_unfilled_choices(story_id: int) -> list:
    """Choices yang belum punya next_part - untuk dilanjutkan penulisannya."""
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT c.*, p.text as part_text
        FROM choices c
        JOIN parts p ON c.part_id = p.id
        WHERE p.story_id = {ph} AND c.next_part_id IS NULL
        ORDER BY c.id ASC
    """, (story_id,))
    result = _rows(cur.fetchall())
    conn.close()
    return result


# ─── User Progress ────────────────────────────────────────────────────────────

def save_progress(user_id: int, story_id: int, current_part_id: int):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(f"""
            INSERT INTO user_progress (user_id, story_id, current_part_id)
            VALUES ({ph},{ph},{ph})
            ON CONFLICT (user_id, story_id) DO UPDATE SET current_part_id = EXCLUDED.current_part_id
        """, (user_id, story_id, current_part_id))
    else:
        cur.execute(f"""
            INSERT INTO user_progress (user_id, story_id, current_part_id)
            VALUES ({ph},{ph},{ph})
            ON CONFLICT(user_id, story_id) DO UPDATE SET current_part_id = excluded.current_part_id
        """, (user_id, story_id, current_part_id))
    conn.commit()
    conn.close()


def get_progress(user_id: int, story_id: int) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM user_progress WHERE user_id = {ph} AND story_id = {ph}",
        (user_id, story_id)
    )
    result = _row(cur.fetchone())
    conn.close()
    return result


def get_all_user_progress(user_id: int) -> list:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT up.*, s.title
        FROM user_progress up
        JOIN stories s ON up.story_id = s.id
        WHERE up.user_id = {ph}
        ORDER BY s.title
    """, (user_id,))
    result = _rows(cur.fetchall())
    conn.close()
    return result


def reset_progress(user_id: int, story_id: int):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"DELETE FROM user_progress WHERE user_id = {ph} AND story_id = {ph}",
        (user_id, story_id)
    )
    conn.commit()
    conn.close()


# ─── User Story Messages ──────────────────────────────────────────────────────

def add_story_message(user_id: int, story_id: int, chat_id: int, message_id: int):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO user_story_messages (user_id, story_id, chat_id, message_id) VALUES ({ph},{ph},{ph},{ph})",
        (user_id, story_id, chat_id, message_id)
    )
    conn.commit()
    conn.close()


def get_story_messages(user_id: int, story_id: int) -> list:
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM user_story_messages WHERE user_id = {ph} AND story_id = {ph}",
        (user_id, story_id)
    )
    result = _rows(cur.fetchall())
    conn.close()
    return result


def clear_story_messages(user_id: int, story_id: int):
    ph = _ph()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"DELETE FROM user_story_messages WHERE user_id = {ph} AND story_id = {ph}",
        (user_id, story_id)
    )
    conn.commit()
    conn.close()
