import os
import requests
import re

ANIWATCH_API_BASE = os.getenv("ANIWATCH_API_BASE", "http://localhost:4000/api/v2/hianime")

def search_anime(query: str):
    params = {"q": query, "page": 1}
    url = f"{ANIWATCH_API_BASE}/search"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    results = []
    for item in data:
        title = item.get("name") or item.get("title") or item.get("slug", "")
        slug = item.get("slug", "")
        if not slug:
            continue
        anime_url = f"https://hianimez.to/watch/{slug}"
        results.append((title, anime_url, slug))
    return results

def get_episodes_list(anime_url: str):
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

    episodes.sort(key=lambda x: int(x[0]))
    return episodes

def extract_episode_stream_and_subtitle(episode_url: str):
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
        "server": "hd-1",
        "category": "sub"
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    sources = data.get("sources", [])
    tracks = data.get("tracks", [])

    hls_1080p = None
    for s in sources:
        if s.get("type") == "hls" and s.get("label", "").lower() == "hd-2":
            hls_1080p = s.get("url")
            break
    if not hls_1080p:
        for s in sources:
            if s.get("type") == "hls":
                hls_1080p = s.get("url")
                break

    subtitle_url = None
    for t in tracks:
        if t.get("srclang", "").lower() == "en":
            subtitle_url = t.get("file")
            break

    return hls_1080p, subtitle_url
