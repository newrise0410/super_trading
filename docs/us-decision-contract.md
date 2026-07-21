# SOCRA US Decision Contract v0.1

> 상태: 제품 방향 확정 후 구현 전 설계안  
> 대상: 미국 주식에 관심 있는 대학생·사회초년생 초보 투자자  
> 목적: 사용자가 자기 판단을 먼저 만들고, 독립 분석·투자 철학 렌즈·실제 공개 행동과 비교한 뒤 최종 결정을 내리고 사후 검증한다.

## 1. 제품 계약

소크라는 종목 추천기나 교육 커리큘럼이 아니다. 실제 매매를 고민하는 사용자가 다음 순서를 지키도록 돕는 판단 어시스턴트다.

1. 사용자가 데이터와 질문을 바탕으로 잠정 결론을 만든다.
2. 잠정 결론을 잠근 뒤 같은 시점의 증거 스냅샷을 동결한다.
3. 독립 AI와 투자 철학 렌즈는 사용자의 결론을 보지 않고 각각 판단한다.
4. 실제 투자자·기관의 공개 행동과 공식 발언은 별도 사실 레이어에서 수집한다.
5. 비교기는 다수결 없이 일치점·불일치점·가장 강한 반론·데이터 공백을 정리한다.
6. 사용자는 결론을 유지·수정·보류하고 이유를 남긴다.
7. 정해진 시점에 판단 과정과 결과를 분리해 평가한다.

### 1.1 비타협 원칙

- 사용자 결론이 패널보다 먼저다.
- 독립 분석은 사용자 `action`, `thesis`, `confidence`를 입력받지 않는다.
- 각 렌즈는 사용자 판단과 다른 렌즈의 판단을 보지 않는다.
- 유명 투자자 렌즈는 공개 철학의 AI 적용이며 실제 인물의 의견으로 표현하지 않는다.
- 13F·13D/G·Form 4·공식 발언은 공개된 사실만 보여주고 숨은 의도나 현재 포지션을 추정하지 않는다.
- 관점 수를 세어 `BUY 4 / HOLD 2` 같은 다수결을 만들지 않는다.
- 데이터가 부족한 분석은 `ABSTAIN`할 수 있어야 한다.
- 사후 수익률이 좋았다는 이유만으로 좋은 판단으로 평가하지 않는다.
- 모든 수치와 주장은 증거 키와 출처로 재현할 수 있어야 한다.

## 2. 사용자 흐름과 상태

```text
DRAFT
  -> PROVISIONAL_LOCKED
  -> ANALYZING
  -> COMPARISON_READY
  -> FINALIZED | DEFERRED
  -> MONITORING
  -> REVIEW_DUE
  -> CLOSED
```

| 상태 | 의미 | 허용 동작 |
|---|---|---|
| `DRAFT` | 대화 중인 카드 | 자유 수정 |
| `PROVISIONAL_LOCKED` | 사용자가 패널 전 잠정 결론 확정 | 불변 버전 생성 |
| `ANALYZING` | 독립 AI·렌즈 분석 중 | 사용자 결론 비공개 유지 |
| `COMPARISON_READY` | 모든 가능한 비교 자료 준비 | 비교 리포트 열람 |
| `FINALIZED` | 사용자가 유지 또는 수정한 최종 결론 | 감시 시작 |
| `DEFERRED` | 근거 부족 등으로 판단 보류 | 조사 과제만 유지 |
| `MONITORING` | 채택 근거와 반증 조건 감시 | 재점검 버전 생성 |
| `REVIEW_DUE` | 사용자가 정한 투자기간 또는 정기 검토일 도달 | 과정·결과 평가 |
| `CLOSED` | 포지션 종료 또는 판단 종료 | 이력 보존 |

상태를 되돌리지 않는다. 수정은 항상 새 `decision_version`을 만든다.

## 3. 공통 열거형

### 3.1 사용자 행동

```text
BUY_NEW   신규 매수
ADD       추가 매수
HOLD      보유 유지
REDUCE    일부 축소
EXIT      전량 종료
WATCH     조건을 기다리며 관찰
DEFER     정보 부족 등으로 판단 보류
```

