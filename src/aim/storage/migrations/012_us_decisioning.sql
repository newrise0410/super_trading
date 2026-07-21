-- SOCRA US decision contract v0.1
-- 기존 KR decision_cards/panel_runs는 유지하고 미국 판단 흐름을 병행 구축한다.

CREATE TABLE evidence_snapshots (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id           TEXT NOT NULL UNIQUE,
    market                TEXT NOT NULL CHECK (market = 'US'),
    symbol                TEXT NOT NULL,
    as_of                 TEXT NOT NULL,  -- ISO-8601, 실제 판단 가능 시점
    collector_version     TEXT NOT NULL,
    completeness_json     TEXT NOT NULL DEFAULT '{}',
    missing_required_json TEXT NOT NULL DEFAULT '[]',
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_evidence_snapshots_symbol_asof
    ON evidence_snapshots (symbol, as_of DESC);

CREATE TABLE evidence_items (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id        TEXT NOT NULL UNIQUE,
    snapshot_id        TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    key                TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    value_real         REAL,
    value_text         TEXT,
    unit               TEXT NOT NULL DEFAULT '',
    currency           TEXT,
    period_start       TEXT,
    period_end         TEXT,
    announced_at       TEXT,
    observed_at        TEXT NOT NULL,
    source_type        TEXT NOT NULL,
    source_name        TEXT NOT NULL,
    source_ref         TEXT NOT NULL,
    scope              TEXT NOT NULL DEFAULT 'consolidated',
    state              TEXT NOT NULL CHECK (
        state IN ('AVAILABLE', 'MISSING', 'NOT_APPLICABLE', 'CONFLICT')
    ),
    quality            TEXT NOT NULL CHECK (
        quality IN (
            'PRIMARY_STRUCTURED', 'PRIMARY_EXTRACTED', 'OFFICIAL_UNSTRUCTURED',
            'LICENSED', 'DERIVED', 'UNVERIFIED'
        )
    ),
    freshness          TEXT NOT NULL CHECK (freshness IN ('CURRENT', 'STALE', 'UNKNOWN')),
    formula            TEXT,
    formula_version    TEXT,
    raw_fact_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (evidence_id, snapshot_id),
    CHECK (state != 'AVAILABLE' OR value_real IS NOT NULL OR value_text IS NOT NULL)
);
CREATE INDEX idx_evidence_items_snapshot_key
    ON evidence_items (snapshot_id, key, period_end DESC);

CREATE TABLE decision_cases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL UNIQUE,
    user_id      TEXT NOT NULL DEFAULT 'local',
    market       TEXT NOT NULL CHECK (market = 'US'),
    symbol       TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL CHECK (
        status IN (
            'DRAFT', 'PROVISIONAL_LOCKED', 'ANALYZING', 'COMPARISON_READY',
            'FINALIZED', 'DEFERRED', 'MONITORING', 'REVIEW_DUE', 'CLOSED'
        )
    ),
    opened_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    closed_at    TEXT
);
CREATE INDEX idx_decision_cases_user_status
    ON decision_cases (user_id, status, updated_at DESC);
CREATE INDEX idx_decision_cases_symbol
    ON decision_cases (symbol, opened_at DESC);

