"""Relative returns compare adjusted series on identical trading dates."""
import pandas as pd
from .leadership import relative_strength

# Investable broad-market proxies: both series include dividend/split adjustments.
BENCHMARKS={'KR':'069500.KS','US':'SPY','JP':'1306.T','TW':'0050.TW','HK':'2800.HK','SG':'ES3.SI'}


def price_signals(asset,benchmark):
    out={k:None for k in ('rs_3m','rs_6m','rs_12m')}
    if 'Close' not in asset or 'Close' not in benchmark:return out
    merged=pd.concat([asset['Close'].rename('asset'),benchmark['Close'].rename('benchmark')],axis=1,sort=True).dropna().sort_index()
    merged=merged[~merged.index.duplicated(keep='last')]
    for label,period in [('rs_3m',63),('rs_6m',126),('rs_12m',252)]:
        if len(merged)>period:out[label]=relative_strength(merged['asset'].iloc[-period-1:].tolist(),merged['benchmark'].iloc[-period-1:].tolist())
    if 'Volume' in asset and len(asset)>=63:
        value=(asset['Close']*asset['Volume']).dropna()
        out['turnover_20d']=float(value.iloc[-20:].mean())
        old=float(value.iloc[-63:-20].mean())
        out['turnover_change']=float(value.iloc[-20:].mean())/old-1 if old>0 else None
    out['as_of']=merged.index[-1].date().isoformat() if len(merged) else None
    out['return_basis']='dividend_and_split_adjusted_fund_proxy'
    out['adjustment']='Yahoo auto_adjust=True for both; ETF fees, tracking error and index coverage apply'
    return out
