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
    Call AniWatch API's /search?q=<query>&page=1.
    The AniWatch response has the shape:
      {
        "status": 200,
        "data": {
          "animes": [ { "id": "...", "name": "...", "episodes": {...} }, … ],
          "mostPopularAnimes": [ … ],
          "searchQuery": "<your-term>",
          "totalPages": 3,
          …
        }
      }

    We only care about data["animes"], which is a list of anime objects.
    Returns a list of (title, anime_url, slug).
    """
    url = f"{ANIWATCH_API_BASE}/search"
    params = {"q": query, "page": 1}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    full_json = resp.json()
    logger.info("AniWatch /search raw JSON: %s", full_json)

    root = full_json.get("data", {})
    anime_list = root.get("animes", [])   # <<< lowercase "animes"

    results = []
    for item in anime_list:
        # Each `item` is a dict like:
        #   {
        #     "id": "naruto-677",
        #     "name": "Naruto",
        #     "jname": "Naruto",
        #     "poster": "https://....jpg",
        #     "duration": "23m",
        #     "type": "TV",
        #     "rating": null,
        #     "episodes": { "sub": 220, "dub": 220 }
        #   }
        #
        # We treat `item["id"]` as the slug for constructing the watch URL.
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
    Given a HiAnime page URL (e.g. "https://hianimez.to/watch/naruto-677"),
    extract the slug ("naruto-677"), then call:
      GET /episode/list?animeId=<slug>
    The AniWatch response is:
      { "status": 200, "data": [ { "episode": 1, "slug": "naruto-episode-1", … }, … ] }
    We return a sorted list of (episode_number, episode_url).
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    url = f"{ANIWATCH_API_BASE}/episode/list"
    params = {"animeId": slug}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

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


def extract_episode_stream_and_subtitle(episode_url: str):
    """
    Given a HiAnime episode URL (e.g. "https://hianimez.to/watch/naruto-episode-1"),
    we compute animeEpisodeId = "<slug>?ep=<n>" and call:
      GET /episode/sources?animeEpisodeId=<…>&server=hd-1&category=sub

    Response shape:
      { "status": 200, "data": {
          "sources": [ { "label": "HD-2", "file": "<m3u8_url>", "type": "hls" }, … ],
          "tracks": [ { "file": "<vtt_url>", "srclang": "en", … }, … ]
      } }

    We return (hls_1080p_url, english_vtt_url).
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
        "server": "hd-1",     # SUB server
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
        # fallback to first HLS
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
