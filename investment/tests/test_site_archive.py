"""Site builds preserve daily investment reports alongside stock reports."""
import runpy
from pathlib import Path


def builder():
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / 'make_site.py'))['build_site']


def write_investment(root, generated, content):
    page=root/'docs'/'invest'/'index.html'
    page.parent.mkdir(parents=True,exist_ok=True)
    page.write_text(f'<html><head><meta name="report-generated" content="{generated}"></head><body>{content}</body></html>',encoding='utf-8')
    return page


def test_investment_archive_keeps_history_and_lists_both_report_types(tmp_path):
    build=builder()
    first=write_investment(tmp_path,'2026-10-07T08:00:00+08:00','First investment report')
    first_content=first.read_text()
    build(tmp_path)
    second=write_investment(tmp_path,'2026-10-07T23:30:00+00:00','Second investment report')
    stock=tmp_path/'strong_20261008.html';stock.write_text('Stock report')
    build(tmp_path)
    archive=tmp_path/'docs'/'reports'
    assert (archive/'investment_20261007.html').read_text()==first_content
    assert (archive/'investment_20261008.html').read_text()==second.read_text()
    assert (archive/'strong_20261008.html').read_text()=='Stock report'
    index=(tmp_path/'docs'/'index.html').read_text()
    assert 'reports/investment_20261008.html' in index
    assert 'reports/strong_20261008.html' in index
    assert index.index('investment_20261008.html')<index.index('investment_20261007.html')
    assert 'AI Investment Ideas' in index
    assert 'Open latest report' not in index


def test_rebuild_does_not_relabel_old_investment_as_today(tmp_path):
    build=builder()
    write_investment(tmp_path,'2026-10-06T08:00:00+08:00','Stored report')
    build(tmp_path);build(tmp_path)
    assert [p.name for p in (tmp_path/'docs'/'reports').glob('investment_*.html')]==['investment_20261006.html']


def test_missing_investment_page_does_not_break_stock_report_build(tmp_path):
    build=builder()
    (tmp_path/'strong_20261008.html').write_text('Stock report')
    build(tmp_path)
    assert not list((tmp_path/'docs'/'reports').glob('investment_*.html'))
    assert 'reports/strong_20261008.html' in (tmp_path/'docs'/'index.html').read_text()
