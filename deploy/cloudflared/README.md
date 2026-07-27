# Cloudflare Tunnel setup

Public exposure for the demo. `cloudflared` is a native binary with a systemd unit — it was
never Docker-dependent, so it is unaffected by this project's no-Docker constraint.

**Not executed by the scaffold.** These are the steps to run on the VPS once.

## Why a tunnel rather than an open port

- No inbound port on the VPS. The firewall can deny everything inbound except SSH; the tunnel
  dials **out** to Cloudflare.
- TLS terminates at Cloudflare's edge, so there is no certificate to renew on the host and Caddy
  can stay on plain HTTP over loopback (`auto_https off` in `deploy/Caddyfile`).
- Free tier, and it reconnects by itself after a network blip — which is the "demo dead when a
  reviewer clicks" risk in the proposal.

## Steps

```bash
# 1. Authenticate (opens a browser link; pick the zone you already manage)
cloudflared tunnel login

# 2. Create the tunnel — this writes credentials to /root/.cloudflared/<TUNNEL_ID>.json
cloudflared tunnel create t2sql

# 3. Route a hostname to it. This creates the CNAME
#    t2sql.<your-domain>  ->  <TUNNEL_ID>.cfargotunnel.com
#    in the same zone already used for the Vercel project.
cloudflared tunnel route dns t2sql t2sql.<your-domain>

# 4. Point the tunnel at Caddy (Caddy fronts BOTH services on one host — see deploy/Caddyfile)
sudo tee /etc/cloudflared/config.yml >/dev/null <<'YAML'
tunnel: t2sql
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: t2sql.<your-domain>
    service: http://localhost:80
  - service: http_status:404
YAML

# 5. Install and start as a systemd service (not a container)
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

## Secrets

The tunnel token / credentials file is **never committed**. Two supported ways to supply it:

- the credentials JSON written by `cloudflared tunnel create` (root-owned, `0600`), or
- `CLOUDFLARE_TUNNEL_TOKEN` in the environment for a token-based connector
  (`cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN"`).

`.gitignore` excludes `.env` and `*.key`/`*.pem`. If a token is ever pasted into a file in this
repository, rotate it in the Cloudflare dashboard — removing the commit is not enough.

## Verifying

```bash
curl -s https://t2sql.<your-domain>/health | jq
sudo journalctl -u cloudflared -n 50 --no-pager
```

`/health` returns the runtime mode and whether a database is configured, so a single curl
distinguishes "the tunnel is down" from "the app is up but running on fixtures".
