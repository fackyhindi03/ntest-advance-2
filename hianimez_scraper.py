# hianimez_scraper.py

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    )
}


def search_anime(query: str):
    """
    Search hianimez.to for anime matching `query`.
    Returns a list of tuples: (title, anime_page_url, anime_id).
    Here, we use anime_page_url itself as the anime_id (for callback_data).
    """
    q = quote_plus(query)
    search_url = f"https://hianimez.to/search?keyword={q}"
    resp = requests.get(search_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results = []
    # The current search results are inside <div class="film-list-wrap">,
    # each item has a <div class="film-poster">, with an <a href="...">
    # and below that a sibling <div class="film-detail"> <h3 class="name"><a>Title</a>
    #
    container = soup.find("div", class_="film-list-wrap")
    if not container:
        # No results container found
        return results

    # Loop over each "poster" item
    for poster_div in container.select("div.film-poster"):
        a_tag = poster_div.find("a", href=True)
        if not a_tag:
            continue

        # Build the full URL
        rel_link = a_tag["href"]  # e.g. "/watch/raven"
        if not rel_link.startswith("http"):
            anime_url = "https://hianimez.to" + rel_link
        else:
            anime_url = rel_link

        # The title is usually in a sibling div.film-detail h3.name > a
        detail_div = poster_div.find_next_sibling("div", class_="film-detail")
        if detail_div:
            name_tag = detail_div.find("h3", class_="name")
            if name_tag and name_tag.a:
                title = name_tag.a.get_text(strip=True)
            else:
                # Fallback: maybe a title attribute on <a>
                title = a_tag.get("title", "").strip()
        else:
            title = a_tag.get("title", "").strip()

        if title and anime_url:
            results.append((title, anime_url, anime_url))

    return results


def get_episodes_list(anime_url: str):
    """
    Given an anime page URL (e.g. https://hianimez.to/watch/raven),
    parse the HTML to extract all available episodes.
    Returns a sorted list of (episode_number, episode_page_url).
    """
    resp = requests.get(anime_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    episodes = []

    # The episodes are usually in a <ul class="episodes"> or <div class="episode-list">.
    # By inspecting the current markup (June 2025), we see:
    # <ul class="episodes">
    #   <li><a href="/watch/raven-episode-1">Episode 1</a></li>
    #   ...
    ul = soup.find("ul", class_="episodes")
    if not ul:
        # Maybe they changed to <div class="episode-list">?
        ul = soup.find("div", class_="episode-list")

    if not ul:
        return episodes

    for a in ul.find_all("a", href=True):
        text = a.get_text(strip=True)
        # Extract the number from “Episode X”
        m = re.search(r"Episode\s*(\d+)", text, re.I)
        if m:
            ep_num = m.group(1)
        else:
            # fallback: try last chunk of the href if it’s numeric
            slug = a["href"].rstrip("/").split("-")[-1]
            ep_num = slug if slug.isdigit() else None

        if not ep_num:
            continue

        ep_url = "https://hianimez.to" + a["href"]
        episodes.append((ep_num, ep_url))

    # Sort by episode number
    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_url: str):
    """
    From an episode page, find:
      1) The SUB – HD-2 (1080p) .m3u8 link
      2) The English subtitle (.vtt) file URL
    Returns (hls_1080p_url or None, subtitle_vtt_url or None)
    """
    resp = requests.get(episode_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # 1) Find the HD-2 (1080p) HLS URL. 
    # Look in the embedded JS for something like:
    #   "label":"HD-2","file":"https://…1080.m3u8"
    hls_1080p = None
    m_hls = re.search(r'"label"\s*:\s*"HD-2"\s*,\s*"file"\s*:\s*"([^"]+\.m3u8)"', html)
    if m_hls:
        hls_1080p = m_hls.group(1)

    # 2) Find the English subtitle track. 
    # Look for: "srclang":"en","file":"...\.vtt"
    subtitle_url = None
    m_sub = re.search(r'"srclang"\s*:\s*"en"\s*,\s*"file"\s*:\s*"([^"]+\.vtt)"', html)
    if m_sub:
        subtitle_url = m_sub.group(1)

    return hls_1080p, subtitle_url
