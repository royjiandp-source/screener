"""Shared data connection and persistent job controls, outside result tables."""


def controls(static=False):
    if static:
        return '<p class="note">저장된 자료 기준 정적 보고서입니다. 목록 갱신·검색·평가는 실행 중인 앱에서 사용할 수 있습니다.</p>'
    return '''<aside class="job-panel"><h3>분석 진행 상태</h3><p id="job-state" role="status">진행 중인 작업 없음</p><button type="button" id="cancel-job" class="secondary" disabled>작업 취소</button><button type="button" id="resume-job" class="secondary" hidden>중단된 작업 재개</button></aside>
<details class="connections"><summary>기관 공시·자료 연결</summary><div class="connection-fields"><label>미국 기관 CIK <input id="manager-cik" placeholder="기관 식별번호" maxlength="10"></label><button type="button" id="manager-refresh" class="secondary">미국 분기 보유 공시 수집</button><p class="muted">SEC 연락처 설정과 확인된 CUSIP 연결이 필요합니다. 13F는 실제 순매수 자료가 아닌 분기 보유 공시입니다.</p><label>출처가 포함된 목록·ETF·기관·수요·전망 JSON 자료 <input id="data-import" type="file" accept="application/json,.json"></label><button type="button" id="import-data" class="secondary">자료 불러오기</button><p class="muted">싱가포르 전체 목록과 자동 수집이 없는 신호는 출처·기준일이 있는 자료를 연결하세요. 수요·전망 자료의 입력 형식은 사용 안내에 설명되어 있습니다.</p></div></details>'''
