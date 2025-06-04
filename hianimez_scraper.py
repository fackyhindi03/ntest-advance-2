import os
import requests
import logging

logger = logging.getLogger(__name__)

ANIWATCH_API_BASE = os.getenv(
    "ANIWATCH_API_BASE",
    "http://localhost:4000/api/v2/hianime"
)


def search_anime(query: str):
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
    extract slug = "raven-of-the-inner-palace-18168". Then call:
        GET /anime/{slug}/episodes

    Returns a list of (episode_number, episodeId) tuples.
    """
    try:
        slug = anime_url.rstrip("/").split("/")[-1]
    except Exception:
        return []

    ep_list_url = f"{ANIWATCH_API_BASE}/anime/{slug}/episodes"
    resp = requests.get(ep_list_url, timeout=10)

    if resp.status_code == 404:
        # Single‐episode fallback
        return [("1", f"{slug}?ep=1")]

    resp.raise_for_status()
    full_json = resp.json()

    episodes_data = full_json.get("data", {}).get("episodes", [])
    episodes = []

    for item in episodes_data:
        ep_num = str(item.get("number", "")).strip()
        ep_id  = item.get("episodeId", "").strip()
        if not ep_num or not ep_id:
            continue
        episodes.append((ep_num, ep_id))

    episodes.sort(key=lambda x: int(x[0]))
    return episodes


def extract_episode_stream_and_subtitle(episode_id: str):
    """
    Given an `episode_id` such as "raven-of-the-inner-palace-18168?ep=1", we now explicitly
    request SUB HD-2 by setting server="hd-2". That ensures the returned `sources` array
    contains exactly the HD-2 HLS entry (if available).

    Returns (hls_link_or_None, subtitle_url_or_None).
    """
    url = f"{ANIWATCH_API_BASE}/episode/sources"
    params = {
        "animeEpisodeId": episode_id,
        "server":          "hd-2",   # <<< FORCE the SUB HD-2 server
        "category":       "sub"
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    data = resp.json().get("data", {})
    sources = data.get("sources", [])
    tracks  = data.get("tracks", [])

    # Since we specifically asked for server=hd-2, the returned `sources` array
    # should already be limited to HD-2. Just pick the first HLS URL we see.
    hls_link = None
    for s in sources:
        if s.get("type") == "hls" and s.get("url"):
            hls_link = s.get("url")
            break

    # If somehow no HLS field was present, hls_link will remain None.

    # Next, find the English subtitle track:
    subtitle_url = None
    for t in tracks:
        if t.get("label", "").lower().startswith("english"):
            subtitle_url = t.get("file")
            break

    return hls_link, subtitle_url
