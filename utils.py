import os
import subprocess
import time
import requests
import logging

logger = logging.getLogger(__name__)

def download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache"):
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
    Downloads an HLS stream to MP4 via ffmpeg.
    On exit code 145 (muxing queue overflow), retries once with a larger queue.
    """
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")

    # 1) Probe for duration (optional)
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            hls_link
        ], capture_output=True, text=True, timeout=15)
        duration = float(result.stdout.strip()) if result.stdout.strip() else None
    except Exception as e:
        logger.warning(f"ffprobe failed ({e}); proceeding without duration")
        duration = None

    # Prepare base ffmpeg command
    base_cmd = [
        "ffmpeg",
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", hls_link,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-progress", "pipe:1",
        "-nostats",
        output_path
    ]

    def run_ffmpeg(cmd):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )
        start_time = time.time()
        last_cb = 0.0

        # parse progress
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            line = line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key == "out_time_ms":
                out_ms = int(val) if val.isdigit() else 0
                curr_s = out_ms / 1e6
                pct = (curr_s / duration * 100) if duration else 0.0
                size_mb = os.path.getsize(output_path) / (1024*1024) if os.path.exists(output_path) else 0.0
                elapsed = time.time() - start_time
                speed = size_mb / elapsed if elapsed > 0 else 0.0
                eta = (elapsed * (100 - pct) / pct) if pct > 0 else None

                # throttle callbacks
                now = time.time()
                if progress_callback and (now - last_cb) > 3.0:
                    last_cb = now
                    progress_callback(size_mb, duration or 0.0, pct, speed, elapsed, eta or 0.0)
            elif key == "progress" and val == "end":
                break

        return proc.wait()

    # First attempt
    ret = run_ffmpeg(base_cmd)
    if ret == 0:
        return output_path

    # If we hit muxing-queue error, retry once with a larger queue
    if ret == 145:
        logger.warning(f"ffmpeg exit {ret} (mux overflow), retrying with larger mux queue")
        retry_cmd = base_cmd.copy()
        # insert just before "-progress"
        idx = retry_cmd.index("-progress")
        retry_cmd[idx:idx] = ["-max_muxing_queue_size", "9999"]
        ret2 = run_ffmpeg(retry_cmd)
        if ret2 == 0:
            return output_path
        else:
            logger.error(f"Retry also failed with exit code {ret2}")

    # give up
    raise RuntimeError(f"ffmpeg failed with exit code {ret}")
