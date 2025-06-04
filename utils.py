import os
import requests
import subprocess
import logging

logger = logging.getLogger(__name__)

def download_and_rename_subtitle(subtitle_url: str, ep_num: str, cache_dir: str = "subtitles_cache") -> str:
    """
    Fetches a .vtt subtitle from subtitle_url and writes it to:
        <cache_dir>/Episode <ep_num>.vtt
    Returns the local file path.
    """
    os.makedirs(cache_dir, exist_ok=True)
    local_filename = f"Episode {ep_num}.vtt"
    local_path = os.path.join(cache_dir, local_filename)

    resp = requests.get(subtitle_url, timeout=15)
    resp.raise_for_status()

    with open(local_path, "wb") as f:
        f.write(resp.content)

    return local_path


def download_and_rename_video(hls_url: str, ep_num: str, cache_dir: str = "videos_cache") -> str:
    """
    Uses ffmpeg to pull down an HLS stream (m3u8) and save as MP4:
        ffmpeg -i <hls_url> -c copy <cache_dir>/Episode <ep_num>.mp4

    Returns the local MP4 file path. Raises an exception if ffmpeg fails.
    """
    os.makedirs(cache_dir, exist_ok=True)
    local_filename = f"Episode {ep_num}.mp4"
    local_path = os.path.join(cache_dir, local_filename)

    # Build ffmpeg command
    cmd = [
        "ffmpeg",
        "-y",              # overwrite output if it exists
        "-i", hls_url,     # input HLS URL
        "-c", "copy",      # copy codecs (no re-encode)
        local_path
    ]

    try:
        # Run ffmpeg and wait for it to finish
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            universal_newlines=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed: {e.stderr}")
        raise RuntimeError(f"Failed to download video for Episode {ep_num}") from e

    return local_path