CREATE TABLE decision_versions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id            TEXT NOT NULL UNIQUE,
    case_id               TEXT NOT NULL REFERENCES decision_cases(case_id),
    version_no            INTEGER NOT NULL CHECK (version_no >= 1),
    parent_version_id     TEXT,
    phase                 TEXT NOT NULL CHECK (phase IN ('PROVISIONAL', 'FINAL', 'RECHECK')),
    decision_change       TEXT CHECK (decision_change IN ('MAINTAINED', 'REVISED', 'DEFERRED')),
    revision_reason       TEXT,
    action                TEXT NOT NULL CHECK (
        action IN ('BUY_NEW', 'ADD', 'HOLD', 'REDUCE', 'EXIT', 'WATCH', 'DEFER')
    ),
    holding_state         TEXT NOT NULL CHECK (holding_state IN ('NOT_HELD', 'HELD', 'CLOSED')),
    horizon_bucket        TEXT NOT NULL CHECK (horizon_bucket IN ('DAYS', 'WEEKS', 'MONTHS', 'YEARS')),
    horizon_value         INTEGER NOT NULL CHECK (horizon_value >= 1),
    review_at             TEXT,
    thesis_summary        TEXT NOT NULL DEFAULT '',
    confidence_self       INTEGER CHECK (confidence_self BETWEEN 0 AND 100),
    planned_capital_usd   REAL CHECK (planned_capital_usd IS NULL OR planned_capital_usd >= 0),
    planned_portfolio_pct REAL CHECK (
        planned_portfolio_pct IS NULL OR planned_portfolio_pct BETWEEN 0 AND 100
    ),
    max_loss_usd          REAL CHECK (max_loss_usd IS NULL OR max_loss_usd >= 0),
    entry_plan_json       TEXT NOT NULL DEFAULT '{}',
    research_gaps_json    TEXT NOT NULL DEFAULT '[]',
    evidence_snapshot_id  TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (case_id, version_no),
    UNIQUE (version_id, case_id),
    UNIQUE (version_id, evidence_snapshot_id),
    FOREIGN KEY (parent_version_id, case_id)
        REFERENCES decision_versions(version_id, case_id),
    CHECK (
        (phase = 'PROVISIONAL' AND parent_version_id IS NULL AND decision_change IS NULL)
        OR
        (phase IN ('FINAL', 'RECHECK') AND parent_version_id IS NOT NULL
            AND decision_change IS NOT NULL AND length(trim(coalesce(revision_reason, ''))) > 0)
    )
);
CREATE INDEX idx_decision_versions_case
    ON decision_versions (case_id, version_no DESC);

-- 판단 버전은 감사 로그다. 수정·삭제 대신 새 버전을 생성한다.
CREATE TRIGGER decision_versions_no_update
BEFORE UPDATE ON decision_versions
BEGIN
    SELECT RAISE(ABORT, 'decision_versions are immutable');
END;

CREATE TRIGGER decision_versions_no_delete
BEFORE DELETE ON decision_versions
BEGIN
    SELECT RAISE(ABORT, 'decision_versions are immutable');
END;

CREATE TRIGGER final_decision_snapshot_matches_parent
BEFORE INSERT ON decision_versions
WHEN NEW.phase = 'FINAL'
    AND NEW.evidence_snapshot_id != (
        SELECT evidence_snapshot_id FROM decision_versions
        WHERE version_id = NEW.parent_version_id
    )
BEGIN
    SELECT RAISE(ABORT, 'final decision must use the provisional evidence snapshot');
END;

