"""Korean two-track screening dashboard and static report rendering."""
import html
from pathlib import Path

from .countries import COUNTRIES, SEARCH_MARKETS
from .discovery.ui import controls
from .valuation import finite

E = lambda value: html.escape('' if value is None else str(value), quote=True)
STATUS = {'unknown':'미확인','improving':'개선','mixed':'혼재','weakening':'악화'}
PARTS = [('valuation','가치평가',35),('quality','사업 품질',25),('financial','재무',20),('allocation','자본배분',10),('growth','성장',10)]


def number(value, suffix='', digits=1):
    if not isinstance(value,(int,float)):
        return '미확인'
    return f'{value:,.{digits}f}{suffix}'


def pct(value):
    return number(value*100 if isinstance(value,(int,float)) else None, '%')


def badge(check):
    status = check.get('status','unknown')
    return f'<span class="badge {E(status)}">{STATUS.get(status,"미확인")}</span>'


def evidence_detail(row):
    a=row.get('analysis',{});m=a.get('metrics',{});v=a.get('valuation',{})
    fields=[('분석 상태',a.get('analysis_status','미수집')),('분석일',a.get('day','미수집')),
            ('자료 충족률',pct(a.get('coverage'))),('공식 검증',m.get('official_verification',{}).get('status','미수집')),
            ('통화',m.get('currency')),('가격',m.get('price')),('정상화',m.get('normalization_method')),
            ('가정 출처',v.get('assumption_source')),('검토 사항',', '.join(a.get('avoid',[])) or '자료 출처와 가정 확인')]
    fields += [(f'{label} /{weight}',number(a.get('parts',{}).get(key))) for key,label,weight in PARTS]
    for label,scenario in v.get('scenarios',{}).items():
        fields.append(({'conservative':'보수적','base':'기준','optimistic':'낙관적'}.get(label,label)+' 가치',number(scenario.get('value'))+' '+str(v.get('currency') or '')+' · 안전마진 '+number(scenario.get('safety_margin'),'%')))
    for key,value in v.get('assumptions',{}).items():
        fields.append((key,str(value)))
    reverse=v.get('reverse_dcf') or {}
    fields.append(('주가 내재 현금흐름 성장률',number(reverse.get('implied_growth'),'%')))
    for e in row['listing'].get('evidence',[]):
        fields.append(('분류 근거',f"{e['label']} · {e['source']} · {e['available_at']} · {e['evidence']}"))
    out='<dl>'+''.join(f'<dt>{E(k)}</dt><dd>{E(value)}</dd>' for k,value in fields)+'</dl>'
    for c in m.get('official_verification',{}).get('comparisons',[]):
        url=str(c.get('source_url') or '')
        if url.startswith(('https://','http://')):
            out+=f'<p><a href="{E(url)}" target="_blank" rel="noopener">공시 원본</a> · {E(c.get("metric"))}: {E(c.get("status"))}</p>'
    return out


def name_cell(row, static):
    item=row['listing']
    detail=evidence_detail(row)
    action='' if static else f'<button class="text-button" type="button" data-detail="{E(item["id"])}">관찰·기관 상세</button>'
    return f'<details class="company"><summary><strong>{E(item["name"])}</strong><small>{E(item["ticker"])}</small></summary>{detail}{action}</details>'


def flow_summary(records):
    if not records:
        return '<span class="muted">미수집</span>'
    lines=[]
    seen=set()
    for r in records:
        key=(r.get('fund'),r['kind'],r['data'].get('manager'))
        if key in seen:continue
        seen.add(key)
        d=r['data'];kind=r['kind']
        label={'etf_holdings':'ETF 편입','etf_nav':'ETF NAV·규모','etf_reported_flow':'ETF 설정/환매','institution_trades':'기관 순매수','institution_holdings':'기관 분기 보유'}.get(kind,kind)
        value=''
        if kind=='etf_holdings':value=' · 비중 '+pct(r.get('weight')) if r.get('weight') is not None else ' · 섹터 연결'
        if kind=='institution_holdings':
            label='기관 공개 보유 (보조)' if d.get('coverage')=='auxiliary_reported_holders' else '기관 분기 보유'
            value=' · '+number(d.get('shares'),digits=0)+'주'
            if finite(d.get('ownership_fraction')):value+=' · 지분 '+pct(d['ownership_fraction'])
        if kind=='etf_reported_flow':value=' · '+number(d.get('net_creation'))+' '+str(d.get('currency') or '')
        date_label=('수집 '+str(r['period'])+' · 구성 기준일 미확인') if kind=='etf_holdings' and d.get('coverage')=='top_holdings_only' and not d.get('holdings_as_of') else str(r['period'])
        lines.append(f'<span>{E(r.get("fund") or d.get("manager") or "")} {E(label+value)}<small>{E(date_label)} · {E(d.get("source"))}</small></span>')
    return '<div class="flow-lines">'+''.join(lines)+'</div>'


