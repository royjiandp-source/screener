"""Two independent screening tracks built from active exchange evidence."""
from bisect import bisect_right
from collections import defaultdict

from .countries import SEARCH_MARKETS
from .db import loads, now
from .discovery.store import init, search, health
from .filings.common import utc
from .signals.leadership import leadership
from .valuation import finite

CORPORATE_TYPES = ('stock', 'adr')
ADJUSTED = 'dividend_and_split_adjusted_fund_proxy'


def signal_status(values):
    values = [v for v in values if finite(v)]
    if not values:
        return 'unknown'
    if all(v > 0 for v in values):
        return 'improving'
    if all(v < 0 for v in values):
        return 'weakening'
    return 'mixed'


def _page(rows, offset, limit):
    return {'items': rows[offset:offset+limit], 'total': len(rows), 'offset': offset, 'limit': limit}


def build_report(con, market=None, query='', min_score=60, observation_offset=0, value_offset=0, limit=50):
    if market and market not in SEARCH_MARKETS:
        raise ValueError('지원 시장은 한국·싱가포르·미국입니다.')
    if not finite(min_score) or not 0 <= min_score <= 100:
        raise ValueError('점수는 0~100 사이여야 합니다.')
    init(con)
    catalog = search(con, '', market, limit=1000000)['items']
    matched = {x['id']:x for x in (search(con, query, market, limit=1000000)['items'] if query.strip() else catalog)}
    by_id = {x['id']: x for x in catalog}
    corporations = [x for x in catalog if x['type'] in CORPORATE_TYPES]
    analyses = {}
    for row in con.execute('SELECT ticker,market,day,data FROM stock_scores s WHERE day=(SELECT MAX(day) FROM stock_scores newer WHERE newer.ticker=s.ticker)'):
        data = loads(row['data'], {})
        analyses[(row['market'], row['ticker'])] = {**data, 'day': row['day']}
    records = defaultdict(list)
    latest = {}
    cutoff = utc()
    for row in con.execute('SELECT * FROM flow_snapshots WHERE observed_at<=? AND available_at<=? ORDER BY period DESC,available_at DESC,id DESC', (cutoff, cutoff)):
        if row['listing_id'] not in by_id:
            continue
        record = {**dict(row), 'data': loads(row['data'], {})}
        records[row['listing_id']].append(record)
        latest.setdefault((row['listing_id'], row['kind']), record)

    observations = {}
    rank_pools = defaultdict(list)
    groups = defaultdict(list)
    for item in corporations:
        rec = latest.get((item['id'], 'leadership'), {})
        data = rec.get('data', {})
        signals = data.get('signals', {})
        date = data.get('period')
        valid = signals.get('return_basis') == ADJUSTED and date and date == signals.get('as_of') and date <= cutoff[:10]
        data = data if valid else {}
        signals = dict(data.get('signals', {}))
        observations[item['id']] = (data, signals)
        if all(finite(signals.get(k)) for k in ('rs_3m','rs_6m','rs_12m','turnover_change')):
            rank_pools[(item['market'], date)].append((item['id'], sum(signals[k] for k in ('rs_3m','rs_6m','rs_12m'))/3, signals['turnover_change']))
        for label in {e['label'] for e in item['evidence']}:
            groups[(item['market'], label)].append(item['id'])
    rank_members = {key:{r[0] for r in pool} for key,pool in rank_pools.items()}
    sorted_pools = {key: (sorted(r[1] for r in rows), sorted(r[2] for r in rows)) for key, rows in rank_pools.items()}

    values = []
    for item in corporations:
        a = analyses.get((item['market'], item['ticker']), {})
        if a.get('score_version') == 'value-v1' and a.get('analysis_status') == 'analyzable' and finite(a.get('total')) and a['total'] >= min_score:
            values.append({'listing': item, 'analysis': a})
    values.sort(key=lambda r: (-r['analysis']['total'], r['listing']['market'], r['listing']['code']))

    fund_by_ticker = defaultdict(list)
    fund_by_sector = defaultdict(list)
    fund_by_listing = defaultdict(list)
    fund_catalog = search(con, '', None, limit=1000000)['items'] if market else catalog
    # Read foreign fund snapshots as well; links require resolved company identities.
    fund_ids = {f['id'] for f in fund_catalog if f['type']=='etf'}
    for row in con.execute('SELECT * FROM flow_snapshots WHERE observed_at<=? AND available_at<=? ORDER BY period DESC,available_at DESC,id DESC',(cutoff,cutoff)):
        if row['listing_id'] in fund_ids:
            latest.setdefault((row['listing_id'],row['kind']),{**dict(row),'data':loads(row['data'],{})})
    for fund in fund_catalog:
        if fund['type']!='etf':
            continue
        for evidence in fund['evidence']:
            fund_by_sector[(fund['market'],evidence['label'])].append(fund)
        holdings = latest.get((fund['id'],'etf_holdings'), {})
        for h in holdings.get('data',{}).get('holdings',[]):
            if h.get('listing_id') in by_id:
                fund_by_listing[h['listing_id']].append((fund,h['weight']))
            else:
                fund_by_ticker[(fund['market'],h['ticker'])].append((fund,h['weight']))

    breadth_cache = {}
    rows = []
    for item in corporations:
        if item['id'] not in matched:
            continue
        lid = item['id']
        data, signals = observations[lid]
        labels = [e['label'] for e in item['evidence']]
        matching_labels=matched[lid].get('matched_labels',[])
        sector = matching_labels[0] if matching_labels else labels[0] if labels else '미분류'
        members = groups.get((item['market'], sector), []) if sector!='미분류' else []
        date = data.get('period')
        breadth_key=(item['market'],sector,date)
        if breadth_key not in breadth_cache:
            breadth = {'status':'unknown', 'as_of':date, 'total_members':len(members)}
            for term in ('3m','6m'):
                sample = [observations[m][1] for m in members if date and observations[m][0].get('period') == date and finite(observations[m][1].get('rs_'+term))]
                rising = [s['return_'+term] > 0 for s in sample if finite(s.get('return_'+term))]
                breadth.update({'sample_'+term:len(sample), 'strong_'+term:sum(s['rs_'+term]>0 for s in sample)/len(sample) if sample else None,
                                'rising_'+term:sum(rising)/len(rising) if rising else None, 'rising_sample_'+term:len(rising)})
            if breadth['sample_3m'] >= 2 and breadth['sample_6m'] >= 2:
                strong = (breadth['strong_3m'], breadth['strong_6m'])
                breadth['status'] = ('improving' if all(x > .5 for x in strong)
                                     else 'weakening' if all(x < .5 for x in strong) else 'mixed')
            breadth_cache[breadth_key]=breadth
        breadth=breadth_cache[breadth_key]
        pool = rank_pools.get((item['market'], date), [])
        if len(pool) >= 20 and lid in rank_members[(item['market'],date)]:
            ranks, liquidities = sorted_pools[(item['market'], date)]
            signals['rs_percentile'] = bisect_right(ranks, sum(signals[k] for k in ('rs_3m','rs_6m','rs_12m'))/3)/len(pool)
            signals['liquidity_percentile'] = bisect_right(liquidities, signals['turnover_change'])/len(pool)
        observed = {**leadership(data.get('trends', {}), signals, len(pool)), 'as_of':date, 'source':data.get('source'), 'benchmark':data.get('benchmark')}
        demand = latest.get((lid,'demand'), {})
        measurements = demand.get('data', {}).get('measurements', [])
        demand_values = [(m['current']-m['previous'])*(-1 if m['metric']=='inventory' else 1) for m in measurements]
        estimates = latest.get((lid,'earnings_estimates'), {})
        e = estimates.get('data', {})
        change = (e['current']-e['previous'])/abs(e['previous']) if finite(e.get('current')) and finite(e.get('previous')) and e['previous'] != 0 else None
        peers = [latest.get((m,'earnings_estimates'), {}) for m in members]
        peers = [p for p in peers if estimates and p.get('period')==estimates.get('period') and p.get('data', {}).get('forecast_period')==e.get('forecast_period')]
        analysis = analyses.get((item['market'],item['ticker']), {})
        valuation = analysis.get('valuation', {}) if analysis.get('score_version')=='value-v1' else {}
        base = valuation.get('scenarios', {}).get('base', {}) if valuation.get('status')=='estimated' else {}
        checks = {
            'demand':{'coverage':demand.get('data',{}).get('coverage'), 'note':demand.get('data',{}).get('note'), 'status':signal_status(demand_values), 'measurements':measurements, 'source':demand.get('data',{}).get('source'), 'as_of':demand.get('period')},
            'profits':{'status':signal_status(list(data.get('trends',{}).values())), 'trends':data.get('trends',{}), 'source':data.get('source'), 'periods':data.get('financial_periods',{})},
            'estimates':{'status':signal_status([change]), 'change':change, 'forecast_period':e.get('forecast_period'), 'source':e.get('source'), 'as_of':estimates.get('period'), 'sample':len(peers),
                         'upward_ratio':sum(p['data']['current']>p['data']['previous'] for p in peers)/len(peers) if peers else None},
            'strength':{'status':signal_status([signals.get('rs_3m'),signals.get('rs_6m')]), 'signals':signals, 'benchmark':data.get('benchmark'), 'as_of':date},
            'breadth':breadth,
            'price':{'status':'unknown' if not finite(base.get('safety_margin')) else 'improving' if base['safety_margin']>=20 else 'weakening' if base['safety_margin']<0 else 'mixed',
                     'safety_margin':base.get('safety_margin'), 'reverse_dcf':valuation.get('reverse_dcf'), 'analysis_day':analysis.get('day')},
        }
        links = [r for r in records[lid] if r['kind'] in ('institution_trades','institution_holdings')]
        linked = {fund['id']:(fund,weight) for fund,weight in [*fund_by_ticker.get((item['market'],item['ticker']),[]),*fund_by_listing.get(lid,[])]}
        if sector!='미분류':
            for fund in fund_by_sector.get((item['market'],sector),[]):
                linked.setdefault(fund['id'],(fund,None))
        for fund,weight in linked.values():
            for kind in ('etf_holdings','etf_reported_flow','etf_nav'):
                rec = latest.get((fund['id'],kind))
                if rec:
                    links.append({**rec, 'fund':fund['ticker'], 'weight':weight, 'relation':'holdings' if weight is not None else 'sector'})
        rows.append({'listing':item, 'sector':sector, 'checks':checks, 'leadership':observed, 'analysis':analysis, 'etf_institution':links})
    rows.sort(key=lambda r: (-(r['leadership']['score'] if finite(r['leadership']['score']) else -1), -len(r['etf_institution']), r['listing']['market'],r['listing']['code']))
    source_health = health(con)
    coverage = {}
    for code in SEARCH_MARKETS:
        subset = [x for x in corporations if x['market']==code]
        snapshot = con.execute('SELECT complete,source,observed_at FROM catalog_snapshots WHERE market=? ORDER BY active DESC,id DESC LIMIT 1',(code,)).fetchone()
        coverage[code] = {'listings':len([x for x in catalog if x['market']==code]), 'companies':len(subset),
                          'signals_collected':sum(bool(observations[x['id']][0]) for x in subset),
                          'signal_failures':sum(latest.get((x['id'],'signal_collection_status'),{}).get('data',{}).get('status')=='failed' for x in subset),
                          'analyzed':sum(bool(analyses.get((code,x['ticker']))) for x in subset),
                          'eligible':sum(v['listing']['market']==code for v in values),
                          'complete':bool(snapshot and snapshot['complete']), 'as_of':snapshot['observed_at'] if snapshot else None,
                          'source':snapshot['source'] if snapshot else None, 'status':source_health.get(code,{}).get('status','not_collected')}
    return {'generated':now().isoformat(timespec='minutes'), 'selected_market':market, 'query':query, 'min_score':min_score,
            'observations':_page(rows,observation_offset,limit), 'value_candidates':_page(values,value_offset,limit), 'coverage':coverage}
