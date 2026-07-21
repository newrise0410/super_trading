"""미국 판단 계약 — 스키마 무결성과 블라인드 도메인 경계."""

from dataclasses import asdict
import sqlite3

import pytest

from aim.decisioning import (
    Alignment,
    AnalysisStance,
    AnalysisVerdict,
    ClaimImportance,
    ClaimKind,
    ComparisonItem,
    ComparisonOperator,
    ComparisonReliability,
    ComparisonSubject,
    DecisionAction,
    DecisionPhase,
    DecisionVersionInput,
    HoldingState,
    Horizon,
    HorizonBucket,
    OutcomeQuadrant,
    OutcomeResult,
    PositionInterpretation,
    ProcessAssessment,
    ProcessResult,
    PublicPositionObservation,
    RecheckRule,
    RuleMode,
    ThesisClaim,
    classify_outcome_quadrant,
)
from aim.storage import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


def _seed_case(conn) -> None:
    conn.execute(
        "INSERT INTO evidence_snapshots"
        " (snapshot_id, market, symbol, as_of, collector_version)"
        " VALUES ('snap-1', 'US', 'MSFT', '2026-07-21T13:30:00Z', 'test-v1')"
    )
    conn.execute(
        "INSERT INTO evidence_items"
        " (evidence_id, snapshot_id, key, symbol, value_real, unit, observed_at,"
        "  source_type, source_name, source_ref, state, quality, freshness)"
        " VALUES ('ev-1', 'snap-1', 'financial.operating_margin', 'MSFT', 44.6, '%',"
        "  '2026-07-21T13:30:00Z', 'SEC_XBRL', 'SEC', 'acc-1', 'AVAILABLE',"
        "  'PRIMARY_STRUCTURED', 'CURRENT')"
    )
    conn.execute(
        "INSERT INTO decision_cases"
        " (case_id, user_id, market, symbol, company_name, status)"
        " VALUES ('case-1', 'local', 'US', 'MSFT', 'Microsoft', 'PROVISIONAL_LOCKED')"
    )
    conn.execute(
        "INSERT INTO decision_versions"
        " (version_id, case_id, version_no, phase, action, holding_state, horizon_bucket,"
        "  horizon_value, thesis_summary, confidence_self, evidence_snapshot_id)"
        " VALUES ('dv-1', 'case-1', 1, 'PROVISIONAL', 'WATCH', 'NOT_HELD', 'MONTHS',"
        "  12, '클라우드 성장을 확인한다', 60, 'snap-1')"
    )
    conn.commit()


def _seed_second_snapshot(conn) -> None:
    conn.execute(
        "INSERT INTO evidence_snapshots"
        " (snapshot_id, market, symbol, as_of, collector_version)"
        " VALUES ('snap-2', 'US', 'MSFT', '2026-07-22T13:30:00Z', 'test-v1')"
    )
    conn.execute(
        "INSERT INTO evidence_items"
        " (evidence_id, snapshot_id, key, symbol, value_real, unit, observed_at,"
        "  source_type, source_name, source_ref, state, quality, freshness)"
        " VALUES ('ev-2', 'snap-2', 'financial.operating_margin', 'MSFT', 43.1, '%',"
        "  '2026-07-22T13:30:00Z', 'SEC_XBRL', 'SEC', 'acc-2', 'AVAILABLE',"
        "  'PRIMARY_STRUCTURED', 'CURRENT')"
    )
    conn.commit()


def test_us_decision_migration_creates_core_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "decision_cases",
        "decision_versions",
        "evidence_snapshots",
        "evidence_items",
        "analysis_runs",
        "public_position_observations",
        "comparison_runs",
        "outcome_reviews",
    } <= tables
    assert conn.execute(
        "SELECT 1 FROM schema_migrations WHERE filename='012_us_decisioning.sql'"
    ).fetchone()


