# email-me

![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)

Python CLI that finds and verifies founder/contact email addresses for a company. Point it at either a **YC company page** (founders + domain scraped from YC's structured data) or **any company website/domain** — e.g. an a16z portfolio company — in which case it derives the domain and scrapes the company's own `/team` and `/about` pages for people. It then generates common professional email permutations and verifies them using DNS MX record lookups and SMTP-level handshake probing. When no individuals can be discovered, it falls back to common role inboxes (`founders@`, `hello@`, `info@`, `contact@`, `team@`). Results are emitted in table, JSON, or CSV format.

## Installation

```bash
pip install -e .
```

To install with dev/test dependencies:

```bash
pip install -e ".[dev]"
```

**Requirements:** Python ≥ 3.10

## Usage

```
email-me <target> <count> [options]
```

`<target>` is either a YC company URL (`https://www.ycombinator.com/companies/<slug>`) or a company website/domain (`acme.com`, `https://acme.com`). The mode is auto-detected.

### Examples

```bash
# YC mode: find 2 verified emails for Stripe founders, show progress
email-me https://www.ycombinator.com/companies/stripe 2 --verbose

# YC mode: 3 verified emails for Dropbox founders, output as JSON
email-me https://www.ycombinator.com/companies/dropbox 3 --format json --verbose

# Generic mode: any company (e.g. an a16z portfolio company) by domain
email-me databricks.com 3 --verbose

# Generic mode: full URL works too; role-inbox fallback if no team page
email-me https://www.somestartup.com 5 --format json

# Output 5 email permutations for Airbnb founders without SMTP verification, as CSV
email-me https://www.ycombinator.com/companies/airbnb 5 --no-smtp --format csv
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--format` | `table` | Output format: `table`, `json`, `csv` |
| `--timeout` | `10` | SMTP connection timeout in seconds |
| `--delay` | `1.0` | Delay between SMTP probes in seconds |
| `--no-catch-all` | off | Don't catch-all results in output and count |
| `--include-unknown` | off | Include unknown results in output |
| `--verbose` | off | Print progress to stderr |
| `--no-smtp` | off | Skip SMTP verification; output permutations only |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (at least 1 result found) |
| 1 | Scraping failed |
| 2 | No verified addresses found |
| 3 | Invalid arguments |

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP GET for YC pages |
| `beautifulsoup4` | HTML parsing |
| `lxml` | Fast HTML parser backend for BS4 |
| `dnspython` | DNS MX record resolution |

## Web app

A small Flask front-end is bundled for browser use. It takes a textarea of YC URLs / company domains (one per line) **or** a `.txt` upload, plus a per-target count, and streams per-email verification results back live as NDJSON.

```bash
pip install -e ".[web]"
email-me-web                       # http://127.0.0.1:8000 (dev server)
email-me-web --host 0.0.0.0 --port 8000   # bind for LAN/server
```

Routes:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Single-page UI |
| `POST` | `/process` | Streams per-event NDJSON (`start` / `company` / `result` / `done` / `error`) |

Per-request caps (in `email_me/web.py`): 25 targets, 20 emails per target, 100 KB upload. The app is **unauthenticated by default** — put it behind a reverse proxy with auth or a Cloudflare-tunnel access policy before exposing it publicly.

## Hosting

> **The unavoidable tradeoff.** Real SMTP verification needs outbound port 25, which every free serverless platform (Vercel, Netlify, Render, Fly, HF Spaces, Cloudflare, AWS Lambda, GCP Cloud Functions/Run) blocks for anti-spam reasons. Port 587 needs auth and won't accept anonymous `RCPT` probes. So pick one:
>
> | Path | Real SMTP verify | Truly free | 24/7 no cold start | Setup |
> |------|:---:|:---:|:---:|---|
> | **Hugging Face Spaces (Docker)** | ❌ permutations only | ✅ | ✅ | drop-in `Dockerfile` is in this repo |
> | **Render free** | ❌ permutations only | ✅ | ⚠️ sleeps after 15 min | drop-in `render.yaml` is in this repo |
> | **Oracle Cloud Always Free VM** | ✅ | ✅ | ✅ | VM provisioning (steps below) |
> | **$4–6/mo VPS (Hetzner / DO / Vultr)** | ✅ | ❌ ($) | ✅ | same as Oracle |
>
> The Docker / Render builds set `EMAIL_ME_DEFAULT_NO_SMTP=1` so the UI clearly labels output as ranked permutations instead of returning a wall of `UNKNOWN`. You can uncheck the toggle in the UI to still attempt SMTP — but on a port-25-blocked host nearly everything will land as `UNKNOWN`.

### Option A — Hugging Face Spaces (free, never sleeps, no credit card)

1. Create a Space at <https://huggingface.co/new-space>: name it, SDK = **Docker**, hardware = free CPU basic.
2. Clone the Space repo locally, copy this project's files into it (or set up your own repo as the Space's git remote), `git push`. HF builds the image from the `Dockerfile`.
3. Open `https://<your-username>-<space-name>.hf.space`. That's it.

