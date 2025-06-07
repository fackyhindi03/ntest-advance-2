import os
import subprocess
import time
import requests
import logging

logger = logging.getLogger(__name__)


def download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache"):
    """
    Downloads subtitle from subtitle_url, saves as "Episode {ep_num}.vtt" in cache_dir.
    Returns the local file path.
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
    Tries, in order:
      1) yt-dlp (if installed)
      2) ffmpeg copy-mode (with max_muxing_queue_size retry)
      3) ffmpeg full re-encode (libx264 + aac)

    Reports progress via progress_callback(downloaded_mb, total_duration_s,
    percent, speed_mb_s, elapsed_s, eta_s).

    Returns path to "Episode {ep_num}.mp4".
    """
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")

    # ─── 1) Try yt-dlp if available ─────────────────────────────────────────────
    try:
        import yt_dlp
        ydl_opts = {
            "format": "best[protocol^=https]",
            "outtmpl": output_path,
            "quiet": True,
            "noprogress": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([hls_link])
        return output_path
    except Exception as e:
        logger.warning(f"yt-dlp failed ({e}); falling back to ffmpeg.")

    # ─── helper to run ffmpeg + report progress ─────────────────────────────────
    def _run_ffmpeg(cmd):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )
        start = time.time()
        last_cb = 0.0

        # attempt to probe duration
        duration = None
        try:
            res = subprocess.run([
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                hls_link
            ], capture_output=True, text=True, timeout=15)
            out = res.stdout.strip()
            duration = float(out) if out else None
        except:
            logger.warning("ffprobe failed; proceeding without duration")

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
                try:
                    out_ms = int(val)
                except:
                    continue
                curr_s = out_ms / 1e6
                pct = (curr_s / duration * 100) if (duration and duration > 0) else 0.0
                size_mb = (os.path.getsize(output_path) / (1024 * 1024)) if os.path.exists(output_path) else 0.0
                elapsed = time.time() - start
                speed = (size_mb / elapsed) if elapsed > 0 else 0.0
                eta = (elapsed * (100 - pct) / pct) if pct > 0 else None

                now = time.time()
                if progress_callback and (now - last_cb) > 3.0:
                    last_cb = now
                    progress_callback(size_mb, duration or 0.0, pct, speed, elapsed, eta or 0.0)

        return proc.wait()

    # ─── 2) ffmpeg copy-mode ─────────────────────────────────────────────────────
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
    code = _run_ffmpeg(base_cmd)
    if code == 0:
        return output_path

    # retry on mux-queue overflow
    if code == 145:
        logger.warning("ffmpeg copy-mode exit 145; retrying with larger mux queue…")
        retry_cmd = base_cmd.copy()
        idx = retry_cmd.index("-progress")
        retry_cmd[idx:idx] = ["-max_muxing_queue_size", "9999"]
        code2 = _run_ffmpeg(retry_cmd)
        if code2 == 0:
            return output_path
        logger.warning(f"Retry also exited with {code2}")

    # ─── 3) full re-encode ───────────────────────────────────────────────────────
    logger.warning("Falling back to full re-encode with libx264/aac…")
    encode_cmd = [
        "ffmpeg",
        "-protocol_whitelist", "file,http,https,tcp,tls",
        "-i", hls_link,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1",
        "-nostats",
        output_path
    ]
    code3 = _run_ffmpeg(encode_cmd)
    if code3 == 0:
        return output_path

    logger.error(f"Full re-encode also failed with exit code {code3}")
    raise RuntimeError(f"ffmpeg failed with exit code {code3}")
