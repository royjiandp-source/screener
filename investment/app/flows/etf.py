"""Creation estimate requires comparable NAV and outstanding share units."""
from ..valuation import finite


def estimate_creation_flow(previous,current):
    out={'flow':None,'method':'estimated_creation','currency':current.get('currency'),'reason':None}
    if previous.get('currency')!=current.get('currency') or not current.get('currency'):
        out['reason']='currency_mismatch'; return out
    if any(not finite(r.get(k)) or r[k]<=0 for r in (previous,current) for k in ('nav','shares')):
        out['reason']='missing_nav_or_shares'; return out
    if not previous.get('corporate_actions_verified') or not current.get('corporate_actions_verified'):
        out['reason']='unverified_corporate_actions'; return out
    if previous.get('unresolved_corporate_action') or current.get('unresolved_corporate_action'):
        out['reason']='ambiguous_corporate_action'; return out
    factor=current.get('share_adjustment_factor',1)
    if not finite(factor) or factor<=0: out['reason']='invalid_share_adjustment'; return out
    out['flow']=current['nav']*(current['shares']-previous['shares']*factor)
    return out
