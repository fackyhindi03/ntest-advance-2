# hianimez_scraper.py

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, unquote_plus


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    )
}


def search_anime(query: str):
    """
    Search hianimez.to for anime matching `query`.
    Returns a list of tuples: (title, anime_page_url, anime_id)
    Here, anime_id == anime_page_url (so we can pass it back in callback_data).
    """
    # URL‐encode the query
    q = quote_plus(query)
    search_url = f"https://hianimez.to/search?keyword={q}"
    resp = requests.get(search_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    # On the search results page, each anime is inside something like:
    # <div class="anime-list-item"> <a href="/watch/one-piece"><img ...> <h2>One Piece</h2> ...
    # We find all <div class="anime-list-item"> or similar. Inspect the HTML.
    for div in soup.find_all("div", class_="anime-list-item"):
        a_tag = div.find("a", href=True)
        if not a_tag:
            continue
        title_tag = div.find("h2")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        rel_link = a_tag["href"]  # e.g. "/watch/one-piece"
        anime_url = "https://hianimez.to" + rel_link
        # We'll use the full anime_url as our "anime_id" in the callback_data
        anime_id = anime_url
        results.append((title, anime_url, anime_id))

    return results


def get_episodes_list(anime_url: str):
    """
    Given a specific anime page URL (e.g. https://hianimez.to/watch/one-piece),
    parse the HTML to extract all available episodes.
    Returns a list of (episode_number, episode_page_url).
    """
    resp = requests.get(anime_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    episodes = []
    # Typically, the episodes are listed as links in a <ul class="episode-list"> or similar.
    # Example markup:
    # <ul class="episodes">
    #   <li><a href="/watch/one-piece-episode-1">Episode 1</a></li>
    #   <li><a href="/watch/one-piece-episode-2">Episode 2</a></li>
    #   ...
    # We adapt based on the actual class names from the site.

    # Look for any <ul> or <div> that contains class "episode-list" or similar
    ep_list_container = soup.find("ul", class_=re.compile(r"episode-list|episodes", re.I))
    if not ep_list_container:
        # fallback: maybe they use a table or <div class="ep-item">
        ep_list_container = soup.find("div", class_=re.compile(r"episode-list|episodes", re.I))

    if not ep_list_container:
        return episodes

    # Now extract each <a> inside:
    for a in ep_list_container.find_all("a", href=True):
        text = a.get_text(strip=True)
        # Try to extract an integer episode number from text
        m = re.search(r"Episode\s*(\d+)", text, re.I)
        if m:
            ep_num = m.group(1)
        else:
            # maybe the URL has the number
            url_piece = a["href"].rstrip("/").split("-")[-1]
            if url_piece.isdigit():
                ep_num = url_piece
            else:
                # skip if we cannot parse a number
                continue
        ep_url = "https://hianimez.to" + a["href"]
        episodes.append((ep_num, ep_url))

    # Sort episodes by numeric order
    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_url: str):
    """
    From an episode page, find:
    1) The SUB – HD-2 (1080p) .m3u8 link
    2) The English subtitle (.vtt) file URL
    Returns (hls_1080p_url or None, subtitle_vtt_url or None).
    """
    resp = requests.get(episode_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # Often, hianimez.injects the streaming sources in JS, such as:
    # var player_config = { "sources": [ { "label": "HD-1", "file": "https://…/low.m3u8" },
    #                                   { "label": "HD-2", "file": "https://…/1080.m3u8" }, … ],
    #                        "tracks": [ { "file": "…en-3.vtt", "kind": "captions", "label": "English", "srclang": "en" }, … ]
    #                      };
    #
    # So we can regex for `"label":"HD-2".+?"file":"(https[^"]+\.m3u8)"`.
    # Then find `"srclang":"en".+?"file":"(https[^"]+\.vtt)"`.

    # 1) Extract HD-2 (1080p) HLS link
    hls_1080p = None
    # Pattern to find: "label":"HD-2","file":"https://...m3u8"
    m_hls = re.search(r'"label"\s*:\s*"HD-2"\s*,\s*"file"\s*:\s*"([^"]+\.m3u8)"', html)
    if m_hls:
        hls_1080p = m_hls.group(1)

    # 2) Extract English subtitle URL
    subtitle_url = None
    # Pattern to find: "srclang":"en","file":"https://...vtt"
    m_sub = re.search(r'"srclang"\s*:\s*"en"\s*,\s*"file"\s*:\s*"([^"]+\.vtt)"', html)
    if m_sub:
        subtitle_url = m_sub.group(1)

    return hls_1080p, subtitle_url
