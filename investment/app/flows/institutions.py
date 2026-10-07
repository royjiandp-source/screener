"""Quarterly holdings changes are not inferred execution-day purchases."""
from ..valuation import finite


def holdings_change(previous,current):
    return {name+'_change':current[name]-previous[name] if finite(previous.get(name)) and finite(current.get(name)) else None for name in ('shares','value')}


def institution_changes(records):
    """Compare disclosed share holdings by manager; missing positions are not trades."""
    groups={}
    for r in records:
        d=r['data']
        if not d.get('manager') or d.get('option') or d.get('other_manager') or d.get('share_type','SH')!='SH':continue
        key=(d['manager'],r['period'])
        stamp=r['available_at']
        group=groups.get(key)
        if not group or stamp>group['stamp']:groups[key]={'stamp':stamp,'rows':[d]}
        elif stamp==group['stamp']:group['rows'].append(d)
    managers={}
    for (manager,period),g in groups.items():
        rows=g['rows'];currency={d.get('currency') for d in rows}
        if len(currency)!=1:continue
        # Multiple rows are separate discretion positions from a resolved filing.
        current={'shares':sum(d['shares'] for d in rows) if all(finite(d.get('shares')) for d in rows) else None,'value':sum(d['value'] for d in rows) if all(finite(d.get('value')) for d in rows) else None,'currency':next(iter(currency)),'complete':all(d.get('complete') for d in rows)}
        managers.setdefault(manager,[]).append((period,current,g['stamp']))
    out=[]
    for manager,quarters in managers.items():
        quarters.sort();period,current,available=quarters[-1]
        previous=quarters[-2] if len(quarters)>1 else None
        comparable=previous and previous[1]['currency']==current['currency']
        change=holdings_change(previous[1],current) if comparable else {'shares_change':None,'value_change':None}
        out.append({'manager':manager,'quarter':period,'previous_quarter':previous[0] if previous else None,'available_at':available,'shares':current['shares'],'value':current['value'],'currency':current['currency'],**change,'note':'공개된 보유 변화이며 실제 거래일·매수금액이 아닙니다. 부재 종목을 자동으로 신규·청산 처리하지 않습니다.'})
    return out
