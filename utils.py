import os
import subprocess
import time
import requests
import logging
from shutil import which

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


def download_with_yt_dlp(hls_link, ep_num, cache_dir="videos_cache"):
    """
    Fast HLS downloader using yt-dlp. Falls back to ffmpeg on failure.
    """
    os.makedirs(cache_dir, exist_ok=True)
    out_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        "--merge-output-format", "mp4",
        "-o", out_path,
        hls_link,
    ]
    try:
        subprocess.run(cmd, check=True)
        return out_path
    except FileNotFoundError:
        logger.warning("yt-dlp not installed; falling back to ffmpeg.")
    except subprocess.CalledProcessError as e:
        logger.warning(f"yt-dlp failed (code {e.returncode}); falling back to ffmpeg.")
    # fallback:
    return _download_with_ffmpeg(hls_link, ep_num, cache_dir)


def _download_with_ffmpeg(hls_link, ep_num, cache_dir="videos_cache", progress_callback=None):
    """
    Original ffmpeg-based downloader (with mux-queue retry).
    """
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"Episode {ep_num}.mp4")

    # 1) probe duration
    try:
        pr = subprocess.run([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",
            hls_link
        ], capture_output=True, text=True, timeout=15)
        duration = float(pr.stdout.strip()) if pr.stdout.strip() else None
    except Exception:
        duration = None
        logger.warning("ffprobe failed; continuing without duration")

    def run_ffmpeg(cmd):
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1
        )
        start = time.time()
        last_cb = 0.0

        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            line = line.strip()
            if "=" not in line:
                continue
            key,val = line.split("=",1)
            if key=="out_time_ms":
                out_ms = int(val) if val.isdigit() else 0
                curr = out_ms/1e6
                pct  = (curr/duration*100) if duration else 0.0
                size = os.path.getsize(output_path)/(1024**2) if os.path.exists(output_path) else 0.0
                elapsed = time.time()-start
                speed   = size/elapsed if elapsed>0 else 0.0
                eta     = (elapsed*(100-pct)/pct) if pct>0 else None

                now = time.time()
                if progress_callback and (now-last_cb)>3.0:
                    last_cb = now
                    progress_callback(size, duration or 0.0, pct, speed, elapsed, eta or 0.0)
            elif key=="progress" and val=="end":
                break

        return proc.wait()

    # base copy-mode
    base_cmd = [
        "ffmpeg",
        "-protocol_whitelist","file,http,https,tcp,tls",
        "-i", hls_link,
        "-c","copy",
        "-bsf:a","aac_adtstoasc",
        "-max_muxing_queue_size","9999",
        "-progress","pipe:1","-nostats",
        output_path
    ]

    code = run_ffmpeg(base_cmd)
    if code == 0:
        return output_path

    logger.warning(f"ffmpeg copy-mode exit {code}")
    if code == 145:
        # retry once
        logger.info("retrying copy-mode…")
        code2 = run_ffmpeg(base_cmd)
        if code2 == 0:
            return output_path
        logger.warning(f"retry also exit {code2}")

    # give up
    raise RuntimeError(f"ffmpeg failed with exit code {code}")


# Expose a single function for your bot to use:
def download_and_rename_video(hls_link, ep_num, cache_dir="videos_cache", progress_callback=None):
    """
    Try yt-dlp first (fast & parallel), then fallback to ffmpeg copy.
    We ignore progress_callback in yt-dlp mode.
    """
    if which("yt-dlp"):
        return download_with_yt_dlp(hls_link, ep_num, cache_dir)
    else:
        return _download_with_ffmpeg(hls_link, ep_num, cache_dir, progress_callback)
