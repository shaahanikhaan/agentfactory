"""Versioned SQLite schema. Only this module may create core tables."""

from __future__ import annotations

MIGRATION_1 = r"""
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    parent_task_id TEXT REFERENCES tasks(task_id),
    correlation_id TEXT NOT NULL,
    requester TEXT NOT NULL,
    goal TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','planning','awaiting_approval','running','verifying','retry_wait','paused_offline','succeeded','failed','cancelled','uncertain_side_effect')),
    priority TEXT NOT NULL CHECK (priority IN ('interactive','normal','batch','idle')),
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('R0','R1','R2','R3')),
    department TEXT NOT NULL,
    deadline TEXT,
    budget_json TEXT NOT NULL,
    input_json TEXT NOT NULL,
    allowed_tools_json TEXT NOT NULL,
    expected_output_schema_json TEXT NOT NULL,
    idempotency_key TEXT,
    result_json TEXT,
    error_json TEXT,
    approval_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    retry_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(task_id),
    PRIMARY KEY (task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id)
);
CREATE INDEX idx_tasks_queue ON tasks(state, priority, retry_at, created_at);
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX idx_tasks_correlation ON tasks(correlation_id);
CREATE UNIQUE INDEX idx_tasks_idempotency ON tasks(requester, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE TABLE task_steps (
    step_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL,
    state TEXT NOT NULL,
    input_json TEXT NOT NULL,
    result_json TEXT,
    checksum TEXT NOT NULL,
    replay_of TEXT,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (task_id, sequence),
    UNIQUE (task_id, role, sequence)
);
CREATE INDEX idx_steps_task ON task_steps(task_id, sequence);
CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(task_id),
    step_id TEXT,
    role TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_hash TEXT NOT NULL,
    input_tokens_estimate INTEGER NOT NULL,
    output_tokens_estimate INTEGER,
    latency_ms INTEGER,
    status TEXT NOT NULL,
    error_code TEXT,
    result_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_agent_runs_usage ON agent_runs(provider, model, created_at);
CREATE TABLE agent_messages (
    message_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    message_type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE provider_configs (
    provider TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE provider_health (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    error_code TEXT,
    checked_at TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, model)
);
CREATE TABLE provider_cooldowns (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    scope TEXT NOT NULL,
    until TEXT NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, model, scope)
);
CREATE TABLE quota_observations (
    observation_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    scope TEXT NOT NULL,
    metric TEXT NOT NULL,
    remaining REAL,
    observed_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE model_capabilities (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    context_limit INTEGER,
    output_limit INTEGER,
    free_tier_status TEXT NOT NULL,
    free_tier_source TEXT,
    verified_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, model)
);
CREATE TABLE tool_registry (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    risk_tier TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE TABLE tool_invocations (
    invocation_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(task_id),
    step_id TEXT,
    tool_name TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX idx_tool_invocations_task ON tool_invocations(task_id, created_at);
CREATE TABLE plugin_registry (
    plugin_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    api_version TEXT NOT NULL,
    manifest_path TEXT NOT NULL UNIQUE,
    manifest_digest TEXT NOT NULL,
    entry_hash TEXT,
    permissions_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    trust_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK (trust_acknowledged IN (0,1)),
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE skill_registry (
    skill_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    body_path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE TABLE idempotency_ledger (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    destination TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved','completed','failed','uncertain')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    receipt TEXT,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
CREATE INDEX idx_idempotency_state ON idempotency_ledger(state, updated_at);
CREATE TABLE approval_requests (
    approval_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(task_id),
    action_type TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    action_summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    destination TEXT NOT NULL,
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('R2','R3')),
    requester TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending','approved','rejected','expired')),
    approver TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX idx_approvals_pending ON approval_requests(state, expires_at);
CREATE TABLE memory_items (
    memory_id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('event','task','preference','fact','procedure','repository','telemetry')),
    content TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public','internal','private','secret')),
    expires_at TEXT,
    approval_status TEXT NOT NULL CHECK (approval_status IN ('pending','approved','rejected')),
    deleted_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_memory_search ON memory_items(type, approval_status, deleted_at, updated_at);
CREATE INDEX idx_memory_dedupe ON memory_items(normalized_hash, type, sensitivity);
CREATE TABLE memory_revisions (
    revision_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memory_items(memory_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (memory_id, revision)
);
CREATE TABLE memory_links (
    link_id TEXT PRIMARY KEY,
    from_memory_id TEXT NOT NULL REFERENCES memory_items(memory_id),
    to_memory_id TEXT NOT NULL REFERENCES memory_items(memory_id),
    relation TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE consolidation_jobs (
    job_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('dry_run','applied','failed')),
    plan_json TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    snapshot_id TEXT,
    created_at TEXT NOT NULL,
    applied_at TEXT
);
CREATE TABLE snapshots (
    snapshot_id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    restore_tested_at TEXT,
    metadata_json TEXT NOT NULL
);
CREATE TABLE audit_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT,
    decision TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX idx_audit_object ON audit_events(object_type, object_id, timestamp);
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(task_id),
    path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    digest TEXT NOT NULL,
    size INTEGER NOT NULL,
    retention TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE evaluation_runs (
    run_id TEXT PRIMARY KEY,
    candidate_id TEXT,
    metric TEXT NOT NULL,
    score REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE evaluation_cases (
    case_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    expected_json TEXT NOT NULL,
    tags_json TEXT NOT NULL
);
CREATE TABLE candidate_releases (
    candidate_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    base_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    path TEXT,
    diff_path TEXT,
    state TEXT NOT NULL,
    gates_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE release_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidate_releases(candidate_id),
    decision TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE rollback_events (
    rollback_id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    snapshot_id TEXT,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MIGRATION_2 = r"""
