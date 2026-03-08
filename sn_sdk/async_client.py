"""Async Stacker News API client using httpx.AsyncClient.

Drop-in async counterpart to :class:`StackerNewsClient`.

Usage::

    import asyncio
    from sn_sdk import AsyncStackerNewsClient

    async def main():
        async with AsyncStackerNewsClient(api_key="sk_...") as client:
            me = await client.me()
            items = await client.browse(sub="bitcoin", limit=5)
            for item in items:
                print(f"[{item.sats} sats] {item.title}")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .auth import resolve_auth
from .exceptions import SNAuthError, SNError, SNGraphQLError
from .models import Item, PayIn

_GQL_URL = "https://stacker.news/api/graphql"

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


class AsyncStackerNewsClient:
    """Async Python client for the Stacker News GraphQL API.

    Parameters
    ----------
    api_key:
        Stacker News API key (``STACKER_NEWS_API_KEY`` env var also accepted).
    use_chrome_cookies:
        Read the active Chrome session cookie from the local Chrome SQLite DB.
        Requires ``pip install stacker-news-sdk[chrome]``.
    timeout:
        HTTP request timeout in seconds (default: 15).
    base_url:
        Override the GraphQL endpoint.
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
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AsyncStackerNewsClient":
        self._client = httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "AsyncStackerNewsClient must be used as an async context manager: "
                "`async with AsyncStackerNewsClient(...) as client:`"
            )
        return self._client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _gql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query/mutation and return the ``data`` field."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        http = self._get_client()
        try:
            resp = await http.post(
                self._base_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **self._headers,
                },
                cookies=self._cookies,
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

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def me(self) -> dict:
        """Return the authenticated user's profile."""
        data = await self._gql("{ me { id name sats stacked } }")
        return data.get("me") or {}

    async def get_item(self, item_id: int | str) -> Item:
        """Fetch a single item by ID, including top-level comments."""
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
        data = await self._gql(query, {"id": str(item_id)})
        raw = data.get("item")
        if not raw:
            raise SNError(f"Item {item_id} not found.")
        return Item.from_dict(raw)

    async def get_pay_in(self, pay_in_id: str) -> PayIn:
        """Fetch the current state of a PayIn."""
        query = f"""
        query GetPayIn($id: ID!) {{
          payIn(id: $id) {{ ...PayInFields }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = await self._gql(query, {"id": pay_in_id})
        raw = data.get("payIn")
        if not raw:
            raise SNError(f"PayIn {pay_in_id} not found.")
        return PayIn.from_dict(raw)

    async def browse(
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
        sort:  ``"hot"`` | ``"recent"`` | ``"top"`` | ``"zap"``.
        limit: Number of items to return (max ~50).
        """
        query = f"""
        query Browse($sub: String, $sort: String, $limit: Int) {{
          items(sub: $sub, sort: $sort, limit: $limit) {{
            items {{ {_ITEM_FIELDS} }}
          }}
        }}
        """
        data = await self._gql(query, {"sub": sub, "sort": sort, "limit": limit})
        items_data = (data.get("items") or {}).get("items") or []
        return [Item.from_dict(i) for i in items_data]

    async def wait_for_payment(
        self,
        pay_in_id: str,
        *,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> PayIn:
        """Poll a PayIn until it reaches PAID state (async version)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payin = await self.get_pay_in(pay_in_id)
            if payin.is_paid:
                return payin
            if payin.state == "FAILED":
                raise SNError(f"PayIn {pay_in_id} failed.")
            await asyncio.sleep(poll_interval)
        raise SNError(f"PayIn {pay_in_id} not confirmed within {timeout}s.")

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def post_discussion(
        self,
        title: str,
        text: str = "",
        *,
        sub: str = "bitcoin",
        boost: int = 0,
    ) -> PayIn:
        """Create a discussion post. Returns a PayIn with the invoice to pay."""
        mutation = f"""
        mutation UpsertDiscussion($title: String!, $text: String, $sub: String, $boost: Int) {{
          upsertDiscussion(title: $title, text: $text, sub: $sub, boost: $boost) {{
            ...PayInFields
          }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = await self._gql(
            mutation, {"title": title, "text": text, "sub": sub, "boost": boost}
        )
        raw = data.get("upsertDiscussion")
        if not raw:
            raise SNError("upsertDiscussion returned no PayIn.")
        return PayIn.from_dict(raw)

    async def comment(self, parent_id: int | str, text: str) -> PayIn:
        """Post a comment or reply. Returns a PayIn (usually Cowboy Credits)."""
        mutation = f"""
        mutation UpsertComment($parentId: ID!, $text: String!) {{
          upsertComment(parentId: $parentId, text: $text) {{
            ...PayInFields
          }}
        }}
        {_PAYIN_FRAGMENT}
        """
        data = await self._gql(mutation, {"parentId": str(parent_id), "text": text})
        raw = data.get("upsertComment")
        if not raw:
            raise SNError("upsertComment returned no PayIn.")
        return PayIn.from_dict(raw)

    async def edit_comment(self, comment_id: int | str, text: str) -> dict:
        """Edit an existing comment."""
        mutation = """
        mutation UpsertComment($id: ID!, $text: String!) {
          upsertComment(id: $id, text: $text) { id payInState }
        }
        """
        data = await self._gql(mutation, {"id": str(comment_id), "text": text})
        return data.get("upsertComment") or {}

    async def set_bio(self, text: str) -> dict:
        """Update the authenticated user's bio."""
        mutation = """
        mutation UpsertBio($text: String!) {
          upsertBio(text: $text) { id text }
        }
        """
        data = await self._gql(mutation, {"text": text})
        return data.get("upsertBio") or {}

    async def get_user(self, name: str) -> dict:
        """Fetch a user's public profile by username."""
        query = """
        query GetUser($name: String!) {
          user(name: $name) {
            id name sats stacked bio
            nItems nComments
          }
        }
        """
        data = await self._gql(query, {"name": name})
        return data.get("user") or {}

    async def browse_multiple(
        self,
        subs: list[str],
        *,
        sort: str = "hot",
        limit: int = 5,
    ) -> dict[str, list[Item]]:
        """Fetch top items from multiple territories concurrently.

        Returns a dict mapping territory name → list of Items.

        Example::

            results = await client.browse_multiple(
                ["bitcoin", "lightning", "AskSN"], limit=5
            )
            for sub, items in results.items():
                print(f"\\n--- {sub} ---")
                for item in items:
                    print(f"  [{item.sats}⚡] {item.title}")
        """
        tasks = [self.browse(sub=sub, sort=sort, limit=limit) for sub in subs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            sub: (items if not isinstance(items, Exception) else [])
            for sub, items in zip(subs, results)
        }
