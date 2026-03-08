"""Tests for AsyncStackerNewsClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from sn_sdk import AsyncStackerNewsClient, SNAuthError, SNError
from sn_sdk.models import Item, PayIn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _item_data(n: int = 1) -> dict:
    return {
        "id": str(n),
        "title": f"Test post {n}",
        "text": "body",
        "url": None,
        "sats": n * 10,
        "ncomments": 0,
        "createdAt": "2026-03-08T10:00:00Z",
        "user": {"name": "satoshi"},
        "sub": {"name": "bitcoin"},
        "comments": {"items": []},
    }


def _payin_data(state: str = "PENDING") -> dict:
    return {
        "id": "p1",
        "payInState": state,
        "payerPrivates": {"payInBolt11": {"bolt11": "lnbc_test"}},
        "item": {"id": "42"} if state == "PAID" else None,
    }


def _mock_gql(client: AsyncStackerNewsClient, return_value: dict):
    """Patch _gql to return a fixed value."""
    return patch.object(client, "_gql", new=AsyncMock(return_value=return_value))


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    async def test_raises_without_context_manager(self):
        c = AsyncStackerNewsClient(api_key="test")
        with pytest.raises(RuntimeError, match="async context manager"):
            await c.me()

    async def test_works_as_context_manager(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"me": {"id": "1", "name": "balthazar", "sats": 100}}):
                result = await c.me()
        assert result["name"] == "balthazar"


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


class TestMe:
    async def test_returns_user_dict(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"me": {"id": "1", "name": "alice", "sats": 5000}}):
                result = await c.me()
        assert result["name"] == "alice"

    async def test_returns_empty_on_null(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"me": None}):
                assert await c.me() == {}


class TestGetItem:
    async def test_returns_item(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"item": _item_data(99)}):
                item = await c.get_item(99)
        assert item.id == "99"
        assert isinstance(item, Item)

    async def test_raises_on_null(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"item": None}):
                with pytest.raises(SNError, match="not found"):
                    await c.get_item(99)


class TestBrowse:
    async def test_returns_item_list(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"items": {"items": [_item_data(i) for i in range(3)]}}):
                items = await c.browse(sub="bitcoin", limit=3)
        assert len(items) == 3
        assert all(isinstance(i, Item) for i in items)

    async def test_empty_result(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"items": {"items": []}}):
                assert await c.browse() == []


class TestBrowseMultiple:
    async def test_fetches_all_subs(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            # All calls return 2 items each
            with patch.object(
                c, "browse",
                side_effect=lambda sub, **kw: [Item.from_dict(_item_data(1))] * 2
            ):
                results = await c.browse_multiple(["bitcoin", "lightning"], limit=2)
        assert set(results.keys()) == {"bitcoin", "lightning"}
        assert all(len(v) == 2 for v in results.values())

    async def test_failed_sub_returns_empty(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            async def _browse(sub, **kw):
                if sub == "bad":
                    raise SNError("territory not found")
                return [Item.from_dict(_item_data(1))]

            with patch.object(c, "browse", side_effect=_browse):
                results = await c.browse_multiple(["bitcoin", "bad"], limit=1)
        assert len(results["bitcoin"]) == 1
        assert results["bad"] == []


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


class TestPostDiscussion:
    async def test_returns_payin(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"upsertDiscussion": _payin_data()}):
                payin = await c.post_discussion("Test", "body", sub="bitcoin")
        assert isinstance(payin, PayIn)
        assert payin.bolt11 == "lnbc_test"

    async def test_raises_on_null(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"upsertDiscussion": None}):
                with pytest.raises(SNError, match="no PayIn"):
                    await c.post_discussion("title")


class TestComment:
    async def test_returns_payin(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            with _mock_gql(c, {"upsertComment": _payin_data()}):
                payin = await c.comment(1234, "great post!")
        assert isinstance(payin, PayIn)


# ---------------------------------------------------------------------------
# wait_for_payment (async)
# ---------------------------------------------------------------------------


class TestWaitForPayment:
    async def test_returns_when_paid(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            paid = PayIn(id="p1", state="PAID", bolt11="", item_id="42")
            with patch.object(c, "get_pay_in", new=AsyncMock(return_value=paid)):
                result = await c.wait_for_payment("p1", poll_interval=0)
        assert result.is_paid

    async def test_raises_on_failed(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            failed = PayIn(id="p1", state="FAILED", bolt11="", item_id=None)
            with patch.object(c, "get_pay_in", new=AsyncMock(return_value=failed)):
                with pytest.raises(SNError, match="failed"):
                    await c.wait_for_payment("p1", poll_interval=0)

    async def test_timeout(self):
        async with AsyncStackerNewsClient(api_key="test") as c:
            pending = PayIn(id="p1", state="PENDING", bolt11="lnbc...", item_id=None)
            with patch.object(c, "get_pay_in", new=AsyncMock(return_value=pending)):
                with pytest.raises(SNError, match="not confirmed"):
                    await c.wait_for_payment("p1", poll_interval=0, timeout=0.01)