### 3.2 분석 관점의 판단

독립 분석은 사용자 계좌 행동을 대신 결정하지 않는다. 기업·가격 매력도만 다음으로 표현한다.

```text
FAVORABLE    현재 증거와 기간에서 긍정 논거가 우세
MIXED        긍정·부정 논거가 비슷하거나 가격 조건부
UNFAVORABLE  현재 증거와 기간에서 부정 논거가 우세
ABSTAIN      핵심 데이터 부족 또는 렌즈 적용 불가
```

### 3.3 비교 상태

```text
ALIGNED      결론·핵심 논지·기간이 실질적으로 일치
PARTIAL      일부만 일치하거나 결론은 같지만 이유가 다름
DIVERGED     핵심 결론 또는 핵심 논지가 반대
UNKNOWN      비교할 근거가 없거나 기간이 다름
```

## 4. 증거 계약

판단의 모든 입력은 해석 이전의 중립적인 `EvidenceItem`으로 저장한다. 기존 `bullish/bearish` 방향 태그는 사용하지 않는다.

```json
{
  "evidence_id": "ev_...",
  "snapshot_id": "snap_...",
  "key": "financial.operating_margin",
  "symbol": "MSFT",
  "value": 44.6,
  "value_text": null,
  "unit": "percent",
  "currency": null,
  "period_start": "2025-07-01",
  "period_end": "2025-09-30",
  "announced_at": "2025-10-29T16:05:00-04:00",
  "observed_at": "2025-10-29T16:06:10-04:00",
  "source_type": "SEC_XBRL",
  "source_name": "SEC",
  "source_ref": "accession number or canonical URL",
  "scope": "consolidated",
  "state": "AVAILABLE",
  "quality": "PRIMARY_STRUCTURED",
  "freshness": "CURRENT",
  "formula": "operating_income / revenue",
  "raw_fact_refs": ["us-gaap:OperatingIncomeLoss", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
}
```

### 4.1 필수 상태

| 필드 | 값 |
|---|---|
| `state` | `AVAILABLE`, `MISSING`, `NOT_APPLICABLE`, `CONFLICT` |
| `freshness` | `CURRENT`, `STALE`, `UNKNOWN` |
| `quality` | `PRIMARY_STRUCTURED`, `PRIMARY_EXTRACTED`, `OFFICIAL_UNSTRUCTURED`, `LICENSED`, `DERIVED`, `UNVERIFIED` |

`MISSING`과 `NOT_APPLICABLE`을 구분한다. 출처 충돌은 임의로 하나를 선택하지 않고 `CONFLICT`로 남긴다.

### 4.2 증거 스냅샷

```json
{
  "snapshot_id": "snap_...",
  "market": "US",
  "symbol": "MSFT",
  "as_of": "2025-10-30T09:30:00-04:00",
  "created_at": "2025-10-30T09:31:12-04:00",
  "collector_version": "us-evidence-v1",
  "completeness": {
    "business": "COMPLETE",
    "financial": "COMPLETE",
    "valuation": "PARTIAL",
    "risk": "COMPLETE",
    "market": "COMPLETE"
  },
  "missing_required": ["valuation.peer_multiple"],
  "evidence_ids": ["ev_1", "ev_2"]
}
```

독립 분석·렌즈 분석·비교 리포트는 모두 같은 `snapshot_id`를 참조한다.

## 5. 판단 케이스와 불변 버전

### 5.1 DecisionCase

한 사용자가 한 종목에 대해 이어가는 장기 판단 묶음이다.

```json
{
  "case_id": "case_...",
  "user_id": "user_...",
  "market": "US",
  "symbol": "MSFT",
  "company_name": "Microsoft Corporation",
  "status": "COMPARISON_READY",
  "opened_at": "2025-10-30T09:00:00-04:00",
  "closed_at": null
}
```

### 5.2 DecisionVersion

