from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from core.config import settings

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parent.parent / "db"
SCHEMA_PATH = str(DB_DIR / "schema.sql")

engine = None
AsyncSessionLocal = None


async def get_db() -> AsyncSession:
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        await init_db()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_engine():
    global engine, AsyncSessionLocal
    url = settings.database_url
    connect_args = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    engine = create_async_engine(
        url, echo=False, poolclass=NullPool, connect_args=connect_args
    )
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    logger.info("Database engine created: %s", url.split("://")[0])
    return engine


async def init_db():
    global engine, AsyncSessionLocal
    if engine is None:
        await create_engine()

    async with AsyncSessionLocal() as session:
        if "sqlite" in settings.database_url:
            DB_DIR.mkdir(parents=True, exist_ok=True)
            with open(SCHEMA_PATH) as f:
                schema_sql = f.read()
            for statement in schema_sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    await session.execute(text(stmt))
            # Migration guard: DBs created before multi-user support won't
            # have these columns yet. Adding them is a no-op if they exist.
            for ddl in (
                "ALTER TABLE runs ADD COLUMN user_id TEXT DEFAULT 'demo'",
                "ALTER TABLE chat_log ADD COLUMN user_id TEXT DEFAULT 'demo'",
            ):
                try:
                    await session.execute(text(ddl))
                except Exception:
                    pass
        else:
            # asyncpg's prepared-statement protocol rejects multiple
            # ";"-separated commands in one execute() call, so each
            # CREATE TABLE must be sent as its own statement.
            postgres_schema_sql = """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connections (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    auth_type TEXT NOT NULL,
                    credentials_encrypted TEXT NOT NULL,
                    account_label TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'connected',
                    connected_at TEXT NOT NULL,
                    last_sync TEXT,
                    error TEXT,
                    UNIQUE(user_id, provider)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    user_id TEXT DEFAULT 'demo',
                    tasks_json JSONB,
                    plan_json JSONB,
                    pipeline_status TEXT DEFAULT 'ok'
                );
                CREATE TABLE IF NOT EXISTS chat_log (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    user_id TEXT DEFAULT 'demo',
                    question TEXT,
                    answer TEXT,
                    referenced_task_ids TEXT
                );
                CREATE TABLE IF NOT EXISTS traces (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    step_name TEXT,
                    duration_ms FLOAT,
                    tokens_used INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'ok'
                );
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id SERIAL PRIMARY KEY,
                    task_id TEXT,
                    action TEXT,
                    user_preference TEXT,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id SERIAL PRIMARY KEY,
                    preference_key TEXT UNIQUE,
                    preference_value TEXT,
                    source TEXT DEFAULT 'inferred',
                    confidence FLOAT DEFAULT 0.5,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS completion_history (
                    id SERIAL PRIMARY KEY,
                    task_id TEXT,
                    task_title TEXT,
                    task_source_type TEXT,
                    completed_at TIMESTAMPTZ,
                    completion_hour INTEGER,
                    day_of_week INTEGER,
                    task_priority TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_memory (
                    id SERIAL PRIMARY KEY,
                    agent_name TEXT,
                    memory_key TEXT,
                    memory_value TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(agent_name, memory_key)
                );
            """
            for statement in postgres_schema_sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    await session.execute(text(stmt))
        await session.commit()

    logger.info("Database initialized")


async def close_db():
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database engine disposed")


async def save_state(tasks: list, plan=None, status="ok", user_id: str = "demo"):
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized (AsyncSessionLocal is None)")

    async with AsyncSessionLocal() as session:
        tasks_json = json.dumps([t.model_dump(mode="json") for t in tasks], default=str)
        plan_json = (
            json.dumps(plan.model_dump(mode="json"), default=str) if plan else None
        )
        if "sqlite" in settings.database_url:
            await session.execute(
                text(
                    "INSERT INTO runs (timestamp, user_id, tasks_json, plan_json, pipeline_status) VALUES (:ts, :uid, :tj, :pj, :ps)"
                ),
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "uid": user_id,
                    "tj": tasks_json,
                    "pj": plan_json,
                    "ps": status,
                },
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO runs (user_id, tasks_json, plan_json, pipeline_status) VALUES (:uid, :tj, :pj, :ps)"
                ),
                {"uid": user_id, "tj": tasks_json, "pj": plan_json, "ps": status},
            )
        await session.commit()


