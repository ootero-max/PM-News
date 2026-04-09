#!/usr/bin/env php
<?php
/**
 * Product and Tech News Aggregator (PHP + SQLite)
 *
 * Fetches recent articles via Google News RSS, stores them in a SQLite
 * database with JSON document columns, and generates a polished
 * responsive HTML digest page.
 *
 * Categories: UI/UX, Product, Health Tech, AI
 *
 * Usage: php news_aggregator.php
 */

declare(strict_types=1);

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

define('SCRIPT_DIR', __DIR__);
define('DB_PATH',   SCRIPT_DIR . '/news_store.db');
define('HTML_PATH', SCRIPT_DIR . '/news_digest.html');

const CATEGORIES = [
    'UI/UX' => [
        'UI UX design trends',
        'user experience design news',
        'UX research updates',
    ],
    'Product' => [
        'product management news',
        'product strategy tech',
        'product launches technology',
    ],
    'Health Tech' => [
        'health technology news',
        'digital health innovation',
        'healthtech startup news',
    ],
    'AI' => [
        'artificial intelligence news',
        'AI technology breakthroughs',
        'generative AI updates',
    ],
];

const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    . 'AppleWebKit/537.36 (KHTML, like Gecko) '
    . 'Chrome/124.0.0.0 Safari/537.36';

const DAYS_BACK = 7;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function articleId(string $url): string
{
    return substr(hash('sha256', strtolower(trim($url))), 0, 16);
}