def observation_rows(report, static=False):
    rows=[]
    for r in report['observations']['items']:
        item=r['listing'];c=r['checks'];s=c['strength']['signals'];t=c['profits']['trends'];b=c['breadth'];e=c['estimates'];p=c['price']
        selection='' if static else f'<input type="checkbox" data-listing="{E(item["id"])}" aria-label="{E(item["name"])} 선택">'
        demand=' · '.join(f"{m['product']} {m['metric']}: {m['previous']} → {m['current']} {m['unit']} ({m['previous_period']} → {m['current_period']})" for m in c['demand']['measurements']) or '수주·판매량·재고·제품 가격 자료 없음'
        profits=f"매출 {pct(t.get('revenue_change'))}<br>이익률 {number(t.get('margin_change')*100 if t.get('margin_change') is not None else None,'%p')}<br>영업현금흐름 {pct(t.get('cashflow_change'))}"
        periods=c['profits'].get('periods',{})
        period_text=' · '.join(f"{v['previous']} → {v['current']}" for v in periods.values())
        estimates=f"이익 전망 {pct(e['change'])}<br>{E(e.get('forecast_period') or '전망 자료 없음')}<small>섹터 상향 {pct(e['upward_ratio'])} · {e['sample']}개</small>"
        strength=f"3개월 {number(s.get('rs_3m'),'%')}<br>6개월 {number(s.get('rs_6m'),'%')}<small>조정 수익률 비율 비교 · {E(c['strength'].get('benchmark') or '비교 자료 없음')}<br>{E(c['strength'].get('as_of') or '')}</small>"
        breadth=f"강세 3개월 {pct(b['strong_3m'])} · {b['sample_3m']}/{b['total_members']}개<br>강세 6개월 {pct(b['strong_6m'])} · {b['sample_6m']}/{b['total_members']}개<small>상승 3/6개월 {pct(b['rising_3m'])} / {pct(b['rising_6m'])}</small>"
        price=f"안전마진 {number(p['safety_margin'],'%')}<small>분석일 {E(p.get('analysis_day') or '미수집')}<br>내재 성장률 {number((p.get('reverse_dcf') or {}).get('implied_growth'),'%')}</small>"
        row=[selection, E(COUNTRIES[item['market']]['name']), E(r['sector']), name_cell(r,static),flow_summary(r['etf_institution']),
             badge(c['demand'])+('<small>부분 확인 · 재고 신호</small>' if c['demand'].get('coverage')=='inventory_only' else '')+f'<small>{E(demand)}<br>{E(c["demand"].get("note"))}<br>{E(c["demand"].get("source"))} {E(c["demand"].get("as_of"))}</small>',
             badge(c['profits'])+'<div>'+profits+f'<small>{E(period_text)}</small></div>',
             badge(e)+'<div>'+estimates+f'<small>{E(e.get("source"))} {E(e.get("as_of"))}</small></div>',
             badge(c['strength'])+'<div>'+strength+'</div>',badge(b)+'<div>'+breadth+'</div>',badge(p)+'<div>'+price+'</div>',
             '<strong>'+number(r['leadership']['score'])+'</strong><small>상대강도 40 · 실적 40 · 유동성 20</small>']
        rows.append('<tr>'+''.join('<td>'+value+'</td>' for value in row)+'</tr>')
    return ''.join(rows) or '<tr><td colspan="12" class="empty">검색 결과가 없습니다. 목록·분류 자료를 수집하거나 다른 검색어를 입력하세요.</td></tr>'