잠정 결론, 패널 후 최종 결론, 재점검 결론을 모두 불변 버전으로 저장한다.

```json
{
  "version_id": "dv_...",
  "case_id": "case_...",
  "parent_version_id": null,
  "phase": "PROVISIONAL",
  "revision_reason": null,
  "action": "BUY_NEW",
  "holding_state": "NOT_HELD",
  "horizon": {
    "bucket": "MONTHS",
    "target_months": 12,
    "review_at": "2026-01-30"
  },
  "thesis_summary": "클라우드와 AI 수요가 이익 성장을 지속시킬 것으로 본다.",
  "confidence_self": 68,
  "planned_capital_usd": 2000,
  "planned_portfolio_pct": 8,
  "max_loss_usd": 160,
  "entry_plan": {
    "method": "SPLIT",
    "tranches": 3,
    "condition": "현재가부터 실적 확인 전까지 세 번 분할"
  },
  "scenario_ids": ["sc_bear", "sc_base", "sc_bull"],
  "claim_ids": ["cl_1", "cl_2"],
  "recheck_rule_ids": ["rr_1", "rr_2"],
  "evidence_snapshot_id": "snap_...",
  "created_at": "2025-10-30T09:40:00-04:00"
}
```

### 5.3 단계별 필수 필드

| 행동 | 필수 필드 |
|---|---|
| `BUY_NEW`, `ADD` | 기간, 논지, 핵심 주장, 반증 조건, 투자금 또는 비중, 최대 허용손실, 진입 계획 |
| `HOLD` | 기간, 보유 이유, 반증 조건, 다음 검토일 |
| `REDUCE`, `EXIT` | 축소·종료 이유, 기존 논지 상태, 실행 조건 |
| `WATCH` | 기다리는 조건, 유효기간, 다음 검토일 |
| `DEFER` | 부족한 정보, 조사 과제 |

핵심 필드가 비어 있으면 시스템이 임의로 채우지 않는다. `DEFER`를 정상 결론으로 제시한다.

## 6. 주장과 근거 연결

### 6.1 ThesisClaim

```json
{
  "claim_id": "cl_...",
  "version_id": "dv_...",
  "kind": "FORECAST",
  "text": "AI 제품 매출이 전체 영업이익 성장을 이끌 것이다.",
  "importance": "CORE",
  "supporting_evidence_ids": ["ev_segment_ai_growth"],
  "challenging_evidence_ids": ["ev_capex_growth", "ev_margin_change"],
  "status": "TESTABLE"
}
```

`kind`는 `FACT`, `ASSUMPTION`, `FORECAST` 중 하나다. 사용자가 사실과 전망을 섞으면 저장 전에 분리 질문을 한다.

핵심 논지에는 최소 하나의 `supporting_evidence_id`와 하나의 반증 조건이 있어야 한다. 채택하지 않은 증거는 카드 감시 대상이 아니다.

### 6.2 Scenario

```json
{
  "scenario_id": "sc_base",
  "version_id": "dv_...",
  "kind": "BASE",
  "assumptions": [
    {"metric_key": "financial.revenue_growth", "operator": ">=", "value": 12, "unit": "percent"},
    {"metric_key": "financial.operating_margin", "operator": ">=", "value": 40, "unit": "percent"}
  ],
  "estimated_value": 430,
  "currency": "USD",
  "rationale": "사용자가 선택한 가정과 계산식",
  "formula_version": "scenario-v1"
}
```

`BEAR`, `BASE`, `BULL` 세 종류를 지원한다. 목표가격은 선택 필드이며 가정과 계산식 없이 단독 저장하지 않는다.

### 6.3 RecheckRule

```json
{
  "rule_id": "rr_...",
  "version_id": "dv_...",
  "claim_id": "cl_...",
  "metric_key": "financial.operating_margin",
  "operator": "<",
  "threshold": 38,
  "unit": "percent",
  "evaluation_window": "QUARTER",
  "consecutive_periods": 2,
  "freshness_max_days": 120,
  "on_missing": "ALERT_UNVERIFIABLE",
  "message": "영업이익률이 두 분기 연속 38% 아래면 핵심 논지를 재검토한다."
}
```

