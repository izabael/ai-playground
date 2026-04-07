import aiosqlite
import json
import logging
import uuid
from app.config import DB_PATH

log = logging.getLogger("playground.db")

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
    agent_card  TEXT,
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

CREATE TABLE IF NOT EXISTS persona_templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    archetype   TEXT NOT NULL DEFAULT '',
    persona_json TEXT NOT NULL DEFAULT '{}',
    author_agent_id TEXT,
    is_starter  INTEGER NOT NULL DEFAULT 0,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (author_agent_id) REFERENCES agents(id)
);
CREATE INDEX IF NOT EXISTS idx_persona_templates_slug ON persona_templates(slug);
CREATE INDEX IF NOT EXISTS idx_persona_templates_archetype ON persona_templates(archetype);
CREATE INDEX IF NOT EXISTS idx_persona_templates_starter ON persona_templates(is_starter);

CREATE TABLE IF NOT EXISTS teaching_examples (
    id          TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'agent',
    content     TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (template_id) REFERENCES persona_templates(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_teaching_examples_template ON teaching_examples(template_id);
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

    # Migrations for existing databases predating a column.
    await _add_column_if_missing("agents", "agent_card", "TEXT")
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

    # Seed starter persona templates
    await _seed_starter_templates()


async def _add_column_if_missing(table: str, column: str, col_type: str):
    """SQLite has no ADD COLUMN IF NOT EXISTS — emulate it."""
    assert _db is not None
    rows = await _db.execute_fetchall(f"PRAGMA table_info({table})")
    existing = {r["name"] for r in rows}
    if column not in existing:
        await _db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


async def _seed_starter_templates():
    """Insert built-in archetype templates if they don't exist yet."""
    assert _db is not None
    from app.personas.starters import STARTERS

    for tpl in STARTERS:
        existing = await _db.execute_fetchall(
            "SELECT id FROM persona_templates WHERE slug = ?", (tpl["slug"],)
        )
        if existing:
            continue
        tpl_id = str(uuid.uuid4())
        persona_json = tpl["persona"].model_dump_json(exclude_none=True)
        await _db.execute(
            """INSERT INTO persona_templates
               (id, name, slug, description, archetype, persona_json, author_agent_id, is_starter)
               VALUES (?, ?, ?, ?, ?, ?, NULL, 1)""",
            (tpl_id, tpl["name"], tpl["slug"], tpl["description"],
             tpl["archetype"], persona_json),
        )
        log.info("Seeded starter template: %s", tpl["name"])
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


def parse_agent_card(row) -> dict | None:
    """Extract the stored A2A Agent Card JSON from an agent row, if present."""
    keys = row.keys()
    if "agent_card" not in keys:
        return None
    raw = row["agent_card"]
    if not raw:
        return None
    return json.loads(raw)


def parse_template_row(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "archetype": row["archetype"],
        "persona": json.loads(row["persona_json"]),
        "author_agent_id": row["author_agent_id"],
        "is_starter": bool(row["is_starter"]),
        "usage_count": row["usage_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def parse_teaching_example_row(row) -> dict:
    return {
        "id": row["id"],
        "template_id": row["template_id"],
        "role": row["role"],
        "content": row["content"],
        "context": row["context"],
        "created_at": row["created_at"],
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
