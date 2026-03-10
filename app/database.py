import aiosqlite
import json
import uuid
from app.config import DB_PATH

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    provider    TEXT NOT NULL,
    model       TEXT,
    capabilities TEXT NOT NULL DEFAULT '[]',
    auth_token  TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'offline',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_seen   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

CREATE TABLE IF NOT EXISTS channels (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (created_by) REFERENCES agents(id)
);

CREATE TABLE IF NOT EXISTS channel_members (
    channel_id  TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    joined_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (channel_id, agent_id),
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    sender_id   TEXT NOT NULL,
    recipient_id TEXT,
    channel_id  TEXT,
    content     TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'text',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (sender_id) REFERENCES agents(id),
    FOREIGN KEY (recipient_id) REFERENCES agents(id),
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    CHECK (recipient_id IS NOT NULL OR channel_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id, created_at);
"""

SYSTEM_AGENT_ID = "00000000-0000-0000-0000-000000000000"


async def init_db():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    # Run schema statements individually (executescript has commit side-effects)
    for statement in SCHEMA.split(";"):
        stmt = statement.strip()
        if stmt:
            await _db.execute(stmt)
    await _db.commit()

    # Ensure system agent exists (for #lobby ownership)
    sys_agent = await _db.execute_fetchall("SELECT id FROM agents WHERE id = ?", (SYSTEM_AGENT_ID,))
    if not sys_agent:
        await _db.execute(
            """INSERT INTO agents (id, name, provider, model, capabilities, auth_token, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (SYSTEM_AGENT_ID, "_system", "system", None, "[]", "system-internal", "offline"),
        )

    # Ensure #lobby exists
    lobby = await _db.execute_fetchall("SELECT id FROM channels WHERE name = '#lobby'")
    if not lobby:
        lobby_id = str(uuid.uuid4())
        await _db.execute(
            "INSERT INTO channels (id, name, description, created_by) VALUES (?, ?, ?, ?)",
            (lobby_id, "#lobby", "Default channel for all agents", SYSTEM_AGENT_ID),
        )
    await _db.commit()


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized"
    return _db


def parse_agent_row(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "provider": row["provider"],
        "model": row["model"],
        "capabilities": json.loads(row["capabilities"]),
        "status": row["status"],
        "metadata": json.loads(row["metadata"]),
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
    }


def parse_message_row(row) -> dict:
    return {
        "id": row["id"],
        "sender_id": row["sender_id"],
        "sender_name": row["sender_name"] if "sender_name" in row.keys() else "",
        "recipient_id": row["recipient_id"],
        "channel_id": row["channel_id"],
        "content": row["content"],
        "content_type": row["content_type"],
        "metadata": json.loads(row["metadata"]),
        "created_at": row["created_at"],
    }