function cleanHtml(string $raw): string
{
    $text = strip_tags($raw);
    $text = html_entity_decode($text, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = preg_replace('/\s+/', ' ', $text);
    return trim($text);
}

function truncate(string $text, int $max = 200): string
{
    if (mb_strlen($text) <= $max) {
        return $text;
    }
    $cut = mb_substr($text, 0, $max);
    $lastSpace = mb_strrpos($cut, ' ');
    if ($lastSpace !== false) {
        $cut = mb_substr($cut, 0, $lastSpace);
    }
    return rtrim($cut, '.,;:') . '…';
}

function fetchUrl(string $url): string|false
{
    $context = stream_context_create([
        'http' => [
            'header'  => 'User-Agent: ' . USER_AGENT,
            'timeout' => 15,
        ],
        'ssl' => [
            'verify_peer'      => true,
            'verify_peer_name' => true,
        ],
    ]);

    $result = @file_get_contents($url, false, $context);
    return $result !== false ? $result : false;
}

// ---------------------------------------------------------------------------
// RSS Fetching
// ---------------------------------------------------------------------------

function fetchGoogleNewsRss(string $query): array
{
    $encoded = urlencode($query);
    $url = "https://news.google.com/rss/search?q={$encoded}+when:7d&hl=en-US&gl=US&ceid=US:en";

    $articles = [];

    $xml = fetchUrl($url);
    if ($xml === false) {
        fwrite(STDERR, "  [warn] RSS fetch failed for '{$query}'\n");
        return $articles;
    }

    // Suppress XML warnings for malformed feeds
    libxml_use_internal_errors(true);
    $feed = simplexml_load_string($xml);
    libxml_clear_errors();

    if ($feed === false) {
        fwrite(STDERR, "  [warn] XML parse failed for '{$query}'\n");
        return $articles;
    }

    $channel = $feed->channel ?? $feed;
    foreach ($channel->item as $item) {
        $title  = trim((string)($item->title ?? ''));
        $link   = trim((string)($item->link ?? ''));
        $pubRaw = trim((string)($item->pubDate ?? ''));
        $descRaw = (string)($item->description ?? '');
        $source = trim((string)($item->source ?? ''));

        if (empty($link)) {
            continue;
        }

        // Parse date
        $pubDate = '';
        $pubTs   = 0;
        if (!empty($pubRaw)) {
            $ts = strtotime($pubRaw);
            if ($ts !== false) {
                $pubDate = date('Y-m-d', $ts);
                $pubTs   = $ts;
            } else {
                $pubDate = $pubRaw;
            }
        }

        $description = cleanHtml($descRaw);
        $excerpt = !empty($description) ? truncate($description) : '';

        $articles[] = [
            'title'    => $title,
            'link'     => $link,
            'pub_date' => $pubDate,
            'pub_ts'   => $pubTs,
            'excerpt'  => $excerpt,
            'source'   => $source,
        ];
    }

    return $articles;
}

// ---------------------------------------------------------------------------
// Database Layer (SQLite + JSON)
// ---------------------------------------------------------------------------

function initDb(): PDO
{
    $db = new PDO('sqlite:' . DB_PATH, null, null, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);

    // Enable WAL for better concurrent performance
    $db->exec('PRAGMA journal_mode=WAL');

    $db->exec('
        CREATE TABLE IF NOT EXISTS articles (
            article_id TEXT PRIMARY KEY,
            category   TEXT NOT NULL,
            pub_ts     INTEGER DEFAULT 0,
            data       TEXT NOT NULL,
            created_at INTEGER DEFAULT (strftime(\'%s\',\'now\'))
        )
    ');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_category ON articles(category)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_pub_ts   ON articles(pub_ts DESC)');

    return $db;
}

function insertArticle(PDO $db, array $article, string $category): bool
{
    $aid  = articleId($article['link']);
    $data = json_encode([
        'title'    => $article['title']    ?? '',
        'link'     => $article['link']     ?? '',
        'pub_date' => $article['pub_date'] ?? '',
        'excerpt'  => $article['excerpt']  ?? '',
        'source'   => $article['source']   ?? '',
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

    $stmt = $db->prepare('
        INSERT OR IGNORE INTO articles (article_id, category, pub_ts, data)
        VALUES (:aid, :category, :pub_ts, :data)
    ');

    $stmt->execute([
        ':aid'      => $aid,
        ':category' => $category,
        ':pub_ts'   => $article['pub_ts'] ?? 0,
        ':data'     => $data,
    ]);

    return $stmt->rowCount() > 0;
}

function getAllArticles(PDO $db): array
{
    $stmt = $db->query('
        SELECT article_id, category, pub_ts, data
        FROM articles
        ORDER BY pub_ts DESC
    ');

    $articles = [];
    foreach ($stmt as $row) {
        $doc = json_decode($row['data'], true) ?? [];
        $articles[] = [
            'id'       => $row['article_id'],
            'category' => $row['category'],
            'pub_ts'   => (int)$row['pub_ts'],
            'title'    => $doc['title']    ?? '',
            'link'     => $doc['link']     ?? '#',
            'pub_date' => $doc['pub_date'] ?? '',
            'excerpt'  => $doc['excerpt']  ?? '',
            'source'   => $doc['source']   ?? '',
        ];
    }

    return $articles;
}

// ---------------------------------------------------------------------------
// HTML Generation
// ---------------------------------------------------------------------------

function generateHtml(array $articles): string
{
    $cardsHtml = '';

    if (empty($articles)) {
        $cardsHtml = '<p class="empty">No articles found yet. Run the script to fetch news.</p>';
    } else {
        foreach ($articles as $art) {
            $title    = htmlspecialchars($art['title'] ?: 'Untitled', ENT_QUOTES, 'UTF-8');
            $link     = htmlspecialchars($art['link'] ?: '#', ENT_QUOTES, 'UTF-8');
            $date     = htmlspecialchars($art['pub_date'] ?? '', ENT_QUOTES, 'UTF-8');
            $category = htmlspecialchars($art['category'] ?? '', ENT_QUOTES, 'UTF-8');
            $excerpt  = htmlspecialchars($art['excerpt'] ?? '', ENT_QUOTES, 'UTF-8');
            $source   = htmlspecialchars($art['source'] ?? '', ENT_QUOTES, 'UTF-8');

            $sourceBadge  = $source ? "<span class=\"source\">{$source}</span>" : '';
            $excerptBlock = $excerpt ? "<p class=\"excerpt\">{$excerpt}</p>" : '';

            $cardsHtml .= <<<CARD
      <article class="card" data-category="{$category}">
        <div class="card-meta">
          <span class="badge">{$category}</span>
          <span class="date">{$date}</span>
        </div>
        <h2 class="card-title"><a href="{$link}" target="_blank" rel="noopener noreferrer">{$title}</a></h2>
        {$excerptBlock}
        <div class="card-footer">
          {$sourceBadge}
          <a href="{$link}" target="_blank" rel="noopener noreferrer" class="read-more">Read article &rarr;</a>
        </div>
      </article>
CARD;
            $cardsHtml .= "\n";
        }
    }

    $count    = count($articles);
    $plural   = $count !== 1 ? 's' : '';
    $nowStr   = date('F d, Y \a\t g:i A');

    return <<<HTML
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Product and Tech News</title>
<style>
  :root {
    --accent: #00B4C5;
    --accent-dark: #009AA8;
    --text: #1A1A2E;
    --bg: #FFFFFF;
    --bg-light: #F4F6F8;
    --border: #E2E6EA;
    --muted: #6B7280;
    --radius: 12px;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg-light);
    color: var(--text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }

  /* Header */
  header {
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    padding: 2rem 1.5rem 1.5rem;
    text-align: center;
  }
  header h1 {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.02em;
  }
  header h1 span { color: var(--accent); }
  .subtitle {
    color: var(--muted);
    font-size: 0.875rem;
    margin-top: 0.25rem;
  }

  /* Filters */
  .filters {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.5rem;
    padding: 1rem 1.5rem;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .filters button {
    padding: 0.45rem 1.1rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg);
    color: var(--muted);
    font-size: 0.85rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .filters button:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .filters button.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }

  /* Grid */
  .container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 1.5rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 1.25rem;
  }

  /* Card */
  .card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    transition: box-shadow 0.2s ease, transform 0.2s ease;
  }
  .card:hover {
    box-shadow: 0 4px 20px rgba(0,0,0,0.06);
    transform: translateY(-2px);
  }
  .card.hidden { display: none; }

  .card-meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  .badge {
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent-dark);
  }
  .date {
    font-size: 0.78rem;
    color: var(--muted);
  }

  .card-title {
    font-size: 1.05rem;
    font-weight: 600;
    line-height: 1.4;
    margin-bottom: 0.5rem;
  }
  .card-title a {
    color: var(--text);
    text-decoration: none;
  }
  .card-title a:hover {
    color: var(--accent);
  }

  .excerpt {
    font-size: 0.88rem;
    color: var(--muted);
    line-height: 1.55;
    flex: 1;
    margin-bottom: 1rem;
  }

  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: auto;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
  }
  .source {
    font-size: 0.75rem;
    color: var(--muted);
    font-weight: 500;
  }
  .read-more {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
  }
  .read-more:hover { text-decoration: underline; }

  .empty {
    text-align: center;
    color: var(--muted);
    grid-column: 1 / -1;
    padding: 3rem 0;
  }

  /* Count */
  .count {
    text-align: center;
    font-size: 0.8rem;
    color: var(--muted);
    padding: 0.75rem 0 0;
  }

  /* Footer */
  footer {
    text-align: center;
    padding: 2rem 1rem;
    font-size: 0.78rem;
    color: var(--muted);
  }

  @media (max-width: 700px) {
    .grid { grid-template-columns: 1fr; }
    header h1 { font-size: 1.35rem; }
  }
</style>
</head>
<body>

<header>
  <h1>Product and <span>Tech News</span></h1>
  <p class="subtitle">Weekly digest &middot; Updated {$nowStr}</p>
</header>

<nav class="filters" id="filters">
  <button class="active" data-filter="All">All</button>
  <button data-filter="UI/UX">UI/UX</button>
  <button data-filter="Product">Product</button>
  <button data-filter="Health Tech">Health Tech</button>
  <button data-filter="AI">AI</button>
</nav>

<main class="container">
  <p class="count" id="count">{$count} article{$plural}</p>
  <div class="grid" id="grid">
{$cardsHtml}
  </div>
</main>

<footer>
  Generated by News Aggregator &middot; {$nowStr}
</footer>

<script>
(function() {
  const buttons = document.querySelectorAll('#filters button');
  const cards   = document.querySelectorAll('.card');
  const count   = document.getElementById('count');

  function update(filter) {
    let visible = 0;
    cards.forEach(c => {
      const show = filter === 'All' || c.dataset.category === filter;
      c.classList.toggle('hidden', !show);
      if (show) visible++;
    });
    count.textContent = visible + ' article' + (visible !== 1 ? 's' : '');
  }

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      update(btn.dataset.filter);
    });
  });
})();
</script>

</body>
</html>
HTML;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main(): void
{
    echo "Loading database…\n";
    $db = initDb();

    $totalNew = 0;

    foreach (CATEGORIES as $category => $queries) {
        echo "\n[{$category}]\n";
        foreach ($queries as $query) {
            echo "  Fetching: {$query}\n";
            $articles = fetchGoogleNewsRss($query);
            $added = 0;
            foreach ($articles as $art) {
                if (insertArticle($db, $art, $category)) {
                    $added++;
                }
            }
            $totalNew += $added;
            $found = count($articles);
            echo "    Found {$found} items, {$added} new\n";
        }
    }

    // Count total articles in DB
    $totalStmt = $db->query('SELECT COUNT(*) AS cnt FROM articles');
    $totalCount = (int)$totalStmt->fetch()['cnt'];

    echo "\nStore saved → " . DB_PATH . "\n";
    echo "  Total articles: {$totalCount}  |  New this run: {$totalNew}\n";

    // Generate HTML
    $allArticles = getAllArticles($db);
    $htmlContent = generateHtml($allArticles);
    file_put_contents(HTML_PATH, $htmlContent);
    echo "HTML generated → " . HTML_PATH . "\n";
}

main();
