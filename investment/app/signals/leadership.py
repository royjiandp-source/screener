"""Observation signals are separate from valuation and predictive probabilities."""
import math


def relative_strength(asset,benchmark):
    if len(asset)<2 or len(asset)!=len(benchmark) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in [*asset,*benchmark]): return None
    return (asset[-1]/asset[0]/(benchmark[-1]/benchmark[0])-1)*100


def leadership(metrics,signals,sample_size):
    missing=[]
    rs=[signals.get(k) for k in ('rs_3m','rs_6m','rs_12m')]
    if any(v is None for v in rs): missing.append('3/6/12개월 상대강도')
    trends=[metrics.get(k) for k in ('revenue_change','margin_change','cashflow_change')]
    if sum(v is not None for v in trends)<2: missing.append('동일 기간 실적 개선 항목 2개')
    rank=signals.get('rs_percentile')
    if rank is None or sample_size<20: missing.append('비교 표본 20개와 상대강도 순위')
    if signals.get('liquidity_percentile') is None: missing.append('거래대금 순위')
    score=None
    if not missing:
        score=round(40*rank+40*sum(v>0 for v in trends if v is not None)/sum(v is not None for v in trends)+20*signals['liquidity_percentile'],1)
    return {'score':score,'missing':missing,'signals':signals,'trends':metrics,'sample_size':sample_size,'weights':{'relative_strength':40,'fundamentals':40,'liquidity':20},'note':'관찰 후보 지표이며 미래 수익률이나 주도주 확정 확률이 아닙니다.'}
