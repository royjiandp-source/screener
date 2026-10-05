"""News analysis (Gemini) + theme engine. / 뉴스 분석 + 테마 엔진.

Each article -> themes, sentiment, confidence, affected industries.
Articles are merged into the market themes listed in themes.json.
Without GEMINI_API_KEY, a keyword matcher is used instead.
"""
import datetime as dt
import json
import os

from .db import dumps, loads

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
BATCH = 25


def keyword_tag(text: str, themes: dict) -> list[str]:
    t = f" {text.lower()} "
    return [name for name, cfg in themes.items() if any(k in t for k in cfg["keywords"])]


def _gemini_batch(articles: list, themes: dict) -> dict:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    theme_list = "\n".join(f"- {n}: {', '.join(c['industries'])}" for n, c in themes.items())
    items = "\n".join(f'{a["id"]}. {a["title"]} | {a["content"][:250]}' for a in articles)
    prompt = f"""You are an equity research analyst. Classify each news item.

Allowed themes (use ONLY these names; use [] if none fit):
{theme_list}

For each item return: id, themes (list), sentiment ("Positive"|"Neutral"|"Negative" for the stocks
in those themes), confidence (0-100), affectedIndustries (list of short industry names).

News:
{items}

Return a JSON array only."""
    resp = client.models.generate_content(
        model=MODEL, contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.1})
    data = json.loads(resp.text)
    return {int(d["id"]): d for d in data if isinstance(d, dict) and "id" in d}


def analyze_pending(con, themes: dict, limit: int = 400) -> dict:
    rows = [dict(r) for r in con.execute(
        "SELECT id,title,content FROM articles WHERE analyzed=0 ORDER BY id DESC LIMIT ?", (limit,))]
    use_ai = bool(os.environ.get("GEMINI_API_KEY"))
    done, ai_errors = 0, 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        result = {}
        if use_ai:
            try:
                result = _gemini_batch(batch, themes)
            except Exception as e:
                ai_errors += 1
                print(f"[themes] Gemini error, using keywords: {type(e).__name__}: {e}")
        for a in batch:
            r = result.get(a["id"])
            if r:
                tags = [t for t in r.get("themes", []) if t in themes]
                sent = r.get("sentiment", "Neutral")
                if sent not in ("Positive", "Neutral", "Negative"):
                    sent = "Neutral"
                conf = int(r.get("confidence") or 0)
                inds, method = r.get("affectedIndustries", []), "gemini"
            else:
                tags = keyword_tag(f'{a["title"]} {a["content"]}', themes)
                sent, conf, inds, method = "Neutral", 40, [], "keyword"
            con.execute("UPDATE articles SET analyzed=1, method=?, themes=?, sentiment=?,"
                        " confidence=?, industries=? WHERE id=?",
                        (method, dumps(tags), sent, conf, dumps(inds), a["id"]))
            done += 1
        con.commit()
    return {"analyzed": done, "ai": use_ai, "ai_errors": ai_errors}


def theme_momentum(con, themes: dict, days: int = 7) -> dict:
    """News count, positive/negative ratio and top headlines per theme."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    out = {t: {"news_count": 0, "positive": 0, "negative": 0, "headlines": []} for t in themes}
    for r in con.execute("SELECT title,url,themes,sentiment,confidence FROM articles"
                         " WHERE analyzed=1 AND published>=? ORDER BY published DESC", (since,)):
        for t in loads(r["themes"], []):
            if t not in out:
                continue
            o = out[t]
            o["news_count"] += 1
            o["positive"] += r["sentiment"] == "Positive"
            o["negative"] += r["sentiment"] == "Negative"
            if len(o["headlines"]) < 5:
                o["headlines"].append({"title": r["title"], "url": r["url"], "sentiment": r["sentiment"]})
    for o in out.values():
        n = o["news_count"]
        o["pos_ratio"] = round(o["positive"] / n, 3) if n else 0.0
        o["neg_ratio"] = round(o["negative"] / n, 3) if n else 0.0
    return out
