# AuctionForever

Auction house helper for WoW Forever (US, PvP Alliance, auction house 110).

- `collector/`: runs on GitHub Actions every 20 minutes. Fetches the house from Blizzard's API, works out what
  sold and what expired, keeps 3 days of hourly history and 14 days of daily summaries, and publishes
  `AuctionForeverData.lua` to the `data` release.
- `sync/`: small Windows program that copies the newest `AuctionForeverData.lua` into the add-on folder.
- `addon/AuctionForever/`: the in-game add-on.

Blizzard API credentials are GitHub secrets and are never printed or stored in the repo.
