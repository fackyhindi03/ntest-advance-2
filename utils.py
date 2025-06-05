import os
import subprocess
import time
import requests
import shutil

def download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache"):
    """
    (Unchanged: downloads subtitle into "Episode {ep_num}.vtt" and returns its path.)
    """
    os.makedirs(cache_dir, exist_ok=True)
    local_filename = os.path.join(cache_dir, f"Episode {ep_num}.vtt")

    response = requests.get(subtitle_url, stream=True, timeout=30)
    response.raise_for_status()

    with open(local_filename, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    return local_filename


def download_and_rename_video(hls_link, ep_num, cache_dir="videos_cache", progress_callback=None):
    """
    Attempts to run ffprobe → ffmpeg to convert HLS→MP4 and report progress.
    If ffprobe/ffmpeg are missing or ffmpeg crashes, returns None to signal failure.
    Otherwise, returns the path to "Episode {ep_num}.mp4".
    """
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")

    # ——————————————
    # STEP A: Check ffprobe
    # ——————————————
    if shutil.which("ffprobe") is None:
        # ffprobe not found → skip conversion
        return None

    # Try to get duration via ffprobe; if it fails, we’ll still continue without duration
    duration = None
    try:
        cmd_probe = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            hls_link
        ]
        proc_probe = subprocess.run(
            cmd_probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=15
        )
        duration = float(proc_probe.stdout.strip())
    except Exception:
        # Any error reading duration → just proceed with duration = None
        duration = None

    # ——————————————
    # STEP B: Check ffmpeg
    # ——————————————
    if shutil.which("ffmpeg") is None:
        # ffmpeg not found → skip conversion
        return None

    # ——————————————
    # STEP C: Run ffmpeg with "-progress pipe:1"
    # ——————————————
    cmd_ffmpeg = [
        "ffmpeg",
        "-i", hls_link,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",  # fix AAC frames if needed
        "-progress", "pipe:1",
        "-nostats",
        output_path
    ]

    try:
        proc = subprocess.Popen(
            cmd_ffmpeg,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            bufsize=1
        )
    except Exception:
        # If launching ffmpeg fails (e.g., segfault immediately), skip conversion
        return None

    start_time = time.time()
    downloaded_mb = 0.0

    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                # ffmpeg process has ended
                break
            continue

        line = line.strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)

        if key == "out_time_ms":
            # “out_time_ms” = number of microseconds processed so far
            try:
                out_time_ms = int(val)
            except ValueError:
                continue

            current_time_s = out_time_ms / 1e6
            if duration:
                percent = (current_time_s / duration) * 100
            else:
                percent = None

            # Get file size so far
            try:
                size_bytes = os.path.getsize(output_path)
            except OSError:
                size_bytes = 0
            downloaded_mb = size_bytes / (1024 * 1024)

            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0

            # Compute ETA if percentage is known
            if percent and percent > 0:
                eta = (elapsed * (100 - percent) / percent)
            else:
                eta = None

            if progress_callback:
                # downloaded_mb, total_duration (or None), percent (or None), speed, elapsed, eta
                progress_callback(downloaded_mb, duration, percent, speed, elapsed, eta)

        elif key == "progress" and val == "end":
            # ffmpeg reported “progress=end” → final update
            try:
                size_bytes = os.path.getsize(output_path)
                downloaded_mb = size_bytes / (1024 * 1024)
            except OSError:
                downloaded_mb = downloaded_mb
            elapsed = time.time() - start_time
            speed = downloaded_mb / elapsed if elapsed > 0 else 0
            percent = 100.0 if duration else None
            eta = 0.0 if duration else None

            if progress_callback:
                progress_callback(downloaded_mb, duration, percent, speed, elapsed, eta)
            break

    retcode = proc.wait()
    # If ffmpeg’s exit code is nonzero (including -11), treat as failure
    if retcode != 0:
        return None

    return output_path