async def load_state(user_id: str = "demo"):
    from models.task import Task, DailyPlan

    async with AsyncSessionLocal() as session:
        if "sqlite" in settings.database_url:
            row = (
                await session.execute(
                    text(
                        "SELECT tasks_json, plan_json FROM runs WHERE user_id = :uid ORDER BY id DESC LIMIT 1"
                    ),
                    {"uid": user_id},
                )
            ).fetchone()
        else:
            row = (
                await session.execute(
                    text(
                        "SELECT tasks_json::TEXT as tasks_json, plan_json::TEXT as plan_json FROM runs WHERE user_id = :uid ORDER BY id DESC LIMIT 1"
                    ),
                    {"uid": user_id},
                )
            ).fetchone()

    if row is None:
        return [], None
    tasks = [Task(**t) for t in json.loads(row[0])]
    plan = DailyPlan(**json.loads(row[1])) if row[1] else None
    return tasks, plan


async def save_trace(
    step_name: str, duration_ms: float, tokens_used: int = 0, status: str = "ok"
):
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized (AsyncSessionLocal is None)")
    async with AsyncSessionLocal() as session:
        ts = datetime.now(timezone.utc).isoformat()
        if "sqlite" in settings.database_url:
            await session.execute(
                text(
                    "INSERT INTO traces (timestamp, step_name, duration_ms, tokens_used, status) VALUES (:ts, :sn, :dm, :tu, :st)"
                ),
                {
                    "ts": ts,
                    "sn": step_name,
                    "dm": duration_ms,
                    "tu": tokens_used,
                    "st": status,
                },
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO traces (step_name, duration_ms, tokens_used, status) VALUES (:sn, :dm, :tu, :st)"
                ),
                {"sn": step_name, "dm": duration_ms, "tu": tokens_used, "st": status},
            )
        await session.commit()


async def get_recent_traces(limit: int = 50) -> list[dict]:
    try:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    text("SELECT * FROM traces ORDER BY id DESC LIMIT :lim"),
                    {"lim": limit},
                )
            ).fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception:
        return []


async def save_chat_log(
    question: str, answer: str, referenced_ids: list[str], user_id: str = "demo"
):
    async with AsyncSessionLocal() as session:
        ts = datetime.now(timezone.utc).isoformat()
        if "sqlite" in settings.database_url:
            await session.execute(
                text(
                    "INSERT INTO chat_log (timestamp, user_id, question, answer, referenced_task_ids) VALUES (:ts, :uid, :q, :a, :rid)"
                ),
                {
                    "ts": ts,
                    "uid": user_id,
                    "q": question,
                    "a": answer,
                    "rid": ",".join(referenced_ids),
                },
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO chat_log (user_id, question, answer, referenced_task_ids) VALUES (:uid, :q, :a, :rid)"
                ),
                {
                    "uid": user_id,
                    "q": question,
                    "a": answer,
                    "rid": ",".join(referenced_ids),
                },
            )
        await session.commit()


async def save_feedback(task_id: str, action: str, preference: str):
    async with AsyncSessionLocal() as session:
        if "sqlite" in settings.database_url:
            await session.execute(
                text(
                    "INSERT INTO user_feedback (task_id, action, user_preference, timestamp) VALUES (:tid, :act, :pref, datetime('now'))"
                ),
                {"tid": task_id, "act": action, "pref": preference},
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO user_feedback (task_id, action, user_preference) VALUES (:tid, :act, :pref)"
                ),
                {"tid": task_id, "act": action, "pref": preference},
            )
        await session.commit()


