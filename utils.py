import os
import subprocess
import time
import requests

def download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache"):
    """
    Downloads subtitle from subtitle_url, saves as "Episode {ep_num}.vtt" in cache_dir.
    Returns the local file path.
    """
    os.makedirs(cache_dir, exist_ok=True)
    local_filename = os.path.join(cache_dir, f"Episode {ep_num}.vtt")

    # Stream‐download via requests
    response = requests.get(subtitle_url, stream=True, timeout=30)
    response.raise_for_status()

    with open(local_filename, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    return local_filename


def download_and_rename_video(hls_link, ep_num, cache_dir="videos_cache", progress_callback=None):
    """
    Uses ffprobe → ffmpeg to download an HLS stream into an MP4.
    Reports progress via progress_callback(downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s).

    Returns the local file path "Episode {ep_num}.mp4".
    """
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")

    # 1) Try ffprobe to get total duration (in seconds)
    duration = None
    try:
        cmd_probe = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            hls_link
        ]
        result = subprocess.run(
            cmd_probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=15
        )
        duration = float(result.stdout.strip())
    except FileNotFoundError as e:
        # ffprobe not installed; skip duration-based percentage
        duration = None
    except Exception:
        # Any ffprobe error—skip percentage-based progress
        duration = None

    # 2) Run ffmpeg with "-progress pipe:1" to get periodic progress on stdout
    cmd_ffmpeg = [
        "ffmpeg",
        "-i", hls_link,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",   # fix AAC frames if needed
        "-progress", "pipe:1",
        "-nostats",
        output_path
    ]
    proc = subprocess.Popen(
        cmd_ffmpeg,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
        bufsize=1
    )

    start_time = time.time()
    downloaded_mb = 0.0

    while True:
        line = proc.stdout.readline()
        if not line:
            # If process has ended, break
            if proc.poll() is not None:
                break
            continue

        line = line.strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)

        if key == "out_time_ms":
            # out_time_ms is microseconds of video processed so far
            try:
                out_time_ms = int(val)
            except ValueError:
                continue

            current_time_s = out_time_ms / 1e6
            if duration is not None and duration > 0:
                percent = (current_time_s / duration) * 100
            else:
                percent = None

            # Check file size so far
            try:
                size_bytes = os.path.getsize(output_path)
            except OSError:
                size_bytes = 0
            downloaded_mb = size_bytes / (1024 * 1024)

            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0

            # ETA only if percent is known
            if percent is not None and percent > 0:
                eta = (elapsed * (100 - percent) / percent)
            else:
                eta = None

            if progress_callback:
                # Report: downloaded_mb, total_duration_s (or None), percent (or None), speed_mb_s, elapsed_s, eta_s (or None)
                progress_callback(downloaded_mb, duration, percent, speed, elapsed, eta)

        elif key == "progress" and val == "end":
            # Encoding finished → final 100% if duration known
            try:
                size_bytes = os.path.getsize(output_path)
                downloaded_mb = size_bytes / (1024 * 1024)
            except OSError:
                downloaded_mb = downloaded_mb
            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0
            percent = 100.0 if duration is not None else None
            eta = 0.0 if duration is not None else None

            if progress_callback:
                progress_callback(downloaded_mb, duration, percent, speed, elapsed, eta)
            break

    retcode = proc.wait()
    if retcode != 0:
        raise RuntimeError(f"ffmpeg failed with code {retcode}")

    return output_path
