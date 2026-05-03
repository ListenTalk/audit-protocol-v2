"""
db.py — SQLite persistence для AI Audit Protocol
==================================================
Два хранилища:
  - CaseStore   → таблица cases  (все кейсы навсегда)
  - SessionStore → таблица sessions (контекст диалогов)

Используется только в main_agent. Остальные сервисы не трогаем.

Выбор SQLite:
  - нет внешних зависимостей (встроен в Python)
  - файл монтируется в Docker volume → данные живут между рестартами
  - для production можно заменить на Postgres, поменяв только этот файл
"""

import json
import sqlite3
import threading
import datetime
import os
from typing import Optional


DB_PATH = os.getenv("DB_PATH", "/data/audit_protocol.db")


# ─── Подключение ─────────────────────────────────────────────────────────────

# SQLite не thread-safe по умолчанию — используем threading.local()
_local = threading.local()

def _get_conn() -> sqlite3.Connection:
    """Один connection на поток. Создаём БД при первом обращении."""
    if not hasattr(_local, "conn"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # лучше для конкурентных чтений
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


# ─── Инициализация схемы ─────────────────────────────────────────────────────

def init_db() -> None:
    """Создаёт таблицы если их нет. Вызывается при старте сервиса."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    TEXT    NOT NULL,
            agent_id      TEXT    NOT NULL,
            user_id       TEXT    NOT NULL,
            question      TEXT    NOT NULL,
            raw_answer    TEXT    NOT NULL,
            raw_confidence REAL   NOT NULL,
            domain        TEXT    NOT NULL,
            validated     INTEGER NOT NULL DEFAULT 0,   -- 0/1 как bool
            final_answer  TEXT    NOT NULL,
            final_confidence REAL NOT NULL,
            source        TEXT    NOT NULL,
            strategy      TEXT,
            validators    INTEGER DEFAULT 0,
            validators_used TEXT,                       -- JSON array
            context       TEXT                          -- JSON array (последние 6)
        );

        CREATE INDEX IF NOT EXISTS idx_cases_user_id   ON cases(user_id);
        CREATE INDEX IF NOT EXISTS idx_cases_domain    ON cases(domain);
        CREATE INDEX IF NOT EXISTS idx_cases_validated ON cases(validated);
        CREATE INDEX IF NOT EXISTS idx_cases_created   ON cases(created_at);

        CREATE TABLE IF NOT EXISTS sessions (
            user_id     TEXT PRIMARY KEY,
            context     TEXT NOT NULL DEFAULT '[]',    -- JSON array
            updated_at  TEXT NOT NULL
        );
    """)
    conn.commit()


# ─── CaseStore ───────────────────────────────────────────────────────────────

class CaseStore:
    """CRUD для таблицы cases."""

    @staticmethod
    def save(
        agent_id:         str,
        user_id:          str,
        question:         str,
        raw_answer:       str,
        raw_confidence:   float,
        domain:           str,
        validated:        bool,
        final_answer:     str,
        final_confidence: float,
        source:           str,
        strategy:         Optional[str] = None,
        validators:       int = 0,
        validators_used:  list[str] = None,
        context:          list[dict] = None,
    ) -> int:
        """Сохранить кейс. Возвращает id записи."""
        conn = _get_conn()
        cur  = conn.execute(
            """
            INSERT INTO cases (
                created_at, agent_id, user_id,
                question, raw_answer, raw_confidence, domain,
                validated, final_answer, final_confidence, source,
                strategy, validators, validators_used, context
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
                agent_id, user_id,
                question, raw_answer, raw_confidence, domain,
                int(validated), final_answer, final_confidence, source,
                strategy, validators,
                json.dumps(validators_used or []),
                json.dumps(context or []),
            ),
        )
        conn.commit()
        return cur.lastrowid

    @staticmethod
    def get_all(
        limit:     int = 100,
        offset:    int = 0,
        user_id:   Optional[str] = None,
        domain:    Optional[str] = None,
        validated: Optional[bool] = None,
    ) -> list[dict]:
        """Получить кейсы с фильтрами и пагинацией."""
        conn   = _get_conn()
        where  = []
        params = []

        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        if domain is not None:
            where.append("domain = ?")
            params.append(domain)
        if validated is not None:
            where.append("validated = ?")
            params.append(int(validated))

        sql = "SELECT * FROM cases"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows = conn.execute(sql, params).fetchall()
        return [_row_to_case(r) for r in rows]

    @staticmethod
    def get_by_id(case_id: int) -> Optional[dict]:
        conn = _get_conn()
        row  = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return _row_to_case(row) if row else None

    @staticmethod
    def count(validated: Optional[bool] = None) -> int:
        conn  = _get_conn()
        where = "" if validated is None else f"WHERE validated = {int(validated)}"
        return conn.execute(f"SELECT COUNT(*) FROM cases {where}").fetchone()[0]

    @staticmethod
    def stats() -> dict:
        """Агрегированная статистика по доменам и confidence."""
        conn = _get_conn()
        total     = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        validated = conn.execute("SELECT COUNT(*) FROM cases WHERE validated=1").fetchone()[0]
        avg_conf  = conn.execute("SELECT AVG(final_confidence) FROM cases").fetchone()[0]

        by_domain = conn.execute(
            "SELECT domain, COUNT(*) as cnt, AVG(final_confidence) as avg_conf "
            "FROM cases GROUP BY domain ORDER BY cnt DESC"
        ).fetchall()

        return {
            "total":         total,
            "validated":     validated,
            "direct":        total - validated,
            "avg_confidence": round(avg_conf or 0, 3),
            "by_domain":     [
                {"domain": r["domain"], "count": r["cnt"],
                 "avg_confidence": round(r["avg_conf"], 3)}
                for r in by_domain
            ],
        }


def _row_to_case(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["validated"]       = bool(d["validated"])
    d["validators_used"] = json.loads(d["validators_used"] or "[]")
    d["context"]         = json.loads(d["context"] or "[]")
    return d


# ─── SessionStore ─────────────────────────────────────────────────────────────

class SessionStore:
    """
    Хранит историю диалога в SQLite.
    Заменяет dict _sessions в памяти — сессии живут между рестартами.
    """

    @staticmethod
    def get(user_id: str) -> list[dict]:
        conn = _get_conn()
        row  = conn.execute(
            "SELECT context FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchone()
        return json.loads(row["context"]) if row else []

    @staticmethod
    def append(user_id: str, message: dict) -> None:
        """Добавить сообщение в конец истории."""
        conn    = _get_conn()
        current = SessionStore.get(user_id)
        current.append(message)
        # храним последние 20 сообщений — не раздуваем БД
        current = current[-20:]
        conn.execute(
            """
            INSERT INTO sessions (user_id, context, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                context    = excluded.context,
                updated_at = excluded.updated_at
            """,
            (user_id, json.dumps(current),
             datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        conn.commit()

    @staticmethod
    def delete(user_id: str) -> None:
        conn = _get_conn()
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()

    @staticmethod
    def all_users() -> list[str]:
        conn = _get_conn()
        rows = conn.execute("SELECT user_id FROM sessions").fetchall()
        return [r["user_id"] for r in rows]
