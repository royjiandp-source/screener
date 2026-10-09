"""Relative returns compare adjusted series on identical trading dates."""
import pandas as pd
from .leadership import relative_strength

# Investable broad-market proxies: both series include dividend/split adjustments.
BENCHMARKS={'KR':'069500.KS','US':'SPY','SG':'ES3.SI'}


def price_signals(asset,benchmark):
    out={k:None for k in ('rs_3m','rs_6m','rs_12m')}
    out['price_1m']=monthly_prices(asset)
    if 'Close' not in asset or 'Close' not in benchmark:return out
    merged=pd.concat([asset['Close'].rename('asset'),benchmark['Close'].rename('benchmark')],axis=1,sort=True).dropna().sort_index()
    merged=merged[~merged.index.duplicated(keep='last')]
    for label,period in [('rs_3m',63),('rs_6m',126),('rs_12m',252)]:
        if len(merged)>period:
            out[label]=relative_strength(merged['asset'].iloc[-period-1:].tolist(),merged['benchmark'].iloc[-period-1:].tolist())
            out['return_'+label[3:]]=(float(merged['asset'].iloc[-1])/float(merged['asset'].iloc[-period-1])-1)*100
    if 'Volume' in asset and len(asset)>=63:
        value=(asset['Close']*asset['Volume']).dropna()
        out['turnover_20d']=float(value.iloc[-20:].mean())
        old=float(value.iloc[-63:-20].mean())
        out['turnover_change']=float(value.iloc[-20:].mean())/old-1 if old>0 else None
    out['as_of']=merged.index[-1].date().isoformat() if len(merged) else None
    out['return_basis']='dividend_and_split_adjusted_fund_proxy'
    out['adjustment']='Yahoo auto_adjust=True for both; ETF fees, tracking error and index coverage apply'
    return out


def monthly_prices(asset):
    """Actual adjusted daily closes over the latest calendar month."""
    if 'Close' not in asset:return None
    series=asset['Close'].dropna().sort_index()
    series=series[~series.index.duplicated(keep='last')]
    series=series[(series>0) & series.map(lambda x: pd.notna(x) and float('-inf')<x<float('inf'))]
    if len(series)<2:return None
    cutoff=series.index[-1]-pd.DateOffset(months=1)
    before=series[series.index<=cutoff]
    start=before.index[-1] if len(before) else cutoff
    series=series[series.index>=start]
    if len(series)<2:return None
    return {'points':[{'date':d.date().isoformat(),'close':float(v)} for d,v in series.items()],
            'start':series.index[0].date().isoformat(),'end':series.index[-1].date().isoformat(),
            'return_pct':(float(series.iloc[-1])/float(series.iloc[0])-1)*100,
            'source':'Yahoo Finance','basis':'dividend_and_split_adjusted',
            'partial':not len(before)}
