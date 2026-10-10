from test_dashboard import con, listing, catalog, score


def test_market_price_thresholds_apply_to_both_tracks(con):
    from app.dashboard import build_report
    rows=[]
    for market,floor in [('KR',5000),('SG',1),('US',5)]:
        low=listing('LOW',market);low['price']=floor-.01
        edge=listing('EDGE',market);edge['price']=floor
        missing=listing('UNKNOWN',market);missing.pop('price')
        catalog(con,[low,edge,missing],market)
        for r in [low,edge,missing]:score(con,r)
        rows.append(edge)
    r=build_report(con)
    assert {x['listing']['id'] for x in r['observations']['items']}=={x['id'] for x in rows}
    assert len(r['value_candidates']['items'])==3


def test_company_search_expands_only_evidenced_industry(con):
    from app.dashboard import build_report
    from app.discovery.store import classify
    a,b,c=[listing(x,'KR') for x in ['A','B','C']]
    a['name']='삼성전자';catalog(con,[a,b],'KR')
    from app.discovery.store import replace_catalog
    replace_catalog(con,'KR',[c],'partial','2026-10-01T00:00:00Z',False)
    r=build_report(con,query='삼성전자')
    assert {x['listing']['id'] for x in r['observations']['items']}=={a['id'],b['id']}
    assert len(build_report(con,query='반도체')['observations']['items'])==2


def test_static_payload_preserves_results_beyond_first_page(con):
    from app.pipeline import static_report
    from app.web import render
    import json,re
    rows=[listing(str(i)) for i in range(55)];catalog(con,rows)
    page=render(static_report(con),static=True)
    data=json.loads(re.search(r'<script id="static-results" type="application/json">(.*?)</script>',page,re.S).group(1))
    assert len(data)==55 and data[0]['html'].startswith('<tr>')
