# CrossList — independent inventory MVP

Standalone web inventory tracker for sellers listing stock on eBay, Vinted, Depop, Facebook Marketplace and other sites.

**Status:** first release is a local manual-listing tracker. It does **not** publish to marketplaces or remotely delist items. When an item sells, live linked listings are marked `action_required` for manual ending.

## Quick start

```bash
git clone https://github.com/treator83/cross_list.git
cd cross_list
cp .env.example .env
# Edit .env to set a long unique CROSSLIST_PASSWORD
docker compose up -d --build
```

Open http://localhost:8787 on the server, log in with the credentials from .env. The Docker port is bound to 127.0.0.1 so the service can coexist with other applications on the same server. Change CROSSLIST_PORT if 8787 is in use.

For access from other devices, configure a secured HTTPS reverse proxy or SSH/Tailscale tunnel. **Never expose HTTP Basic authentication over public unencrypted HTTP.** Protect and back up the dedicated CrossList Docker volume.

## Features

- Create and edit inventory items with SKU, name, description, price and quantity
- Record URLs, per-marketplace prices and statuses across eBay, Vinted, Depop and Facebook
- Mark sold; flag live linked listings for manual end; acknowledge completion
- SQLite persistence, Docker deployment, health endpoint and basic regression test
- Entirely separate from vinted_telegram

## Not implemented yet

Real marketplace connections, OAuth, marketplace publishing, order imports, background workers, photo uploads and automatic delisting. Those depend on authorised API access. No marketplace credentials are required or stored in this version.

## Local development

```bash
export CROSSLIST_PASSWORD=use-a-local-only-password
export CROSSLIST_DB=/tmp/crosslist-dev.sqlite3
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The development server defaults to http://localhost:8000.

Run tests from the repo root with `pip install pytest httpx` and `python -m pytest -q`.
