import re
from urllib.parse import urlsplit

from .config import Settings


def safe_error(exc: Exception, settings: Settings) -> str:
    text = str(exc)
    if settings.api_key:
        text = text.replace(settings.api_key, "[redacted]")
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", text)
    text = re.sub(r"(?i)(authorization|api[_-]?key)[=: ]+[^\s,}]+", r"\1=[redacted]", text)
    return f"{type(exc).__name__}: {text[:650]}"


def allowed_link(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username
    except ValueError:
        return False
