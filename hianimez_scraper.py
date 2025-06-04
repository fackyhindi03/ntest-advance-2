# hianimez_scraper.py

import os
import requests

# Load the AniWatch API base URL from the environment.
ANIWATCH_API_BASE = os.getenv(
    "ANIWATCH_API_BASE",
    "http://localhost:4000/api/v2/hianime"
)


def search_anime(query: str):
    """
    Call AniWatch API's /search?q=<query>&page=1.
    The AniWatch response uses data["Animes"] for the actual results list.

    Returns a list of tuples: (title, anime_url, slug).
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    root = resp.json().get("data", {})              # root is a dict containing keys "Animes", etc.
    anime_list = root.get("Animes", [])             # This is the actual array of anime objects

    results = []
    for item in anime_list:
        # Each `item` should be a dict like { "slug": "...", "name": "...", … }
        # But just in case it's ever a plain string, we fall back:
        if isinstance(item, str):
            slug = item
            title = slug.replace("-", " ").title()
        else:
            slug = item.get("slug", "")
            title = item.get("name") or item.get("title") or slug.replace("-", " ").title()

        if not slug:
            continue

        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))

    return results


def get_episodes_list(anime_url: str):
    """
    Given a HiAnime page URL (e.g. "https://hianimez.to/watch/naruto"),
    extract the slug ("naruto") and fetch episodes via:
       GET /episode/list?animeId=<slug>
    Returns a sorted list of (episode_number, episode_url).
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    url = f"{ANIWATCH_API_BASE}/episode/list"
    params = {"animeId": slug}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    # Here, AniWatch’s /episode/list returns an array of objects like { "episode": 1, "slug": "naruto-episode-1", … }
    episodes_data = resp.json().get("data", [])
    episodes = []
    for item in episodes_data:
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
    Given a HiAnime episode URL (e.g. "https://hianimez.to/watch/naruto-episode-1"),
    derive animeEpisodeId = "<slug>?ep=<n>" and call:
       GET /episode/sources?animeEpisodeId=<…>&server=hd-1&category=sub

    Returns (hls_1080p_url, english_vtt_url) or (None, None).
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
        "server": "hd-1",     # “hd-1” is the SUB server, from which we look for label="HD-2"
        "category": "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json().get("data", {})
    sources = data.get("sources", [])
    tracks = data.get("tracks", [])

    # 1) Pick out the “HD-2” HLS link (1080p)
    hls_1080p = None
    for s in sources:
        if s.get("type") == "hls" and s.get("label", "").lower() == "hd-2":
            hls_1080p = s.get("url")
            break
    if not hls_1080p:
        # fallback: first HLS if HD-2 not found
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
