# Execution ledger

Native execution authorized by user. Existing codex branch reused with its existing workflow modification preserved. No push or publish.

- Tasks 1/3 foundation: watched missing-module/API tests fail, implemented versioned catalog/search/jobs and selective non-destructive valuation. Suite 48 passed.
- Tasks 4/5/6 pure calculations: relative strength, conservative missing gates, ETF shares/NAV creation estimates, distinct institutional share/value changes and safe 13F XML parser added; tests watched fail then pass.
- Task 2: live source probes in progress. US/KR/TW attempted; JP Excel dependency required. HK/SG automatic connections not claimed.
- Ruling: Single provider module initially groups small source adapters; split when actual working source schemas warrant it — avoids empty provider files — cost is future file move.
- Ruling: Source failures retain existing catalog and report unavailable; verified file import will bridge provider-specific access without claiming a live connection.
- Ruling: Continue existing checkout because local runtime and credential configuration are attached to it; preserve unrelated workflow change and do not copy credentials into isolated checkouts.
- Pending: working provider connections, validated data ingestion, signals enrichment, ETF/institution connectors, API/UI verification, whole-change review.

- Actual catalog probes: US 13,251; KR 2,758 companies after exact duplicate row reconciliation; TW 1,988; JP 4,447 via changed .xlsx URL; HK 17,265 securities. SG automatic source unavailable; explicit source import is implemented.
- Fresh reviewer found cancellation race, selective theme overwrite, overly generic profile classification, stranded queue/resume, supplemental 13F date, and unverified ETF corporate action estimates. Each important issue received a failing regression then fix. Suite now 70 passed.
- Live UI valuation exposed pre-existing NaN mom_1m breaking JSON: finite normalization at financial source and cached JSON reader/writer fixed; regression first failed and now passes.
- Ruling: missing KRX credentials and SEC contact remain required configuration, not fabricated or bypassed. Asked for SEC email and local KRX_ID/PW settings; neither supplied yet.
- Ruling: SG and non-KR/US official flow adapters require verified source access; source imports implemented with explicit provenance, status not claimed live. No paid subscription created.
- Pending integration verification: updated browser search/evaluate/detail UI, real provider status; pricing dividend basis requires correction before a comparable observation score is advertised. Official issuer creation adapters not connected. Overall expanded spec is not fully complete.

- 배당 비교 기준 수정: 동일 조정 방식의 광범위 시장 ETF 대조, 이전 가격지수 기록 순위 제외. 회귀 테스트 포함 71개 통과. 자동 연결 미완료: SG 종목원장, 공식 ETF 설정·환매 원자료. KRX 인증과 SEC 연락처 설정 대기.
