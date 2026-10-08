"""
Archive stock and investment reports, then build docs/index.html.
종목·투자 보고서를 날짜별로 보관하고 전체 결과 목록을 만듭니다.
"""
import csv
import datetime as dt
import html
import shutil
import re
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
from pathlib import Path

HERE = Path(__file__).parent
SGT = ZoneInfo("Asia/Singapore")


class ReportMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.generated = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'report-generated':
            self.generated = attrs.get('content')


def archive_investment(page, reports):
    if not page.exists():
        return
    content = page.read_bytes()
    text = content.decode('utf-8')
    metadata = ReportMetadata()
    metadata.feed(text)
    # Existing two-table exports predate the explicit generated-date metadata.
    fallback = re.search(r'기준 시각 ([0-9T:+Z.\-]+)', text)
    stamp = metadata.generated or (fallback.group(1) if fallback else None)
    if not stamp:
        print('Investment archive skipped: report generation date unavailable.')
        return
    generated = dt.datetime.fromisoformat(stamp)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=SGT)
    day = generated.astimezone(SGT).strftime('%Y%m%d')
    target = reports / f'investment_{day}.html'
    temporary = target.with_suffix('.html.tmp')
    temporary.write_bytes(content)
    temporary.replace(target)


def info(p):
    stamp = p.stem.split("_")[1]
    day = dt.datetime.strptime(stamp, "%Y%m%d").date()
    c = p.with_suffix(".csv")
    n, strong = 0, 0
    if c.exists():
        with c.open(encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        n = len(rows)
        strong = sum(r.get("signal") == "STRONG" for r in rows)
    return day, n, strong, c.exists()


def build_site(root=HERE):
    root = Path(root)
    docs = root / 'docs'
    reports = docs / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    (docs / '.nojekyll').touch()
    for source in root.glob('strong_*.*'):
        if source.suffix in ('.html', '.csv'):
            shutil.move(str(source), reports / source.name)
    archive_investment(docs / 'invest' / 'index.html', reports)
    pages = list(reports.glob('strong_*.html')) + list(reports.glob('investment_*.html'))
    pages.sort(key=lambda page: (page.stem.rsplit('_',1)[1], page.stem.startswith('investment_')), reverse=True)
    rows = []
    for page in pages:
        if page.stem.startswith('investment_'):
            stamp = page.stem.rsplit('_',1)[1]
            day = dt.datetime.strptime(stamp, '%Y%m%d').date()
            label = 'AI Investment Ideas / AI 투자 아이디어'
            extra = '섹터·주도주 후보 · 가치투자 고득점 기업'
        else:
            day, count, strong, has_csv = info(page)
            label = 'Strong vs Index / 지수 대비 강세 종목'
            csv_link = f' · <a href="reports/{page.stem}.csv">CSV</a>' if has_csv else ''
            extra = f'{count} stocks · {strong} STRONG{csv_link}'
        rows.append(f'<li><div><a href="reports/{page.name}">{day} ({day:%a}) · {label}</a></div><span>{extra}</span></li>')


    (docs / "index.html").write_text(f"""<!doctype html>
    <html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Screener Reports / 스크리너 결과</title>
    <style>
    body{{font-family:-apple-system,system-ui,sans-serif;max-width:720px;margin:0 auto;padding:20px 16px;color:#222;background:#fff}}
    h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#666;margin:0 0 20px;font-size:14px}}
    .btn{{display:block;text-align:center;background:#1a7f37;color:#fff;padding:14px;border-radius:10px;
    text-decoration:none;font-weight:600;margin-bottom:24px}}
    ul{{list-style:none;padding:0;margin:0}} li{{display:flex;justify-content:space-between;gap:12px;
    padding:12px 0;border-bottom:1px solid #eee;flex-wrap:wrap}}
    li a{{color:#0969da;text-decoration:none}} li span{{color:#666;font-size:14px}}
    footer{{color:#888;font-size:12px;margin-top:24px}}
    @media (prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}li{{border-color:#30363d}}
    li a{{color:#58a6ff}}.sub,li span{{color:#8b949e}}}}
    </style></head><body>
    <h1>Screener reports / 스크리너 결과</h1>
    <p class="sub">지수보다 강한 종목 · SG / US / KR · updated weekdays ~07:00 SGT</p>
    <a class="btn" style="background:#0969da" href="invest/">AI investment ideas / AI 투자 아이디어 →</a>
    <h2 style="font-size:16px">All reports / 전체 결과</h2>
    <ul>{''.join(rows)}</ul>
    <footer>Daily data from Yahoo Finance. Not financial advice. / 투자 조언이 아닙니다.<br>
    Last build: {html.escape(dt.datetime.now(SGT).strftime('%Y-%m-%d %H:%M'))}</footer>
    </body></html>""", encoding="utf-8")
    print(f"Site built: {len(pages)} report(s) in docs/")


if __name__ == '__main__':
    build_site()
