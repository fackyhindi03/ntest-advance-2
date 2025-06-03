# hianimez_scraper.py

import re
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# We will use an async function to launch Playwright and render the page.
# Then we’ll wrap it in a synchronous helper so our bot code can call it directly.

async def _fetch_search_page_html(query: str) -> str:
    """
    Internal coroutine: Launch headless Chromium with Playwright, go to
    'https://hianimez.to/search?keyword=<query>', wait for the
    'div.film-poster' elements to appear, then return the full HTML.
    """
    url = f"https://hianimez.to/search?keyword={query}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, timeout=30000)  # 30s timeout

        # Wait until at least one .film-poster card is visible (or timeout after 15s)
        try:
            await page.wait_for_selector("div.film-poster", timeout=15000)
        except Exception:
            # Even if no film-poster appears, we'll still grab whatever HTML is loaded
            pass

        html = await page.content()
        await browser.close()
        return html


def _rendered_search_html(query: str) -> str:
    """
    A synchronous wrapper around the async function to fetch the fully
    rendered HTML of the search page. The query should already be
    URL-encoded (spaces -> '+') if necessary.
    """
    # Playwright wants the query part URL‐encoded. We'll do minimal encoding here:
    from urllib.parse import quote_plus
    encoded = quote_plus(query)

    # Run the coroutine in an event loop and get the HTML
    html: str = asyncio.get_event_loop().run_until_complete(
        _fetch_search_page_html(encoded)
    )
    return html


def search_anime(query: str):
    """
    Return a list of (title, anime_url, anime_id) for search results.
    We will:
      1) use Playwright to get fully rendered HTML
      2) parse with BeautifulSoup against 'div.film-poster'
      3) extract titles and '/watch/...' links
    """
    html = _rendered_search_html(query)
    soup = BeautifulSoup(html, "lxml")

    results = []
    container = soup.find("div", class_="film-list-wrap")
    if not container:
        return results

    for poster_div in container.select("div.film-poster"):
        a_tag = poster_div.find("a", href=True)
        if not a_tag:
            continue

        rel_link = a_tag["href"].strip()  # e.g. "/watch/one-piece"
        anime_url = "https://hianimez.to" + rel_link

        # Title is in sibling <div class="film-detail"> <h3 class="name"><a>Title</a></h3>
        detail_div = poster_div.find_next_sibling("div", class_="film-detail")
        if detail_div:
            name_tag = detail_div.find("h3", class_="name")
            title = name_tag.a.get_text(strip=True) if name_tag and name_tag.a else a_tag.get("title", "").strip()
        else:
            title = a_tag.get("title", "").strip()

        if title and anime_url:
            results.append((title, anime_url, anime_url))

    return results


def get_episodes_list(anime_url: str):
    """
    Given a specific anime page (e.g. https://hianimez.to/watch/one-piece),
    fetch that page with Playwright too, wait for 'ul.episodes' to appear,
    then parse Episode links.
    """
    # Same pattern: load rendered page via Playwright
    async def _fetch_episodes_html(url: str) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            page = await browser.new_page()
            await page.goto(url, timeout=30000)
            try:
                await page.wait_for_selector("ul.episodes", timeout=15000)
            except:
                pass
            html = await page.content()
            await browser.close()
            return html

    html: str = asyncio.get_event_loop().run_until_complete(_fetch_episodes_html(anime_url))
    soup = BeautifulSoup(html, "lxml")

    episodes = []
    ul = soup.find("ul", class_="episodes")
    if not ul:
        ul = soup.find("div", class_="episode-list")
    if not ul:
        return episodes

    for a in ul.find_all("a", href=True):
        text = a.get_text(strip=True)
        m = re.search(r"Episode\s*(\d+)", text, re.I)
        if m:
            ep_num = m.group(1)
        else:
            slug = a["href"].rstrip("/").split("-")[-1]
            ep_num = slug if slug.isdigit() else None

        if not ep_num:
            continue

        ep_url = "https://hianimez.to" + a["href"]
        episodes.append((ep_num, ep_url))

    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_url: str):
    """
    For each episode page, we only need the final HTML to extract:
      1) "label":"HD-2","file":"...1080.m3u8"
      2) "srclang":"en","file":"...vtt"
    The <video> player details are usually embedded in JavaScript, so we do not
    necessarily need Playwright again—requests/cloudscraper might suffice here.
    However, if Hianimez also renders that section via JS, you can re‐use the
    Playwright approach. For simplicity, we’ll attempt a direct HTTP GET via cloudscraper
    (since the “player_config” JSON is often inlined, not SOAP‐fetched).
    """
    import cloudscraper

    scraper = cloudscraper.create_scraper(
        { 
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/115.0 Safari/537.36"
                )
            }
        }
    )

    resp = scraper.get(episode_url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # 1) Find HD-2 (1080p) .m3u8
    hls_1080p = None
    m_hls = re.search(r'"label"\s*:\s*"HD-2"\s*,\s*"file"\s*:\s*"([^"]+\.m3u8)"', html)
    if m_hls:
        hls_1080p = m_hls.group(1)

    # 2) Find English subtitle .vtt
    subtitle_url = None
    m_sub = re.search(r'"srclang"\s*:\s*"en"\s*,\s*"file"\s*:\s*"([^"]+\.vtt)"', html)
    if m_sub:
        subtitle_url = m_sub.group(1)

    return hls_1080p, subtitle_url
