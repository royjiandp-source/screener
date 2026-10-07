"""Explicit source imports cover markets whose automatic access is unavailable."""
from .store import replace_catalog,classify,set_health
from ..filings.common import utc


def import_catalog(con,market,rows,source,observed_at,complete):
    if not source.strip():raise ValueError('자료 출처가 필요합니다.')
    for r in rows:
        if r.get('themes') and not r.get('theme_evidence'):raise ValueError('테마는 사업 관련 근거가 필요합니다.')
    sid=replace_catalog(con,market,rows,source,observed_at,complete)
    if complete:
        for r in rows:
            for field,kind in [('industry','industry'),('sector','industry')]:
                if r.get(field):classify(con,r['id'],r[field],kind,source,r[field],observed_at)
            for theme in r.get('themes',[]):
                if not r.get('theme_evidence'):raise ValueError('테마는 사업 관련 근거가 필요합니다.')
                classify(con,r['id'],theme,'theme',source,r['theme_evidence'],observed_at)
    set_health(con,market,{'status':'imported','listings':len(rows),'source':source,'automatic_connection':False})
    return sid
