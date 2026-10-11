"""Low-PBR screening, independent of the DCF value score."""
from .valuation import finite


def assess(metrics, max_pbr=.5):
    pbr = metrics.get('pbr')
    if not finite(pbr) or not 0 < pbr <= max_pbr:
        return None
    equity, margin, ocf = (metrics.get(k) for k in ('equity', 'op_margin', 'ocf'))
    # Missing inputs do not become passing checks; confirmed losses are excluded.
    if metrics.get('equity_nonpositive') or any(finite(v) and v <= 0 for v in (equity, margin, ocf)):
        return None
    missing = [label for label, v in [('자본', equity), ('영업이익률', margin), ('영업현금흐름', ocf), ('부채비율', metrics.get('debt_ratio')), ('ROE', metrics.get('roe'))] if not finite(v)]
    return {'pbr': pbr, 'discount': (1-pbr)*100, 'missing': missing,
            'status': '기본 재무조건 충족' if not missing else '자료 부족 · 검토 후보',
            'verified': not missing}