def value_rows(report,static=False):
    rows=[]
    for r in report['value_candidates']['items']:
        item=r['listing'];a=r['analysis'];m=a.get('metrics',{});base=a.get('valuation',{}).get('scenarios',{}).get('base',{})
        fields=[E(COUNTRIES[item['market']]['name']),name_cell(r,static),E(m.get('sector') or m.get('industry') or ' · '.join(e['label'] for e in item['evidence']) or '미분류'),
                '<strong class="score">'+number(a['total'])+'</strong>',number(base.get('safety_margin'),'%'),number(m.get('roic'),'%'),number(m.get('op_margin'),'%'),number(m.get('debt_ratio'),'%'),
                number(m.get('ocf'))+' / '+number(m.get('fcf'))+'<small>'+E(m.get('financial_currency') or m.get('currency'))+'</small>',
                number(m.get('revenue_growth'),'%')+' / '+number(m.get('eps_growth'),'%'),
                pct(a.get('coverage'))+'<small>'+E(m.get('official_verification',{}).get('status','미검증'))+'<br>'+E(a.get('day'))+'</small>']
        rows.append('<tr>'+''.join('<td>'+v+'</td>' for v in fields)+'</tr>')
    return ''.join(rows) or f'<tr><td colspan="11" class="empty">{number(report["min_score"],digits=0)}점 이상이며 평가 가능한 기업이 없습니다. 전체 목록과 기업 평가 상태를 확인하세요.</td></tr>'


def coverage_text(report):
    labels=[]
    for code,c in report['coverage'].items():
        if report.get('selected_market') and code!=report['selected_market']:continue
        scope='목록 확보' if c['complete'] else '부분 목록' if c['listings'] else '전체 목록 미확보'
        source_status={'refreshing':'목록 갱신 중','connection_unavailable':'갱신 실패 · 이전 목록 보존','source_error':'수집 오류 · 이전 목록 보존','imported':'입력 자료','partial':'부분 목록 수집','not_collected':'미수집','captured':'수집 완료'}.get(c['status'],c['status'])
        labels.append(f'<span><b>{E(COUNTRIES[code]["name"])}</b> {E(scope)} · {E(source_status)} · {c["companies"]:,}개 기업 · 주가·실적 자료 {c.get("signals_collected",0):,}개 · 수집 실패 {c.get("signal_failures",0):,}개 · 평가 기록 {c["analyzed"]:,}개 · 기준 충족 {c["eligible"]:,}개<small>{E(c.get("source") or "출처 있는 전체 목록을 연결하세요")} · {E(c.get("as_of") or "미수집")}</small></span>')
    return ''.join(labels)


def fragments(report):
    return {'observations':observation_rows(report),'values':value_rows(report),'coverage':coverage_text(report)}


def table(kind, headers, body):
    return f'<div class="scroll" tabindex="0" aria-label="{E(kind)} 표 가로 스크롤"><table data-result-table="{E(kind)}"><thead><tr>'+''.join(f'<th scope="col">{E(x)}</th>' for x in headers)+'</tr></thead><tbody id="'+('observation-body' if kind=='observations' else 'value-body')+'">'+body+'</tbody></table></div>'


