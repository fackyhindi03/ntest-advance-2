# hianimez_scraper.py

import re
import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from urllib.parse import quote_plus

async def _fetch_search_page_html(encoded_query: str) -> str:
    url = f"https://hianimez.to/search?keyword={encoded_query}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        try:
            await page.wait_for_selector("div.film-poster", timeout=15000)
        except:
            pass
        html = await page.content()
        await browser.close()
        return html

def _rendered_search_html(query: str) -> str:
    """
    Synchronous wrapper around the async Playwright fetch.
    Always creates a fresh event loop, so it works inside any thread.
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
    Returns a list of (title, anime_url, anime_url).
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

        rel_link = a_tag["href"].strip()
        anime_url = "https://hianimez.to" + rel_link

        detail_div = poster_div.find_next_sibling("div", class_="film-detail")
        if detail_div:
            name_tag = detail_div.find("h3", class_="name")
            title = name_tag.a.get_text(strip=True) if name_tag and name_tag.a else a_tag.get("title", "").strip()
        else:
            title = a_tag.get("title", "").strip()

        if title and anime_url:
            results.append((title, anime_url, anime_url))

    return results

# Similarly, update get_episodes_list to use a fresh loop:

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

# extract_episode_stream_and_subtitle can remain unchanged (it uses cloudscraper).