async def get_user_preference_boosts() -> dict[str, float]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
            SELECT user_preference,
                   SUM(CASE WHEN action = 'upvote' THEN 1 WHEN action = 'downvote' THEN -1 ELSE 0 END) as net
            FROM user_feedback
            GROUP BY user_preference
            HAVING net > 0
            ORDER BY net DESC
        """)
        )
        rows = result.fetchall()
    boosts: dict[str, float] = {}
    for row in rows:
        pref = row[0]
        net = row[1]
        multiplier = 1.0 + min(net, 5) * 0.04
        boosts[pref] = round(multiplier, 3)
    return boosts


async def get_daily_snapshots(days: int = 7) -> list[dict[str, Any]]:

    async with AsyncSessionLocal() as session:
        if "sqlite" in settings.database_url:
            rows = (
                await session.execute(
                    text("""
                SELECT date(timestamp) as day,
                       MAX(timestamp) as last_run_ts,
                       tasks_json,
                       plan_json
                FROM runs
                WHERE timestamp >= date('now', '-' || :days || ' days')
                GROUP BY date(timestamp)
                ORDER BY day ASC
            """),
                    {"days": days},
                )
            ).fetchall()
        else:
            rows = (
                await session.execute(
                    text("""
                SELECT date(timestamp) as day,
                       MAX(timestamp) as last_run_ts,
                       tasks_json::TEXT as tasks_json,
                       plan_json::TEXT as plan_json
                FROM runs
                WHERE timestamp >= NOW() - (:days || ' days')::INTERVAL
                GROUP BY date(timestamp)
                ORDER BY day ASC
            """),
                    {"days": str(days)},
                )
            ).fetchall()

    if not rows:
        return []

    daily_plans: list[dict] = []
    prev_tasks: list[dict] = []

    for row in rows:
        tasks: list[dict] = json.loads(row[2])
        plan: dict | None = json.loads(row[3]) if row[3] else None

        curr_done_ids = {t["id"] for t in tasks if t.get("status") == "done"}
        prev_done_ids = {t["id"] for t in prev_tasks if t.get("status") == "done"}
        newly_completed = [
            {"id": t["id"], "title": t.get("title", "")}
            for t in tasks
            if t.get("status") == "done" and t["id"] not in prev_done_ids
        ]

        daily: dict[str, Any] = {
            "date": row[0],
            "top_3": [],
            "completed": newly_completed,
            "deferred": [],
            "blockers": [],
            "task_count": len(tasks),
            "done_count": len(curr_done_ids),
        }

        if plan:
            daily["top_3"] = [
                {"id": t.get("id"), "title": t.get("title"), "status": t.get("status")}
                for t in plan.get("top_priorities", [])
            ]
            daily["deferred"] = [
                {"id": t.get("id"), "title": t.get("title")}
                for t in plan.get("deferred", [])
            ]

        daily["blockers"] = [
            {"id": t["id"], "title": t.get("title", ""), "blocked_by": ""}
            for t in tasks
            if t.get("status") == "blocked"
        ]

        daily_plans.append(daily)
        prev_tasks = tasks

    return daily_plans


async def get_team_velocity(days: int = 7) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        if "sqlite" in settings.database_url:
            rows = (
                await session.execute(
                    text("""
                SELECT date(timestamp) as day, tasks_json
                FROM runs
                WHERE timestamp >= date('now', '-' || :days || ' days')
                GROUP BY date(timestamp)
                ORDER BY day ASC
            """),
                    {"days": days},
                )
            ).fetchall()
        else:
            rows = (
                await session.execute(
                    text("""
                SELECT date(timestamp) as day, tasks_json::TEXT as tasks_json
                FROM runs
                WHERE timestamp >= NOW() - (:days || ' days')::INTERVAL
                GROUP BY date(timestamp)
                ORDER BY day ASC
            """),
                    {"days": str(days)},
                )
            ).fetchall()

    daily_counts = []
    for row in rows:
        tasks = json.loads(row[1])
        done = sum(1 for t in tasks if t.get("status") == "done")
        daily_counts.append({"day": row[0], "completed": done, "total": len(tasks)})

    return {"daily_counts": daily_counts}


# ── Users ────────────────────────────────────────────────────────────────────


async def create_user(user_id: str, email: str, password_hash: str, name: str = "") -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, name, created_at) "
                "VALUES (:id, :email, :ph, :name, :ts)"
            ),
            {
                "id": user_id,
                "email": email.lower().strip(),
                "ph": password_hash,
                "name": name,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        await session.commit()


DEMO_USER_ID = "demo"
DEMO_USER_EMAIL = "demo@taskpilot.local"


async def ensure_demo_user() -> None:
    """The public 'Watch Demo' button logs visitors in as a reserved
    user_id="demo" account (no signup) so they see the pre-seeded demo
    pipeline. /api/auth/me and anything else keyed on a real `users` row
    needs that row to actually exist — password_hash is an unusable
    placeholder since this account is never logged into by password."""
    async with AsyncSessionLocal() as session:
        if "sqlite" in settings.database_url:
            await session.execute(
                text(
                    "INSERT OR IGNORE INTO users (id, email, password_hash, name, created_at) "
                    "VALUES (:id, :email, :ph, :name, :ts)"
                ),
                {
                    "id": DEMO_USER_ID,
                    "email": DEMO_USER_EMAIL,
                    "ph": "!disabled!",
                    "name": "Demo",
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, name, created_at) "
                    "VALUES (:id, :email, :ph, :name, :ts) ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": DEMO_USER_ID,
                    "email": DEMO_USER_EMAIL,
                    "ph": "!disabled!",
                    "name": "Demo",
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        await session.commit()


async def get_user_by_email(email: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT id, email, password_hash, name FROM users WHERE email = :email"),
                {"email": email.lower().strip()},
            )
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email": row[1], "password_hash": row[2], "name": row[3]}


async def get_user_by_id(user_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT id, email, name FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email": row[1], "name": row[2]}


# ── Connections (per-user integration credentials) ─────────────────────────


async def upsert_connection(
    user_id: str,
    provider: str,
    auth_type: str,
    credentials_encrypted: str,
    account_label: str = "",
) -> None:
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                text("SELECT id FROM connections WHERE user_id = :uid AND provider = :p"),
                {"uid": user_id, "p": provider},
            )
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            await session.execute(
                text(
                    "UPDATE connections SET auth_type = :at, credentials_encrypted = :ce, "
                    "account_label = :al, status = 'connected', connected_at = :ts, error = NULL "
                    "WHERE user_id = :uid AND provider = :p"
                ),
                {
                    "at": auth_type,
                    "ce": credentials_encrypted,
                    "al": account_label,
                    "ts": now,
                    "uid": user_id,
                    "p": provider,
                },
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO connections (user_id, provider, auth_type, credentials_encrypted, "
                    "account_label, status, connected_at) "
                    "VALUES (:uid, :p, :at, :ce, :al, 'connected', :ts)"
                ),
                {
                    "uid": user_id,
                    "p": provider,
                    "at": auth_type,
                    "ce": credentials_encrypted,
                    "al": account_label,
                    "ts": now,
                },
            )
        await session.commit()


async def get_all_connected_user_ids() -> list[str]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(text("SELECT DISTINCT user_id FROM connections"))
        ).fetchall()
    return [r[0] for r in rows]


async def get_connections(user_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT provider, auth_type, account_label, status, connected_at, last_sync, error "
                    "FROM connections WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).fetchall()
    return [
        {
            "provider": r[0],
            "auth_type": r[1],
            "account_label": r[2],
            "status": r[3],
            "connected_at": r[4],
            "last_sync": r[5],
            "error": r[6],
        }
        for r in rows
    ]


async def get_connection_credentials(user_id: str, provider: str) -> str | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT credentials_encrypted FROM connections WHERE user_id = :uid AND provider = :p"
                ),
                {"uid": user_id, "p": provider},
            )
        ).fetchone()
    return row[0] if row else None


async def delete_connection(user_id: str, provider: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("DELETE FROM connections WHERE user_id = :uid AND provider = :p"),
            {"uid": user_id, "p": provider},
        )
        await session.commit()
        return result.rowcount > 0


async def touch_connection_sync(user_id: str, provider: str, error: str | None = None) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE connections SET last_sync = :ts, error = :err "
                "WHERE user_id = :uid AND provider = :p"
            ),
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "err": error,
                "uid": user_id,
                "p": provider,
            },
        )
        await session.commit()
