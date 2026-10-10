from test_dashboard import con,listing,catalog


def test_news_queue_requires_recent_positive_direct_company_match(con):
    from app.db import now
    from app.news_candidates import build_news_candidates
    a=listing('NVDA');a['name']='NVIDIA Corp';catalog(con,[a])
    for title in ['Nvidia wins contract for new chips','Nvidia denies supply agreement rumor','Market expansion continues']:
        con.execute('INSERT INTO articles(url,title,source,published,market) VALUES(?,?,?,?,?)',('https://example.com/'+title,title,'Publisher',now().isoformat(),'US'))
    r=build_news_candidates(con,[a],{a['id']})
    assert len(r)==1 and r[0]['signals']==['수주·계약 관련']
    assert build_news_candidates(con,[a],set())==[]


def test_news_section_is_below_both_existing_flows(con):
    from app.pipeline import report
    from app.web import render
    page=render(report(con),static=True)
    assert page.index('id="news-candidates-panel"')>page.index('id="value-panel"')
    assert page.count('data-result-table=')==2
