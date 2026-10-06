"""Dashboard HTML (no template engine). / 대시보드 화면."""
import html
from .countries import COUNTRIES

E = lambda x: html.escape("" if x is None else str(x))  # noqa: E731

PARTS = [("valuation", "가치평가", 35), ("quality", "사업의 질", 25),
         ("financial", "재무", 20), ("allocation", "자본배분", 10),
         ("growth", "성장", 10)]
CYCLE_KO = {"Expansion": "확장기", "Recovery": "회복기", "Slowdown": "둔화기",
            "Recession": "침체기", "Unknown": "판단 불가"}
FLAG = {"US": "🇺🇸", "KR": "🇰🇷", "SG": "🇸🇬", "JP": "🇯🇵", "TW": "🇹🇼", "HK": "🇭🇰"}


def f(x, suffix="", d=1):
    if x is None:
        return '<span class="na">–</span>'
    try:
        return f"{x:,.{d}f}{suffix}"
    except (TypeError, ValueError):
        return E(x)


def bar(v, mx):
    pct = 0 if not mx else max(0, min(100, v / mx * 100))
    return f'<span class="bar" title="{v}/{mx}"><i style="width:{pct:.0f}%"></i></span>'


def stock_rows(items, show_reasons=False):
    out = []
    for s in items:
        m = s.get("metrics", {})
        p = s.get("parts", {})
        parts = "".join(f'<td class="c">{bar(p.get(k, 0), mx)}<small>{p.get(k, 0):g}</small></td>'
                        for k, _, mx in PARTS)
        val = s.get("valuation", {})
        scenarios = " · ".join(f"{E(name)}: {f(v.get('value'), ' ' + (m.get('currency') or ''), 2)} (안전마진 {f(v.get('safety_margin'), '%')})"
                               for name, v in val.get("scenarios", {}).items()) or "가치평가 보류"
        assumptions = ", ".join(f"{E(k)}={E(v)}" for k, v in val.get("assumptions", {}).items())
        flags = ", ".join(s.get("risk_flags", [])) or "–"
        detail = f"""<details><summary><b>{E(s['ticker'])}</b> {E(m.get('name'))}</summary>
<div class="det">Sector: {E(m.get('sector'))} / {E(m.get('industry'))} · {E(m.get('country'))}<br>
Revenue growth {f(m.get('revenue_growth'), '%')} · Op margin {f(m.get('op_margin'), '%')} · EPS growth {f(m.get('eps_growth'), '%')}<br>
ROE {f(m.get('roe'), '%')} · ROIC {f(m.get('roic'), '%')} · Debt ratio {f(m.get('debt_ratio'), '%', 0)} · Current ratio {f(m.get('current_ratio'), '', 2)}<br>
FCF yield {f(m.get('fcf_yield'), '%')} · PER {f(m.get('per'))} · PBR {f(m.get('pbr'))} · PSR {f(m.get('psr'))} · EV/EBITDA {f(m.get('ev_ebitda'))}<br>
DCF value {f(m.get('dcf_value'), ' ' + (m.get('currency') or ''), 2)} (upside {f(m.get('dcf_upside'), '%')}) · Price {f(m.get('price'), '', 2)} · 1M {f(m.get('mom_1m'), '%')}<br>
Themes: {E(', '.join(s.get('all_themes', [])))} · Data coverage {f((s.get('coverage') or 0) * 100, '%', 0)}<br>
분석 상태: {E(s.get('analysis_status', 'legacy_score_requires_rerun'))} · 자료: {E(s.get('data_quality', 'unverified'))}<br>
가치 시나리오: {scenarios}<br>가정: {E(val.get('assumption_source'))} · {assumptions}<br>
정상화: {E(m.get('normalization_method'))} · {E(m.get('normalization_note'))}<br>
수집 시각: {E(m.get('collected_at'))} · 기간 말: {E(m.get('period_end'))}<br>
Risk flags: {E(flags)}</div></details>"""
        reasons = f'<td>{E(", ".join(s.get("avoid", [])))}</td>' if show_reasons else ""
        out.append(f"""<tr><td>{FLAG.get(s.get('market'), '')}</td><td class="name">{detail}</td>
<td>{E(s.get('theme'))}</td><td class="c total">{f(s.get('total'))}</td>{parts}
<td class="c">{f(m.get('roe'), '%')}</td><td class="c">{f(m.get('fcf_yield'), '%')}</td>
<td class="c">{f(m.get('per'))}</td><td class="c risk-{E(s.get('risk'))}">{E(s.get('risk'))}</td>{reasons}</tr>""")
    return "".join(out)


