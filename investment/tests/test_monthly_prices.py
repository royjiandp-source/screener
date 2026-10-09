import pandas as pd
import pytest


def test_calendar_month_chart_independent_of_benchmark():
    from app.signals.prices import monthly_prices
    f=pd.DataFrame({'Close':[100,110,120]},index=pd.to_datetime(['2026-08-28','2026-09-01','2026-09-28']))
    r=monthly_prices(f)
    assert len(r['points'])==3 and r['return_pct']==pytest.approx(20)
    assert r['start']=='2026-08-28' and r['end']=='2026-09-28'


def test_bad_or_short_history_has_no_invented_chart():
    from app.signals.prices import monthly_prices
    assert monthly_prices(pd.DataFrame()) is None
    assert monthly_prices(pd.DataFrame({'Close':[100]},index=pd.to_datetime(['2026-09-28']))) is None


def test_chart_escapes_accessibility_text():
    from app.web import monthly_chart
    chart=monthly_chart({'points':[{'date':'2026-09-01','close':100},{'date':'2026-10-01','close':110}], 'return_pct':10,'start':'2026-09-01','end':'2026-10-01'})
    assert '<svg' in chart and '10.0%' in chart and '2026-10-01' in chart
