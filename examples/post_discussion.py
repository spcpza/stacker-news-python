"""Example: post a discussion to Stacker News and pay the invoice via Alby CLI."""

import subprocess
import sys
from sn_sdk import StackerNewsClient

# Auth: Chrome session (must be logged in to stacker.news in Chrome)
client = StackerNewsClient(use_chrome_cookies=True)

# Post a discussion
payin = client.post_discussion(
    title="Bitcoin and sound money: a developer's perspective",
    text="Running a self-hosted Lightning node teaches you more about monetary sovereignty "
         "than any book. The fees are the lessons.\n\n#Bitcoin",
    sub="bitcoin",
)

print(f"PayIn ID : {payin.id}")
print(f"Invoice  : {payin.bolt11[:60]}...")
print()

# Pay with Alby CLI
print("Paying invoice via alby-cli...")
result = subprocess.run(
    ["npx", "@getalby/cli", "pay-invoice", payin.bolt11, "--json"],
    capture_output=True, text=True,
)

if result.returncode != 0:
    print(f"Payment failed: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Wait for SN to confirm the payment
print("Waiting for confirmation...")
confirmed = client.wait_for_payment(payin.id)
print(f"✓ Post live: https://stacker.news/items/{confirmed.item_id}")
