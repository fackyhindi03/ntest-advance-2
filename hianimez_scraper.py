# hianimez_scraper.py

import os
import requests
import re

# Read the base URL of the AniWatch API from an environment variable.
# For example: "https://aniwatch-xyz123.koyeb.app/api/v2/hianime"
ANIWATCH_API_BASE = os.getenv("ANIWATCH_API_BASE", "http://localhost:4000/api/v2/hianime")


def search_anime(query: str):
    """
    Call the AniWatch API's /search endpoint.
    Returns a list of tuples: (title, anime_page_url, slug).
    E.g. ("Naruto", "https://hianimez.to/watch/naruto", "naruto").
    """
    params = {"q": query, "page": 1}
    url = f"{ANIWATCH_API_BASE}/search"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    results = []
    for item in data:
        title = item.get("name") or item.get("title") or item.get("slug", "")
        slug = item.get("slug", "")
        if not slug:
            continue
        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))
    return results


def get_episodes_list(anime_url: str):
    """
    Given an anime page URL (e.g. "https://hianimez.to/watch/naruto"), extract
    the slug ("naruto") and retrieve the list of episodes via AniWatch API.
    Returns a list of (ep_num, ep_url) sorted by ep_num.
    """
    # Extract slug: everything after the last slash in /watch/<slug>
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    # The AniWatch API doesn't have a separate 'episodes list' endpoint; in the 
    # Telethon code, they scraped the anime page and fetched episodes via HTML.
    # However, AniWatch provides an endpoint like `/episode/list?animeId=<slug>`.
    # (Adjust according to your actual API documentation.)
    #
    # For the sake of example, let's assume AniWatch has:
    #   GET {ANIWATCH_API_BASE}/episode/list?animeId=<slug>
    #    → returns JSON: { data: [ { episode: 1, slug: "naruto-episode-1" }, ... ] }
    #
    # If your Telethon code used a different route, update this accordingly.

    url = f"{ANIWATCH_API_BASE}/episode/list"
    params = {"animeId": slug}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    episodes = []
    for item in data:
        ep_num = str(item.get("episode", "")).strip()
        ep_slug = item.get("slug", "")
        if not ep_num or not ep_slug:
            continue
        ep_url = f"https://hianimez.to/watch/{ep_slug}"
        episodes.append((ep_num, ep_url))

    # Sort by numeric episode number
    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_url: str):
    """
    Call AniWatch API's /episode/sources to retrieve the HLS and subtitle tracks.
    Returns (hls_1080p_url, english_vtt_url) or (None, None) if missing.
    """
    # episode_url is like: "https://hianimez.to/watch/naruto-episode-1"
    # We must extract "<slug>?ep=<num>" for the API call. Example: "naruto?ep=1"
    try:
        # Split on "/watch/" → "naruto-episode-1"
        # Then split on "-episode-" to get slug + episode number
        path = episode_url.rstrip("/").split("/")[-1]  # e.g. "naruto-episode-1"
        if "-episode-" in path:
            anime_slug, ep_num = path.split("-episode-", maxsplit=1)
            ep_id = f"{anime_slug}?ep={ep_num}"
        else:
            # Fallback: if the slug already has "?ep=..." in it
            ep_id = path
    except Exception:
        ep_id = None

    if not ep_id:
        return None, None

    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": ep_id,
        "server": "hd-1",    # The Telethon code used hd-1 for SUB first
        "category": "sub"    # We want SUB, not DUB
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", {})

    sources = data.get("sources", [])
    tracks = data.get("tracks", [])

    # 1) Find an HLS source labeled "HD-2" (1080p). Fallback to first HLS if not found.
    hls_1080p = None
    for s in sources:
        if s.get("type") == "hls" and s.get("label", "").lower() == "hd-2":
            hls_1080p = s.get("url")
            break
    if not hls_1080p:
        # fallback to any hls
        for s in sources:
            if s.get("type") == "hls":
                hls_1080p = s.get("url")
                break

    # 2) Find the English subtitle track (srclang="en")
    subtitle_url = None
    for t in tracks:
        if t.get("srclang", "").lower() == "en":
            subtitle_url = t.get("file")
            break

    return hls_1080p, subtitle_url
