-- ELI database schema reference (auto-generated; DO NOT hand-edit).
-- Authoritative builder: eli/core/init_data.py (run on install + every boot).
-- Regenerate: see the header note in init_data.py. Contains ZERO data — schema only.
-- A fresh install creates every table below with 0 rows (clean slate).

-- ======================================================================
-- user.sqlite3
-- ======================================================================
CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            value TEXT,
            content TEXT,
            tags TEXT,
            kind TEXT,
            ts REAL,
            timestamp REAL,
            source TEXT,
            status TEXT,
            weight REAL DEFAULT 1.0,
            confidence REAL DEFAULT 1.0,
            importance REAL DEFAULT 0.5
        );
CREATE VIRTUAL TABLE memories_fts
            USING fts5(text, tags, content='memories', content_rowid='id')
/* memories_fts(text,tags) */;
CREATE TABLE IF NOT EXISTS 'memories_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE IF NOT EXISTS 'memories_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS 'memories_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE IF NOT EXISTS 'memories_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            timestamp REAL,
            ts REAL,
            created_at REAL,
            updated_at REAL,
            title TEXT
        );
CREATE TABLE conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            ts REAL,
            timestamp REAL
        );
CREATE TABLE recall_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            query TEXT,
            results_count INTEGER,
            result_count INTEGER,
            memory_id INTEGER
        );
CREATE TABLE habit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            event TEXT,
            details TEXT,
            data TEXT,
            timestamp REAL,
            ts REAL,
            name TEXT,
            cmd TEXT,
            method TEXT,
            command TEXT
        );
CREATE TABLE habit_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            command TEXT,
            hour INTEGER,
            minute INTEGER,
            days TEXT,
            enabled INTEGER DEFAULT 1,
            timestamp REAL,
            ts REAL,
            pattern TEXT,
            action TEXT,
            trigger_phrase TEXT,
            action_type TEXT
        );
CREATE TABLE habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            cmd TEXT,
            method TEXT,
            count INTEGER DEFAULT 0,
            hour INTEGER,
            minute INTEGER,
            timestamp REAL,
            command TEXT,
            enabled INTEGER DEFAULT 1,
            ts REAL
        );
CREATE TABLE corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original TEXT,
            corrected TEXT,
            timestamp REAL,
            ts REAL
        );
CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            category TEXT,
            observation TEXT,
            content TEXT,
            text TEXT,
            details TEXT,
            timestamp REAL,
            ts REAL
        );
CREATE TABLE session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            summary TEXT,
            content TEXT,
            turns_count INTEGER,
            started_at REAL,
            ended_at REAL,
            source TEXT,
            timestamp REAL,
            ts REAL
        );
CREATE TABLE improvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            category TEXT,
            area TEXT,
            description TEXT,
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            created_at REAL,
            title TEXT,
            name TEXT,
            improvement TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            source TEXT,
            count INTEGER DEFAULT 1,
            suggestion TEXT,
            applied INTEGER DEFAULT 0
        );
CREATE TABLE failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            user_input TEXT,
            command TEXT,
            error TEXT,
            traceback TEXT,
            confidence REAL,
            low_confidence INTEGER DEFAULT 0,
            context TEXT,
            context_json TEXT,
            occurrence_count INTEGER DEFAULT 1,
            first_seen REAL,
            last_seen REAL,
            failure TEXT,
            name TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            description TEXT,
            source TEXT,
            signature TEXT,
            status TEXT,
            count INTEGER DEFAULT 1
        );
CREATE TABLE capability_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            proposed_name TEXT,
            capability TEXT,
            description TEXT,
            examples TEXT,
            plugin_code TEXT,
            reasoning TEXT,
            rationale TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT,
            notes TEXT,
            created_at REAL,
            updated_at REAL,
            source TEXT,
            category TEXT
        );
CREATE TABLE error_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT,
            details TEXT,
            timestamp REAL,
            occurrence_count INTEGER DEFAULT 1,
            first_seen REAL,
            last_seen REAL
        );
CREATE TABLE user_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT,
            pattern_data TEXT,
            timestamp REAL,
            ts REAL
        );
CREATE TABLE learning_replay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            input_text TEXT,
            output_text TEXT,
            action TEXT,
            outcome TEXT,
            reward REAL,
            metadata TEXT,
            timestamp REAL,
            ts REAL
        );
CREATE TABLE user_model (
            user_id       TEXT PRIMARY KEY,
            identity      TEXT,
            comms_style   TEXT,
            current_focus TEXT,
            interests     TEXT,
            habits        TEXT,
            goals         TEXT,
            relationship  TEXT,
            dossier       TEXT,
            brief         TEXT,
            sources       TEXT,
            confidence    REAL,
            updated_at    REAL,
            ts            REAL
        );
CREATE TABLE kg_entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    type        TEXT    DEFAULT 'concept',
    aliases     TEXT    DEFAULT '',
    description TEXT    DEFAULT '',
    confidence  REAL    DEFAULT 1.0,
    ts          REAL    NOT NULL
);
CREATE UNIQUE INDEX kg_entities_name ON kg_entities(LOWER(name));
CREATE TABLE kg_relations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    predicate   TEXT    NOT NULL,
    object_id   INTEGER NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    weight      REAL    DEFAULT 1.0,
    source      TEXT    DEFAULT 'inferred',
    ts          REAL    NOT NULL
);
CREATE INDEX kg_rel_subj ON kg_relations(subject_id);
CREATE INDEX kg_rel_obj  ON kg_relations(object_id);
CREATE UNIQUE INDEX kg_rel_unique
    ON kg_relations(subject_id, LOWER(predicate), object_id);
