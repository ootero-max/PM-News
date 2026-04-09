#!/usr/bin/env python3
"""
Product and Tech News Aggregator
Fetches recent articles via Google News RSS, stores them in JSON,
and generates a polished responsive HTML digest page.

Categories: UI/UX, Product, Health Tech, AI
"""

import json
import hashlib
import html
import os
import sys
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import quote
from xml.etree import ElementTree

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
JSON_PATH = SCRIPT_DIR / "news_store.json"
HTML_PATH = SCRIPT_DIR / "news_digest.html"

CATEGORIES = {
    "UI/UX": [
        "UI UX design trends",
        "user experience design news",
        "UX research updates",
    ],
    "Product": [
        "product management news",
        "product strategy tech",
        "product launches technology",
    ],
    "Health Tech": [
        "health technology news",
        "digital health innovation",
        "healthtech startup news",
    ],
    "AI": [
        "artificial intelligence news",
        "AI technology breakthroughs",
        "generative AI updates",
    ],
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DAYS_BACK = 7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def article_id(url: str) -> str:
    """Stable hash for deduplication."""
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]


def clean_html(raw: str) -> str:
    """Strip HTML tags and decode entities for plain-text excerpts."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len].rsplit(" ", 1)[0].rstrip(".,;:") + "…"


def fetch_url(url: str, timeout: int = 15) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# RSS fetching
# ---------------------------------------------------------------------------


def fetch_google_news_rss(query: str) -> list[dict]:
    """Return articles from Google News RSS for *query* (last 7 days)."""
    encoded = quote(query)
    url = (
        f"https://news.google.com/rss/search?"
        f"q={encoded}+when:7d&hl=en-US&gl=US&ceid=US:en"
    )
    articles = []
    try:
        data = fetch_url(url)
        root = ElementTree.fromstring(data)
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date_raw = item.findtext("pubDate", "").strip()
            description = clean_html(item.findtext("description", ""))
            source = item.findtext("source", "").strip()

            if not link:
                continue

            # Parse date
            pub_date = ""
            pub_ts = 0
            if pub_date_raw:
                try:
                    dt = parsedate_to_datetime(pub_date_raw)
                    pub_date = dt.strftime("%Y-%m-%d")
                    pub_ts = int(dt.timestamp())
                except Exception:
                    pub_date = pub_date_raw

            excerpt = truncate(description) if description else ""

            articles.append(
                {
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "pub_ts": pub_ts,
                    "excerpt": excerpt,
                    "source": source,
                }
            )
    except Exception as exc:
        print(f"  [warn] RSS fetch failed for '{query}': {exc}", file=sys.stderr)

    return articles


# ---------------------------------------------------------------------------
# Store management (JSON)
# ---------------------------------------------------------------------------


def load_store() -> dict:
    if JSON_PATH.exists():
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as fh:
                store = json.load(fh)
            # Backward compat: ensure every entry has an excerpt field
            for art in store.get("articles", []):
                art.setdefault("excerpt", "")
                art.setdefault("pub_ts", 0)
                art.setdefault("source", "")
            return store
        except (json.JSONDecodeError, KeyError):
            pass
    return {"articles": [], "seen_ids": []}


def save_store(store: dict) -> None:
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2, ensure_ascii=False)


def merge_articles(store: dict, new_articles: list[dict], category: str) -> int:
    """Merge *new_articles* into *store*, returning count of truly new ones."""
    seen = set(store.get("seen_ids", []))
    added = 0
    for art in new_articles:
        aid = article_id(art["link"])
        if aid in seen:
            continue
        seen.add(aid)
        art["id"] = aid
        art["category"] = category
        store["articles"].append(art)
        added += 1
    store["seen_ids"] = list(seen)
    return added


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------


def generate_html(articles: list[dict]) -> str:
    # Sort newest-first
    sorted_arts = sorted(articles, key=lambda a: a.get("pub_ts", 0), reverse=True)

    cards_html = []
    for art in sorted_arts:
        title = html.escape(art.get("title", "Untitled"))
        link = html.escape(art.get("link", "#"))
        date = html.escape(art.get("pub_date", ""))
        category = html.escape(art.get("category", ""))
        excerpt = html.escape(art.get("excerpt", ""))
        source = html.escape(art.get("source", ""))

        source_badge = f'<span class="source">{source}</span>' if source else ""
        excerpt_block = f'<p class="excerpt">{excerpt}</p>' if excerpt else ""

        cards_html.append(f"""\
      <article class="card" data-category="{category}">
        <div class="card-meta">
          <span class="badge">{category}</span>
          <span class="date">{date}</span>
        </div>
        <h2 class="card-title"><a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a></h2>
        {excerpt_block}
        <div class="card-footer">
          {source_badge}
          <a href="{link}" target="_blank" rel="noopener noreferrer" class="read-more">Read article &rarr;</a>
        </div>
      </article>""")

    cards_joined = "\n".join(cards_html) if cards_html else '<p class="empty">No articles found yet. Run the script to fetch news.</p>'

    now_str = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dazos PM News</title>
<style>
  :root {{
    --bg: #0b1929;
    --bg2: #0f2132;
    --card: #132840;
    --card2: #1a3350;
    --border: #1e3d5c;
    --accent: #00aaff;
    --accent2: #0088cc;
    --text: #ffffff;
    --text2: #8aaccc;
    --text3: #4a7a9b;
    --radius: 12px;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: radial-gradient(ellipse at 50% 40%, #0f2d4a 0%, var(--bg) 70%);
    background-attachment: fixed;
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }}

  /* Header */
  header {{
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 2rem 1.5rem 1.5rem;
    text-align: center;
  }}
  header h1 {{
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.02em;
  }}
  header h1 span {{ color: var(--accent); }}
  .subtitle {{
    color: var(--text2);
    font-size: 0.875rem;
    margin-top: 0.25rem;
  }}

  /* Filters */
  .filters {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.5rem;
    padding: 1rem 1.5rem;
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  .filters button {{
    padding: 0.45rem 1.1rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    color: var(--text2);
    font-size: 0.85rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }}
  .filters button:hover {{
    border-color: var(--accent);
    color: var(--accent);
    background: var(--card2);
  }}
  .filters button.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}

  /* Grid */
  .container {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 1.5rem;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 1.25rem;
  }}

  /* Card */
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    transition: box-shadow 0.2s ease, transform 0.2s ease;
  }}
  .card:hover {{
    box-shadow: 0 4px 24px rgba(0, 170, 255, 0.08);
    transform: translateY(-2px);
    border-color: var(--accent2);
  }}
  .card.hidden {{ display: none; }}

  .card-meta {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }}
  .badge {{
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: rgba(0, 170, 255, 0.12);
    color: var(--accent);
  }}
  .date {{
    font-size: 0.78rem;
    color: var(--text3);
  }}

  .card-title {{
    font-size: 1.05rem;
    font-weight: 600;
    line-height: 1.4;
    margin-bottom: 0.5rem;
  }}
  .card-title a {{
    color: var(--text);
    text-decoration: none;
  }}
  .card-title a:hover {{
    color: var(--accent);
  }}

  .excerpt {{
    font-size: 0.88rem;
    color: var(--text2);
    line-height: 1.55;
    flex: 1;
    margin-bottom: 1rem;
  }}

  .card-footer {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: auto;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
  }}
  .source {{
    font-size: 0.75rem;
    color: var(--text3);
    font-weight: 500;
  }}
  .read-more {{
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
  }}
  .read-more:hover {{ text-decoration: underline; }}

  .empty {{
    text-align: center;
    color: var(--text2);
    grid-column: 1 / -1;
    padding: 3rem 0;
  }}

  /* Count */
  .count {{
    text-align: center;
    font-size: 0.8rem;
    color: var(--text3);
    padding: 0.75rem 0 0;
  }}

  /* Footer */
  footer {{
    text-align: center;
    padding: 2rem 1rem;
    font-size: 0.78rem;
    color: var(--text3);
  }}

  /* Refresh bar */
  .refresh-bar {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    padding: 0.75rem 1.5rem;
    background: var(--card);
    border-bottom: 1px solid var(--border);
  }}
  .last-refreshed {{
    font-size: 0.8rem;
    color: var(--text3);
  }}
  .refresh-btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0.4rem 1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card2);
    color: var(--accent);
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }}
  .refresh-btn:hover {{
    background: var(--border);
    border-color: var(--accent);
  }}
  .refresh-btn.loading {{
    opacity: 0.6;
    pointer-events: none;
  }}
  .refresh-btn svg {{
    transition: transform 0.3s;
  }}
  .refresh-btn.loading svg {{
    animation: spin 0.8s linear infinite;
  }}
  @keyframes spin {{
    to {{ transform: rotate(360deg); }}
  }}

  @media (max-width: 700px) {{
    .grid {{ grid-template-columns: 1fr; }}
    header h1 {{ font-size: 1.35rem; }}
  }}
</style>
</head>
<body>

<header>
  <h1>Dazos <span>PM News</span></h1>
  <p class="subtitle">Weekly digest &middot; Updated {now_str}</p>
</header>

<div class="refresh-bar">
  <span class="last-refreshed" id="last-refreshed">Last refreshed: {now_str}</span>
  <button class="refresh-btn" id="refresh-btn" title="Refresh news">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
    Refresh
  </button>
</div>

<nav class="filters" id="filters">
  <button class="active" data-filter="All">All</button>
  <button data-filter="UI/UX">UI/UX</button>
  <button data-filter="Product">Product</button>
  <button data-filter="Health Tech">Health Tech</button>
  <button data-filter="AI">AI</button>
</nav>

<main class="container">
  <p class="count" id="count">{len(sorted_arts)} article{"s" if len(sorted_arts) != 1 else ""}</p>
  <div class="grid" id="grid">
{cards_joined}
  </div>
</main>

<footer>
  Dazos PM News &middot; {now_str}
</footer>

<script>
(function() {{
  const buttons = document.querySelectorAll('#filters button');
  const cards   = document.querySelectorAll('.card');
  const count   = document.getElementById('count');

  function update(filter) {{
    let visible = 0;
    cards.forEach(c => {{
      const show = filter === 'All' || c.dataset.category === filter;
      c.classList.toggle('hidden', !show);
      if (show) visible++;
    }});
    count.textContent = visible + ' article' + (visible !== 1 ? 's' : '');
  }}

  buttons.forEach(btn => {{
    btn.addEventListener('click', () => {{
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      update(btn.dataset.filter);
    }});
  }});

  // Refresh button
  const refreshBtn = document.getElementById('refresh-btn');
  const lastRefreshed = document.getElementById('last-refreshed');

  refreshBtn.addEventListener('click', async () => {{
    refreshBtn.classList.add('loading');
    refreshBtn.disabled = true;
    try {{
      const resp = await fetch('/refresh', {{ method: 'POST' }});
      if (resp.ok) {{
        const now = new Date().toLocaleString('en-US', {{
          year: 'numeric', month: 'long', day: 'numeric',
          hour: 'numeric', minute: '2-digit'
        }});
        lastRefreshed.textContent = 'Last refreshed: ' + now;
        window.location.reload();
      }}
    }} catch (e) {{
      console.error('Refresh failed', e);
    }} finally {{
      refreshBtn.classList.remove('loading');
      refreshBtn.disabled = false;
    }}
  }});
}})();
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("Loading existing store…")
    store = load_store()
    total_new = 0

    for category, queries in CATEGORIES.items():
        print(f"\n[{category}]")
        for q in queries:
            print(f"  Fetching: {q}")
            articles = fetch_google_news_rss(q)
            added = merge_articles(store, articles, category)
            total_new += added
            print(f"    Found {len(articles)} items, {added} new")

    save_store(store)
    print(f"\nStore saved → {JSON_PATH}")
    print(f"  Total articles: {len(store['articles'])}  |  New this run: {total_new}")

    html_content = generate_html(store["articles"])
    with open(HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(html_content)
    print(f"HTML generated → {HTML_PATH}")


if __name__ == "__main__":
    main()
