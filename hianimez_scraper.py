# hianimez_scraper.py

import os
import requests
import logging

logger = logging.getLogger(__name__)

# If you have set ANIWATCH_API_BASE in your environment, use that.
ANIWATCH_API_BASE = os.getenv(
    "ANIWATCH_API_BASE",
    "http://localhost:4000/api/v2/hianime"
)


def search_anime(query: str):
    """
    Search for anime by name. Returns a list of tuples:
      [ (title, anime_url, animeId), … ]
    Works whether the API returns { data: { animes: […] } }
    or returns { animes: […], … } directly.
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    full_json = resp.json()
    logger.info("AniWatch /search raw JSON: %s", full_json)

    # new format: full_json is already the data dict
    # old format: full_json = { "data": { … } }
    root = full_json.get("data", full_json)

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
    Given a page URL like "https://hianimez.to/watch/<slug>",
    fetches /anime/<slug>/episodes and returns a sorted list of
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
    # adapt for both formats again:
    root = full_json.get("data", full_json)
    episodes_data = root.get("episodes", [])

    episodes = []
    for item in episodes_data:
        ep_num = str(item.get("number", "")).strip()
        ep_id  = item.get("episodeId", "").strip()
        if ep_num and ep_id:
            episodes.append((ep_num, ep_id))

    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_id: str):
    """
    Given episodeId like "<slug>?ep=1", calls
      GET /episode/sources?animeEpisodeId={episode_id}&server=hd-2&category=sub
    and returns (hls_link_or_None, subtitle_url_or_None).
    """
    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": episode_id,
        "server":          "hd-2",   # force SUB-HD2
        "category":        "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    # again support { data: { … } } vs direct
    root = data.get("data", data)

    sources = root.get("sources", [])
    tracks  = root.get("tracks", [])

    hls_link = None
    for s in sources:
        if s.get("type") == "hls" and s.get("url"):
            hls_link = s["url"]
            break

    subtitle_url = None
    for t in tracks:
        if t.get("label", "").lower().startswith("english"):
            subtitle_url = t.get("file")
            break

    return hls_link, subtitle_url