def test_us_schema_upgrades_database_at_migration_11(tmp_path):
    connection = db.connect(tmp_path / "upgrade.db")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        for sql_file in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
            if sql_file.name >= "012_us_decisioning.sql":
                continue
            connection.executescript(sql_file.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (filename) VALUES (?)", (sql_file.name,)
            )
        connection.commit()

        assert db.migrate(connection) == ["012_us_decisioning.sql"]
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_cases'"
        ).fetchone()
    finally:
        connection.close()


def test_decision_versions_are_immutable_and_versioned(conn):
    _seed_case(conn)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE decision_versions SET action='BUY_NEW' WHERE version_id='dv-1'")

    conn.execute(
        "INSERT INTO decision_versions"
        " (version_id, case_id, version_no, parent_version_id, phase, decision_change,"
        "  revision_reason, action, holding_state, horizon_bucket, horizon_value,"
        "  thesis_summary, confidence_self, evidence_snapshot_id)"
        " VALUES ('dv-2', 'case-1', 2, 'dv-1', 'FINAL', 'MAINTAINED',"
        "  '반론을 검토했지만 관망 조건을 유지한다', 'WATCH', 'NOT_HELD', 'MONTHS', 12,"
        "  '클라우드 성장을 확인한다', 55, 'snap-1')"
    )
    assert conn.execute(
        "SELECT parent_version_id FROM decision_versions WHERE version_id='dv-2'"
    ).fetchone()["parent_version_id"] == "dv-1"


def test_schema_rejects_non_blind_analysis(conn):
    _seed_case(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO analysis_runs"
            " (analysis_id, case_id, provisional_version_id, snapshot_id, analysis_type,"
            "  blind_to_user_conclusion, run_status, model_provider, model_name, prompt_version)"
            " VALUES ('an-1', 'case-1', 'dv-1', 'snap-1', 'INDEPENDENT', 0, 'PENDING',"
            "  'fake', 'fake-v1', 'prompt-v1')"
        )


def test_final_decision_must_keep_provisional_snapshot(conn):
    _seed_case(conn)
    _seed_second_snapshot(conn)
    with pytest.raises(sqlite3.IntegrityError, match="provisional evidence snapshot"):
        conn.execute(
            "INSERT INTO decision_versions"
            " (version_id, case_id, version_no, parent_version_id, phase, decision_change,"
            "  revision_reason, action, holding_state, horizon_bucket, horizon_value,"
            "  thesis_summary, evidence_snapshot_id)"
            " VALUES ('dv-2', 'case-1', 2, 'dv-1', 'FINAL', 'REVISED', '규모를 줄였다',"
            "  'WATCH', 'NOT_HELD', 'MONTHS', 12, '논지는 유지한다', 'snap-2')"
        )


def test_decision_cannot_cite_evidence_from_another_snapshot(conn):
    _seed_case(conn)
    _seed_second_snapshot(conn)
    with pytest.raises(sqlite3.IntegrityError, match="decision snapshot"):
        conn.execute(
            "INSERT INTO decision_evidence_refs (version_id, evidence_id, role)"
            " VALUES ('dv-1', 'ev-2', 'CONTEXT')"
        )


def _buy_input(**overrides) -> DecisionVersionInput:
    claim = ThesisClaim(
        claim_id="cl-1",
        kind=ClaimKind.FORECAST,
        text="클라우드 매출 성장이 이익 성장을 이끈다",
        importance=ClaimImportance.CORE,
        supporting_evidence_ids=("ev-1",),
    )
    rule = RecheckRule(
        rule_id="rr-1",
        mode=RuleMode.AUTOMATIC,
        metric_key="financial.operating_margin",
        operator=ComparisonOperator.LT,
        threshold=38,
        message="영업이익률이 38% 아래면 재검토한다",
        claim_id=claim.claim_id,
    )
    values = {
        "case_id": "case-1",
        "symbol": "MSFT",
        "phase": DecisionPhase.PROVISIONAL,
        "action": DecisionAction.BUY_NEW,
        "holding_state": HoldingState.NOT_HELD,
        "horizon": Horizon(HorizonBucket.MONTHS, 12, "2027-07-21"),
        "evidence_snapshot_id": "snap-1",
        "thesis_summary": "클라우드와 AI 수요가 이익 성장을 지속시킬 것으로 본다",
        "confidence_self": 68,
        "planned_capital_usd": 2000,
        "planned_portfolio_pct": 8,
        "max_loss_usd": 160,
        "entry_plan": {"method": "SPLIT", "tranches": 3},
        "claims": (claim,),
        "recheck_rules": (rule,),
    }
    values.update(overrides)
    return DecisionVersionInput(**values)


