# hianimez_scraper.py

import re
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from urllib.parse import quote_plus
import cloudscraper

# ——————————————————————————————————————————————————————————————
# 1) Helper to fetch a fully‐rendered search page via Playwright
# ——————————————————————————————————————————————————————————————
async def _fetch_search_page_html(encoded_query: str) -> str:
    url = f"https://hianimez.to/search?keyword={encoded_query}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        try:
            # Wait up to 15s for at least one .film-poster element
            await page.wait_for_selector("div.film-poster", timeout=15000)
        except:
            # Even if none appear, grab whatever HTML is loaded
            pass

        html = await page.content()
        await browser.close()
        return html

def _rendered_search_html(query: str) -> str:
    """
    Synchronous wrapper around _fetch_search_page_html.
    Always creates a fresh event loop so it works inside any thread.
    """
    encoded = quote_plus(query)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_fetch_search_page_html(encoded))
    finally:
        loop.close()

def search_anime(query: str):
    """
    Search hianimez.to for anime matching `query`.
    Returns a list of tuples (title, anime_page_url, anime_page_url).
    We use the full anime_page_url as the “anime_id” for callback_data.
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

        detail_div = poster_div.find_next_sibling("div", class_="film-detail")
        if detail_div:
            name_tag = detail_div.find("h3", class_="name")
            title = name_tag.a.get_text(strip=True) if (name_tag and name_tag.a) else a_tag.get("title", "").strip()
        else:
            title = a_tag.get("title", "").strip()

        if title and anime_url:
            results.append((title, anime_url, anime_url))

    return results


# ——————————————————————————————————————————————————————————————
# 2) Helper to fetch a fully‐rendered episodes page via Playwright
# ——————————————————————————————————————————————————————————————
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

def get_episodes_list(anime_url: str):
    """
    Given an anime page URL (e.g. https://hianimez.to/watch/one-piece),
    return a sorted list of (episode_number, episode_page_url).
    """
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(_fetch_episodes_html(anime_url))
    finally:
        loop.close()

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


# ——————————————————————————————————————————————————————————————
# 3) Extract the SUB‐HD2 (1080p) .m3u8 link + English .vtt subtitle URL
#    using cloudscraper
# ——————————————————————————————————————————————————————————————
def extract_episode_stream_and_subtitle(episode_url: str):
    """
    For a given episode page (e.g. https://hianimez.to/watch/one-piece-episode-1),
    return a tuple (hd2_m3u8_url, english_vtt_url), or (None, None) if not found.
    """
    # Use Cloudscraper to bypass Cloudflare if needed
    scraper = cloudscraper.create_scraper({
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0 Safari/537.36"
            )
        }
    })

    resp = scraper.get(episode_url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # 1) Find HD-2 (1080p) HLS link in JavaScript
    hls_1080p = None
    m_hls = re.search(r'"label"\s*:\s*"HD-2"\s*,\s*"file"\s*:\s*"([^"]+\.m3u8)"', html)
    if m_hls:
        hls_1080p = m_hls.group(1)

    # 2) Find English subtitle .vtt in JavaScript tracks
    subtitle_url = None
    m_sub = re.search(r'"srclang"\s*:\s*"en"\s*,\s*"file"\s*:\s*"([^"]+\.vtt)"', html)
    if m_sub:
        subtitle_url = m_sub.group(1)

    return hls_1080p, subtitle_url