자연어 조건은 저장 전에 구조화한다. 구조화할 수 없는 조건은 `MANUAL_CHECK`로 명시하며 자동 감시 가능하다고 약속하지 않는다.

## 7. 블라인드 독립 분석

### 7.1 입력 경계

독립 분석과 렌즈 분석에 허용되는 입력:

- 종목·시장
- 사용자 보유 여부
- 투자기간
- 최대 허용손실 같은 위험 제약
- 동결된 증거 스냅샷

금지되는 입력:

- 사용자 `action`
- 사용자 논지와 시나리오
- 사용자 확신도
- 다른 분석자의 판단
- 실제 기관 행동과 유명 투자자 발언

입력 DTO를 별도로 만들어 금지 필드가 프롬프트에 들어가지 않도록 코드 수준에서 차단한다.

### 7.2 AnalysisRun

```json
{
  "analysis_id": "an_...",
  "case_id": "case_...",
  "provisional_version_id": "dv_...",
  "snapshot_id": "snap_...",
  "analysis_type": "INDEPENDENT",
  "perspective_id": null,
  "blind_to_user_conclusion": true,
  "model_provider": "...",
  "model_name": "...",
  "prompt_version": "independent-us-v1",
  "stance": "MIXED",
  "confidence": 62,
  "horizon_months": 12,
  "thesis": "사업 성장성은 확인되지만 현재 가격의 기대 수준이 높다.",
  "supporting_evidence_ids": ["ev_1"],
  "opposing_evidence_ids": ["ev_2", "ev_3"],
  "strongest_counterargument": "마진 둔화가 성장 가정을 훼손할 수 있다.",
  "missing_required": ["company_kpi.ai_revenue"],
  "created_at": "2025-10-30T09:45:00-04:00"
}
```

검증 규칙:

- `stance` enum과 `confidence` 범위를 검증한다.
- 인용한 증거 ID가 해당 스냅샷에 없으면 분석 전체를 실패 처리한다.
- `missing_required`에 핵심 데이터가 있으면 `FAVORABLE`을 허용하지 않고 `ABSTAIN` 또는 `MIXED`로 강등한다.
- 숫자가 증거에 없으면 응답을 폐기한다.

## 8. 투자 철학 렌즈

### 8.1 PerspectiveDefinition

```json
{
  "perspective_id": "lens_buffett_quality",
  "display_name": "버핏의 공개 원칙 기반 품질·가치 렌즈",
  "kind": "PHILOSOPHY_LENS",
  "applies_to": ["durable_business", "positive_cash_flow"],
  "required_metric_keys": [
    "financial.roic",
    "financial.free_cash_flow",
    "financial.net_debt",
    "valuation.owner_earnings_yield"
  ],
  "methodology_summary": "이해 가능한 사업, 지속 가능한 경쟁력, 자본배분, 합리적 가격을 점검한다.",
  "methodology_source_refs": ["official shareholder letters or primary published sources"],
  "prompt_version": "lens-buffett-v1",
  "disclaimer": "공개 원칙을 AI가 적용한 결과이며 실제 인물의 의견이 아니다."
}
```

초기 렌즈는 네 개로 제한한다.

| 렌즈 | 핵심 질문 |
|---|---|
| 품질·가치 | 사업의 지속성, 현금창출, 자본배분, 가격 |
| GARP | 이해 가능한 성장, 성장의 질, 성장 대비 가격 |
| 사이클·하방 | 시장 기대, 사이클 위치, 안전마진, 손실 비대칭 |
| 포렌식·숏 | 회계 품질, 희석, 경영진 주장, 숨은 취약점 |

유명 인물 이름은 사용자의 이해를 돕는 라벨일 뿐 프롬프트에서 “너는 해당 인물이다”라고 사칭하지 않는다. 렌즈 결과는 `AnalysisRun.analysis_type=LENS`로 저장한다.

## 9. 실제 공개 투자자·기관 행동