Output mode will be permutation-only by default — clearly labeled in the UI banner.

### Option B — Render free (one-click via Blueprint)

1. Push this repo to GitHub.
2. <https://dashboard.render.com> → **New → Blueprint** → connect the repo. Render reads `render.yaml` and provisions a free web service.
3. Open the assigned `*.onrender.com` URL.

Same permutation-only default. First request after 15-min idle takes ~30s to cold-start.

### Option C — Oracle Cloud Always Free VM (real SMTP verification, $0/mo)

This is the only **free** path where SMTP verification actually runs.

1. Provision an **Ampere A1 Always Free** Ubuntu 22.04 VM in the Oracle Cloud console. Note the public IP.
2. Open ingress port 80 in your VCN security list, then on the VM: `sudo iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT && sudo netfilter-persistent save`.
3. Verify port 25 outbound: `nc -vz alt1.gmail-smtp-in.l.google.com 25` should succeed. If not, file a free Oracle support request to lift the SMTP restriction, or move to a $4–6/mo VPS where it's never blocked.
4. Install + run:

   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git
   git clone <your-repo-url> ~/email-me && cd ~/email-me
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e ".[web]" gunicorn
   ```

5. systemd unit at `/etc/systemd/system/email-me.service`:

   ```ini
   [Unit]
   Description=email-me web
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/email-me
   ExecStart=/home/ubuntu/email-me/.venv/bin/gunicorn \
       --workers 2 --threads 4 --worker-class gthread --timeout 600 \
       --bind 0.0.0.0:80 \
       "email_me.web:create_app()"
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   ```bash
   sudo systemctl daemon-reload && sudo systemctl enable --now email-me
   ```

Front it with [Caddy](https://caddyserver.com/) for auto-HTTPS if you want a domain.

### Common gotchas (all paths)

- The app is **unauthenticated** by default. Before exposing it publicly add Caddy basic-auth, a Cloudflare Tunnel access policy, or bind to `127.0.0.1` and use an SSH tunnel.
- Streaming bulk runs can be long; production deploys must set `--timeout 600` (already in the configs above) or gunicorn kills the response mid-stream.
- Per-host scrape throttle defaults to 1 s and is governed by `--delay`. Bulk over many YC links takes real time — that's intentional politeness, not a bug.

## Notes

- **Port 25 blocked:** Most residential ISPs and cloud providers block outbound port 25. The tool falls back to port 587 automatically.
- **Catch-all servers:** Some domains accept all RCPT TO addresses. These are flagged as `CATCH_ALL`.
- **Greylisting:** Large mail providers may temporarily defer connections from unknown IPs, producing `UNKNOWN` results for valid addresses.
- **Result of Port 25 blocked:** I catch all emails automatically rather than only spitting out verified ones
"# yc-email-bot" 
"# yc-email-bot" 
"# yc-email-bot" 
