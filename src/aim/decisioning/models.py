"""SOCRA US 판단 계약의 도메인 모델.

이 모듈은 기존 KR ``decision_cards``와 독립적이다. 특히 블라인드 분석용 DTO에는
사용자의 행동·논지·확신도를 넣을 수 없도록 타입 경계로 차단한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Mapping


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    PROVISIONAL_LOCKED = "PROVISIONAL_LOCKED"
    ANALYZING = "ANALYZING"
    COMPARISON_READY = "COMPARISON_READY"
    FINALIZED = "FINALIZED"
    DEFERRED = "DEFERRED"
    MONITORING = "MONITORING"
    REVIEW_DUE = "REVIEW_DUE"
    CLOSED = "CLOSED"


class DecisionPhase(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    RECHECK = "RECHECK"


class DecisionChange(StrEnum):
    MAINTAINED = "MAINTAINED"
    REVISED = "REVISED"
    DEFERRED = "DEFERRED"


class DecisionAction(StrEnum):
    BUY_NEW = "BUY_NEW"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    WATCH = "WATCH"
    DEFER = "DEFER"


class HoldingState(StrEnum):
    NOT_HELD = "NOT_HELD"
    HELD = "HELD"
    CLOSED = "CLOSED"


class HorizonBucket(StrEnum):
    DAYS = "DAYS"
    WEEKS = "WEEKS"
    MONTHS = "MONTHS"
    YEARS = "YEARS"


class ClaimKind(StrEnum):
    FACT = "FACT"
    ASSUMPTION = "ASSUMPTION"
    FORECAST = "FORECAST"


class ClaimImportance(StrEnum):
    CORE = "CORE"
    SECONDARY = "SECONDARY"


class ClaimStatus(StrEnum):
    TESTABLE = "TESTABLE"
    UNVERIFIABLE = "UNVERIFIABLE"
    RESOLVED = "RESOLVED"


class ScenarioKind(StrEnum):
    BEAR = "BEAR"
    BASE = "BASE"
    BULL = "BULL"


class RuleMode(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class ComparisonOperator(StrEnum):
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    EQ = "="
    NE = "!="
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    CHANGED = "CHANGED"


class MissingAction(StrEnum):
    ALERT_UNVERIFIABLE = "ALERT_UNVERIFIABLE"
    MANUAL_CHECK = "MANUAL_CHECK"
    IGNORE = "IGNORE"


class EvidenceState(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONFLICT = "CONFLICT"


class EvidenceFreshness(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class EvidenceQuality(StrEnum):
    PRIMARY_STRUCTURED = "PRIMARY_STRUCTURED"
    PRIMARY_EXTRACTED = "PRIMARY_EXTRACTED"
    OFFICIAL_UNSTRUCTURED = "OFFICIAL_UNSTRUCTURED"
    LICENSED = "LICENSED"
    DERIVED = "DERIVED"
    UNVERIFIED = "UNVERIFIED"


class AnalysisType(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    LENS = "LENS"


class AnalysisStance(StrEnum):
    FAVORABLE = "FAVORABLE"
    MIXED = "MIXED"
    UNFAVORABLE = "UNFAVORABLE"
    ABSTAIN = "ABSTAIN"


class Alignment(StrEnum):
    ALIGNED = "ALIGNED"
    PARTIAL = "PARTIAL"
    DIVERGED = "DIVERGED"
    UNKNOWN = "UNKNOWN"


class ComparisonSubject(StrEnum):
    INDEPENDENT_ANALYSIS = "INDEPENDENT_ANALYSIS"
    LENS_ANALYSIS = "LENS_ANALYSIS"
    PUBLIC_POSITION = "PUBLIC_POSITION"
    PUBLIC_STATEMENT = "PUBLIC_STATEMENT"


class ComparisonReliability(StrEnum):
    INDEPENDENT_MODEL = "INDEPENDENT_MODEL"
    SIMULATED_LENS = "SIMULATED_LENS"
    PRIMARY_PUBLIC_FACT = "PRIMARY_PUBLIC_FACT"
    SECONDARY_PUBLIC_REPORT = "SECONDARY_PUBLIC_REPORT"
    UNVERIFIED = "UNVERIFIED"


class PositionInterpretation(StrEnum):
    DISCLOSED_LONG_NEW = "DISCLOSED_LONG_NEW"
    DISCLOSED_LONG_INCREASED = "DISCLOSED_LONG_INCREASED"
    DISCLOSED_LONG_DECREASED = "DISCLOSED_LONG_DECREASED"
    DISCLOSED_LONG_UNCHANGED = "DISCLOSED_LONG_UNCHANGED"
    DISCLOSED_LONG_EXITED = "DISCLOSED_LONG_EXITED"
    PUT_HELD = "PUT_HELD"
    CALL_HELD = "CALL_HELD"
    UNKNOWN = "UNKNOWN"


class ProcessResult(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"
    PENDING = "PENDING"


class OutcomeResult(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"
    NEUTRAL = "NEUTRAL"
    PENDING = "PENDING"


class OutcomeQuadrant(StrEnum):
    GOOD_PROCESS_GOOD_OUTCOME = "GOOD_PROCESS_GOOD_OUTCOME"
    GOOD_PROCESS_BAD_OUTCOME = "GOOD_PROCESS_BAD_OUTCOME"
    BAD_PROCESS_GOOD_OUTCOME = "BAD_PROCESS_GOOD_OUTCOME"
    BAD_PROCESS_BAD_OUTCOME = "BAD_PROCESS_BAD_OUTCOME"


@dataclass(frozen=True)
class Horizon:
    bucket: HorizonBucket
    value: int
    review_at: str | None = None

    def __post_init__(self) -> None:
        if self.value < 1:
            raise ValueError("horizon value must be positive")


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    snapshot_id: str
    key: str
    symbol: str
    value: float | str | None
    unit: str
    observed_at: str
    source_type: str
    source_name: str
    source_ref: str
    state: EvidenceState
    quality: EvidenceQuality
    freshness: EvidenceFreshness
    currency: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    announced_at: str | None = None
    scope: str = "consolidated"
    formula: str | None = None
    formula_version: str | None = None
    raw_fact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence_id", self.evidence_id),
            ("snapshot_id", self.snapshot_id),
            ("key", self.key),
            ("symbol", self.symbol),
            ("observed_at", self.observed_at),
            ("source_ref", self.source_ref),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if self.state is EvidenceState.AVAILABLE and self.value is None:
            raise ValueError("available evidence must have a value")


@dataclass(frozen=True)
class ThesisClaim:
    claim_id: str
    kind: ClaimKind
    text: str
    importance: ClaimImportance = ClaimImportance.CORE
    status: ClaimStatus = ClaimStatus.TESTABLE
    supporting_evidence_ids: tuple[str, ...] = ()
    challenging_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim_id.strip() or not self.text.strip():
            raise ValueError("claim id and text are required")
        if (
            self.importance is ClaimImportance.CORE
            and self.status is ClaimStatus.TESTABLE
            and not self.supporting_evidence_ids
        ):
            raise ValueError("a testable core claim needs supporting evidence")


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    kind: ScenarioKind
    assumptions: tuple[Mapping[str, Any], ...]
    estimated_value: float | None = None
    currency: str = "USD"
    rationale: str = ""
    formula_version: str | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario id is required")
        if self.estimated_value is not None and (
            not self.assumptions or not self.rationale.strip()
        ):
            raise ValueError("estimated value needs assumptions and rationale")


@dataclass(frozen=True)
class RecheckRule:
    rule_id: str
    mode: RuleMode
    message: str
    metric_key: str | None = None
    operator: ComparisonOperator | None = None
    threshold: float | None = None
    unit: str = ""
    evaluation_window: str | None = None
    consecutive_periods: int = 1
    freshness_max_days: int | None = None
    on_missing: MissingAction = MissingAction.ALERT_UNVERIFIABLE
    claim_id: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.message.strip():
            raise ValueError("rule id and message are required")
        if self.consecutive_periods < 1:
            raise ValueError("consecutive periods must be positive")
        if self.freshness_max_days is not None and self.freshness_max_days < 1:
            raise ValueError("freshness limit must be positive")
        if self.mode is RuleMode.AUTOMATIC:
            if not self.metric_key or self.operator is None:
                raise ValueError("automatic rule needs metric and operator")
            if self.operator is not ComparisonOperator.CHANGED and self.threshold is None:
                raise ValueError("automatic comparison needs a threshold")


@dataclass(frozen=True)
class BlindAnalysisContext:
    """LLM에 전달 가능한 최소 컨텍스트.

    고의로 ``action``, ``thesis_summary``, ``confidence_self`` 필드를 제공하지 않는다.
    분석 실행 식별자는 저장 계층이 별도로 보유하며 프롬프트 DTO에는 포함하지 않는다.
    """

    market: str
    symbol: str
    holding_state: HoldingState
    horizon: Horizon
    max_loss_usd: float | None
    evidence_snapshot_id: str


@dataclass(frozen=True)
class DecisionVersionInput:
    case_id: str
    symbol: str
    phase: DecisionPhase
    action: DecisionAction
    holding_state: HoldingState
    horizon: Horizon
    evidence_snapshot_id: str
    thesis_summary: str = ""
    confidence_self: int | None = None
    parent_version_id: str | None = None
    decision_change: DecisionChange | None = None
    revision_reason: str | None = None
    planned_capital_usd: float | None = None
    planned_portfolio_pct: float | None = None
    max_loss_usd: float | None = None
    entry_plan: Mapping[str, Any] = field(default_factory=dict)
    claims: tuple[ThesisClaim, ...] = ()
    scenarios: tuple[Scenario, ...] = ()
    recheck_rules: tuple[RecheckRule, ...] = ()
    research_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.case_id.strip()
            or not self.symbol.strip()
            or not self.evidence_snapshot_id.strip()
        ):
            raise ValueError("case, symbol, and evidence snapshot are required")
        if self.confidence_self is not None and not 0 <= self.confidence_self <= 100:
            raise ValueError("confidence must be between 0 and 100")
        if self.planned_capital_usd is not None and self.planned_capital_usd < 0:
            raise ValueError("planned capital cannot be negative")
        if self.planned_portfolio_pct is not None and not 0 <= self.planned_portfolio_pct <= 100:
            raise ValueError("portfolio percentage must be between 0 and 100")
        if self.max_loss_usd is not None and self.max_loss_usd < 0:
            raise ValueError("max loss cannot be negative")

        if self.phase is DecisionPhase.PROVISIONAL:
            if self.parent_version_id is not None or self.decision_change is not None:
                raise ValueError("provisional version cannot have parent or decision change")
        elif (
            not self.parent_version_id
            or self.decision_change is None
            or not (self.revision_reason or "").strip()
        ):
            raise ValueError("final/recheck version needs parent, change type, and reason")

        if (
            self.action is DecisionAction.BUY_NEW
            and self.holding_state is not HoldingState.NOT_HELD
        ):
            raise ValueError("new buy requires not-held state")
        if self.action in {
            DecisionAction.ADD,
            DecisionAction.HOLD,
            DecisionAction.REDUCE,
            DecisionAction.EXIT,
        } and self.holding_state is not HoldingState.HELD:
            raise ValueError(f"{self.action} requires held state")

        if self.action is DecisionAction.DEFER:
            if not self.research_gaps:
                raise ValueError("deferred decision needs research gaps")
            return

        if not self.thesis_summary.strip():
            raise ValueError("non-deferred decision needs a thesis")

        if self.action in {DecisionAction.BUY_NEW, DecisionAction.ADD}:
            if not (
                (self.planned_capital_usd is not None and self.planned_capital_usd > 0)
                or (self.planned_portfolio_pct is not None and self.planned_portfolio_pct > 0)
            ):
                raise ValueError("buy/add needs planned capital or portfolio percentage")
            if self.max_loss_usd is None or self.max_loss_usd <= 0:
                raise ValueError("buy/add needs a positive max loss")
            if not self.entry_plan:
                raise ValueError("buy/add needs an entry plan")

        if self.action in {
            DecisionAction.BUY_NEW,
            DecisionAction.ADD,
            DecisionAction.HOLD,
            DecisionAction.WATCH,
        }:
            if not any(c.importance is ClaimImportance.CORE for c in self.claims):
                raise ValueError("active thesis needs at least one core claim")
            if not self.recheck_rules:
                raise ValueError("active thesis needs at least one recheck rule")

    def to_blind_context(self, market: str = "US") -> BlindAnalysisContext:
        if market != "US":
            raise ValueError("US decision contract only supports market=US")
        return BlindAnalysisContext(
            market=market,
            symbol=self.symbol,
            holding_state=self.holding_state,
            horizon=self.horizon,
            max_loss_usd=self.max_loss_usd,
            evidence_snapshot_id=self.evidence_snapshot_id,
        )


@dataclass(frozen=True)
class AnalysisVerdict:
    stance: AnalysisStance
    confidence: int
    thesis: str
    supporting_evidence_ids: tuple[str, ...] = ()
    opposing_evidence_ids: tuple[str, ...] = ()
    strongest_counterargument: str = ""
    missing_required: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError("analysis confidence must be between 0 and 100")
        if not self.thesis.strip():
            raise ValueError("analysis thesis is required")

    def enforce_missing_data_policy(self) -> AnalysisVerdict:
        """근거 공백이 있는데 긍정 판정을 내리는 권위 편향을 차단한다."""
        if self.missing_required and self.stance is AnalysisStance.FAVORABLE:
            return replace(self, stance=AnalysisStance.MIXED, confidence=min(self.confidence, 40))
        return self

    def validate_evidence_refs(self, allowed_ids: set[str]) -> None:
        cited = set(self.supporting_evidence_ids) | set(self.opposing_evidence_ids)
        unknown = cited - allowed_ids
        if unknown:
            raise ValueError(f"analysis cited evidence outside snapshot: {sorted(unknown)}")


_REQUIRED_13F_LIMITATIONS = {
    "QUARTER_END_SNAPSHOT",
    "FILING_LAG",
    "SHORTS_NOT_REPORTED",
    "HEDGES_UNKNOWN",
    "RATIONALE_UNKNOWN",
    "CURRENT_POSITION_UNKNOWN",
}


@dataclass(frozen=True)
class PublicPositionObservation:
    observation_id: str
    actor_id: str
    symbol: str
    form_type: str
    report_period: str
    filed_at: str
    source_ref: str
    interpretation: PositionInterpretation
    limitations: tuple[str, ...]
    shares_disclosed: float | None = None
    market_value_usd: float | None = None
    change_vs_prior_shares_pct: float | None = None
    put_call: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("observation_id", self.observation_id),
            ("actor_id", self.actor_id),
            ("symbol", self.symbol),
            ("form_type", self.form_type),
            ("source_ref", self.source_ref),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if self.form_type.startswith("13F"):
            missing = _REQUIRED_13F_LIMITATIONS - set(self.limitations)
            if missing:
                raise ValueError(f"13F observation is missing limitations: {sorted(missing)}")
        if self.put_call not in (None, "PUT", "CALL"):
            raise ValueError("put_call must be PUT, CALL, or None")


@dataclass(frozen=True)
class ComparisonItem:
    subject_type: ComparisonSubject
    subject_id: str
    conclusion_alignment: Alignment
    thesis_alignment: Alignment
    horizon_alignment: Alignment
    behavior_alignment: Alignment
    reason: str
    reliability: ComparisonReliability
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.reason.strip():
            raise ValueError("comparison subject and reason are required")
        if (
            self.subject_type is ComparisonSubject.PUBLIC_POSITION
            and self.conclusion_alignment is not Alignment.UNKNOWN
        ):
            raise ValueError("public position cannot be converted into conclusion alignment")


@dataclass(frozen=True)
class ProcessAssessment:
    business_understanding: int
    evidence_quality: int
    valuation_expectations: int
    falsifiability: int
    risk_plan: int
    contrary_view: int

    def __post_init__(self) -> None:
        for name, score in self.as_dict().items():
            if score not in (0, 1, 2):
                raise ValueError(f"{name} score must be 0, 1, or 2")

    def as_dict(self) -> dict[str, int]:
        return {
            "business_understanding": self.business_understanding,
            "evidence_quality": self.evidence_quality,
            "valuation_expectations": self.valuation_expectations,
            "falsifiability": self.falsifiability,
            "risk_plan": self.risk_plan,
            "contrary_view": self.contrary_view,
        }

    @property
    def total(self) -> int:
        return sum(self.as_dict().values())

    def result(self, good_threshold: int = 8) -> ProcessResult:
        if not 1 <= good_threshold <= 12:
            raise ValueError("good process threshold must be between 1 and 12")
        return ProcessResult.GOOD if self.total >= good_threshold else ProcessResult.BAD


def classify_outcome_quadrant(
    process_result: ProcessResult, outcome_result: OutcomeResult
) -> OutcomeQuadrant:
    """과정과 결과가 모두 확정된 경우에만 사분면을 만든다."""
    if process_result not in (ProcessResult.GOOD, ProcessResult.BAD):
        raise ValueError("process result must be GOOD or BAD")
    if outcome_result not in (OutcomeResult.GOOD, OutcomeResult.BAD):
        raise ValueError("outcome result must be GOOD or BAD")
    return OutcomeQuadrant(
        f"{process_result.value}_PROCESS_{outcome_result.value}_OUTCOME"
    )