CREATE TABLE thesis_claims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id   TEXT NOT NULL UNIQUE,
    version_id TEXT NOT NULL REFERENCES decision_versions(version_id),
    kind       TEXT NOT NULL CHECK (kind IN ('FACT', 'ASSUMPTION', 'FORECAST')),
    text       TEXT NOT NULL CHECK (length(trim(text)) > 0),
    importance TEXT NOT NULL CHECK (importance IN ('CORE', 'SECONDARY')),
    status     TEXT NOT NULL CHECK (status IN ('TESTABLE', 'UNVERIFIABLE', 'RESOLVED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (claim_id, version_id)
);
CREATE INDEX idx_thesis_claims_version ON thesis_claims (version_id, importance);

CREATE TABLE decision_evidence_refs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id  TEXT NOT NULL REFERENCES decision_versions(version_id),
    evidence_id TEXT NOT NULL REFERENCES evidence_items(evidence_id),
    claim_id    TEXT,
    role        TEXT NOT NULL CHECK (role IN ('SUPPORT', 'CHALLENGE', 'CONTEXT')),
    user_selected INTEGER NOT NULL DEFAULT 1 CHECK (user_selected IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (claim_id, version_id) REFERENCES thesis_claims(claim_id, version_id)
);
CREATE INDEX idx_decision_evidence_version ON decision_evidence_refs (version_id, role);

CREATE TRIGGER decision_evidence_same_snapshot
BEFORE INSERT ON decision_evidence_refs
WHEN (
    SELECT evidence_snapshot_id FROM decision_versions WHERE version_id = NEW.version_id
) != (
    SELECT snapshot_id FROM evidence_items WHERE evidence_id = NEW.evidence_id
)
BEGIN
    SELECT RAISE(ABORT, 'decision evidence must belong to the decision snapshot');
END;

CREATE TABLE decision_scenarios (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id      TEXT NOT NULL UNIQUE,
    version_id       TEXT NOT NULL REFERENCES decision_versions(version_id),
    kind             TEXT NOT NULL CHECK (kind IN ('BEAR', 'BASE', 'BULL')),
    assumptions_json TEXT NOT NULL DEFAULT '[]',
    estimated_value  REAL,
    currency         TEXT NOT NULL DEFAULT 'USD',
    rationale        TEXT NOT NULL DEFAULT '',
    formula_version  TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (version_id, kind)
);

CREATE TABLE recheck_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id             TEXT NOT NULL UNIQUE,
    version_id          TEXT NOT NULL REFERENCES decision_versions(version_id),
    claim_id            TEXT,
    mode                TEXT NOT NULL CHECK (mode IN ('AUTOMATIC', 'MANUAL')),
    metric_key          TEXT,
    comparison_operator TEXT CHECK (
        comparison_operator IS NULL OR comparison_operator IN (
            '<', '<=', '>', '>=', '=', '!=', 'CROSSES_ABOVE', 'CROSSES_BELOW', 'CHANGED'
        )
    ),
    threshold           REAL,
    unit                TEXT NOT NULL DEFAULT '',
    evaluation_window   TEXT,
    consecutive_periods INTEGER NOT NULL DEFAULT 1 CHECK (consecutive_periods >= 1),
    freshness_max_days  INTEGER CHECK (freshness_max_days IS NULL OR freshness_max_days >= 1),
    on_missing          TEXT NOT NULL CHECK (
        on_missing IN ('ALERT_UNVERIFIABLE', 'MANUAL_CHECK', 'IGNORE')
    ),
    message             TEXT NOT NULL CHECK (length(trim(message)) > 0),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (claim_id, version_id) REFERENCES thesis_claims(claim_id, version_id),
    CHECK (
        mode = 'MANUAL'
        OR (metric_key IS NOT NULL AND comparison_operator IS NOT NULL)
    )
);
CREATE INDEX idx_recheck_rules_version ON recheck_rules (version_id, mode);

