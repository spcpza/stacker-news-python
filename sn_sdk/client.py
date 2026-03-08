"""Stacker News API client."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .auth import resolve_auth
from .exceptions import SNAuthError, SNError, SNGraphQLError, SNPaymentRequired
from .models import Comment, Item, PayIn

_GQL_URL = "https://stacker.news/api/graphql"

# ---------------------------------------------------------------------------
# GraphQL fragments
# ---------------------------------------------------------------------------

_PAYIN_FRAGMENT = """
fragment PayInFields on PayIn {
  id
  payInState
  payerPrivates {
    payInBolt11 { bolt11 }
  }
  item { id }
}
"""

_ITEM_FIELDS = """
  id title text url sats ncomments createdAt
  user { name }
  sub { name }
"""

_COMMENT_FIELDS = """
  id text sats createdAt
  user { name }
  comments(limit: 50) {
    items {
      id text sats createdAt
      user { name }
    }
  }
"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class StackerNewsClient:
    """Python client for the Stacker News GraphQL API.

    Parameters
    ----------
    api_key:
        Stacker News API key (``STACKER_NEWS_API_KEY`` env var also accepted).
        API keys are currently gated — request one at hello@stacker.news.
    use_chrome_cookies:
        Read the active Chrome session cookie from the local Chrome SQLite DB.
        Requires ``pip install stacker-news-sdk[chrome]``.
        Chrome must be open and logged in to stacker.news.
    timeout:
        HTTP request timeout in seconds.
    base_url:
        Override the GraphQL endpoint (default: https://stacker.news/api/graphql).

    Examples
    --------
    API key auth:

    >>> client = StackerNewsClient(api_key="sk_...")

    Chrome session auth (macOS/Linux):

    >>> client = StackerNewsClient(use_chrome_cookies=True)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        use_chrome_cookies: bool = False,
        timeout: float = 15.0,
        base_url: str = _GQL_URL,
    ) -> None:
        self._headers, self._cookies = resolve_auth(api_key, use_chrome_cookies)
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query/mutation and return the ``data`` field.

        Raises:
            SNAuthError: if the server returns an auth error.
            SNGraphQLError: if the server returns GraphQL errors.
            SNError: for other HTTP or network errors.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            resp = httpx.post(
                self._base_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **self._headers,
                },
                cookies=self._cookies,
                timeout=self._timeout,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            raise SNError(f"Network error: {exc}") from exc

        if resp.status_code == 401:
            raise SNAuthError("Not authenticated. Check your API key or Chrome session.")
        if resp.status_code != 200:
            raise SNError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        if errors := body.get("errors"):
            msg = errors[0].get("message", "GraphQL error")
            if "Forbidden" in msg or "auth" in msg.lower():
                raise SNAuthError(msg)
            raise SNGraphQLError(msg, errors)

        return body.get("data", {})

    def _handle_payin(self, payin_data: dict | None) -> PayIn | None:
        """Parse a PayIn from a mutation response."""
        if not payin_data:
            return None
        return PayIn.from_dict(payin_data)

    def wait_for_payment(self, pay_in_id: str, *, poll_interval: float = 2.0, timeout: float = 300.0) -> PayIn:
        """Poll a PayIn until it reaches PAID state.

        Parameters
        ----------
        pay_in_id:  The PayIn ID returned by a post/comment mutation.
        poll_interval: Seconds between polls (default 2).
        timeout:    Maximum wait time in seconds (default 5 minutes).

        Returns:
            The confirmed ``PayIn`` with ``item_id`` populated.

        Raises:
            SNError: if the payment doesn't confirm within ``timeout``.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payin = self.get_pay_in(pay_in_id)
            if payin.is_paid:
                return payin
            if payin.state == "FAILED":
                raise SNError(f"PayIn {pay_in_id} failed.")
            time.sleep(poll_interval)
        raise SNError(f"PayIn {pay_in_id} not confirmed within {timeout}s.")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def me(self) -> dict:
        """Return the authenticated user's profile."""
        data = self._gql("{ me { id name sats stacked } }")
        return data.get("me") or {}

    def get_item(self, item_id: int | str) -> Item:
        """Fetch a single item (post) by ID, including top-level comments."""
        query = f"""
        query GetItem($id: ID!) {{
          item(id: $id) {{
            {_ITEM_FIELDS}
            comments(limit: 10, sort: "top") {{
              items {{ {_COMMENT_FIELDS} }}
            }}
          }}
        }}
        """
        data = self._gql(query, {"id": str(item_id)})
        raw = data.get("item")
        if not raw:
            raise SNError(f"Item {item_id} not found.")
        return Item.from_dict(raw)

    def get_pay_in(self, pay_in_id: str) -> PayIn:
        """Fetch the current state of a PayIn."""
        query = f"""
        query GetPayIn($id: ID!) {{
          payIn(id: $id) {{
            ...PayInFields
          }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = self._gql(query, {"id": pay_in_id})
        raw = data.get("payIn")
        if not raw:
            raise SNError(f"PayIn {pay_in_id} not found.")
        return PayIn.from_dict(raw)

    def browse(
        self,
        *,
        sub: str | None = None,
        sort: str = "hot",
        limit: int = 10,
    ) -> list[Item]:
        """Browse items in a territory (or the front page).

        Parameters
        ----------
        sub:   Territory name, e.g. ``"bitcoin"``, ``"AskSN"``, ``"lightning"``.
               ``None`` returns the front page.
        sort:  ``"hot"`` (default) | ``"recent"`` | ``"top"`` | ``"zap"``.
        limit: Number of items to return (max ~50).

        Returns:
            List of :class:`Item` objects.
        """
        query = f"""
        query Browse($sub: String, $sort: String, $limit: Int) {{
          items(sub: $sub, sort: $sort, limit: $limit) {{
            items {{ {_ITEM_FIELDS} }}
          }}
        }}
        """
        data = self._gql(query, {"sub": sub, "sort": sort, "limit": limit})
        items_data = (data.get("items") or {}).get("items") or []
        return [Item.from_dict(i) for i in items_data]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def post_discussion(
        self,
        title: str,
        text: str = "",
        *,
        sub: str = "bitcoin",
        boost: int = 0,
    ) -> PayIn:
        """Create a discussion post.

        Returns a :class:`PayIn` — pay the ``bolt11`` invoice with your
        Lightning wallet to make the post go live.

        Parameters
        ----------
        title: Post title.
        text:  Post body (Markdown).
        sub:   Territory to post in (default: ``"bitcoin"``).
        boost: Optional boost amount in sats.
        """
        mutation = f"""
        mutation UpsertDiscussion($title: String!, $text: String, $sub: String, $boost: Int) {{
          upsertDiscussion(title: $title, text: $text, sub: $sub, boost: $boost) {{
            ...PayInFields
          }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = self._gql(mutation, {"title": title, "text": text, "sub": sub, "boost": boost})
        payin = self._handle_payin(data.get("upsertDiscussion"))
        if not payin:
            raise SNError("upsertDiscussion returned no PayIn.")
        return payin

    def post_link(
        self,
        title: str,
        url: str,
        text: str = "",
        *,
        sub: str = "bitcoin",
        boost: int = 0,
    ) -> PayIn:
        """Create a link post.

        Returns a :class:`PayIn` — pay the ``bolt11`` invoice to publish.
        """
        mutation = f"""
        mutation UpsertLink($title: String!, $url: String!, $text: String, $sub: String, $boost: Int) {{
          upsertLink(title: $title, url: $url, text: $text, sub: $sub, boost: $boost) {{
            ...PayInFields
          }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = self._gql(mutation, {"title": title, "url": url, "text": text, "sub": sub, "boost": boost})
        payin = self._handle_payin(data.get("upsertLink"))
        if not payin:
            raise SNError("upsertLink returned no PayIn.")
        return payin

    def comment(
        self,
        parent_id: int | str,
        text: str,
    ) -> PayIn:
        """Post a comment on an item or reply to another comment.

        Comments use Cowboy Credits and typically cost 0 real sats.
        A PayIn is still returned for consistency — check ``payin.bolt11``
        to see if payment is needed.

        Parameters
        ----------
        parent_id: The item or comment ID to reply to.
        text:      Comment body (Markdown).
        """
        mutation = f"""
        mutation UpsertComment($parentId: ID!, $text: String!) {{
          upsertComment(parentId: $parentId, text: $text) {{
            ...PayInFields
          }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = self._gql(mutation, {"parentId": str(parent_id), "text": text})
        payin = self._handle_payin(data.get("upsertComment"))
        if not payin:
            raise SNError("upsertComment returned no PayIn.")
        return payin

    def edit_comment(self, comment_id: int | str, text: str) -> dict:
        """Edit an existing comment."""
        mutation = """
        mutation UpsertComment($id: ID!, $text: String!) {
          upsertComment(id: $id, text: $text) { id payInState }
        }
        """
        data = self._gql(mutation, {"id": str(comment_id), "text": text})
        return data.get("upsertComment") or {}

    def set_bio(self, text: str) -> dict:
        """Update the authenticated user's bio."""
        mutation = """
        mutation UpsertBio($text: String!) {
          upsertBio(text: $text) { id text }
        }
        """
        data = self._gql(mutation, {"text": text})
        return data.get("upsertBio") or {}