def render(report,static=False):
    market=report.get('selected_market') or ''
    options='<option value="">전체 시장</option>'+''.join(f'<option value="{code}"'+(' selected' if code==market else '')+f'>{E(COUNTRIES[code]["name"])}</option>' for code in SEARCH_MARKETS)
    selection=f'<form id="market-form"><label>검색 시장 <select id="market">{options}</select></label><button type="submit">적용</button><button type="button" id="catalog-refresh" class="secondary">선택 시장 목록 갱신</button></form>' if not static else '<p>'+E(COUNTRIES.get(market,{}).get('name','한국 · 싱가포르 · 미국'))+'</p>'
    search=f'<form id="sector-form"><label class="grow">섹터·기업 검색 <input id="sector-query" placeholder="반도체, AI, 전력, 기업명·종목 코드" maxlength="100" value="{E(report.get("query"))}"></label><button>검색</button></form>' if not static else '<p>섹터 검색: '+E(report.get('query') or '전체')+'</p>'
    value_filter=f'<form id="value-form"><label>최소 점수 <input id="min-score" type="number" min="0" max="100" step="0.1" value="{E(report["min_score"])}"></label><button>적용</button><button type="button" id="evaluate-market" class="secondary">전체 기업 가치평가</button></form>' if not static else f'<p>최소 점수 {number(report["min_score"])} /100</p>'
    css=(Path(__file__).parent/'dashboard.css').read_text()
    scripts='' if static else '<script src="assets/dashboard.js" defer></script>'
    pagination=lambda track: '' if static else f'<div class="pagination"><button class="secondary" data-page="{track}" data-direction="-1">이전</button><span id="{track}-count"></span><button class="secondary" data-page="{track}" data-direction="1">다음</button></div>'
    obs=table('observations',['선택','시장','섹터','후보 기업','ETF·기관 근거','수요 회복','이익 개선','예상 실적 상향','시장 대비 강세','상승의 확산','가격 부담','관찰 점수'],observation_rows(report,static))
    val=table('values',['시장','기업','섹터','가치 점수 /100','안전마진','ROIC','영업이익률','부채비율','영업현금흐름 / FCF','매출 / EPS 성장','자료 충족률·검증'],value_rows(report,static))
    import_controls=controls(static)
    observation_caption=f'현재 표시 {len(report["observations"]["items"]):,}개 / 검색 결과 {report["observations"]["total"]:,}개'
    value_caption=f'현재 표시 {len(report["value_candidates"]["items"]):,}개 / 기준 충족 {report["value_candidates"]["total"]:,}개'
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="report-generated" content="{E(report['generated'])}"><title>시장 탐색 · 섹터와 가치투자</title><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 16 16%27%3E%3Cpath fill=%27%230075de%27 d=%27M2 10h3v4H2zm5-4h3v8H7zm5-4h3v12h-3z%27/%3E%3C/svg%3E"><style>{css}</style>{scripts}</head><body><main>
<header><p class="eyebrow">KR / SG / US · INVESTMENT SCREENER</p><h1>섹터의 변화에서, 기업의 가치까지</h1><p class="muted">자금·실적·가격의 근거로 후보를 좁히고, 전체 상장 목록에서 가치 점수가 높은 기업을 확인합니다.</p></header>
{selection}<div id="coverage" class="coverage">{coverage_text(report)}</div><p id="global-state" role="status"></p>
<section aria-labelledby="observation-title"><div class="section-heading"><span class="step">01</span><div><h2 id="observation-title">섹터·주도주 후보</h2><p class="muted">ETF·기관 분석 → 섹터 검색·평가 → 주도주 후보 지표</p></div></div>
{search}<div class="workflow-actions">{'' if static else '<button type="button" id="show-funds" class="secondary">ETF·기관 자료 조회</button><button type="button" id="enrich-all" class="secondary">검색 결과 관찰 자료 수집</button><button type="button" id="enrich-selected" class="secondary">선택 종목·ETF 자료 수집</button><button type="button" id="evaluate-selected" class="secondary">선택 종목 가치평가</button>'}</div>
<div id="funds-panel"></div><p class="note">관찰 점수는 상대강도·실적·유동성 기준입니다. 여섯 신호 전체의 종합점수가 아니며, 미확인 항목은 상세 근거로 확인하세요.</p>
<p class="note" id="observation-summary">{observation_caption}</p>{obs}{pagination('observation')}<details class="guide"><summary>여섯 가지 신호의 확인 기준</summary><dl>
<dt>수요 회복</dt><dd>신규 수주·판매량 증가, 재고 감소, 제품 가격 상승</dd><dt>이익 개선</dt><dd>매출뿐 아니라 영업이익률·현금흐름도 개선되는지</dd><dt>예상 실적 상향</dt><dd>같은 기간의 이익 전망을 올리는 기업이 섹터 안에서 늘어나는지</dd><dt>시장 대비 강세</dt><dd>최근 3·6개월의 배당·분할 조정 수익률이 시장 비교 ETF보다 높은지</dd><dt>상승의 확산</dt><dd>대표 종목 외에 여러 관련 기업이 함께 오르는지 · 확보 표본과 전체 기업 수 확인</dd><dt>가격 부담</dt><dd>좋아질 실적을 현재 주가가 이미 과도하게 반영했는지 · 가치 시나리오와 주가 내재 성장률 확인</dd></dl></details></section>
<section aria-labelledby="value-title"><div class="section-heading"><span class="step">02</span><div><h2 id="value-title">가치투자 고득점 기업</h2><p class="muted">거래소 전체 목록 → 가치투자 지표 평가 → 높은 점수의 기업</p></div></div>
{value_filter}<p class="note">섹터 검색과 독립된 전체 기업 기준 · 가치평가 35 / 사업 품질 25 / 재무 20 / 자본배분 10 / 성장 10 · 자료 부족·검토 보류·전용 모형 필요 기업 제외</p>
<p class="note" id="value-summary">{value_caption}</p>{val}{pagination('value')}</section>
{import_controls}<div id="detail-panel" class="detail-panel" hidden></div><footer>기준 시각 {E(report['generated'])} · 기업명을 펼치면 출처·가정·자료 상태를 볼 수 있습니다. 실제 자료가 없는 항목은 미확인으로 표시됩니다.</footer>
</main></body></html>'''
