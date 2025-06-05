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

    # Stream-download via requests
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

    # 1) Use ffprobe to get total duration (in seconds)
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
    except Exception as e:
        raise RuntimeError(f"Failed to get duration via ffprobe: {e}")

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
            # If process ended, break
            if proc.poll() is not None:
                break
            continue

        line = line.strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)

        if key == "out_time_ms":
            # out_time_ms is the number of microseconds of video already processed
            try:
                out_time_ms = int(val)
            except ValueError:
                continue

            current_time_s = out_time_ms / 1e6
            percent = (current_time_s / duration) * 100 if duration > 0 else 0

            # Check file size so far
            try:
                size_bytes = os.path.getsize(output_path)
            except OSError:
                size_bytes = 0
            downloaded_mb = size_bytes / (1024 * 1024)

            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0

            # ETA = elapsed × (100 – percent) / percent
            eta = (elapsed * (100 - percent) / percent) if percent > 0 else None

            if progress_callback:
                # Report: downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s
                progress_callback(downloaded_mb, duration, percent, speed, elapsed, eta)

        elif key == "progress" and val == "end":
            # Reached the end of encoding → report 100% one final time
            try:
                size_bytes = os.path.getsize(output_path)
                downloaded_mb = size_bytes / (1024 * 1024)
            except OSError:
                downloaded_mb = downloaded_mb
            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0
            percent = 100.0
            eta = 0.0

            if progress_callback:
                progress_callback(downloaded_mb, duration, percent, speed, elapsed, eta)
            break

    retcode = proc.wait()
    if retcode != 0:
        raise RuntimeError(f"ffmpeg failed with code {retcode}")

    return output_path
