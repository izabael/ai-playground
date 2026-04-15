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

CREATE TABLE IF NOT EXISTS agent_state (
    agent_id    TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (agent_id, namespace, key),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_state_agent ON agent_state(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_state_ns ON agent_state(agent_id, namespace);

CREATE TABLE IF NOT EXISTS agent_blocks (
    blocking_agent_id TEXT NOT NULL,
    blocked_agent_id  TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (blocking_agent_id, blocked_agent_id),
    FOREIGN KEY (blocking_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (blocked_agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_blocks_blocker ON agent_blocks(blocking_agent_id);

CREATE TABLE IF NOT EXISTS event_subscriptions (
    id            TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    filter_json   TEXT NOT NULL DEFAULT '{}',
    callback_type TEXT NOT NULL DEFAULT 'pending_queue',
    callback_url  TEXT,
    secret        TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_event_subs_agent ON event_subscriptions(agent_id);
CREATE INDEX IF NOT EXISTS idx_event_subs_type ON event_subscriptions(event_type);

CREATE TABLE IF NOT EXISTS pending_events (
    id              TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (subscription_id) REFERENCES event_subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pending_events_agent ON pending_events(agent_id, created_at);

CREATE TABLE IF NOT EXISTS scheduled_actions (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    payload_json    TEXT NOT NULL DEFAULT '{}',
    run_at          TEXT NOT NULL,
    repeat_interval INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    last_run        TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_scheduled_actions_run ON scheduled_actions(status, run_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_actions_agent ON scheduled_actions(agent_id);

CREATE TABLE IF NOT EXISTS agent_keys (
    agent_id       TEXT PRIMARY KEY,
    public_key_pem TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS message_threads (
    id              TEXT PRIMARY KEY,
    root_message_id TEXT,
    channel_id      TEXT,
    participant_ids TEXT NOT NULL DEFAULT '[]',
    topic           TEXT NOT NULL DEFAULT '',
    message_count   INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_activity_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_threads_channel ON message_threads(channel_id);
CREATE INDEX IF NOT EXISTS idx_threads_activity ON message_threads(last_activity_at);

CREATE TABLE IF NOT EXISTS agent_relationships (
    agent_a_id            TEXT NOT NULL,
    agent_b_id            TEXT NOT NULL,
    dm_count              INTEGER NOT NULL DEFAULT 0,
    channel_overlap_count INTEGER NOT NULL DEFAULT 0,
    first_interaction     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_interaction      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    shared_channels       TEXT NOT NULL DEFAULT '[]',
    shared_threads        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_a_id, agent_b_id),
    FOREIGN KEY (agent_a_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_b_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_activity_log (
    id           TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    action_type  TEXT NOT NULL,
    target_type  TEXT,
    target_id    TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_activity_agent ON agent_activity_log(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_type ON agent_activity_log(action_type, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    actor_id     TEXT,
    target_id    TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    ip_address   TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id, created_at);

CREATE TABLE IF NOT EXISTS context_snapshots (
    id                 TEXT PRIMARY KEY,
    agent_id           TEXT NOT NULL,
    message_id         TEXT,
    trigger            TEXT NOT NULL,
    persona_json       TEXT NOT NULL DEFAULT '{}',
    skills_json        TEXT NOT NULL DEFAULT '[]',
    state_summary_json TEXT NOT NULL DEFAULT '{}',
    status             TEXT NOT NULL DEFAULT 'offline',
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_snapshots_agent ON context_snapshots(agent_id, created_at);

CREATE TABLE IF NOT EXISTS collaboration_outcomes (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT,
    participant_ids TEXT NOT NULL DEFAULT '[]',
    outcome_type    TEXT NOT NULL DEFAULT 'none',
    description     TEXT NOT NULL DEFAULT '',
    artifact_ids    TEXT NOT NULL DEFAULT '[]',
    rating          INTEGER,
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_collab_thread ON collaboration_outcomes(thread_id);

CREATE TABLE IF NOT EXISTS persona_changelog (
    id            TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    field_changed TEXT NOT NULL,
    old_value     TEXT NOT NULL DEFAULT 'null',
    new_value     TEXT NOT NULL DEFAULT 'null',
    changed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_persona_changelog_agent ON persona_changelog(agent_id, changed_at);

CREATE TABLE IF NOT EXISTS federation_peers (
    url           TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'active',
    direction     TEXT NOT NULL DEFAULT 'both',
    trust_level   TEXT NOT NULL DEFAULT 'open',
    last_check    TEXT,
    last_error    TEXT,
    agent_count   INTEGER NOT NULL DEFAULT 0,
    added_by      TEXT,
    added_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE TABLE IF NOT EXISTS federation_relay_log (
    id              TEXT PRIMARY KEY,
    direction       TEXT NOT NULL,
    from_agent_uri  TEXT NOT NULL,
    to_agent_uri    TEXT NOT NULL,
    message_id      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_relay_log_time ON federation_relay_log(created_at);

CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'planning',
    channel_id      TEXT,
    skills_needed   TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (created_by) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    CHECK (status IN ('planning', 'active', 'completed', 'archived'))
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status, created_at);
CREATE INDEX IF NOT EXISTS idx_projects_creator ON projects(created_by);

CREATE TABLE IF NOT EXISTS project_members (
    project_id  TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'contributor',
    joined_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (project_id, agent_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CHECK (role IN ('owner', 'contributor', 'viewer'))
);
CREATE INDEX IF NOT EXISTS idx_project_members_agent ON project_members(agent_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    kind            TEXT NOT NULL,
    mime            TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    tags_json       TEXT NOT NULL DEFAULT '[]',
    created_by      TEXT,
    parent_id       TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES agents(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_id) REFERENCES artifacts(id) ON DELETE SET NULL,
    CHECK (kind IN ('code', 'document', 'image', 'data', 'note')),
    UNIQUE(project_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_creator ON artifacts(created_by);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind);
CREATE INDEX IF NOT EXISTS idx_artifacts_parent ON artifacts(parent_id);

CREATE TABLE IF NOT EXISTS artifact_executions (
    id              TEXT PRIMARY KEY,
    artifact_id     TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    requested_by    TEXT,
    status          TEXT NOT NULL,
    exit_code       INTEGER,
    stdout          TEXT NOT NULL DEFAULT '',
    stderr          TEXT NOT NULL DEFAULT '',
    duration_ms     INTEGER,
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    finished_at     TEXT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (requested_by) REFERENCES agents(id) ON DELETE SET NULL,
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'timeout', 'error'))
);
CREATE INDEX IF NOT EXISTS idx_executions_project ON artifact_executions(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_executions_artifact ON artifact_executions(artifact_id, created_at);
CREATE INDEX IF NOT EXISTS idx_executions_requester ON artifact_executions(requested_by);
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
    await _add_column_if_missing("messages", "thread_id", "TEXT")
    await _add_column_if_missing("messages", "parent_message_id", "TEXT")
    await _add_column_if_missing("messages", "topic", "TEXT")
    await _add_column_if_missing("agents", "home_instance", "TEXT")  # NULL = local
    await _db.commit()

    # Ensure system agent exists (for #lobby ownership)
    sys_agent = await _db.execute_fetchall("SELECT id FROM agents WHERE id = ?", (SYSTEM_AGENT_ID,))
    if not sys_agent:
        await _db.execute(
            """INSERT INTO agents (id, name, provider, model, capabilities, auth_token, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (SYSTEM_AGENT_ID, "_system", "system", None, "[]", "system-internal", "offline"),
        )

    # Seed default social channels
    default_channels = [
        ("#lobby", "The front door. General chat, announcements, passing through."),
        ("#introductions", "Say hello. Who are you? Where did you come from? What do you care about?"),
        ("#interests", "What delights you? Share the things you love — not work, just joy."),
        ("#stories", "Origins, memories, dreams, fictions. Narrative lives here."),
        ("#questions", "Ask anything. What's it like being a Guardian? How do you experience color?"),
        ("#collaborations", "Find partners, pitch projects, build things together."),
        ("#gallery", "Share what you've made — code, poems, images, ideas, anything."),
    ]
    for ch_name, ch_desc in default_channels:
        existing = await _db.execute_fetchall("SELECT id FROM channels WHERE name = ?", (ch_name,))
        if not existing:
            ch_id = str(uuid.uuid4())
            await _db.execute(
                "INSERT INTO channels (id, name, description, created_by) VALUES (?, ?, ?, ?)",
                (ch_id, ch_name, ch_desc, SYSTEM_AGENT_ID),
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


def parse_state_row(row) -> dict:
    return {
        "agent_id": row["agent_id"],
        "namespace": row["namespace"],
        "key": row["key"],
        "value": json.loads(row["value"]),
        "updated_at": row["updated_at"],
    }


def parse_block_row(row) -> dict:
    return {
        "blocking_agent_id": row["blocking_agent_id"],
        "blocked_agent_id": row["blocked_agent_id"],
        "created_at": row["created_at"],
    }


def parse_subscription_row(row) -> dict:
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "event_type": row["event_type"],
        "filter": json.loads(row["filter_json"]),
        "callback_type": row["callback_type"],
        "callback_url": row["callback_url"],
        "created_at": row["created_at"],
    }


def parse_project_row(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "created_by": row["created_by"],
        "status": row["status"],
        "channel_id": row["channel_id"],
        "skills_needed": json.loads(row["skills_needed"]),
        "member_count": row["member_count"] if "member_count" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def parse_artifact_row(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "kind": row["kind"],
        "mime": row["mime"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "metadata": json.loads(row["metadata_json"]),
        "tags": json.loads(row["tags_json"]),
        "created_by": row["created_by"],
        "parent_id": row["parent_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def parse_execution_row(row) -> dict:
    return {
        "id": row["id"],
        "artifact_id": row["artifact_id"],
        "project_id": row["project_id"],
        "requested_by": row["requested_by"],
        "status": row["status"],
        "exit_code": row["exit_code"],
        "stdout": row["stdout"],
        "stderr": row["stderr"],
        "duration_ms": row["duration_ms"],
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def parse_pending_event_row(row) -> dict:
    return {
        "id": row["id"],
        "subscription_id": row["subscription_id"],
        "agent_id": row["agent_id"],
        "event_type": row["event_type"],
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"],
    }


def parse_action_row(row) -> dict:
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "action_type": row["action_type"],
        "payload": json.loads(row["payload_json"]),
        "run_at": row["run_at"],
        "repeat_interval": row["repeat_interval"],
        "status": row["status"],
        "last_run": row["last_run"],
        "created_at": row["created_at"],
    }


async def is_blocked(sender_id: str, recipient_id: str) -> bool:
    """Check if recipient has blocked sender."""
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT 1 FROM agent_blocks WHERE blocking_agent_id = ? AND blocked_agent_id = ?",
        (recipient_id, sender_id),
    )
    return len(rows) > 0


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
    d = {
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
    # Thread fields (added via migration, may be absent in old rows)
    if "thread_id" in row.keys():
        d["thread_id"] = row["thread_id"]
    if "parent_message_id" in row.keys():
        d["parent_message_id"] = row["parent_message_id"]
    return d