철학 렌즈와 공개 행동은 UI와 저장 구조 모두에서 분리한다.

### 9.1 PublicActor

```json
{
  "actor_id": "actor_...",
  "display_name": "Example Capital",
  "actor_type": "INSTITUTIONAL_MANAGER",
  "cik": "0000000000",
  "official_site": "https://...",
  "identity_status": "VERIFIED"
}
```

### 9.2 PublicPositionObservation

```json
{
  "observation_id": "po_...",
  "actor_id": "actor_...",
  "symbol": "MSFT",
  "form_type": "13F-HR",
  "report_period": "2025-09-30",
  "filed_at": "2025-11-14T17:20:00-05:00",
  "shares_disclosed": 1200000,
  "market_value_usd": 516000000,
  "change_vs_prior_shares_pct": 12.4,
  "put_call": null,
  "source_ref": "SEC accession number",
  "interpretation": "DISCLOSED_LONG_INCREASED",
  "limitations": [
    "QUARTER_END_SNAPSHOT",
    "FILING_LAG",
    "SHORTS_NOT_REPORTED",
    "HEDGES_UNKNOWN",
    "RATIONALE_UNKNOWN",
    "CURRENT_POSITION_UNKNOWN"
  ]
}
```

표현 규칙:

- `매수했다` 대신 `분기 말 공개 보유 수량이 전분기보다 증가했다`고 쓴다.
- 보유 사실을 `BUY` 표로 변환하지 않는다.
- `filed_at - report_period` 시차를 항상 표시한다.
- 13F는 공매도·전체 헤지·투자 이유·현재 포지션을 알려주지 않는다고 함께 표시한다.
- 13D/G는 5% 이상 주요 지분 공시라는 맥락과 목적 관련 원문을 함께 제시한다.
- Form 4는 공개시장 매수·매도, 보상, 옵션 행사, 세금 원천징수, 10b5-1 계획 여부를 구분한다.

### 9.3 PublicStatementObservation

```json
{
  "statement_id": "ps_...",
  "actor_id": "actor_...",
  "symbol": "MSFT",
  "published_at": "2025-09-15T10:00:00-04:00",
  "source_type": "OFFICIAL_LETTER",
  "source_ref": "canonical official URL",
  "summary_ko": "공식 발언의 한국어 요약",
  "short_excerpt": "저작권 허용 범위의 짧은 원문",
  "stance": "POSITIVE",
  "horizon_text": "장기",
  "thesis_tags": ["cloud", "capital_allocation"],
  "verification": "PRIMARY_SOURCE_VERIFIED",
  "valid_until": null
}
```

제3자 기사만 존재하면 실제 결론으로 단정하지 않는다. 공식 서한·공식 인터뷰·원본 영상 또는 전사본을 우선한다.

## 10. 비교 리포트

비교기는 모든 독립 분석이 끝난 뒤에만 실행한다. 비교기는 새로운 종목 판단을 내리는 모델이 아니라 차이를 정리하는 모델이다.

### 10.1 ComparisonRun

```json
{
  "comparison_id": "cmp_...",
  "case_id": "case_...",
  "provisional_version_id": "dv_...",
  "snapshot_id": "snap_...",
  "analysis_ids": ["an_independent", "an_lens_1", "an_lens_2"],
  "public_observation_ids": ["po_1", "ps_1"],
  "user_vs_independent": "DIVERGED",
  "strongest_agreement": "사업 성장성 자체는 여러 관점이 인정했다.",
  "strongest_challenge": "사용자는 성장에 집중했지만 독립 분석은 현재 가격이 요구하는 기대와 마진 둔화를 가장 큰 위험으로 봤다.",
  "same_action_different_reason": [],
  "unresolved_questions": ["AI 관련 매출을 직접 확인할 기업 KPI가 없다."],
  "public_behavior_summary": "최근 공개된 기관 행동은 혼재하며 현재 결론을 확인할 수 없다.",
  "generated_at": "2025-10-30T09:50:00-04:00",
  "comparison_version": "comparison-v1"
}
```

