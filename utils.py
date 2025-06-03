# utils.py

import os
import requests
from urllib.parse import urlparse


def download_and_rename_subtitle(subtitle_url: str, episode_number: str, cache_dir: str = "subtitles_cache"):
    """
    Download the .vtt subtitle from subtitle_url, rename it to "Episode <episode_number>.vtt",
    and save it inside cache_dir. Returns the full local filepath.
    
    Example:
      subtitle_url = "https://s.megastatics.com/subtitle/abc123.vtt"
      episode_number = "3"
      → saves as "subtitles_cache/Episode 3.vtt"
    """
    # Ensure the cache directory exists
    os.makedirs(cache_dir, exist_ok=True)

    # Download the .vtt
    resp = requests.get(subtitle_url, stream=True, timeout=15)
    resp.raise_for_status()

    # Construct the local filename
    local_filename = os.path.join(cache_dir, f"Episode {episode_number}.vtt")

    # Write out the content
    with open(local_filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                f.write(chunk)

    return local_filename
