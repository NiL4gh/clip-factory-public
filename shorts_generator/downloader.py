import subprocess
import os
import glob
import typing
from .logger import ui_logger

def _is_local_path(url: str) -> bool:
    clean = str(url).strip('"').strip("'")
    if not clean:
        return False
    if clean.startswith(('http://', 'https://', 'ftp://', 'rtmp://', 'www.')):
        return False
    if os.path.isabs(clean) or clean.startswith(('/', '\\', './', '.\\', '~')):
        return True
    if len(clean) >= 2 and clean[1] == ':':
        return True
    ext = os.path.splitext(clean)[1].lower()
    if ext in ('.mp4', '.mov', '.mkv', '.avi', '.webm', '.flv', '.m4v', '.wmv'):
        return True
    return False


def _resolve_local_file(path_or_name: str) -> typing.Optional[str]:
    clean = str(path_or_name).strip('"').strip("'")
    if not clean:
        return None
    if os.path.exists(clean) and os.path.isfile(clean):
        return clean

    fname = os.path.basename(clean)
    candidates = [
        clean,
        os.path.join(os.path.expanduser("~"), "Downloads", fname),
    ]
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.exists(downloads_dir):
        try:
            for item in os.listdir(downloads_dir):
                sub = os.path.join(downloads_dir, item)
                if os.path.isdir(sub):
                    candidates.append(os.path.join(sub, fname))
        except Exception:
            pass
    try:
        from .config import BASE_DIR
        uploads_dir = os.path.join(BASE_DIR, "uploads")
        if os.path.exists(uploads_dir):
            for root, _, files in os.walk(uploads_dir):
                if fname in files:
                    candidates.append(os.path.join(root, fname))
    except Exception:
        pass

    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def download_video(url, work_dir, cookie_path=None):
    output_mp4 = f"{work_dir}/source.mp4"

    ui_logger.log(f"Starting download for: {url}")
    # Clean old source files to prevent conflicts
    for f in glob.glob(f"{work_dir}/source.*"):
        try:
            os.remove(f)
        except OSError:
            pass

    import shutil
    clean_url = str(url).strip('"').strip("'")
    local_resolved = _resolve_local_file(clean_url)
    if local_resolved:
        ui_logger.log(f"Local file detected: '{local_resolved}'. Linking to work directory...")
        try:
            os.link(local_resolved, output_mp4)
            ui_logger.log("Local file link complete.")
        except Exception:
            ui_logger.log(f"Link failed, copying '{local_resolved}'...")
            shutil.copy2(local_resolved, output_mp4)
            ui_logger.log("Local file copy complete.")
        return output_mp4

    if _is_local_path(clean_url):
        raise FileNotFoundError(
            f"Local video file not found: '{clean_url}'. "
            "Please verify the file exists on your disk or wait for the upload to finish."
        )

    # Client selection rationale (confirmed via --verbose per-client diagnostic):
    # - android: skipped when cookies present (yt-dlp warning confirmed)
    # - web/ios/mweb: SABR streaming forced → needs PO Token → HTTPS DASH streams dropped
    # - tv_embedded: triggers fallback that exposes WEB-S HLS (m3u8) streams at 720p/1080p
    #   AND ANDR-V DASH video-only streams. HLS streams bypass the SABR/PO Token block.
    # Format priority: DASH adaptive (best quality) → 1080p HLS combined → best available
    # --remux-video mp4: handles both DASH and HLS → mp4 container without re-encoding video
    cmd = [
        'yt-dlp',
        '-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        '-S', 'res:1080,fps,codec:h264',
        '--remux-video', 'mp4',
        '-o', output_mp4,
        '--no-warnings',
    ]
    if cookie_path and os.path.exists(cookie_path):
        cmd.extend(['--cookies', str(cookie_path)])
    cmd.append(url)

    ui_logger.log(f"Downloading with web client + Deno n-challenge solver (cookies: {cookie_path})...")
    # On Colab/Linux, prepend the Deno binary directory so yt-dlp can use it for
    # the n-challenge JavaScript solver. On Windows, leave PATH untouched — Deno
    # is not at that path and prepending it with ":" (Linux separator) corrupts
    # the Windows PATH, breaking the subprocess entirely.
    env = os.environ.copy()
    if os.name != "nt":
        env["PATH"] = f"/root/.deno/bin:{env.get('PATH', '')}"

    extra_kwargs = {}
    if os.name == "nt":
        extra_kwargs["creationflags"] = 0x08000000

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env, **extra_kwargs)
        # Log format selection so we can confirm which stream yt-dlp actually picked
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                if any(k in line.lower() for k in ["warning", "fallback", "unavailable", "skipping",
                                                     "downloading 1 format", "merger", "[info]"]):
                    ui_logger.log(f"yt-dlp: {line.strip()}")
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                if any(k in line.lower() for k in ["format", "merger", "destination", "downloading 1"]):
                    ui_logger.log(f"yt-dlp: {line.strip()}")
    except subprocess.CalledProcessError as e:
        stderr_str = e.stderr or ""
        ui_logger.log(f"yt-dlp failed: {stderr_str[-600:]}")
        if any(sig in stderr_str.lower() for sig in ["sign in", "confirm your age", "cookies", "login"]):
            ui_logger.error("⚠️ cookies.txt may be expired. Re-export from browser.")
        raise RuntimeError(f"yt-dlp failed: {stderr_str[-600:]}")

    ui_logger.log("Download complete.")

    # Diagnostic: log source format so we can diagnose quality issues
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name,bit_rate,r_frame_rate",
             "-of", "default=noprint_wrappers=1", output_mp4],
            capture_output=True, text=True, timeout=15
        )
        if probe.stdout.strip():
            ui_logger.log(f"📐 Source video: {probe.stdout.strip().replace(chr(10), ' | ')}")
            # Warn if source is below 720p — output clips will have visible quality issues
            for line in probe.stdout.strip().splitlines():
                if line.startswith("height="):
                    h = int(line.split("=")[1])
                    if h < 720:
                        ui_logger.error(f"⚠️ Source video is only {h}p — clips will look poor. Use a 1080p video for best results.")
                    break
    except Exception:
        pass

    return output_mp4

