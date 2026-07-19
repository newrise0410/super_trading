# AIM — 나의 AI 투자 매니저

KR/US 시장의 장시작·마감 정시 리포트, 다중 전략 시뮬레이션, 투자근거 Q&A를 제공하는 개인용 AI 투자 매니저.

- 기획서: [PLAN.md](PLAN.md)
- 레퍼런스 리포 분석: `references/` (7개, gitignore됨 — 각자 클론)
- 코드 출처 추적: [PROVENANCE.md](PROVENANCE.md)

## 빠른 시작 (mock 모드 — 외부 의존성/API키 불필요)

```bash
set PYTHONPATH=src        # PowerShell: $env:PYTHONPATH="src"
python -m aim init-db
python -m aim briefing kr-close --mock --channel console
```

## 설치 (실데이터 사용 시)

```bash
pip install -e .
copy .env.example .env    # 값 입력
aim briefing kr-close --channel console
```

## 구조

```
src/aim/
├── config.py         # .env/환경변수 설정 (stdlib만 사용)
├── events.py         # 이벤트 버스 — 스케줄러는 이벤트만 발행 (§10.6-5)
├── pipelines.py      # 리포트 파이프라인 오케스트레이션
├── data/             # ① 데이터 레이어 (Provider 프로토콜 + mock/pykrx/KIS)
├── storage/          # repository 패턴 + SQLite 마이그레이션 (§10.6-1)
│   └── migrations/   #   판단 로그(decisions) 스키마 = 서비스 기준 (§10.6-4)
├── brain/            # ③ 두뇌 — P1 룰 기반 → P2 멀티에이전트 토론
├── simulation/       # ② 전략 시뮬레이션 (P3)
├── reports/          # 마스터/개인 리포트 분리 생성 (§10.6-2)
├── delivery/         # Notifier 인터페이스 + console/telegram (§10.6-3)
└── scheduler/        # 장 캘린더 + APScheduler 러너
```

> ⚠️ 본 프로젝트의 모든 산출물은 정보 제공 목적이며 투자 자문이 아닙니다. 투자 판단과 책임은 본인에게 있습니다.
