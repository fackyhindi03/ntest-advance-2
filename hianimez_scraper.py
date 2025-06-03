# hianimez_scraper.py

import re
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# Instead of requests, we use cloudscraper to bypass Cloudflare
scraper = cloudscraper.create_scraper(
    {
        # You can optionally add default headers here:
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    }
)
 
def search_anime(query: str):
    """
    Search hianimez.to for anime matching `query`.
    Returns a list of tuples: (title, anime_page_url, anime_id).
    We use anime_page_url itself as anime_id, so that the bot can callback later.
    """
    q = quote_plus(query)
    search_url = f"https://hianimez.to/search?keyword={q}"

    # Use cloudscraper instead of requests
    resp = scraper.get(search_url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results = []
    # As of mid-2025, the search results are rendered into a <div class="film-list-wrap">,
    # each item under <div class="film-poster">. Inside, the <a href> points to /watch/<anime-slug>.
    #
    container = soup.find("div", class_="film-list-wrap")
    if not container:
        return results

    for poster_div in container.select("div.film-poster"):
        a_tag = poster_div.find("a", href=True)
        if not a_tag:
            continue

        rel_link = a_tag["href"].strip()  # e.g. "/watch/one-piece"
        if not rel_link.startswith("http"):
            anime_url = "https://hianimez.to" + rel_link
        else:
            anime_url = rel_link

        # The title is now in a sibling <div class="film-detail"><h3 class="name"><a>Title</a>…
        detail_div = poster_div.find_next_sibling("div", class_="film-detail")
        if detail_div:
            name_tag = detail_div.find("h3", class_="name")
            if name_tag and name_tag.a:
                title = name_tag.a.get_text(strip=True)
            else:
                title = a_tag.get("title", "").strip()
        else:
            title = a_tag.get("title", "").strip()

        if title and anime_url:
            results.append((title, anime_url, anime_url))

    return results


def get_episodes_list(anime_url: str):
    """
    Given an anime page URL (e.g. https://hianimez.to/watch/one-piece),
    return a sorted list of (episode_number, episode_page_url).
    """
    resp = scraper.get(anime_url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    episodes = []
    # Typically episodes are in:
    #   <ul class="episodes">
    #     <li><a href="/watch/one-piece-episode-1">Episode 1</a></li>
    #     ...
    ul = soup.find("ul", class_="episodes")
    if not ul:
        # Fallback if they changed it to <div class="episode-list">:
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
    For a given episode page (e.g. https://hianimez.to/watch/one-piece-episode-1),
    return (hd2_m3u8_url, english_vtt_url) or (None, None) if not found.
    """
    resp = scraper.get(episode_url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # 1) Find “label":"HD-2","file":"...1080.m3u8"
    hls_1080p = None
    m_hls = re.search(r'"label"\s*:\s*"HD-2"\s*,\s*"file"\s*:\s*"([^"]+\.m3u8)"', html)
    if m_hls:
        hls_1080p = m_hls.group(1)

    # 2) Find the English subtitle track: "srclang":"en","file":"...vtt"
    subtitle_url = None
    m_sub = re.search(r'"srclang"\s*:\s*"en"\s*,\s*"file"\s*:\s*"([^"]+\.vtt)"', html)
    if m_sub:
        subtitle_url = m_sub.group(1)

    return hls_1080p, subtitle_url