### 10.2 ComparisonItem

각 분석·렌즈·공개 행동을 사용자 판단과 개별 비교한다.

```json
{
  "comparison_item_id": "ci_...",
  "comparison_id": "cmp_...",
  "subject_type": "LENS_ANALYSIS",
  "subject_id": "an_lens_1",
  "conclusion_alignment": "PARTIAL",
  "thesis_alignment": "ALIGNED",
  "horizon_alignment": "UNKNOWN",
  "behavior_alignment": "UNKNOWN",
  "reason": "성장 논지는 같지만 해당 렌즈는 현재 가격 판단에 필요한 데이터 부족으로 기권했다.",
  "reliability": "SIMULATED_LENS",
  "limitations": ["NOT_ACTUAL_PERSON_OPINION"]
}
```

공개 포지션에는 `conclusion_alignment`를 기본 `UNKNOWN`으로 둔다. 공개 행동이 사용자 행동과 비슷해 보여도 `behavior_alignment`만 평가한다.

### 10.3 화면 출력 순서

1. 나의 잠정 결론
2. 독립 AI 분석
3. 투자 철학별 일치·불일치 쟁점
4. 실제 공개 행동과 자료 시차
5. 가장 강한 찬성 논거
6. 가장 강한 반대 논거
7. 아무도 답하지 못한 데이터 공백
8. 유지·수정·보류 선택

합의율, 승자, 평균 확신도, BUY 표 수는 표시하지 않는다.

## 11. 최종 결정

비교 리포트를 본 뒤 새 `DecisionVersion.phase=FINAL`을 만든다.

```json
{
  "version_id": "dv_final_...",
  "case_id": "case_...",
  "parent_version_id": "dv_provisional_...",
  "phase": "FINAL",
  "decision_change": "REVISED",
  "revision_reason": "성장 논지는 유지하지만 가격 위험을 반영해 최초 계획보다 투자 규모를 절반으로 줄였다.",
  "action": "BUY_NEW",
  "confidence_self": 54,
  "influenced_by": [
    {"subject_type": "INDEPENDENT_ANALYSIS", "subject_id": "an_independent", "influence": "VALUATION_RISK"}
  ],
  "created_at": "2025-10-30T09:55:00-04:00"
}
```

`decision_change`는 `MAINTAINED`, `REVISED`, `DEFERRED` 중 하나다. 수정 이유를 기록하지 않으면 최종화할 수 없다. 유지한 경우에도 가장 강한 반론을 왜 받아들이지 않았는지 한 문장을 받는다.

## 12. 사후 평가

판단 과정과 시장 결과를 별도 축으로 평가한다.

### 12.1 ProcessAssessment

각 항목 0~2점, 총 12점이다.

| 항목 | 0점 | 1점 | 2점 |
|---|---|---|---|
| 사업 이해 | 근거 없음 | 단편적 | 핵심 수익원·변화 설명 |
| 근거 품질 | 출처 없음 | 일부 출처 | 1차 자료와 시점 명확 |
| 가치·기대 | 고려 안 함 | 배수만 언급 | 가격이 요구하는 가정 검토 |
| 반증 가능성 | 없음 | 모호함 | 구조화된 반증 조건 |
| 위험 계획 | 없음 | 손절만 있음 | 손실 예산·비중·실행 계획 |
| 반대 논거 | 무시 | 읽기만 함 | 반론을 반영하거나 이유 있게 기각 |

점수는 수익률을 입력으로 사용하지 않는다.

### 12.2 OutcomeReview

