"""Command-line interface for stacker-news-python.

Usage:
  sn browse [--sub TERRITORY] [--sort hot|recent|top] [--limit N]
  sn item ITEM_ID
  sn me
  sn user USERNAME
  sn post --title TITLE [--text TEXT] [--sub TERRITORY]
  sn comment PARENT_ID TEXT

Authentication:
  Set STACKER_NEWS_API_KEY environment variable, or use --chrome flag.
"""

from __future__ import annotations

import json
import os
import sys

import click

from .client import StackerNewsClient
from .exceptions import SNAuthError, SNError


def _make_client(chrome: bool) -> StackerNewsClient:
    api_key = os.environ.get("STACKER_NEWS_API_KEY")
    try:
        return StackerNewsClient(
            api_key=api_key or None,
            use_chrome_cookies=chrome and not api_key,
        )
    except (ValueError, ImportError) as exc:
        click.echo(f"Auth error: {exc}", err=True)
        click.echo(
            "Set STACKER_NEWS_API_KEY or use --chrome flag "
            "(requires pip install stacker-news-sdk[chrome]).",
            err=True,
        )
        sys.exit(1)


@click.group()
@click.option("--chrome", is_flag=True, help="Use Chrome session cookie for auth.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.pass_context
def cli(ctx: click.Context, chrome: bool, as_json: bool) -> None:
    """Stacker News CLI — browse, post, and comment from your terminal."""
    ctx.ensure_object(dict)
    ctx.obj["chrome"] = chrome
    ctx.obj["as_json"] = as_json


# ---------------------------------------------------------------------------
# browse
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--sub", "-s", default=None, help="Territory name (e.g. bitcoin, lightning).")
@click.option("--sort", default="hot", show_default=True,
              type=click.Choice(["hot", "recent", "top", "zap"]),
              help="Sort order.")
@click.option("--limit", "-n", default=10, show_default=True, help="Number of items.")
@click.pass_context
def browse(ctx: click.Context, sub: str | None, sort: str, limit: int) -> None:
    """Browse posts in a territory or the front page."""
    client = _make_client(ctx.obj["chrome"])
    try:
        items = client.browse(sub=sub, sort=sort, limit=limit)
    except SNError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if ctx.obj["as_json"]:
        data = [
            {"id": i.id, "title": i.title, "sats": i.sats,
             "user": i.user, "url": i.stacker_url}
            for i in items
        ]
        click.echo(json.dumps(data, indent=2))
        return

    territory = f"~{sub}" if sub else "front page"
    click.echo(f"\n{'─'*60}")
    click.echo(f" Stacker News — {territory} ({sort})")
    click.echo(f"{'─'*60}")
    for i in items:
        click.echo(f"  {i.sats:>6} ⚡  {i.title[:55]}")
        click.echo(f"         @{i.user}  {i.stacker_url}")
    click.echo()


# ---------------------------------------------------------------------------
# item
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("item_id", type=int)
@click.pass_context
def item(ctx: click.Context, item_id: int) -> None:
    """Fetch a post by ID and show its comments."""
    client = _make_client(ctx.obj["chrome"])
    try:
        it = client.get_item(item_id)
    except SNError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if ctx.obj["as_json"]:
        click.echo(json.dumps({
            "id": it.id, "title": it.title, "text": it.text,
            "sats": it.sats, "user": it.user,
            "comments": [{"id": c.id, "user": c.user, "text": c.text} for c in it.comments],
        }, indent=2))
        return

    click.echo(f"\n{'─'*60}")
    click.echo(f" {it.title}")
    click.echo(f" @{it.user}  ·  {it.sats} sats  ·  {it.stacker_url}")
    click.echo(f"{'─'*60}")
    if it.text:
        click.echo(f"\n{it.text[:500]}\n")
    if it.comments:
        click.echo(f"  Top comments ({len(it.comments)}):")
        for c in it.comments:
            click.echo(f"    @{c.user}: {c.text[:100]}")
    click.echo()


# ---------------------------------------------------------------------------
# me
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def me(ctx: click.Context) -> None:
    """Show your authenticated user profile."""
    client = _make_client(ctx.obj["chrome"])
    try:
        profile = client.me()
    except SNAuthError as exc:
        click.echo(f"Auth error: {exc}", err=True)
        sys.exit(1)

    if ctx.obj["as_json"]:
        click.echo(json.dumps(profile, indent=2))
        return

    if not profile:
        click.echo("Not authenticated or no user returned.", err=True)
        sys.exit(1)

    click.echo(f"\n  @{profile.get('name')}")
    click.echo(f"  Sats:    {profile.get('sats', 0):,}")
    click.echo(f"  Stacked: {profile.get('stacked', 0):,}")
    click.echo()


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("username")
@click.pass_context
def user(ctx: click.Context, username: str) -> None:
    """Show a user's public profile."""
    client = _make_client(ctx.obj["chrome"])
    # Use raw GQL for user lookup (not in sync client yet — call directly)
    try:
        data = client._gql(
            """query GetUser($name: String!) {
              user(name: $name) { id name sats stacked bio nItems nComments }
            }""",
            {"name": username},
        )
    except SNError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    profile = data.get("user") or {}
    if not profile:
        click.echo(f"User @{username} not found.", err=True)
        sys.exit(1)

    if ctx.obj["as_json"]:
        click.echo(json.dumps(profile, indent=2))
        return

    click.echo(f"\n  @{profile.get('name')}")
    click.echo(f"  Stacked: {profile.get('stacked', 0):,} sats")
    click.echo(f"  Posts:   {profile.get('nItems', 0)}")
    click.echo(f"  Comments:{profile.get('nComments', 0)}")
    if bio := profile.get("bio"):
        click.echo(f"\n  Bio: {bio[:200]}")
    click.echo()


# ---------------------------------------------------------------------------
# post
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--title", "-t", required=True, help="Post title.")
@click.option("--text", default="", help="Post body (Markdown).")
@click.option("--sub", "-s", default="bitcoin", show_default=True,
              help="Territory to post in.")
@click.option("--dry-run", is_flag=True, help="Show the invoice but do not pay.")
@click.pass_context
def post(ctx: click.Context, title: str, text: str, sub: str, dry_run: bool) -> None:
    """Create a discussion post. Prints the Lightning invoice to pay."""
    client = _make_client(ctx.obj["chrome"])
    try:
        payin = client.post_discussion(title=title, text=text, sub=sub)
    except SNError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if ctx.obj["as_json"]:
        click.echo(json.dumps({
            "pay_in_id": payin.id,
            "bolt11": payin.bolt11,
            "state": payin.state,
        }, indent=2))
        return

    click.echo(f"\n  PayIn: {payin.id}")
    click.echo(f"  Invoice: {payin.bolt11[:70]}...")
    click.echo()
    if dry_run:
        click.echo("  (--dry-run: post created, pay the invoice above to publish)")
    else:
        click.echo("  Pay the invoice above with your Lightning wallet to publish.")
    click.echo()


# ---------------------------------------------------------------------------
# comment
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("parent_id", type=int)
@click.argument("text")
@click.pass_context
def comment(ctx: click.Context, parent_id: int, text: str) -> None:
    """Post a comment on an item or reply to a comment."""
    client = _make_client(ctx.obj["chrome"])
    try:
        payin = client.comment(parent_id, text)
    except SNError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if ctx.obj["as_json"]:
        click.echo(json.dumps({"pay_in_id": payin.id, "state": payin.state}, indent=2))
        return

    click.echo(f"  Comment posted (PayIn: {payin.id}, state: {payin.state})")


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
