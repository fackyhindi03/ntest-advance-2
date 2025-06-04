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
      [ (title, anime_url, animeId), … ]
    where `animeId` is the slug (e.g. "raven-of-the-inner-palace-18168"),
    and anime_url = "https://hianimez.to/watch/{animeId}".
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
            # item is a dict with keys "id" (the slug), "name", "jname", etc.
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
    extract slug = "raven-of-the-inner-palace-18168". Then call:
        GET /anime/{slug}/episodes

    Returns a list of (episode_number, episodeId) tuples, where episodeId is already the
    correct string to pass into /episode/sources (e.g. "raven-of-the-inner-palace-18168?ep=1").
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    # Use the v2 endpoint for listing all episodes:
    ep_list_url = f"{ANIWATCH_API_BASE}/anime/{slug}/episodes"
    resp = requests.get(ep_list_url, timeout=10)

    # If the anime truly does not exist (or is a single‐episode special),
    # this endpoint may 404. In that case, we assume a single‐episode fallback.
    if resp.status_code == 404:
        # Single-episode fallback: treat it as Episode 1
        return [("1", f"{slug}?ep=1")]

    resp.raise_for_status()
    full_json = resp.json()

    # The v2 API returns:
    #   { success: true, data: { totalEpisodes: number, episodes: [ { number, title, episodeId, … }, … ] } }
    episodes_data = full_json.get("data", {}).get("episodes", [])
    episodes = []

    for item in episodes_data:
        # Each item has fields:
        #   "number": <int>, 
        #   "episodeId": "<anime-slug>?ep=<n>", 
        #   etc.
        ep_num = str(item.get("number", "")).strip()
        ep_id  = item.get("episodeId", "").strip()
        if not ep_num or not ep_id:
            continue
        episodes.append((ep_num, ep_id))

    # Sort by numeric episode number just in case
    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_id: str):
    """
    Given an `episode_id` of the form "<animeSlug>?ep=<n>", call:
        GET /episode/sources?animeEpisodeId={episode_id}&server=hd-1&category=sub

    Then extract:
      1) the HLS URL (pick label=="hd-2" first, otherwise fallback to any "hls" source)
      2) the English (.vtt) subtitle URL

    Returns (hls_link_or_None, subtitle_url_or_None).
    """
    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": episode_id,
        "server": "hd-1",   # we want the SUB server
        "category": "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json().get("data", {})
    sources = data.get("sources", [])
    tracks  = data.get("tracks", [])

    # 1) Find "hd-2" HLS link (1080p). The v2 API uses "url" as the key.
    hls_1080p = None
    for s in sources:
        # The v2 shape is: { "url": "...master.m3u8", "type":"hls", "quality":"hd-2", … }
        # Sometimes the label/quality key might be "label" or "quality". We'll check both.
        label = (s.get("label") or s.get("quality") or "").lower()
        if s.get("type") == "hls" and label == "hd-2":
            hls_1080p = s.get("url")
            break

    # fallback to *any* HLS if we didn't find "hd-2"
    if not hls_1080p:
        for s in sources:
            if s.get("type") == "hls" and s.get("url"):
                hls_1080p = s.get("url")
                break

    # 2) Find English subtitle track (v2 uses "tracks" → { "file":"…vtt", "label":"English", … })
    subtitle_url = None
    for t in tracks:
        if t.get("label", "").lower().startswith("english"):
            subtitle_url = t.get("file")
            break

    return hls_1080p, subtitle_url
