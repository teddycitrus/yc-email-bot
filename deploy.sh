#!/usr/bin/env bash
#
# email-me — one-shot deploy script for Oracle Cloud Always Free (Ubuntu 22.04).
#
# Usage (on a fresh VM, after SSH'ing in):
#
#   curl -fsSL https://raw.githubusercontent.com/teddycitrus/yc-email-bot/main/deploy.sh | sudo bash
#
#   # ...or, if you've already git-cloned the repo:
#   sudo bash deploy.sh
#
# Env-var overrides (optional):
#   PORT=80                                  # public port (default 80)
#   REPO_URL=https://github.com/.../repo.git # use a fork
#   SERVICE_USER=ubuntu                      # systemd run-as user (Oracle Linux: opc)
#
# What it does:
#   1. installs python3 / venv / git / iptables-persistent / netcat
#   2. clones (or updates) the repo into /opt/email-me
#   3. builds the venv and installs the [web] extra + gunicorn
#   4. opens iptables ingress for $PORT (saved persistent)
#   5. probes outbound TCP/25 — if blocked, defaults the app to no-SMTP mode
#      so users see ranked permutations instead of a wall of UNKNOWN
#   6. installs/enables/starts a systemd unit that survives reboots
#   7. prints the live URL
#
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

PORT="${PORT:-80}"
REPO_URL="${REPO_URL:-https://github.com/teddycitrus/yc-email-bot.git}"
SERVICE_USER="${SERVICE_USER:-ubuntu}"
INSTALL_DIR="/opt/email-me"
UNIT_PATH="/etc/systemd/system/email-me.service"

say()  { printf "\n\033[1;36m▶\033[0m %s\n" "$*"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; }

[[ $EUID -eq 0 ]] || { err "Run as root: sudo bash deploy.sh"; exit 1; }
id "$SERVICE_USER" &>/dev/null || { err "User '$SERVICE_USER' not found. On Oracle Linux use SERVICE_USER=opc."; exit 1; }
command -v apt-get >/dev/null || { err "This script targets Debian/Ubuntu. For Oracle Linux, please use the manual steps in the README."; exit 1; }

# 1. OS packages -------------------------------------------------------------
say "Installing system packages"
apt-get update -qq
apt-get install -qq -y python3 python3-venv python3-pip git \
                      iptables-persistent netcat-openbsd curl >/dev/null
ok "system packages ready"

# 2. Source code -------------------------------------------------------------
say "Fetching application code"
mkdir -p "$INSTALL_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" fetch --quiet origin
    sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" reset --quiet --hard origin/HEAD
    ok "updated $INSTALL_DIR"
else
    # `git clone <dir>` requires <dir> empty; if a previous half-install left
    # files, wipe and recreate before cloning.
    if [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        rm -rf "$INSTALL_DIR"
        mkdir -p "$INSTALL_DIR"
        chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    fi
    sudo -u "$SERVICE_USER" git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    ok "cloned into $INSTALL_DIR"
fi

# 3. Python venv + deps ------------------------------------------------------
say "Setting up Python environment"
if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]]; then
    sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/.venv"
fi
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet \
    -e "$INSTALL_DIR[web]" gunicorn
ok "venv ready ($INSTALL_DIR/.venv)"

# 4. Firewall ----------------------------------------------------------------
say "Opening ingress on TCP/$PORT"
if ! iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT &>/dev/null; then
    # Insert before the default REJECT rule that Oracle's Ubuntu images ship with.
    iptables -I INPUT 1 -p tcp --dport "$PORT" -j ACCEPT
fi
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4
ok "iptables saved (rules.v4)"
warn "REMINDER: also open TCP/$PORT in your Oracle VCN Security List — that's a one-time console step the script can't do for you."

# 5. Outbound port 25 sanity check ------------------------------------------
say "Probing outbound TCP/25 (real SMTP verification)"
NO_SMTP_VALUE="0"
if timeout 5 nc -z alt1.gmail-smtp-in.l.google.com 25 &>/dev/null; then
    ok "port 25 outbound: OPEN — real SMTP verification will work"
else
    warn "port 25 outbound: BLOCKED — running in permutation-only mode"
    warn "to enable real verification, file a free Oracle support request:"
    warn "  'Please remove the SMTP egress restriction from my Always Free tenancy.'"
    NO_SMTP_VALUE="1"
fi

# 6. systemd unit ------------------------------------------------------------
say "Installing systemd service"
cat > "$UNIT_PATH" <<EOF
[Unit]
Description=email-me web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=EMAIL_ME_DEFAULT_NO_SMTP=$NO_SMTP_VALUE
ExecStart=$INSTALL_DIR/.venv/bin/gunicorn \\
    --workers 2 --threads 4 --worker-class gthread --timeout 600 \\
    --bind 0.0.0.0:$PORT \\
    "email_me.web:create_app()"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --quiet email-me
systemctl restart email-me
ok "service installed and started"

# 7. Verify it's actually serving -------------------------------------------
say "Waiting for service to respond"
for i in {1..15}; do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then
        ok "responding on 127.0.0.1:$PORT"
        break
    fi
    sleep 1
    if [[ $i -eq 15 ]]; then
        err "Service didn't respond in 15s. Check: sudo journalctl -u email-me -n 50"
        exit 1
    fi
done

# 8. Final report ------------------------------------------------------------
PUBLIC_IP="$(curl -fsS -m 5 ifconfig.me 2>/dev/null || echo '<your-public-ip>')"
URL="http://$PUBLIC_IP"
[[ "$PORT" != "80" ]] && URL="$URL:$PORT"

printf "\n\033[1;32m═══════════════════════════════════════════════════════\033[0m\n"
printf "  email-me is live\n"
printf "  → %s/\n" "$URL"
printf "\033[1;32m═══════════════════════════════════════════════════════\033[0m\n\n"
printf "  manage:  sudo systemctl {status,restart,stop} email-me\n"
printf "  logs:    sudo journalctl -u email-me -f\n"
printf "  update:  sudo bash %s/deploy.sh\n\n" "$INSTALL_DIR"

if [[ "$NO_SMTP_VALUE" == "1" ]]; then
    printf "  \033[1;33m! SMTP egress blocked\033[0m — app is running in permutation-only\n"
    printf "    mode. File a free Oracle support ticket to enable port 25.\n\n"
fi
