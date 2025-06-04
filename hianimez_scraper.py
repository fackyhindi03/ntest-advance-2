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
    (Unchanged from before.)
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
    Given a HiAnime page URL (e.g. "https://hianimez.to/watch/raven-of-the-inner-palace-18168"),
    extract slug = "raven-of-the-inner-palace-18168", then call:
      GET /episode/list?animeId=<slug>

    If that returns 404, treat it as a single-episode anime and return [("1", anime_url)].
    Otherwise, parse the JSON array and return a sorted list of (episode_number, episode_url).
    """
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
        if resp.status_code == 404:
            # Single-episode fallback: return exactly one entry, Episode 1
            return [("1", anime_url)]
        else:
            raise

    episodes_data = resp.json().get("data", [])
    episodes = []
    for item in episodes_data:
        ep_num = str(item.get("episode", "")).strip()
        ep_slug = item.get("slug", "")
        if not ep_num or not ep_slug:
            continue
        ep_url = f"https://hianimez.to/watch/{ep_slug}"
        episodes.append((ep_num, ep_url))

    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(ep_slug: str, ep_num: str):
    """
    Given:
      ep_slug = e.g. "raven-of-the-inner-palace-18168-episode-1"  (or sometimes just "raven-of-the-inner-palace-18168")
      ep_num  = e.g. "1"

    Build:
      anime_slug = ep_slug.split("-episode-")[0]    → "raven-of-the-inner-palace-18168"
      animeEpisodeId = f"{anime_slug}?ep={ep_num}"

    Then call:
      GET /episode/sources?animeEpisodeId=<animeEpisodeId>&server=hd-1&category=sub

    Finally, return (hls_1080p_url, english_vtt_url) or (None, None).
    """
    # Determine the base "anime_slug" even if ep_slug doesn't contain "-episode-"
    if "-episode-" in ep_slug:
        anime_slug = ep_slug.split("-episode-")[0]
    else:
        anime_slug = ep_slug

    ep_id = f"{anime_slug}?ep={ep_num}"
    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": ep_id,
        "server": "hd-1",   # SUB server, inside which we look for "HD-2"
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
        # Fallback to the first HLS if no "HD-2" label
        for s in sources:
            if s.get("type") == "hls":
                hls_1080p = s.get("file")
                break

    # 2) Find the English subtitle track
    subtitle_url = None
    for t in tracks:
        if t.get("srclang", "").lower() == "en":
            subtitle_url = t.get("file")
            break

    return hls_1080p, subtitle_url
