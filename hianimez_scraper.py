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
    Search for anime by name. Returns a list of tuples:
      [ (title, anime_url, slug), … ]
    This version will look under:
      1) data.animes
      2) top‐level animes
      3) top‐level mostPopularAnimes
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    full_json = resp.json()
    logger.info("AniWatch /search raw JSON: %s", full_json)

    # 1) If the API wraps under "data", unwrap it; otherwise work with the root
    root = full_json.get("data", full_json)

    # 2) Try each possible list key in turn
    anime_list = root.get("animes")
    if anime_list is None:
        anime_list = root.get("mostPopularAnimes", [])
    if anime_list is None:
        anime_list = []

    results = []
    for item in anime_list:
        if isinstance(item, str):
            slug = item
            title = slug.replace("-", " ").title()
        else:
            slug = item.get("id", "").strip()
            title = (
                item.get("name")
                or item.get("jname")
                or slug.replace("-", " ").title()
            ).strip()

        if not slug:
            continue

        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))

    return results


def get_episodes_list(anime_url: str):
    """
    Given a HiAnime page URL (".../watch/<slug>"), calls
      GET /anime/<slug>/episodes
    and returns a sorted list of:
      [ (episode_number, episodeId), … ]
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    ep_list_url = f"{ANIWATCH_API_BASE}/anime/{slug}/episodes"
    resp = requests.get(ep_list_url, timeout=10)

    # Single‐episode fallback if the endpoint 404s
    if resp.status_code == 404:
        return [("1", f"{slug}?ep=1")]

    resp.raise_for_status()
    full_json = resp.json()
    root = full_json.get("data", full_json)
    episodes_data = root.get("episodes", [])

    episodes = []
    for item in episodes_data:
        num = str(item.get("number", "")).strip()
        eid = item.get("episodeId", "").strip()
        if num and eid:
            episodes.append((num, eid))

    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_id: str):
    """
    Given an `episode_id` like "slug?ep=1", calls
      GET /episode/sources?animeEpisodeId={episode_id}&server=hd-2&category=sub
    Returns (hls_link_or_None, subtitle_url_or_None).
    """
    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": episode_id,
        "server":          "hd-2",
        "category":        "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    root = data.get("data", data)

    # Pick the HLS link with quality "hd-2"
    hls_link = None
    for s in root.get("sources", []):
        if s.get("type") == "hls" and s.get("url"):
            hls_link = s["url"]
            break

    # Pick the English subtitle track
    subtitle_url = None
    for t in root.get("tracks", []):
        if t.get("label", "").lower().startswith("english"):
            subtitle_url = t.get("file")
            break

    return hls_link, subtitle_url
