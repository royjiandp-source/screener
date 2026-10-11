import pytest
from app.book_value import assess


def metrics(**changes):
    return dict(pbr=.3, equity=100, op_margin=10, ocf=20, debt_ratio=80, roe=8, **changes)


def test_low_pbr_requires_positive_multiple_and_excludes_financial_losses():
    for pbr in [0, -.2, .51, None, float('nan')]:
        assert assess({**metrics(), 'pbr':pbr}) is None
    for key in ['equity', 'op_margin', 'ocf']:
        assert assess({**metrics(), key:-1}) is None
    assert assess({**metrics(), 'equity_nonpositive':True}) is None


def test_missing_financials_remain_explicit_and_threshold_is_adjustable():
    assert assess(metrics())['verified']
    partial=assess({'pbr':.4})
    assert not partial['verified'] and '자본' in partial['missing']
    assert assess({**metrics(), 'pbr':.7}, .8)['discount']==pytest.approx(30)


def test_report_overlap_uses_all_results_and_latest_metrics(tmp_path, monkeypatch):
    from app.db import connect, dumps
    from app.discovery.store import replace_catalog
    from app.dashboard import build_report
    from app.web import render
    monkeypatch.setenv('INVEST_DB',str(tmp_path/'book.db'))
    c=connect()
    rows=[dict(id=f'US:NASDAQ:{code}:stock',market='US',exchange='NASDAQ',code=code,ticker=code,name=code,type='stock',price=10,currency='USD') for code in ['AAA','BBB']]
    replace_catalog(c,'US',rows,'Exchange','2026-10-01T00:00:00Z',True)
    for row in rows:
        data={'score_version':'value-v1','analysis_status':'analyzable','total':80,'metrics':{**metrics(),'currency':'USD','price':10},'valuation':{}}
        c.execute('INSERT INTO stock_scores VALUES(?,?,?,?,?)',('2026-10-10',row['ticker'],'US',80,dumps(data)))
    c.commit()
    r=build_report(c,limit=1)
    assert len(r['book_candidates'])==2
    assert all(x['overlap']==['가치투자1','섹터주도주'] for x in r['book_candidates'])
    page=render(r,static=True)
    assert page.index('data-tab="value-panel"')<page.index('data-tab="book-panel"')<page.index('data-tab="news-candidates-panel"')<page.index('data-tab="observation-panel"')
    assert 'class="overlap-row"' in page
    assert 'data-book-pbr="0.3"' in page
    c.close()
