"""Data models for Stacker News SDK."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PayIn:
    """A pending Lightning payment for a Stacker News post."""

    id: str
    state: str          # "PENDING" | "PAID" | "FAILED"
    bolt11: str         # bolt11 invoice to pay
    item_id: str | None = None  # populated once PAID

    @property
    def is_paid(self) -> bool:
        return self.state == "PAID"

    @property
    def is_pending(self) -> bool:
        return self.state == "PENDING"

    @classmethod
    def from_dict(cls, data: dict) -> "PayIn":
        bolt11 = (
            data.get("payerPrivates", {})
            .get("payInBolt11", {})
            .get("bolt11", "")
        )
        item_id = None
        if data.get("item"):
            item_id = str(data["item"]["id"])
        return cls(
            id=str(data["id"]),
            state=data.get("payInState", "PENDING"),
            bolt11=bolt11,
            item_id=item_id,
        )


@dataclass
class Comment:
    """A Stacker News comment."""

    id: str
    text: str
    sats: int = 0
    user: str = ""
    created_at: str = ""
    comments: list["Comment"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Comment":
        return cls(
            id=str(data.get("id", "")),
            text=data.get("text", ""),
            sats=int(data.get("sats", 0)),
            user=(data.get("user") or {}).get("name", ""),
            created_at=data.get("createdAt", ""),
            comments=[
                Comment.from_dict(c)
                for c in (data.get("comments", {}).get("items") or [])
            ],
        )


@dataclass
class Item:
    """A Stacker News post (discussion, link, or question)."""

    id: str
    title: str
    text: str = ""
    url: str | None = None
    sats: int = 0
    user: str = ""
    sub: str = ""
    n_comments: int = 0
    created_at: str = ""
    comments: list[Comment] = field(default_factory=list)

    @property
    def stacker_url(self) -> str:
        return f"https://stacker.news/items/{self.id}"

    @classmethod
    def from_dict(cls, data: dict) -> "Item":
        return cls(
            id=str(data.get("id", "")),
            title=data.get("title", ""),
            text=data.get("text", ""),
            url=data.get("url"),
            sats=int(data.get("sats", 0)),
            user=(data.get("user") or {}).get("name", ""),
            sub=(data.get("sub") or {}).get("name", ""),
            n_comments=int(data.get("ncomments", 0)),
            created_at=data.get("createdAt", ""),
            comments=[
                Comment.from_dict(c)
                for c in (data.get("comments", {}).get("items") or [])
            ],
        )
