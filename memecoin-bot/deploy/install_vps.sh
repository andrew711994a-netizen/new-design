#!/bin/bash
# Εγκατάσταση σε server με Ubuntu 22.04/24.04. Τρέχει το bot ως υπηρεσία: ξεκινά με την εκκίνηση
# του server και ξανανοίγει μόνο του αν σταματήσει. Χρήση: bash deploy/install_vps.sh
set -e
cd "$(dirname "$0")/.."
sudo apt-get update -q && sudo apt-get install -y -q python3-venv
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-live.txt
[ -f .env ] || cp .env.example .env
sudo tee /etc/systemd/system/memebot.service >/dev/null <<UNIT
[Unit]
Description=Meme coin bot
After=network-online.target
Wants=network-online.target

[Service]
User=$(whoami)
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/python -m memebot
Restart=always
RestartSec=15
TimeoutStopSec=120
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable memebot
echo
echo "Έτοιμο. Συμπλήρωσε το .env (nano .env) και μετά: sudo systemctl restart memebot"
echo "Κατάσταση: sudo systemctl status memebot · Μηνύματα: journalctl -u memebot -f"
echo "Διακοπή: sudo systemctl stop memebot (πουλάει πρώτα τις ανοιχτές θέσεις στο live)"
