# Domain

**Primary URL (current):** https://frame-2yxu.onrender.com

When a custom domain is configured, update:

- `README.md` — top three links
- `docs/PROOF.md` — all `frame-2yxu.onrender.com` URLs
- `docs/CONTEXT.md` — **Live URLs** section
- `apps/web/index.html` — `API_BASE` default (or use `?api=` query param)

---

## Setup (manual)

**Option A — Subdomain:** Add `frame.yourdomain.com` as a **CNAME** to `frame-2yxu.onrender.com` (or the target Render provides).

**Option B — New domain:** e.g. `getframe.dev`, `framereceipt.com` — register at Namecheap or Cloudflare.

**Render:** Dashboard → service → **Custom Domains** → add domain → add the CNAME Render shows → SSL auto-provisions (5–15 minutes).

---

## Record when live

| Field | Value |
|-------|--------|
| Live URL | `https://YOUR_DOMAIN` |
| Previous URL | `https://frame-2yxu.onrender.com` (may remain reachable) |
| Custom domain added | `[DATE]` |
| Registrar | `[REGISTRAR]` |
| SSL | Render auto-provisioned |
