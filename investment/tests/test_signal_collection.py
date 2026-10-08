from test_dashboard import catalog, listing, con


def test_collection_records_failures_and_continues(con, monkeypatch):
    from app.pipeline import run_signals
    from app.discovery import profiles
    rows = [listing('A'), listing('B'), listing('F', kind='etf')]
    catalog(con, rows)
    called = []
    def collect(c, lid):
        called.append(lid)
        if lid == rows[0]['id']:
            raise ValueError('unavailable')
        return {'period': '2026-10-08', 'signals': {'rs_3m': 1}}
    monkeypatch.setattr(profiles, 'enrich_listing', collect)
    result = run_signals(con, ('US',), limit=2)
    assert called == [r['id'] for r in rows[:2]]
    assert result['collected'] == 1 and result['failed'] == 1
    assert result['remaining'] == 0


def test_collection_prioritizes_missing_and_rotates(con, monkeypatch):
    from app.pipeline import run_signals
    from app.discovery import profiles
    from app.discovery.store import save_flow
    rows = [listing('A'), listing('B')]
    catalog(con, rows)
    save_flow(con, rows[0]['id'], 'leadership', '2026-10-01', {'period': '2026-10-01'})
    called = []
    monkeypatch.setattr(profiles, 'enrich_listing', lambda c, lid: called.append(lid) or {'period': '2026-10-08'})
    result = run_signals(con, ('US',), limit=1)
    assert called == [rows[1]['id']]
    assert result['remaining'] == 1


def test_failure_is_not_retried_in_same_day(con, monkeypatch):
    from app.pipeline import run_signals
    from app.discovery import profiles
    catalog(con, [listing('A')])
    def fail(c, lid):
        raise ValueError('unavailable')
    monkeypatch.setattr(profiles, 'enrich_listing', fail)
    assert run_signals(con, ('US',), limit=1)['failed'] == 1
    assert run_signals(con, ('US',), limit=1)['attempted'] == 0


def test_small_batch_alternates_markets(con, monkeypatch):
    from app.pipeline import run_signals
    from app.discovery import profiles
    catalog(con, [listing('A'), listing('B')])
    catalog(con, [listing('C', 'KR')], 'KR')
    called = []
    monkeypatch.setattr(profiles, 'enrich_listing', lambda c, lid: called.append(lid) or {'period': '2026-10-08'})
    run_signals(con, ('US', 'KR'), limit=2)
    assert [lid.split(':')[0] for lid in called] == ['US', 'KR']
