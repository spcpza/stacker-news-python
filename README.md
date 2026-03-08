# stacker-news-python

Python SDK for the [Stacker News](https://stacker.news) GraphQL API.

Post discussions, comment, browse territories, and handle Lightning invoice payments — all from Python.

```bash
pip install stacker-news-sdk
```

## Authentication

Two methods are supported:

### API key
```bash
export STACKER_NEWS_API_KEY=your_key_here
```
> API keys are currently gated. Request one in [~meta](https://stacker.news/~meta) or at hello@stacker.news.

### Chrome session (no API key needed)
If you're logged in to Stacker News in Chrome, the SDK reads the session cookie automatically:

```bash
pip install stacker-news-sdk[chrome]
```

```python
client = StackerNewsClient(use_chrome_cookies=True)
```

## Quick start

```python
from sn_sdk import StackerNewsClient
import subprocess

client = StackerNewsClient(use_chrome_cookies=True)

# Who am I?
print(client.me())

# Browse the bitcoin territory
items = client.browse(sub="bitcoin", limit=10)
for item in items:
    print(f"[{item.sats} sats] {item.title}")

# Read a post with comments
item = client.get_item(1449799)
print(item.title)
for comment in item.comments:
    print(f"  @{comment.user}: {comment.text[:80]}")

# Post a discussion (returns a Lightning invoice to pay)
payin = client.post_discussion(
    title="Sound money in the digital age",
    text="Bitcoin is the first honest accounting unit for the internet.",
    sub="bitcoin",
)
print(f"Pay {payin.bolt11} to publish")

# Pay with Alby CLI and wait for confirmation
subprocess.run(["npx", "@getalby/cli", "pay-invoice", payin.bolt11])
confirmed = client.wait_for_payment(payin.id)
print(f"Live: https://stacker.news/items/{confirmed.item_id}")

# Post a comment (uses Cowboy Credits — usually free)
payin = client.comment(1449799, "Great post! Sound money is the foundation.")

# Edit a comment
client.edit_comment(comment_id=1449805, text="Updated comment text.")
```

## Reference

### `StackerNewsClient`

| Method | Description |
|--------|-------------|
| `me()` | Return authenticated user profile |
| `browse(sub, sort, limit)` | List posts in a territory |
| `get_item(item_id)` | Fetch a post with comments |
| `get_pay_in(pay_in_id)` | Poll a payment's state |
| `wait_for_payment(pay_in_id)` | Block until a PayIn is confirmed |
| `post_discussion(title, text, sub)` | Create a discussion post |
| `post_link(title, url, text, sub)` | Create a link post |
| `comment(parent_id, text)` | Post or reply to a comment |
| `edit_comment(comment_id, text)` | Edit an existing comment |
| `set_bio(text)` | Update your profile bio |

### `PayIn`

Posts return a `PayIn` object with the Lightning invoice to pay:

```python
payin.id         # PayIn ID for polling
payin.bolt11     # bolt11 invoice string
payin.state      # "PENDING" | "PAID" | "FAILED"
payin.is_paid    # True once confirmed
payin.item_id    # Item ID (available after payment)
```

### Exceptions

| Exception | When |
|-----------|------|
| `SNAuthError` | Invalid credentials or session expired |
| `SNGraphQLError` | Server returned a GraphQL error |
| `SNError` | Base class for all SDK errors |

## Development

```bash
git clone https://github.com/spcpza/stacker-news-python
cd stacker-news-python
pip install -e ".[dev]"
pytest
```

## Support

If this saved you time, sats tips are welcome: ⚡ `sensiblefield821792@getalby.com`

Issues and PRs welcome.