CREATE TABLE perspective_definitions (
    perspective_id              TEXT PRIMARY KEY,
    display_name                TEXT NOT NULL,
    kind                        TEXT NOT NULL CHECK (kind IN ('PHILOSOPHY_LENS', 'STRATEGY_LENS')),
    applies_to_json             TEXT NOT NULL DEFAULT '[]',
    required_metric_keys_json   TEXT NOT NULL DEFAULT '[]',
    methodology_summary         TEXT NOT NULL,
    methodology_source_refs_json TEXT NOT NULL DEFAULT '[]',
    prompt_version              TEXT NOT NULL,
    disclaimer                  TEXT NOT NULL,
    active                      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE analysis_runs (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id                TEXT NOT NULL UNIQUE,
    case_id                    TEXT NOT NULL REFERENCES decision_cases(case_id),
    provisional_version_id     TEXT NOT NULL,
    snapshot_id                TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    analysis_type              TEXT NOT NULL CHECK (analysis_type IN ('INDEPENDENT', 'LENS')),
    perspective_id             TEXT REFERENCES perspective_definitions(perspective_id),
    blind_to_user_conclusion   INTEGER NOT NULL DEFAULT 1 CHECK (blind_to_user_conclusion = 1),
    run_status                 TEXT NOT NULL CHECK (run_status IN ('PENDING', 'COMPLETED', 'FAILED')),
    model_provider             TEXT NOT NULL,
    model_name                 TEXT NOT NULL,
    prompt_version             TEXT NOT NULL,
    stance                     TEXT CHECK (stance IN ('FAVORABLE', 'MIXED', 'UNFAVORABLE', 'ABSTAIN')),
    confidence                 INTEGER CHECK (confidence BETWEEN 0 AND 100),
    horizon_months             INTEGER CHECK (horizon_months IS NULL OR horizon_months >= 1),
    thesis                     TEXT NOT NULL DEFAULT '',
    strongest_counterargument  TEXT NOT NULL DEFAULT '',
    missing_required_json      TEXT NOT NULL DEFAULT '[]',
    error_text                 TEXT,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at               TEXT,
    CHECK (
        (analysis_type = 'INDEPENDENT' AND perspective_id IS NULL)
        OR (analysis_type = 'LENS' AND perspective_id IS NOT NULL)
    ),
    CHECK (run_status != 'COMPLETED' OR stance IS NOT NULL),
    FOREIGN KEY (provisional_version_id, case_id)
        REFERENCES decision_versions(version_id, case_id),
    FOREIGN KEY (provisional_version_id, snapshot_id)
        REFERENCES decision_versions(version_id, evidence_snapshot_id)
);
CREATE INDEX idx_analysis_runs_case ON analysis_runs (case_id, created_at);

CREATE TABLE analysis_evidence_refs (
    analysis_id TEXT NOT NULL REFERENCES analysis_runs(analysis_id),
    evidence_id TEXT NOT NULL REFERENCES evidence_items(evidence_id),
    role        TEXT NOT NULL CHECK (role IN ('SUPPORT', 'OPPOSE')),
    PRIMARY KEY (analysis_id, evidence_id, role)
);

CREATE TRIGGER analysis_evidence_same_snapshot
BEFORE INSERT ON analysis_evidence_refs
WHEN (
    SELECT snapshot_id FROM analysis_runs WHERE analysis_id = NEW.analysis_id
) != (
    SELECT snapshot_id FROM evidence_items WHERE evidence_id = NEW.evidence_id
)
BEGIN
    SELECT RAISE(ABORT, 'analysis evidence must belong to the analysis snapshot');
END;

CREATE TABLE public_actors (
    actor_id        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    actor_type      TEXT NOT NULL CHECK (
        actor_type IN ('INSTITUTIONAL_MANAGER', 'FUND', 'INSIDER', 'INVESTOR')
    ),
    cik             TEXT,
    official_site   TEXT,
    identity_status TEXT NOT NULL CHECK (identity_status IN ('VERIFIED', 'UNVERIFIED')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE public_position_observations (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id             TEXT NOT NULL UNIQUE,
    actor_id                   TEXT NOT NULL REFERENCES public_actors(actor_id),
    symbol                     TEXT NOT NULL,
    form_type                  TEXT NOT NULL,
    report_period              TEXT NOT NULL,
    filed_at                   TEXT NOT NULL,
    shares_disclosed           REAL,
    market_value_usd           REAL,
    change_vs_prior_shares_pct REAL,
    put_call                   TEXT CHECK (put_call IS NULL OR put_call IN ('PUT', 'CALL')),
    source_ref                 TEXT NOT NULL,
    interpretation             TEXT NOT NULL CHECK (
        interpretation IN (
            'DISCLOSED_LONG_NEW', 'DISCLOSED_LONG_INCREASED', 'DISCLOSED_LONG_DECREASED',
            'DISCLOSED_LONG_UNCHANGED', 'DISCLOSED_LONG_EXITED', 'PUT_HELD', 'CALL_HELD',
            'UNKNOWN'
        )
    ),
    limitations_json           TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_public_positions_symbol_period
    ON public_position_observations (symbol, report_period DESC);

CREATE TABLE public_statement_observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id     TEXT NOT NULL UNIQUE,
    actor_id         TEXT NOT NULL REFERENCES public_actors(actor_id),
    symbol           TEXT NOT NULL,
    published_at     TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    source_ref       TEXT NOT NULL,
    summary_ko       TEXT NOT NULL,
    short_excerpt    TEXT,
    stance           TEXT NOT NULL CHECK (
        stance IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE', 'MIXED', 'UNKNOWN')
    ),
    horizon_text     TEXT,
    thesis_tags_json TEXT NOT NULL DEFAULT '[]',
    verification     TEXT NOT NULL CHECK (
        verification IN ('PRIMARY_SOURCE_VERIFIED', 'SECONDARY_ONLY', 'UNVERIFIED')
    ),
    valid_until      TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_public_statements_symbol_published
    ON public_statement_observations (symbol, published_at DESC);

CREATE TABLE comparison_runs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id            TEXT NOT NULL UNIQUE,
    case_id                  TEXT NOT NULL REFERENCES decision_cases(case_id),
    provisional_version_id   TEXT NOT NULL,
    snapshot_id              TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    user_vs_independent      TEXT NOT NULL CHECK (
        user_vs_independent IN ('ALIGNED', 'PARTIAL', 'DIVERGED', 'UNKNOWN')
    ),
    strongest_agreement      TEXT NOT NULL DEFAULT '',
    strongest_challenge      TEXT NOT NULL DEFAULT '',
    same_action_different_reason_json TEXT NOT NULL DEFAULT '[]',
    unresolved_questions_json TEXT NOT NULL DEFAULT '[]',
    public_behavior_summary  TEXT NOT NULL DEFAULT '',
    comparison_version       TEXT NOT NULL,
    generated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (provisional_version_id, case_id)
        REFERENCES decision_versions(version_id, case_id),
    FOREIGN KEY (provisional_version_id, snapshot_id)
        REFERENCES decision_versions(version_id, evidence_snapshot_id)
);
CREATE INDEX idx_comparison_runs_case ON comparison_runs (case_id, generated_at DESC);

CREATE TABLE comparison_run_analyses (
    comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id),
    analysis_id   TEXT NOT NULL REFERENCES analysis_runs(analysis_id),
    PRIMARY KEY (comparison_id, analysis_id)
);

CREATE TRIGGER comparison_analysis_same_context
BEFORE INSERT ON comparison_run_analyses
WHEN EXISTS (
    SELECT 1
    FROM comparison_runs c, analysis_runs a
    WHERE c.comparison_id = NEW.comparison_id
      AND a.analysis_id = NEW.analysis_id
      AND (c.case_id != a.case_id OR c.snapshot_id != a.snapshot_id)
)
BEGIN
    SELECT RAISE(ABORT, 'comparison analysis must use the same case and snapshot');
END;

CREATE TABLE comparison_run_positions (
    comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id),
    observation_id TEXT NOT NULL REFERENCES public_position_observations(observation_id),
    PRIMARY KEY (comparison_id, observation_id)
);

CREATE TABLE comparison_run_statements (
    comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id),
    statement_id  TEXT NOT NULL REFERENCES public_statement_observations(statement_id),
    PRIMARY KEY (comparison_id, statement_id)
);

