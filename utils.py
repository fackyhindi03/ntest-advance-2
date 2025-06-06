import os
import subprocess
import time
import requests
import logging
import re

logger = logging.getLogger(__name__)

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
    Converts an HLS stream (hls_link) into a local MP4 file named "Episode {ep_num}.mp4" in cache_dir.
    If ffprobe can return a valid duration, progress_callback(downloaded_mb, total_duration_s,
    percent, speed_mb_s, elapsed_s, eta_s) will be invoked periodically; otherwise it proceeds without %.
    Returns the local MP4 file path.

    This version adds `-protocol_whitelist "file,http,https,tcp,tls"` to the ffmpeg command
    to avoid crashes on certain HLS streams (exit code -11).
    """
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")

    # ─── 1) Try to get total duration (in seconds) via ffprobe ───────────────────────────────
    duration = None
    try:
        cmd_probe = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            hls_link
        ]
        result = subprocess.run(cmd_probe, capture_output=True, text=True, timeout=15)
        result_stdout = result.stdout.strip()
        if result_stdout:
            duration = float(result_stdout)
        else:
            raise RuntimeError("ffprobe returned empty stdout")
    except Exception as e:
        logger.warning(f"ffprobe failed for {hls_link}: {e}. Continuing without duration.")
        duration = None

    # ─── 2) Run ffmpeg, whitelisting HLS protocols ───────────────────────────────────────────
    # Using "-progress pipe:1" to get progress info on stdout.
    cmd_ffmpeg = [
        "ffmpeg",
        "-protocol_whitelist", "file,http,https,tcp,tls",
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
        stderr=subprocess.DEVNULL,  # ignore stderr, progress is on stdout
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    start_time = time.time()
    downloaded_mb = 0.0

    # Parse ffmpeg progress output (key=value lines)
    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            else:
                continue

        line = line.strip()
        if "=" not in line:
            continue

        key, val = line.split("=", 1)

        if key == "out_time_ms":
            # out_time_ms = microseconds of video processed
            try:
                out_time_ms = int(val)
            except ValueError:
                continue

            current_time_s = out_time_ms / 1_000_000.0
            percent = (current_time_s / duration) * 100 if (duration and duration > 0) else None

            # Check file size so far
            try:
                size_bytes = os.path.getsize(output_path)
            except OSError:
                size_bytes = 0
            downloaded_mb = size_bytes / (1024 * 1024)

            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0

            eta = None
            if percent is not None and percent > 0:
                eta = elapsed * (100 - percent) / percent

            if progress_callback:
                # Report: downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s
                progress_callback(downloaded_mb, duration, percent or 0.0, speed, elapsed, eta or 0.0)

        elif key == "progress" and val == "end":
            # Final progress (100%)
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
        # -11 means segmentation fault; any non-zero return is treated as failure
        raise RuntimeError(f"ffmpeg failed with exit code {retcode}")

    return output_path
