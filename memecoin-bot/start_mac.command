#!/bin/bash
cd "$(dirname "$0")"
if [ ! -f .venv/installed.ok ]; then
  echo "Πρώτη εκκίνηση: εγκατάσταση (1-3 λεπτά)..."
  python3 -m venv .venv || { echo "Δεν βρέθηκε Python 3. Κατέβασέ το από https://www.python.org/downloads/"; read -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  if ! .venv/bin/python -m pip install -r requirements-live.txt; then
    echo "Η βιβλιοθήκη για live δεν εγκαταστάθηκε· το paper δουλεύει κανονικά."
    .venv/bin/python -m pip install -r requirements.txt || { echo "Η εγκατάσταση απέτυχε. Έλεγξε τη σύνδεση και ξαναδοκίμασε."; read -r; exit 1; }
  fi
  touch .venv/installed.ok
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Φτιάχτηκε το αρχείο ρυθμίσεων .env και ανοίγει τώρα."
  echo "Συμπλήρωσε το PUMPPORTAL_API_KEY (και το NTFY_TOPIC), αποθήκευσε, κλείσε το και πάτα Enter εδώ."
  open -e .env
  read -r
fi
while true; do
  echo
  echo "  1 = Εκκίνηση bot"
  echo "  2 = Έλεγχος εγκατάστασης (σύνδεση, κλειδί API, ειδοποιήσεις)"
  echo "  3 = Αναφορά αποτελεσμάτων"
  echo "  4 = Πίνακας κόστους"
  echo "  5 = Backtest (επανάληψη της καταγεγραμμένης αγοράς)"
  echo "  6 = Ρυθμίσεις (.env)"
  read -r -p "Επιλογή 1-6 και Enter: " CH
  case "$CH" in
    1) echo "Το bot τρέχει. Για να σταματήσει: Ctrl+C ή κλείσε το παράθυρο."
       caffeinate -i .venv/bin/python -m memebot ;;   # ο Mac δεν «κοιμάται» όσο τρέχει
    2) .venv/bin/python -m memebot check ;;
    3) .venv/bin/python -m memebot report ;;
    4) .venv/bin/python -m memebot costs ;;
    5) .venv/bin/python -m memebot backtest ;;
    6) open -e .env; read -r -p "Αποθήκευσε, κλείσε το και πάτα Enter. " ;;
  esac
done
