"""Tests for StackerNewsClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sn_sdk import StackerNewsClient, SNAuthError, SNError
from sn_sdk.exceptions import SNGraphQLError
from sn_sdk.models import Item, Comment, PayIn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _client(api_key: str = "test_key") -> StackerNewsClient:
    return StackerNewsClient(api_key=api_key)


def _mock_gql(client: StackerNewsClient, return_value: dict):
    return patch.object(client, "_gql", return_value=return_value)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_api_key_header_set(self):
        c = StackerNewsClient(api_key="sk_test")
        assert c._headers.get("X-Api-Key") == "sk_test"
        assert c._cookies == {}

    def test_no_auth_raises(self):
        with pytest.raises(ValueError, match="No authentication"):
            StackerNewsClient()

    def test_env_var_api_key(self, monkeypatch):
        monkeypatch.setenv("STACKER_NEWS_API_KEY", "env_key")
        c = StackerNewsClient()
        assert c._headers.get("X-Api-Key") == "env_key"

    def test_chrome_cookies_require_pycookiecheat(self, monkeypatch):
        monkeypatch.delenv("STACKER_NEWS_API_KEY", raising=False)
        with patch.dict("sys.modules", {"pycookiecheat": None}):
            with pytest.raises(ImportError, match="pycookiecheat"):
                StackerNewsClient(use_chrome_cookies=True)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestPayIn:
    def test_from_dict_paid(self):
        data = {
            "id": "42",
            "payInState": "PAID",
            "payerPrivates": {"payInBolt11": {"bolt11": "lnbc..."}},
            "item": {"id": "99"},
        }
        p = PayIn.from_dict(data)
        assert p.id == "42"
        assert p.is_paid
        assert p.bolt11 == "lnbc..."
        assert p.item_id == "99"

    def test_from_dict_pending(self):
        data = {
            "id": "7",
            "payInState": "PENDING",
            "payerPrivates": {"payInBolt11": {"bolt11": "lnbc_invoice"}},
            "item": None,
        }
        p = PayIn.from_dict(data)
        assert p.is_pending
        assert p.item_id is None

    def test_from_dict_missing_bolt11(self):
        data = {"id": "1", "payInState": "PENDING", "payerPrivates": {}, "item": None}
        p = PayIn.from_dict(data)
        assert p.bolt11 == ""


class TestItem:
    def test_from_dict_full(self):
        data = {
            "id": "123",
            "title": "Bitcoin is sound money",
            "text": "Proof of work is truth.",
            "url": None,
            "sats": 420,
            "ncomments": 7,
            "createdAt": "2026-03-08T10:00:00Z",
            "user": {"name": "satoshi"},
            "sub": {"name": "bitcoin"},
            "comments": {"items": []},
        }
        item = Item.from_dict(data)
        assert item.id == "123"
        assert item.title == "Bitcoin is sound money"
        assert item.sats == 420
        assert item.user == "satoshi"
        assert item.sub == "bitcoin"
        assert item.stacker_url == "https://stacker.news/items/123"

    def test_from_dict_with_comments(self):
        data = {
            "id": "1",
            "title": "Q&A",
            "text": "",
            "url": None,
            "sats": 0,
            "ncomments": 1,
            "createdAt": "",
            "user": {"name": "a"},
            "sub": {"name": "AskSN"},
            "comments": {
                "items": [
                    {"id": "c1", "text": "reply", "sats": 5, "createdAt": "", "user": {"name": "b"}, "comments": {"items": []}},
                ]
            },
        }
        item = Item.from_dict(data)
        assert len(item.comments) == 1
        assert item.comments[0].text == "reply"


# ---------------------------------------------------------------------------
# read operations
# ---------------------------------------------------------------------------


class TestMe:
    def test_returns_user_dict(self):
        c = _client()
        with _mock_gql(c, {"me": {"id": "1", "name": "balthazar", "sats": 5000}}):
            result = c.me()
        assert result["name"] == "balthazar"

    def test_returns_empty_on_null(self):
        c = _client()
        with _mock_gql(c, {"me": None}):
            assert c.me() == {}


class TestGetItem:
    def _item_data(self):
        return {
            "id": "99",
            "title": "Test post",
            "text": "",
            "url": None,
            "sats": 10,
            "ncomments": 0,
            "createdAt": "",
            "user": {"name": "x"},
            "sub": {"name": "bitcoin"},
            "comments": {"items": []},
        }

    def test_returns_item(self):
        c = _client()
        with _mock_gql(c, {"item": self._item_data()}):
            item = c.get_item(99)
        assert item.id == "99"
        assert item.title == "Test post"

    def test_raises_on_null(self):
        c = _client()
        with _mock_gql(c, {"item": None}):
            with pytest.raises(SNError, match="not found"):
                c.get_item(99)


class TestBrowse:
    def _items_data(self, n: int = 3):
        return {
            "items": {
                "items": [
                    {"id": str(i), "title": f"Post {i}", "text": "", "url": None,
                     "sats": i * 10, "ncomments": i, "createdAt": "", "user": {"name": "x"},
                     "sub": {"name": "bitcoin"}, "comments": {"items": []}}
                    for i in range(n)
                ]
            }
        }

    def test_returns_item_list(self):
        c = _client()
        with _mock_gql(c, self._items_data(3)):
            items = c.browse(sub="bitcoin", limit=3)
        assert len(items) == 3
        assert all(isinstance(i, Item) for i in items)

    def test_empty_response(self):
        c = _client()
        with _mock_gql(c, {"items": {"items": []}}):
            assert c.browse() == []


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


class TestPostDiscussion:
    def _payin_data(self, state: str = "PENDING"):
        return {
            "upsertDiscussion": {
                "id": "p1",
                "payInState": state,
                "payerPrivates": {"payInBolt11": {"bolt11": "lnbc_test"}},
                "item": None,
            }
        }

    def test_returns_payin(self):
        c = _client()
        with _mock_gql(c, self._payin_data()):
            payin = c.post_discussion("Test Title", "Test text", sub="bitcoin")
        assert isinstance(payin, PayIn)
        assert payin.bolt11 == "lnbc_test"
        assert payin.is_pending

    def test_raises_on_null(self):
        c = _client()
        with _mock_gql(c, {"upsertDiscussion": None}):
            with pytest.raises(SNError, match="no PayIn"):
                c.post_discussion("title")


class TestComment:
    def _payin_data(self):
        return {
            "upsertComment": {
                "id": "c1",
                "payInState": "PENDING",
                "payerPrivates": {"payInBolt11": {"bolt11": ""}},
                "item": {"id": "42"},
            }
        }

    def test_returns_payin(self):
        c = _client()
        with _mock_gql(c, self._payin_data()):
            payin = c.comment(1234, "Great post!")
        assert isinstance(payin, PayIn)

    def test_raises_on_null(self):
        c = _client()
        with _mock_gql(c, {"upsertComment": None}):
            with pytest.raises(SNError):
                c.comment(1, "text")


# ---------------------------------------------------------------------------
# wait_for_payment
# ---------------------------------------------------------------------------


class TestWaitForPayment:
    def test_returns_when_paid(self):
        c = _client()
        paid_payin = PayIn(id="p1", state="PAID", bolt11="", item_id="42")
        with patch.object(c, "get_pay_in", return_value=paid_payin):
            result = c.wait_for_payment("p1", poll_interval=0)
        assert result.is_paid

    def test_raises_on_failed(self):
        c = _client()
        failed = PayIn(id="p1", state="FAILED", bolt11="", item_id=None)
        with patch.object(c, "get_pay_in", return_value=failed):
            with pytest.raises(SNError, match="failed"):
                c.wait_for_payment("p1", poll_interval=0)

    def test_timeout_raises(self):
        c = _client()
        pending = PayIn(id="p1", state="PENDING", bolt11="lnbc...", item_id=None)
        with patch.object(c, "get_pay_in", return_value=pending):
            with pytest.raises(SNError, match="not confirmed"):
                c.wait_for_payment("p1", poll_interval=0, timeout=0.01)


# ---------------------------------------------------------------------------
# GraphQL error handling
# ---------------------------------------------------------------------------


class TestGQLErrors:
    def test_auth_error_raises_sn_auth_error(self):
        c = _client()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "errors": [{"message": "Forbidden: auth required"}]
            }
            mock_post.return_value = mock_resp
            with pytest.raises(SNAuthError):
                c.me()

    def test_graphql_error_raises_sn_graphql_error(self):
        c = _client()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "errors": [{"message": "item not found"}]
            }
            mock_post.return_value = mock_resp
            with pytest.raises(SNGraphQLError, match="not found"):
                c.get_item(9999)

    def test_http_401_raises_auth_error(self):
        c = _client()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_post.return_value = mock_resp
            with pytest.raises(SNAuthError):
                c.me()
