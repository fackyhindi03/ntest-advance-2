import os
import requests
import subprocess
import logging

logger = logging.getLogger(__name__)


def download_and_rename_subtitle(subtitle_url: str, ep_num: str,
                                 cache_dir: str = "subtitles_cache") -> str:
    """
    Fetches a .vtt subtitle from `subtitle_url` and saves it to:
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


def download_and_rename_video(hls_url: str, ep_num: str,
                             cache_dir: str = "videos_cache") -> str:
    """
    Uses ffmpeg to pull down an HLS stream (m3u8) and save as MP4:
        ffmpeg -i <hls_url> -c copy <cache_dir>/Episode <ep_num>.mp4
    Returns the local MP4 file path. Raises if ffmpeg fails.
    """
    os.makedirs(cache_dir, exist_ok=True)
    local_filename = f"Episode {ep_num}.mp4"
    local_path = os.path.join(cache_dir, local_filename)

    cmd = [
        "ffmpeg",
        "-y",             # overwrite output if it already exists
        "-i", hls_url,    # input HLS URL
        "-c", "copy",     # copy both audio & video without re-encoding
        local_path
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            universal_newlines=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed (download_and_rename_video): {e.stderr}")
        raise RuntimeError(f"Failed to download video for Episode {ep_num}") from e

    return local_path


def transcode_to_telegram_friendly(input_path: str, ep_num: str,
                                   cache_dir: str = "videos_cache") -> str:
    """
    If the MP4 at `input_path` is >50 MB, re-encode it so that
    the result is under ~50 MB. Returns the new file path.
    Raises on failure.
    """
    MAX_BYTES = 50 * 1024 * 1024  # 50 MB

    try:
        file_size = os.path.getsize(input_path)
    except OSError:
        raise RuntimeError(f"Cannot access {input_path} to check size")

    # If already ≤50 MB, no need to re-encode
    if file_size <= MAX_BYTES:
        return input_path

    # Otherwise, build a “small” filename
    base_dir = os.path.dirname(input_path)
    small_filename = f"Episode {ep_num}_small.mp4"
    small_path = os.path.join(base_dir, small_filename)

    # ffmpeg arguments to scale down & lower bitrate:
    #   • scale width=640 px (auto height),
    #   • H.264 @ ~800 kbps, AAC @ 128 kbps
    cmd = [
        "ffmpeg",
        "-y",                      # overwrite if exists
        "-i", input_path,
        "-vf", "scale=640:-2",     # scale width=640, preserve aspect ratio
        "-c:v", "libx264",
        "-b:v", "800k",
        "-preset", "veryfast",
        "-c:a", "aac",
        "-b:a", "128k",
        small_path
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            universal_newlines=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed (transcode_to_telegram_friendly): {e.stderr}")
        raise RuntimeError(f"Failed to transcode Episode {ep_num} to small MP4") from e

    # Confirm new file is ≤50 MB:
    try:
        new_size = os.path.getsize(small_path)
    except OSError:
        raise RuntimeError(f"Could not access re-encoded file {small_path}")

    if new_size > MAX_BYTES:
        # If it’s still too big, delete it and error out
        try:
            os.remove(small_path)
        except OSError:
            pass
        raise RuntimeError(f"Re-encoded file still too large ({new_size} bytes)")

    return small_path