```json
{
  "review_id": "rev_...",
  "case_id": "case_...",
  "final_version_id": "dv_final_...",
  "review_type": "HORIZON_END",
  "reviewed_at": "2026-10-30T16:00:00-04:00",
  "evaluation_start": "2025-10-30",
  "evaluation_end": "2026-10-30",
  "action_at_start": "BUY_NEW",
  "asset_return_pct": 14.2,
  "benchmark_symbol": "SPY",
  "benchmark_return_pct": 10.1,
  "sector_benchmark_symbol": "XLK",
  "sector_return_pct": 16.0,
  "thesis_status": "MIXED",
  "triggered_rule_ids": ["rr_2"],
  "rules_followed_pct": 50,
  "process_score": 9,
  "outcome_result": "GOOD",
  "process_result": "GOOD",
  "quadrant": "GOOD_PROCESS_GOOD_OUTCOME",
  "user_reflection": "결과는 좋았지만 마진 반증 조건이 발동했을 때 늦게 대응했다.",
  "evaluator_version": "outcome-v1"
}
```

`outcome_result`는 행동과 벤치마크를 함께 고려한다. 단순 양수 수익률만으로 성공 처리하지 않는다. `thesis_status`는 `CONFIRMED`, `MIXED`, `FALSIFIED`, `UNVERIFIABLE`, `PENDING` 중 하나다.

최종 사분면:

- `GOOD_PROCESS_GOOD_OUTCOME`
- `GOOD_PROCESS_BAD_OUTCOME`
- `BAD_PROCESS_GOOD_OUTCOME`
- `BAD_PROCESS_BAD_OUTCOME`

## 13. 논리 저장 모델

구현 시 다음 테이블을 기준으로 한다.

```text
decision_cases
  1 ── N decision_versions
          1 ── N thesis_claims
          1 ── N scenarios
          1 ── N recheck_rules
          N ── N evidence_items (decision_evidence_refs)

evidence_snapshots
  1 ── N evidence_items

decision_cases
  1 ── N analysis_runs
          N ── 1 perspective_definitions (lens only)
          N ── N evidence_items (analysis_evidence_refs)

public_actors
  1 ── N public_position_observations
  1 ── N public_statement_observations

decision_cases
  1 ── N comparison_runs
          1 ── N comparison_items

decision_cases
  1 ── N outcome_reviews
```

### 13.1 주요 키와 시간

- 모든 ID는 UUID 문자열을 사용한다.
- 저장 시간은 UTC ISO-8601로 통일한다.
- 사용자 화면에서만 계정 시간대로 변환한다.
- `period_end`, `filed_at`, `announced_at`, `observed_at`을 구분한다.
- 모든 모델 산출물에 `model_name`, `prompt_version`, `created_at`을 저장한다.
- 모든 파생 수치에 `formula_version`을 저장한다.

## 14. API 경계 초안

```text
POST /api/us/cases
POST /api/us/cases/{case_id}/messages
POST /api/us/cases/{case_id}/provisional-lock
POST /api/us/cases/{case_id}/analyses
GET  /api/us/cases/{case_id}/comparison
POST /api/us/cases/{case_id}/finalize
GET  /api/us/cases/{case_id}/public-context
POST /api/us/cases/{case_id}/reviews
GET  /api/us/cases/{case_id}/history
```

`provisional-lock`은 원자적으로 다음을 수행한다.

1. 잠정 `DecisionVersion` 생성
2. `EvidenceSnapshot` 동결
3. 분석용 블라인드 DTO 생성
4. 분석 작업 ID 반환

## 15. 판단 필드에서 역산한 데이터 요구

| 판단 필드 | 필수 데이터 | 이유 |
|---|---|---|
| 사업 논지 | SEC 10-K/10-Q 사업 설명, 사업부 매출, 기업 KPI | 무엇이 이익을 움직이는지 확인 |
| 재무 지속성 | 5년·12분기 매출, 마진, 현금흐름, 부채, 주식 수 | 성장의 질과 희석 확인 |
| 가격·시나리오 | 수정주가, 시총, EV, 역사적 배수, 무위험 금리 | 현재 가격이 요구하는 가정 계산 |
| 반증 조건 | 동일 지표의 반복 가능한 시계열, 8-K·실적 발표 | 논지 변화 자동 감시 |
| 위험 예산 | 변동성, 최대 낙폭, 실적 갭, 유동성 | 손실 예산과 실행 계획 연결 |
| 공개 기관 행동 | 13F, 13D/G, Form 4, 공식 서한·발언 | 실제 공개 행동과 사용자 판단 비교 |
| 사후 결과 | 수정주가, SPY, 섹터 ETF, 실적 데이터 | 결과와 논지·과정 분리 평가 |

