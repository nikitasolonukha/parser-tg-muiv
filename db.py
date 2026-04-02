import sqlite3
from datetime import datetime
from pathlib import Path

DATABASE_PATH = Path("data/posts.db")


def _prepare_path(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _table_has_column(conn, column):
    cur = conn.execute("PRAGMA table_info(posts)")
    for row in cur.fetchall():
        if row[1] == column:
            return True
    return False


def init_db(db_path=DATABASE_PATH):
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                channel_title TEXT,
                channel_username TEXT,
                message_id INTEGER NOT NULL,
                message_text TEXT,
                message_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (channel_id, message_id)
            )
            """
        )
        if not _table_has_column(conn, "channel_username"):
            cur.execute("ALTER TABLE posts ADD COLUMN channel_username TEXT")
        conn.commit()


def save_post(
    channel_id,
    message_id,
    message_text,
    message_date,
    channel_title=None,
    channel_username=None,
    db_path=DATABASE_PATH,
):
    if isinstance(message_date, datetime):
        message_date_iso = message_date.isoformat()
    else:
        message_date_iso = str(message_date)
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO posts (channel_id, channel_title, channel_username, message_id, message_text, message_date)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, message_id) DO UPDATE SET
                channel_title = excluded.channel_title,
                channel_username = excluded.channel_username,
                message_text = excluded.message_text,
                message_date = excluded.message_date
            """,
            (
                str(channel_id),
                channel_title,
                channel_username,
                int(message_id),
                message_text,
                message_date_iso,
            ),
        )
        conn.commit()


def _normalize_keywords(keywords):
    if isinstance(keywords, str):
        raw = [keywords]
    else:
        raw = list(keywords)
    cleaned = []
    for item in raw:
        if item is None:
            continue
        word = str(item).strip()
        if word:
            cleaned.append(word)
    return cleaned


def search_posts(keywords, limit=20, db_path=DATABASE_PATH):
    words = _normalize_keywords(keywords)
    if not words:
        return []
    pieces = []
    for _ in words:
        pieces.append("LOWER(COALESCE(message_text, '')) LIKE ?")
    like_values = []
    for word in words:
        like_values.append(f"%{word.lower()}%")
    query = " AND ".join(pieces)
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            f"""
            SELECT channel_id, channel_title, channel_username, message_id, message_text, message_date, created_at
            FROM posts
            WHERE {query}
            ORDER BY message_date DESC
            LIMIT ?
            """,
            (*like_values, limit),
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append(dict(row))
        return result


def get_latest_posts(limit=20, db_path=DATABASE_PATH):
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT channel_id, channel_title, channel_username, message_id, message_text, message_date, created_at
            FROM posts
            ORDER BY message_date DESC
            LIMIT ?
            """,
            (limit,),
        )
        data = cursor.fetchall()
        latest = []
        for row in data:
            latest.append(dict(row))
        return latest


def _safe_limit(limit, default=20, min_value=1, max_value=100):
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = default
    if lim < min_value:
        lim = min_value
    if lim > max_value:
        lim = max_value
    return lim


def _calc_relevance(text, words):
    if not text:
        return 0
    lower_text = text.lower()
    score = 0
    for word in words:
        if not word:
            continue
        w = word.lower()
        if w in lower_text:
            score += lower_text.count(w)
    return score


def advanced_search_posts(
    keywords,
    mode="all",
    limit=20,
    sort="date",
    channel_filter=None,
    db_path=DATABASE_PATH,
):
    words = _normalize_keywords(keywords)
    if not words:
        return []

    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in {"all", "any"}:
        normalized_mode = "all"

    normalized_sort = str(sort).strip().lower()
    if normalized_sort not in {"date", "relevance"}:
        normalized_sort = "date"

    lim = _safe_limit(limit, default=20, min_value=1, max_value=150)

    where_clauses = []
    params = []
    for word in words:
        where_clauses.append("LOWER(COALESCE(message_text, '')) LIKE ?")
        params.append(f"%{word.lower()}%")

    joiner = " AND " if normalized_mode == "all" else " OR "
    text_where = joiner.join(where_clauses)

    channel_sql = ""
    if channel_filter is not None and str(channel_filter).strip():
        channel_sql = " AND (LOWER(COALESCE(channel_id, '')) = ? OR LOWER(COALESCE(channel_title, '')) LIKE ?)"
        c = str(channel_filter).strip().lower()
        params.append(c)
        params.append(f"%{c}%")

    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            f"""
            SELECT channel_id, channel_title, channel_username, message_id, message_text, message_date, created_at
            FROM posts
            WHERE ({text_where}) {channel_sql}
            ORDER BY message_date DESC
            LIMIT ?
            """,
            (*params, lim),
        )
        rows = cursor.fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["relevance_score"] = _calc_relevance(item.get("message_text"), words)
        result.append(item)

    if normalized_sort == "relevance":
        result.sort(key=lambda x: (x.get("relevance_score", 0), x.get("message_date") or ""), reverse=True)
    else:
        result.sort(key=lambda x: x.get("message_date") or "", reverse=True)

    return result


def get_channels(db_path=DATABASE_PATH):
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT channel_id, channel_title
            FROM posts
            GROUP BY channel_id, channel_title
            ORDER BY COALESCE(channel_title, channel_id) ASC
            """
        ).fetchall()

    channels = []
    for row in rows:
        channels.append(dict(row))
    return channels


def get_posts_count(db_path=DATABASE_PATH):
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM posts").fetchone()
    return int(row[0] if row else 0)


def get_posts_per_channel(db_path=DATABASE_PATH):
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                channel_id,
                channel_title,
                COUNT(*) AS posts_count
            FROM posts
            GROUP BY channel_id, channel_title
            ORDER BY posts_count DESC, channel_title ASC
            """
        ).fetchall()
    result = []
    for row in rows:
        result.append(dict(row))
    return result


def get_last_post_date(db_path=DATABASE_PATH):
    db_path = _prepare_path(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT MAX(message_date) FROM posts").fetchone()
    if not row:
        return None
    return row[0]


def get_db_stats(db_path=DATABASE_PATH):
    total = get_posts_count(db_path=db_path)
    channels = get_channels(db_path=db_path)
    per_channel = get_posts_per_channel(db_path=db_path)
    last_date = get_last_post_date(db_path=db_path)
    return {
        "total_posts": total,
        "channels": channels,
        "posts_per_channel": per_channel,
        "last_post_date": last_date,
    }
