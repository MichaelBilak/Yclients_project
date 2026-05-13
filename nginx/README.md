# Nginx routing for production

The checked-in [nginx.conf](nginx.conf) is a **single-host** example: TLS on `bi.your-domain.com`, external path `/yclients-api/sync/` → FastAPI sync controls only, and `/` → Metabase.

## Splitting product portal vs Metabase

For a Salistica-style product you usually want:

| Traffic | Target |
|--------|--------|
| `app.your-domain.com` / `/` | Static **product** UI (or proxy to a `portal` container) + `/api` → FastAPI |
| `bi.your-domain.com` or `mb.your-domain.com` | **Metabase** (internal or analyst-only), not the customer landing |

Steps:

1. Copy [nginx.portal.sample.conf](nginx.portal.sample.conf) as a second `server` block or separate file included from `conf.d/`.
2. Point DNS **A** records for `app` and `mb` subdomains to the same VPS IP (or use path-based routing on one host).
3. Mount product static files (e.g. `root /var/www/portal;`) or `proxy_pass` to a Node/Vite preview build.
4. Keep PostgreSQL bound to Docker internal network only; expose **443** (and **80** for ACME) on the host.

See also the root [README.md](../README.md) sections **Dashboard JSON API** and **Deployment**.