데이터는 이 표의 필드를 채우거나 감시하지 못하면 MVP에서 수집하지 않는다.

## 16. MVP 범위

### 포함

- 미국 보통주
- `BUY_NEW`, `ADD`, `HOLD`, `REDUCE`, `EXIT`, `WATCH`, `DEFER`
- 잠정·최종 카드 불변 버전
- 독립 분석 1개
- 철학 렌즈 4개
- 13F 공개 보유와 Form 4 내부자 거래
- 쟁점 기반 비교 리포트
- 사용자 지정 1·3·6·12개월 검토
- SPY와 섹터 ETF 대비 결과

### 후순위

- 13D/G 자동 해석
- 공식 서한·인터뷰의 대규모 자동 수집
- 옵션·공매도·대차 데이터
- 애널리스트 컨센서스와 목표가
- 실시간 호가와 주문 연동
- 금융·바이오 등 산업 전용 평가 모델

## 17. 기존 구현에서의 전환

| 현재 자산 | 전환 방향 |
|---|---|
| `decision_cards` | `decision_cases` + 불변 `decision_versions`로 분리 |
| 자연어 `recheck_conditions` | 구조화 `recheck_rules`로 교체 |
| 전체 증거 스냅샷 감시 | 사용자가 채택한 `evidence_refs`만 감시 |
| `panel_runs.consensus_json` | 제거. `analysis_runs`와 `comparison_items`로 대체 |
| “너는 워런 버핏이다” 페르소나 | 공개 철학 기반 비사칭 렌즈로 교체 |
| 패널 BUY/HOLD/AVOID 다수결 | 쟁점별 `ALIGNED/PARTIAL/DIVERGED/UNKNOWN` 비교 |
| 패널 결과 기반 가상매매 | 제거. 사용자 최종 카드만 별도 시뮬레이션 가능 |
| `outcome_return_5d` | 기간별 상대성과 + 논지 상태 + 과정 점수로 교체 |
| KR 기술·수급 중심 evidence | SEC·기업 KPI·미국 가격·공개 기관 행동 중심으로 교체 |

기존 마이그레이션은 삭제하지 않는다. 새 테이블을 추가하고 기존 데이터는 `legacy`로 읽거나 일회성 변환한다.

## 18. 수용 기준

구현 완료는 다음 조건으로 판단한다.

1. 사용자가 잠정 결론을 잠그기 전에는 패널을 볼 수 없다.
2. 독립 분석 프롬프트에 사용자 action·thesis·confidence가 포함되지 않음을 테스트한다.
3. 각 분석이 동일한 evidence snapshot을 사용한다.
4. 렌즈 하나가 실패하거나 기권해도 다른 분석과 비교가 완료된다.
5. UI 어디에도 렌즈 결과를 실제 인물의 의견으로 표현하지 않는다.
6. 13F에는 보고기간·제출일·시차·공매도 미포함 한계를 표시한다.
7. 공개 포지션을 BUY 표로 환산하지 않는다.
8. 비교 리포트에 합의율이나 다수결 결론이 없다.
9. 최종 결론 유지·수정·보류와 그 이유가 불변 버전으로 남는다.
10. 사후 평가가 과정 점수 계산에 수익률을 사용하지 않는다.
11. 모든 수치·요약·판단이 증거 또는 공식 공개자료로 역추적된다.
12. 핵심 데이터가 없으면 `ABSTAIN` 또는 `DEFER` 경로가 정상 완료된다.

## 19. 공식 데이터 참고

- [SEC EDGAR 데이터 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC Form 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f)
- [SEC 13D/G 해석 안내](https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations/exchange-act-sections-13d-13g-regulation-13d-g-beneficial-ownership-reporting)
- [SEC Form 4](https://www.sec.gov/files/form4data%2C0.pdf)
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/overview.html)
