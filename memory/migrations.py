import logging

from memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Each key is a schema version; value is an ordered list of DDL statements.
MIGRATIONS: dict[int, list[str]] = {
    1: [
        """CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role       TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
            content    TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            tokens     INTEGER,
            skill_name TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS skills (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            description TEXT,
            md_path     TEXT NOT NULL,
            enabled     BOOLEAN DEFAULT TRUE,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_run    DATETIME,
            run_count   INTEGER DEFAULT 0,
            last_error  TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS cron_jobs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            cron_expr  TEXT NOT NULL,
            enabled    BOOLEAN DEFAULT TRUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            next_run   DATETIME,
            last_run   DATETIME,
            FOREIGN KEY (skill_name) REFERENCES skills(name)
        )""",
        """CREATE TABLE IF NOT EXISTS credentials (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            service    TEXT UNIQUE NOT NULL,
            data       BLOB NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS file_watches (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            path       TEXT NOT NULL,
            pattern    TEXT,
            skill_name TEXT,
            enabled    BOOLEAN DEFAULT TRUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
}


async def run_migrations(store: MemoryStore) -> None:
    await store.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    row = await store.fetchone("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version")
    current_version: int = row["v"] if row else 0
    logger.debug("Current schema version: %d", current_version)

    for version in sorted(MIGRATIONS):
        if version <= current_version:
            continue
        for statement in MIGRATIONS[version]:
            await store.execute(statement)
        await store.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        logger.info("Applied migration v%d", version)
