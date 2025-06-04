# hianimez_scraper.py

import os
import requests

# Read the AniWatch API base from the environment.
# If not set, it will default to localhost (for local testing).
ANIWATCH_API_BASE = os.getenv(
    "ANIWATCH_API_BASE",
    "http://localhost:4000/api/v2/hianime"
)


def search_anime(query: str):
    """
    Call AniWatch API's /search?q=<query>&page=1.
    Handles two possible response formats:
      1) data = ["naruto", "naruto-shippuden", …]     (list of slugs)
      2) data = [ { "slug": "naruto", "name": "Naruto", … }, … ]

    Returns a list of tuples: (title, anime_url, slug).
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    json_data = resp.json().get("data", [])
    results = []

    for item in json_data:
        if isinstance(item, str):
            # AniWatch returned a plain string = slug
            slug = item
            title = slug.replace("-", " ").title()
        else:
            # AniWatch returned a dict with fields
            slug = item.get("slug", "")
            title = item.get("name") or item.get("title") or slug.replace("-", " ").title()

        if not slug:
            continue

        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))

    return results


def get_episodes_list(anime_url: str):
    """
    Given an anime page URL (e.g. "https://hianimez.to/watch/naruto"),
    extract the slug ("naruto") and fetch the list of episodes via AniWatch API.
    Returns a list of (episode_number, episode_url) sorted by number.
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

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
    Call AniWatch API's /episode/sources?animeEpisodeId=<slug>?ep=<n>&server=hd-1&category=sub
    and return (hls_1080p_url, english_vtt_url) or (None, None) if not found.
    """
    try:
        path = episode_url.rstrip("/").split("/")[-1]
        if "-episode-" in path:
            anime_slug, ep_num = path.split("-episode-", maxsplit=1)
            ep_id = f"{anime_slug}?ep={ep_num}"
        else:
            ep_id = path
    except Exception:
        return None, None

    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": ep_id,
        "server": "hd-1",     # we want SUB first, then look for HD-2
        "category": "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json().get("data", {})
    sources = data.get("sources", [])
    tracks = data.get("tracks", [])

    # 1) Find the HD-2 (1080p) HLS link
    hls_1080p = None
    for s in sources:
        if s.get("type") == "hls" and s.get("label", "").lower() == "hd-2":
            hls_1080p = s.get("url")
            break
    if not hls_1080p:
        # fallback to the first HLS if HD-2 not found
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