def get_video_title(url: str, cookie_path: str = None) -> str:
    """Return the video title from yt-dlp without downloading. Empty string on failure."""
    clean_url = str(url).strip('"').strip("'")
    local_resolved = _resolve_local_file(clean_url)
    if local_resolved:
        return os.path.splitext(os.path.basename(local_resolved))[0]
    if _is_local_path(clean_url):
        return os.path.splitext(os.path.basename(clean_url))[0]

    cmd = [
        'yt-dlp', '--print', 'title', '--skip-download', '--no-warnings',
    ]
    if cookie_path and os.path.exists(cookie_path):
        cmd += ['--cookies', str(cookie_path)]
    cmd.append(url)
    env = os.environ.copy()
    if os.name != "nt":
        env["PATH"] = f"/root/.deno/bin:{env.get('PATH', '')}"
    try:
        extra_kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env, **extra_kwargs)
        title = result.stdout.strip()
        if not title:
            ui_logger.log("⚠️ Could not fetch video title from yt-dlp — log folder will be unnamed.")
        return title
    except Exception as e:
        ui_logger.log(f"⚠️ get_video_title failed: {e}")
        return ""


def download_srt(video_url: str, output_dir: str, video_id: str) -> typing.Optional[str]:
    try:
        clean_url = str(video_url).strip('"').strip("'")
        if _is_local_path(clean_url) or _resolve_local_file(clean_url):
            return None # Fallback to whisper for local files

        from shorts_generator.config import BASE_DIR
        cookie_path = os.path.join(BASE_DIR, "cookies.txt")
        
        # Build yt-dlp command to download auto-generated English SRT subtitles
        cmd = [
            'yt-dlp',
            '--write-auto-sub',
            '--sub-lang', 'en',
            '--convert-subs', 'srt',
            '--skip-download',
            '--no-warnings',
        ]
        if cookie_path and os.path.exists(cookie_path):
            cmd.extend(['--cookies', str(cookie_path)])
        cmd.extend(['-o', f"{output_dir}/{video_id}.%(ext)s", video_url])
        
        # Run the command with a 30 second timeout
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        
        # Search for first matching file matching the pattern output_dir/video_id*.srt
        pattern = os.path.join(output_dir, f"{video_id}*.srt")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
            
        return None
    except Exception as e:
        ui_logger.log(f"Warning: download_srt failed: {e}")
        return None

