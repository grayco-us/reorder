# Manual smoke test steps (requires a running Home Assistant instance):
# 1. Set cat litter product, aliases [kitty litter], zinc, test identifier.
# 2. Add 'kitty litter' to Shopping List. One dry-run queued order appears.
# 3. Add 'kitty litter' again. Still one queued order.
# 4. Add unrelated 'bananas'. No new order.
# 5. Restart Home Assistant. Queue persists.
# 6. Approve order from Developer Tools. Status changes, no purchase.
