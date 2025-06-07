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
    Search for anime by name. Returns a list of (title, anime_url, slug).
    Works whether the API wraps under `data.animes` or returns
    at top level under `animes` or `mostPopularAnimes`.
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    full_json = resp.json()
    logger.info("AniWatch /search raw JSON: %s", full_json)

    # 1) unwrap data if present, else use root
    root = full_json.get("data", full_json)

    # 2) try both 'animes' and 'mostPopularAnimes'
    anime_list = root.get("animes")
    if anime_list is None:
        anime_list = root.get("mostPopularAnimes", [])

    results = []
    for item in anime_list:
        if isinstance(item, str):
            slug = item
            title = slug.replace("-", " ").title()
        else:
            slug = item.get("id", "")
            title = (
                item.get("name")
                or item.get("jname")
                or slug.replace("-", " ").title()
            )

        if not slug:
            continue

        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))

    return results


def get_episodes_list(anime_url: str):
    """
    Fetches /anime/<slug>/episodes and returns a sorted list of
      [ (episode_number, episodeId), … ]
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    ep_list_url = f"{ANIWATCH_API_BASE}/anime/{slug}/episodes"
    resp = requests.get(ep_list_url, timeout=10)

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
    Given episodeId like "<slug>?ep=1", calls /episode/sources
    and returns (hls_link, subtitle_url).
    """
    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": episode_id,
        "server":          "hd-2",
        "category":        "sub",
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    root = data.get("data", data)

    # pick HLS 1080p
    hls_link = None
    for s in root.get("sources", []):
        if s.get("type") == "hls" and s.get("url"):
            hls_link = s["url"]
            break

    # pick English subtitle
    subtitle_url = None
    for t in root.get("tracks", []):
        if t.get("label", "").lower().startswith("english"):
            subtitle_url = t.get("file")
            break

    return hls_link, subtitle_url