def test_blind_analysis_context_excludes_user_conclusion():
    decision = _buy_input()
    context = asdict(decision.to_blind_context())
    assert context["symbol"] == "MSFT"
    assert context["evidence_snapshot_id"] == "snap-1"
    assert {"action", "thesis_summary", "confidence_self"}.isdisjoint(context)


def test_buy_requires_risk_budget_and_entry_plan():
    with pytest.raises(ValueError, match="positive max loss"):
        _buy_input(max_loss_usd=None)
    with pytest.raises(ValueError, match="entry plan"):
        _buy_input(entry_plan={})


def test_analysis_gap_policy_and_evidence_boundary():
    verdict = AnalysisVerdict(
        stance=AnalysisStance.FAVORABLE,
        confidence=83,
        thesis="성장은 긍정적이지만 기업 KPI가 빠졌다",
        supporting_evidence_ids=("ev-1",),
        opposing_evidence_ids=("ev-2",),
        missing_required=("company_kpi.ai_revenue",),
    )
    normalized = verdict.enforce_missing_data_policy()
    assert normalized.stance is AnalysisStance.MIXED
    assert normalized.confidence == 40
    with pytest.raises(ValueError, match="outside snapshot"):
        normalized.validate_evidence_refs({"ev-1"})


def test_13f_observation_requires_all_limitations():
    with pytest.raises(ValueError, match="missing limitations"):
        PublicPositionObservation(
            observation_id="po-1",
            actor_id="actor-1",
            symbol="MSFT",
            form_type="13F-HR",
            report_period="2026-06-30",
            filed_at="2026-08-14",
            source_ref="sec-accession",
            interpretation=PositionInterpretation.DISCLOSED_LONG_INCREASED,
            limitations=("FILING_LAG",),
        )

    observation = PublicPositionObservation(
        observation_id="po-1",
        actor_id="actor-1",
        symbol="MSFT",
        form_type="13F-HR",
        report_period="2026-06-30",
        filed_at="2026-08-14",
        source_ref="sec-accession",
        interpretation=PositionInterpretation.DISCLOSED_LONG_INCREASED,
        limitations=(
            "QUARTER_END_SNAPSHOT",
            "FILING_LAG",
            "SHORTS_NOT_REPORTED",
            "HEDGES_UNKNOWN",
            "RATIONALE_UNKNOWN",
            "CURRENT_POSITION_UNKNOWN",
        ),
    )
    assert observation.interpretation is PositionInterpretation.DISCLOSED_LONG_INCREASED


def test_public_position_cannot_be_treated_as_same_conclusion():
    with pytest.raises(ValueError, match="cannot be converted"):
        ComparisonItem(
            subject_type=ComparisonSubject.PUBLIC_POSITION,
            subject_id="po-1",
            conclusion_alignment=Alignment.ALIGNED,
            thesis_alignment=Alignment.UNKNOWN,
            horizon_alignment=Alignment.UNKNOWN,
            behavior_alignment=Alignment.ALIGNED,
            reason="공개 보유 수량이 증가했다",
            reliability=ComparisonReliability.PRIMARY_PUBLIC_FACT,
        )


def test_process_and_outcome_are_classified_separately():
    assessment = ProcessAssessment(2, 2, 1, 2, 1, 1)
    assert assessment.total == 9
    process = assessment.result()
    assert process is ProcessResult.GOOD
    assert classify_outcome_quadrant(process, OutcomeResult.BAD) is (
        OutcomeQuadrant.GOOD_PROCESS_BAD_OUTCOME
    )
