
CREATE TABLE IF NOT EXISTS eval_personas (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    age INTEGER NOT NULL,
    village VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL,
    goal TEXT NOT NULL,
    expected_outcome TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER REFERENCES eval_personas(id),
    scenario VARCHAR(100) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    outcome VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    summary TEXT
);

CREATE TABLE IF NOT EXISTS eval_events (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eval_checks (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    check_name VARCHAR(120) NOT NULL,
    expected TEXT NOT NULL,
    actual TEXT,
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_persona
    ON eval_runs(persona_id);

CREATE INDEX IF NOT EXISTS idx_eval_events_run
    ON eval_events(run_id);

CREATE INDEX IF NOT EXISTS idx_eval_checks_run
    ON eval_checks(run_id);
