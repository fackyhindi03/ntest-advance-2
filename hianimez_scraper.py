# hianimez_scraper.py

import os
import requests
import logging

logger = logging.getLogger(__name__)

ANIWATCH_API_BASE = os.getenv(
    "ANIWATCH_API_BASE",
    "http://localhost:4000/api/v2/hianime"
)


def search_anime(query: str):
    """
    (unchanged)
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    full_json = resp.json()
    logger.info("AniWatch /search raw JSON: %s", full_json)

    root = full_json.get("data", {})
    anime_list = root.get("animes", [])

    results = []
    for item in anime_list:
        if isinstance(item, str):
            slug = item
            title = slug.replace("-", " ").title()
        else:
            slug = item.get("id", "")
            title = item.get("name") or item.get("jname") or slug.replace("-", " ").title()

        if not slug:
            continue

        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))

    return results


def get_episodes_list(anime_url: str):
    """
    Given a HiAnime URL (e.g. "https://hianimez.to/watch/naruto-677"), extract the slug ("naruto-677"),
    then call AniWatch's /episode/list?animeId=<slug>.

    If AniWatch returns 404, treat it as a single‐episode anime, and return [("1", slug)].
    Otherwise, parse the JSON array and return a sorted list of (episode_number, episode_url).
    """
    # 1) Extract the slug itself from the URL
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    ep_list_url = f"{ANIWATCH_API_BASE}/episode/list"
    params = {"animeId": slug}

    try:
        resp = requests.get(ep_list_url, params=params, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as http_err:
        # If it's a 404, assume "movie"/"OVA"/"special" → single episode
        if resp.status_code == 404:
            # Return a single‐episode list: episode "1" maps back to the same slug
            return [("1", anime_url)]
        else:
            # re‐raise for any other HTTP error (e.g. 500)
            raise

    # 2) If we did get a 200, parse the JSON array under "data"
    episodes_data = resp.json().get("data", [])
    episodes = []
    for item in episodes_data:
        ep_num = str(item.get("episode", "")).strip()
        ep_slug = item.get("slug", "")
        if not ep_num or not ep_slug:
            continue
        ep_url = f"https://hianimez.to/watch/{ep_slug}"
        episodes.append((ep_num, ep_url))

    # 3) Sort by numeric episode number
    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_url: str):
    """
    (unchanged from before)
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
        "server": "hd-1",   # “hd-1” is the SUB server
        "category": "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json().get("data", {})
    sources = data.get("sources", [])
    tracks = data.get("tracks", [])

    # 1) Find HD-2 (1080p) HLS link
    hls_1080p = None
    for s in sources:
        if s.get("type") == "hls" and s.get("label", "").lower() == "hd-2":
            hls_1080p = s.get("file")
            break
    if not hls_1080p:
        # fallback to the first HLS if HD-2 not found
        for s in sources:
            if s.get("type") == "hls":
                hls_1080p = s.get("file")
                break

    # 2) Find English subtitle track
    subtitle_url = None
    for t in tracks:
        if t.get("srclang", "").lower() == "en":
            subtitle_url = t.get("file")
            break

    return hls_1080p, subtitle_url