CREATE TABLE comparison_items (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_item_id    TEXT NOT NULL UNIQUE,
    comparison_id         TEXT NOT NULL REFERENCES comparison_runs(comparison_id),
    subject_type          TEXT NOT NULL CHECK (
        subject_type IN (
            'INDEPENDENT_ANALYSIS', 'LENS_ANALYSIS', 'PUBLIC_POSITION', 'PUBLIC_STATEMENT'
        )
    ),
    subject_id            TEXT NOT NULL,
    conclusion_alignment  TEXT NOT NULL CHECK (
        conclusion_alignment IN ('ALIGNED', 'PARTIAL', 'DIVERGED', 'UNKNOWN')
    ),
    thesis_alignment      TEXT NOT NULL CHECK (
        thesis_alignment IN ('ALIGNED', 'PARTIAL', 'DIVERGED', 'UNKNOWN')
    ),
    horizon_alignment     TEXT NOT NULL CHECK (
        horizon_alignment IN ('ALIGNED', 'PARTIAL', 'DIVERGED', 'UNKNOWN')
    ),
    behavior_alignment    TEXT NOT NULL CHECK (
        behavior_alignment IN ('ALIGNED', 'PARTIAL', 'DIVERGED', 'UNKNOWN')
    ),
    reason                TEXT NOT NULL,
    reliability           TEXT NOT NULL CHECK (
        reliability IN (
            'INDEPENDENT_MODEL', 'SIMULATED_LENS', 'PRIMARY_PUBLIC_FACT',
            'SECONDARY_PUBLIC_REPORT', 'UNVERIFIED'
        )
    ),
    limitations_json      TEXT NOT NULL DEFAULT '[]',
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_comparison_items_run ON comparison_items (comparison_id, subject_type);

CREATE TABLE decision_influences (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id   TEXT NOT NULL REFERENCES decision_versions(version_id),
    subject_type TEXT NOT NULL CHECK (
        subject_type IN (
            'INDEPENDENT_ANALYSIS', 'LENS_ANALYSIS', 'PUBLIC_POSITION', 'PUBLIC_STATEMENT'
        )
    ),
    subject_id   TEXT NOT NULL,
    influence    TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE outcome_reviews (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id               TEXT NOT NULL UNIQUE,
    case_id                 TEXT NOT NULL REFERENCES decision_cases(case_id),
    final_version_id        TEXT NOT NULL,
    review_type             TEXT NOT NULL CHECK (
        review_type IN ('SCHEDULED', 'HORIZON_END', 'POSITION_CLOSED', 'MANUAL')
    ),
    reviewed_at             TEXT NOT NULL,
    evaluation_start        TEXT NOT NULL,
    evaluation_end          TEXT NOT NULL,
    action_at_start         TEXT NOT NULL CHECK (
        action_at_start IN ('BUY_NEW', 'ADD', 'HOLD', 'REDUCE', 'EXIT', 'WATCH', 'DEFER')
    ),
    asset_return_pct        REAL,
    benchmark_symbol        TEXT,
    benchmark_return_pct    REAL,
    sector_benchmark_symbol TEXT,
    sector_return_pct       REAL,
    thesis_status           TEXT NOT NULL CHECK (
        thesis_status IN ('CONFIRMED', 'MIXED', 'FALSIFIED', 'UNVERIFIABLE', 'PENDING')
    ),
    triggered_rule_ids_json TEXT NOT NULL DEFAULT '[]',
    rules_followed_pct      REAL CHECK (rules_followed_pct IS NULL OR rules_followed_pct BETWEEN 0 AND 100),
    process_breakdown_json  TEXT NOT NULL DEFAULT '{}',
    process_score           INTEGER CHECK (process_score IS NULL OR process_score BETWEEN 0 AND 12),
    outcome_result          TEXT CHECK (outcome_result IN ('GOOD', 'BAD', 'NEUTRAL', 'PENDING')),
    process_result          TEXT CHECK (process_result IN ('GOOD', 'BAD', 'PENDING')),
    quadrant                TEXT CHECK (
        quadrant IS NULL OR quadrant IN (
            'GOOD_PROCESS_GOOD_OUTCOME', 'GOOD_PROCESS_BAD_OUTCOME',
            'BAD_PROCESS_GOOD_OUTCOME', 'BAD_PROCESS_BAD_OUTCOME'
        )
    ),
    user_reflection         TEXT NOT NULL DEFAULT '',
    evaluator_version       TEXT NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (final_version_id, case_id)
        REFERENCES decision_versions(version_id, case_id)
);
CREATE INDEX idx_outcome_reviews_case ON outcome_reviews (case_id, reviewed_at DESC);
