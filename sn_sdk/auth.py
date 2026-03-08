"""Authentication helpers for Stacker News SDK.

Two auth methods are supported:

1. **API key** — set ``STACKER_NEWS_API_KEY`` in your environment or pass
   ``api_key=`` to ``StackerNewsClient``.  API keys are currently gated;
   request one at hello@stacker.news or in ~meta.

2. **Chrome session cookies** — if you are logged in to Stacker News in
   Chrome, the SDK can read the session cookie from Chrome's SQLite
   database automatically (macOS / Linux).  Requires ``pycookiecheat``:

       pip install stacker-news-sdk[chrome]
"""

from __future__ import annotations

import os


def get_api_key_headers(api_key: str) -> dict[str, str]:
    """Return headers for API key authentication."""
    return {"X-Api-Key": api_key}


def get_chrome_cookies(url: str = "https://stacker.news") -> dict[str, str]:
    """Read Stacker News session cookies from Chrome's local database.

    Requires ``pycookiecheat`` (``pip install stacker-news-sdk[chrome]``).
    Chrome must be open and logged in to Stacker News.

    Returns:
        Cookie dict suitable for use with ``httpx`` or ``requests``.

    Raises:
        ImportError: if pycookiecheat is not installed.
        RuntimeError: if cookies cannot be read.
    """
    try:
        import pycookiecheat  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "pycookiecheat is required for Chrome cookie auth.\n"
            "Install with: pip install stacker-news-sdk[chrome]"
        ) from exc

    try:
        cookies = pycookiecheat.chrome_cookies(url)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to read Chrome cookies: {exc}\n"
            "Make sure Chrome is open and you are logged in to stacker.news."
        ) from exc

    if "__Secure-next-auth.session-token" not in cookies and "next-auth.session-token" not in cookies:
        raise RuntimeError(
            "Stacker News session cookie not found in Chrome.\n"
            "Please log in to stacker.news in Chrome and try again."
        )

    return cookies


def resolve_auth(
    api_key: str | None,
    use_chrome_cookies: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve auth to (headers, cookies) tuple.

    Priority: explicit api_key > env var > Chrome cookies.
    """
    key = api_key or os.environ.get("STACKER_NEWS_API_KEY", "")
    if key:
        return get_api_key_headers(key), {}

    if use_chrome_cookies:
        return {}, get_chrome_cookies()

    raise ValueError(
        "No authentication provided.\n"
        "Set STACKER_NEWS_API_KEY, pass api_key=, or set use_chrome_cookies=True."
    )