CREATE TABLE research_sources (
    source_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX idx_research_accessed ON research_sources(accessed_at);
CREATE INDEX idx_research_hash ON research_sources(content_hash);
"""

MIGRATION_3 = r"""
CREATE TABLE agent_blueprints (
    blueprint_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (name, version)
);
CREATE TABLE factory_runs (
    run_id TEXT PRIMARY KEY,
    blueprint_id TEXT NOT NULL REFERENCES agent_blueprints(blueprint_id),
    requester TEXT NOT NULL,
    idempotency_key TEXT,
    goal TEXT NOT NULL,
    input_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','running','awaiting_approval','retry_wait','paused_offline','interrupted','failed','succeeded','cancelled','uncertain_side_effect')),
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX idx_factory_runs_state ON factory_runs(state, updated_at);
CREATE UNIQUE INDEX idx_factory_runs_idempotency ON factory_runs(requester, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE TABLE factory_run_tasks (
    run_id TEXT NOT NULL REFERENCES factory_runs(run_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL,
    materialized INTEGER NOT NULL DEFAULT 0 CHECK (materialized IN (0,1)),
    materialized_digest TEXT,
    PRIMARY KEY (run_id, step_id),
    UNIQUE (task_id)
);
CREATE INDEX idx_factory_tasks_task ON factory_run_tasks(task_id);
CREATE TABLE evaluation_case_results (
    run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('development','held_out')),
    passed INTEGER NOT NULL CHECK (passed IN (0,1)),
    score REAL NOT NULL,
    expected_json TEXT NOT NULL,
    actual_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
CREATE INDEX idx_evaluation_case_results_case ON evaluation_case_results(case_id, run_id);
"""

MIGRATION_4 = """
CREATE TABLE experience_captures (
    capture_key TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN ('succeeded','failed')),
    attempt INTEGER NOT NULL,
    memory_id TEXT REFERENCES memory_items(memory_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('captured','skipped_sensitive')),
    created_at TEXT NOT NULL,
    UNIQUE (task_id, outcome, attempt)
);
CREATE INDEX idx_experience_captures_task ON experience_captures(task_id, created_at);
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, MIGRATION_1),
    (2, MIGRATION_2),
    (3, MIGRATION_3),
    (4, MIGRATION_4),
]