CREATE VIRTUAL TABLE kg_entities_fts
    USING fts5(name, aliases, description, content='kg_entities', content_rowid='id')
/* kg_entities_fts(name,aliases,description) */;
CREATE TABLE IF NOT EXISTS 'kg_entities_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE IF NOT EXISTS 'kg_entities_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS 'kg_entities_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE IF NOT EXISTS 'kg_entities_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TRIGGER kg_ent_ai AFTER INSERT ON kg_entities BEGIN
    INSERT INTO kg_entities_fts(rowid, name, aliases, description)
    VALUES (new.id, new.name, COALESCE(new.aliases,''), COALESCE(new.description,''));
END;
CREATE TRIGGER kg_ent_au AFTER UPDATE ON kg_entities BEGIN
    INSERT INTO kg_entities_fts(kg_entities_fts, rowid, name, aliases, description)
    VALUES ('delete', old.id, old.name, COALESCE(old.aliases,''), COALESCE(old.description,''));
    INSERT INTO kg_entities_fts(rowid, name, aliases, description)
    VALUES (new.id, new.name, COALESCE(new.aliases,''), COALESCE(new.description,''));
END;
CREATE TRIGGER kg_ent_ad AFTER DELETE ON kg_entities BEGIN
    INSERT INTO kg_entities_fts(kg_entities_fts, rowid, name, aliases, description)
    VALUES ('delete', old.id, old.name, COALESCE(old.aliases,''), COALESCE(old.description,''));
END;
CREATE TABLE news_articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    url         TEXT,
    summary     TEXT,
    category    TEXT,
    fetched_at  REAL    NOT NULL,
    published   TEXT,
    score       INTEGER DEFAULT 0,
    UNIQUE(url)
);
CREATE VIRTUAL TABLE news_fts USING fts5(
    title, summary, source, category,
    content='news_articles', content_rowid='id'
)
/* news_fts(title,summary,source,category) */;
CREATE TABLE IF NOT EXISTS 'news_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE IF NOT EXISTS 'news_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS 'news_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE IF NOT EXISTS 'news_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TRIGGER news_ai AFTER INSERT ON news_articles BEGIN
    INSERT INTO news_fts(rowid, title, summary, source, category)
    VALUES (new.id, new.title, new.summary, new.source, new.category);
END;
CREATE TABLE news_reflections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    REAL    NOT NULL,
    ended_at      REAL    NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    summary       TEXT    NOT NULL,
    sources       TEXT
);
CREATE TABLE runtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            event_type TEXT,
            source TEXT,
            action TEXT,
            subject TEXT,
            content TEXT,
            payload_json TEXT,
            severity TEXT,
            outcome TEXT,
            confidence REAL,
            reusable INTEGER DEFAULT 1,
            session_id TEXT,
            user_id TEXT,
            request_id TEXT,
            signature TEXT
        );
CREATE INDEX idx_runtime_events_ts ON runtime_events(ts);
CREATE INDEX idx_runtime_events_type ON runtime_events(event_type);
CREATE INDEX idx_runtime_events_signature ON runtime_events(signature);

-- ======================================================================
-- agent.sqlite3
-- ======================================================================
CREATE TABLE agent_dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                action TEXT,
                agents_used TEXT,
                confidence REAL,
                elapsed_ms REAL,
                ok INTEGER,
                summary TEXT
            );
CREATE TABLE agent_metrics (
            agent TEXT NOT NULL,
            action TEXT NOT NULL,
            runs INTEGER NOT NULL DEFAULT 0,
            contributions INTEGER NOT NULL DEFAULT 0,
            sum_self_conf REAL NOT NULL DEFAULT 0.0,
            sum_density REAL NOT NULL DEFAULT 0.0,
            rolling_score REAL NOT NULL DEFAULT 0.5,
            last_updated REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY (agent, action)
        );

-- ======================================================================
-- system_index.sqlite3
-- ======================================================================
CREATE TABLE desktop_apps (
                id INTEGER PRIMARY KEY,
                name TEXT,
                exec TEXT,
                desktop_id TEXT,
                categories TEXT,
                last_used REAL
            );
CREATE TABLE executables (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT UNIQUE
            );
CREATE TABLE user_dirs (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT UNIQUE
            );
CREATE TABLE recent_files (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT,
                last_opened REAL
            );

-- ======================================================================
-- coding_memory.sqlite3
-- ======================================================================
CREATE TABLE coding_bug_fixes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    signature    TEXT NOT NULL,
    bug_class    TEXT NOT NULL,
    language     TEXT DEFAULT 'python',
    error_excerpt TEXT DEFAULT '',
    fix_summary  TEXT DEFAULT '',
    fix_diff     TEXT DEFAULT '',
    success_count INTEGER DEFAULT 1,
    created_ts   REAL,
    last_ts      REAL
);
CREATE INDEX coding_bug_sig  ON coding_bug_fixes(signature);
CREATE INDEX coding_bug_class ON coding_bug_fixes(bug_class);

