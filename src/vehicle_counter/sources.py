from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SOURCE_KIND_LOCAL_FILE = "local_file"
SOURCE_KIND_YOUTUBE_URL = "youtube_url"
SOURCE_KIND_DIRECT_STREAM = "direct_stream"
STREAM_FORMAT_MJPEG = "mjpeg"
STREAM_FORMAT_HLS = "hls"
STREAM_FORMAT_RTSP = "rtsp"
SUPPORTED_STREAM_FORMATS = {
    STREAM_FORMAT_MJPEG,
    STREAM_FORMAT_HLS,
    STREAM_FORMAT_RTSP,
}


@dataclass
class VideoSource:
    source_kind: str
    original_input: str
    playable_input: str
    display_name: str
    is_live: bool = False
    stream_format: str | None = None


def resolve_local_file_source(path):
    normalized_path = (path or "").strip()
    if not normalized_path:
        return None, "Choose a local video file first."

    file_path = Path(normalized_path)
    if not file_path.exists():
        return None, "The selected video file does not exist."

    return (
        VideoSource(
            source_kind=SOURCE_KIND_LOCAL_FILE,
            original_input=str(file_path),
            playable_input=str(file_path),
            display_name=file_path.name,
            is_live=False,
        ),
        None,
    )


def resolve_youtube_source(url):
    normalized_url = normalize_youtube_url(url)
    if not normalized_url:
        return None, "Paste a valid YouTube watch, short-link, or live URL."

    try:
        import yt_dlp
    except Exception:
        return (
            None,
            "YouTube support requires the 'yt-dlp' package. Install dependencies again and retry.",
        )

    ydl_options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "format": "best[protocol^=http]/best[protocol^=m3u8]/best",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(normalized_url, download=False)
    except Exception as exc:
        return None, map_youtube_resolution_error(exc)

    video_info = unwrap_video_info(info)
    if not video_info:
        return None, "The YouTube URL could not be resolved into a playable stream."

    live_status = str(video_info.get("live_status") or "").lower()
    is_live = bool(video_info.get("is_live")) or live_status in {
        "is_live",
        "post_live",
    }

    if live_status == "is_upcoming":
        return None, "This YouTube live stream has not started yet."

    playable_input = extract_playable_input(video_info)
    if not playable_input:
        if live_status in {"was_live", "post_live"}:
            return None, "This YouTube live stream has already ended."
        return None, "The YouTube stream is unavailable or could not be extracted."

    title = (video_info.get("title") or "YouTube video").strip()
    return (
        VideoSource(
            source_kind=SOURCE_KIND_YOUTUBE_URL,
            original_input=normalized_url,
            playable_input=playable_input,
            display_name=title,
            is_live=is_live,
            stream_format="youtube",
        ),
        None,
    )


def resolve_direct_stream_source(url):
    normalized_url = normalize_direct_stream_url(url)
    if not normalized_url:
        return None, (
            "Paste a valid direct stream URL. Supported formats: MJPEG over HTTP/HTTPS, "
            "HLS (.m3u8), or RTSP."
        )

    stream_format, error_message = detect_direct_stream_format(normalized_url)
    if error_message:
        return None, error_message

    display_name = build_direct_stream_display_name(normalized_url, stream_format)
    return (
        VideoSource(
            source_kind=SOURCE_KIND_DIRECT_STREAM,
            original_input=normalized_url,
            playable_input=normalized_url,
            display_name=display_name,
            is_live=True,
            stream_format=stream_format,
        ),
        None,
    )


def normalize_youtube_url(url):
    normalized_url = (url or "").strip()
    if not normalized_url:
        return None

    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    path = parsed.path or ""

    valid_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
    if host not in valid_hosts:
        return None

    if host.endswith("youtu.be") and path.strip("/"):
        return normalized_url

    if path == "/watch" and parse_qs(parsed.query).get("v"):
        return normalized_url

    if path.startswith("/live/") and path.strip("/").split("/", 1)[-1]:
        return normalized_url

    return None


def normalize_direct_stream_url(url):
    normalized_url = (url or "").strip()
    if not normalized_url:
        return None

    parsed = urlparse(normalized_url)
    if parsed.scheme.lower() not in {"http", "https", "rtsp"}:
        return None

    if not parsed.netloc:
        return None

    return normalized_url


def detect_direct_stream_format(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    combined_path = f"{parsed.path}?{parsed.query}".lower()

    if scheme == "rtsp":
        return STREAM_FORMAT_RTSP, None

    if combined_path.endswith(".m3u8") or ".m3u8?" in combined_path:
        return STREAM_FORMAT_HLS, None

    if looks_like_mjpeg_stream(combined_path):
        return STREAM_FORMAT_MJPEG, None

    return (
        None,
        "Unsupported direct stream format. Use an MJPEG URL, an HLS .m3u8 URL, or an RTSP URL.",
    )


def looks_like_mjpeg_stream(path_and_query):
    mjpeg_markers = (
        ".mjpg",
        ".mjpeg",
        "mjpg",
        "mjpeg",
        "mjpeg.cgi",
        "video.cgi",
        "videostream",
        "video_feed",
        "stream",
        "axis-cgi/mjpg",
    )
    return any(marker in path_and_query for marker in mjpeg_markers)


def build_direct_stream_display_name(url, stream_format):
    parsed = urlparse(url)
    host = parsed.netloc or "camera"
    format_label = stream_format.upper() if stream_format else "STREAM"
    return f"{format_label} stream ({host})"


def unwrap_video_info(info):
    if not info:
        return None

    entries = info.get("entries")
    if entries:
        for entry in entries:
            if entry:
                return entry

    return info


def extract_playable_input(video_info):
    direct_url = video_info.get("url")
    if direct_url:
        return direct_url

    requested_formats = video_info.get("requested_formats") or []
    for fmt in requested_formats:
        playable_url = fmt.get("url")
        if playable_url:
            return playable_url

    formats = video_info.get("formats") or []
    for fmt in reversed(formats):
        playable_url = fmt.get("url")
        if playable_url:
            return playable_url

    return None


def map_youtube_resolution_error(exc):
    message = str(exc).strip()
    lowered = message.lower()

    if any(keyword in lowered for keyword in ("unsupported url", "invalid url")):
        return "Paste a valid YouTube watch, short-link, or live URL."

    if any(keyword in lowered for keyword in ("video unavailable", "private video", "members-only")):
        return "The YouTube video is unavailable."

    if any(keyword in lowered for keyword in ("sign in to confirm your age", "confirm your age")):
        return "This YouTube video requires age verification and cannot be opened in the app."

    if any(keyword in lowered for keyword in ("network", "timed out", "temporarily unavailable", "connection")):
        return "The YouTube stream could not be reached. Check your network connection and try again."

    if "live event will begin" in lowered:
        return "This YouTube live stream has not started yet."

    return f"YouTube extraction failed: {message or 'Unknown error.'}"