def stock_table(items, empty, show_reasons=False):
    if not items:
        return f'<p class="na">{empty}</p>'
    head = "".join(f'<th class="c">{lbl}<br><small>/{mx}</small></th>' for _, lbl, mx in PARTS)
    extra = "<th>Reason 이유</th>" if show_reasons else ""
    return f"""<div class="scroll"><table><tr><th></th><th>Stock 종목</th><th>Theme 테마</th>
<th class="c">Score<br><small>/100</small></th>{head}<th class="c">ROE</th><th class="c">FCF yield</th>
<th class="c">PER</th><th class="c">Risk</th>{extra}</tr>{stock_rows(items, show_reasons)}</table></div>"""


def render(r: dict, static: bool = False) -> str:
    selected = r.get("selected_market")
    countries = r.get("countries", {})
    links = '<a href="?">전체</a> ' + " ".join(
        f'<a href="?market={code}" aria-current="{ "page" if selected == code else "false"}">{FLAG[code]} {E(meta["name"])}</a>'
        for code, meta in COUNTRIES.items())
    summary = "".join(f'<tr><td>{E(meta["name"])}</td><td>{meta.get("configured", 0)}</td>'
                      f'<td>{meta.get("analyzed", 0)}</td><td>{meta.get("valuation_available", 0)}</td>'
                      f'<td>{meta.get("candidates", 0)}</td><td>{E(meta.get("data_status", "미수집"))}</td></tr>'
                      for code, meta in countries.items() if not selected or code == selected)
    country_section = f'<h2>국가별 가치투자</h2><nav>{links}</nav><div class="scroll"><table><tr><th>국가</th><th>설정 종목</th><th>분석 기록</th><th>가치평가 가능</th><th>안전마진 후보</th><th>데이터 상태</th></tr>{summary}</table></div><p class="na">명시적 후보 목록 기준 · 공식 공시 검증 전 · 할인율은 초기 가정 · 미수집 자료는 순위에 포함하지 않습니다.</p>'
    mac = r.get("macro") or {}
    cycle = mac.get("cycle", "Unknown")
    favored = [t["theme"] for t in r.get("themes", []) if t.get("favored_by_cycle")]

    cards = "".join(f'<div class="card"><small>{lbl}</small><b>{f(mac.get(k), u, 2)}</b></div>' for k, lbl, u in [
        ("fed_rate", "Fed rate 기준금리", "%"), ("us10y", "US 10Y 국채", "%"),
        ("cpi_yoy", "CPI YoY 물가", "%"), ("ppi_yoy", "PPI YoY 생산자물가", "%"),
        ("gdp_yoy", "GDP YoY 성장률", "%"), ("unemployment", "Unemployment 실업률", "%"),
        ("m2_yoy", "M2 YoY 통화량", "%")])

    theme_rows = "".join(f"""<tr><td>{i}</td><td><b>{E(t['theme'])}</b>{' <span class="tag">cycle ✓</span>' if t.get('favored_by_cycle') else ''}
<br><small class="na">{E(', '.join(t.get('industries', [])))}</small></td>
<td class="c total">{f(t.get('score'))}</td><td class="c">{t.get('news_count', 0)}</td>
<td class="c">{f((t.get('pos_ratio') or 0) * 100, '%', 0)}</td><td class="c">{f(t.get('flow_1m'), '%')}</td>
<td>{'<br>'.join(f'<a href="{E(h["url"])}" target="_blank" rel="noopener">{E(h["title"][:90])}</a>' for h in t.get('headlines', [])[:2]) or '<span class="na">–</span>'}</td></tr>"""
                         for i, t in enumerate(r.get("themes", []), 1))

    by_mkt = "".join(f"""<div class="mk"><h3>{FLAG[m]} {m}</h3><ol>{''.join(f"<li><b>{E(s['ticker'])}</b> {E(s['metrics'].get('name'))} <span class='na'>· {E(s['theme'])}</span> <b class='sc'>{f(s['total'])}</b></li>" for s in items) or '<li class=na>–</li>'}</ol></div>"""
                     for m, items in (r.get("top_by_market") or {}).items())

    lr = r.get("last_run") or {}
    run_btn = "" if static else """<button id="run" onclick="runNow()">Run now / 지금 실행</button>
<span id="st" class="na"></span>"""
    script = "" if static else """<script>
async function runNow(){const b=document.getElementById('run'),s=document.getElementById('st');
b.disabled=true;s.textContent=' Running… 실행 중 (5–15 min)';
await fetch('api/run?step=all',{method:'POST'});
const t=setInterval(async()=>{const j=await (await fetch('api/status')).json();
if(!j.running){clearInterval(t);location.reload();}},10000);}
</script>"""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Investment Ideas</title>
<style>
:root{{--bg:#fff;--fg:#1f2328;--mut:#656d76;--line:#d0d7de;--card:#f6f8fa;--acc:#1a7f37;--bar:#2da44e;--warn:#cf222e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#30363d;--card:#161b22;--acc:#3fb950;--bar:#3fb950;--warn:#f85149}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif}}
main{{max-width:1200px;margin:auto}} h1{{font-size:22px;margin:0}} h2{{font-size:17px;margin:28px 0 8px}}
h3{{font-size:15px;margin:0 0 6px}} a{{color:#0969da}} .na{{color:var(--mut)}}
.top{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}}
.cycle{{display:inline-block;background:var(--acc);color:#fff;border-radius:20px;padding:4px 12px;font-weight:600}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-top:10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}}
.card small{{display:block;color:var(--mut)}} .card b{{font-size:18px}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top;text-align:left}}
th{{background:var(--card);white-space:nowrap}} .c{{text-align:center;white-space:nowrap}}
.total{{font-weight:700;font-size:15px}} .name{{min-width:200px}}
.bar{{display:block;width:44px;height:6px;background:var(--line);border-radius:3px;margin:3px auto}}
.bar i{{display:block;height:100%;background:var(--bar);border-radius:3px}}
.risk-High{{color:var(--warn);font-weight:700}} .risk-Medium{{color:#bf8700}}
.tag{{font-size:11px;background:var(--acc);color:#fff;border-radius:10px;padding:1px 6px}}
details summary{{cursor:pointer}} .det{{color:var(--mut);font-size:12px;margin-top:4px}}
.mks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}
.mk{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}}
.mk ol{{margin:0;padding-left:20px}} .sc{{float:right}}
button{{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:8px 14px;font-weight:600;cursor:pointer}}
button:disabled{{opacity:.5}} footer{{color:var(--mut);font-size:12px;margin:30px 0}}
</style></head><body><main>
<div class="top"><div><h1>AI Investment Ideas · AI 투자 아이디어</h1>
<span class="na">Data day {E(r.get('day') or '–')} · built {E(r.get('generated'))} · news stored {r.get('news_total', 0)} ·
last run: {E(lr.get('status'))} {E((lr.get('finished') or lr.get('started') or '')[:16])}</span></div>
<div>{run_btn}</div></div>

{country_section}
<h2>미국 거시 참고 정보 · Economic cycle</h2>
<span class="cycle">{E(cycle)} · {CYCLE_KO.get(cycle, '')}</span>
<span class="na"> Favored themes 유리한 테마: {E(', '.join(favored) or '–')}</span>
<div class="cards">{cards}</div>

<h2>Top Themes · 주요 테마 <small class="na">(score /15 = news volume + positive news + 1M price flow)</small></h2>
<div class="scroll"><table><tr><th>#</th><th>Theme 테마</th><th class="c">Score</th><th class="c">News 7d</th>
<th class="c">Positive</th><th class="c">Flow 1M</th><th>Latest headlines 최근 뉴스</th></tr>{theme_rows}</table></div>

<h2>Top Stocks · 상위 종목 <small class="na">(click a name for details · 이름 클릭 시 상세)</small></h2>
{stock_table(r.get('top_stocks', []), '가치평가 가능한 종목 없음 · 추가 검토·자료 부족 목록을 확인하세요.')}

<h2>Top 5 by market · 시장별 상위 5</h2><div class="mks">{by_mkt}</div>

<h2>Value Picks · 가치주 <small class="na">(기준 안전마진 ≥ 20% · 초기 검토 기준)</small></h2>
{stock_table(r.get('value_picks', []), '안전마진 기준을 충족한 평가 가능 종목 없음')}

<h2>Avoid List · 회피 목록 <small class="na">(high debt, losses, weak cash flow, high risk)</small></h2>
<details><summary>{len(r.get('avoid_list', []))} stocks — click to show / 클릭해서 보기</summary>
{stock_table(r.get('avoid_list', []), 'None. / 없음', show_reasons=True)}</details>

<h2>추가 검토·자료 부족</h2>
{stock_table(r.get('review_list', []), '보류 종목 없음', show_reasons=True)}
<footer>점수 = 가치평가 35 + 사업의 질 25 + 재무 20 + 자본배분 10 + 성장 10.<br>
자료가 없는 항목은 0점이며, 핵심 가치평가 자료 부족 시 총점을 부여하지 않습니다. 뉴스·거시는 투자 점수에 포함하지 않습니다.<br>
Data: Yahoo Finance (보조 데이터), Google News, FRED (미국). 공식 공시 수집·역사 시점 백테스트는 아직 연결 전입니다.<br>
AI does not make investment decisions. This is a list of companies worth reviewing — the final decision is yours.<br>
AI가 투자 결정을 대신하지 않습니다. 검토할 가치가 있는 기업 리스트이며, 최종 판단은 투자자가 합니다.</footer>
</main>{script}</body></html>"""
