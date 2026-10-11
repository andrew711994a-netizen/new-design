"""Ζωντανή ροή από το PumpPortal: νέα tokens, συναλλαγές και αποφοιτήσεις.

Μία σύνδεση για όλα (το PumpPortal αποκλείει όποιον ανοίγει πολλές). Τα νέα tokens και
οι αποφοιτήσεις είναι δωρεάν· οι συναλλαγές χρεώνονται 0,01 SOL ανά 10.000 και θέλουν
κλειδί API, γι' αυτό το bot ζητά συναλλαγές μόνο για τα tokens που παρακολουθεί.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Awaitable, Callable
from urllib.parse import urlparse

Handler = Callable[[str, dict, float], Awaitable[None]]


def is_pumpportal(url: str) -> bool:
    return "pumpportal.fun" in url


def ssl_context(url: str):
    """Έλεγχος πιστοποιητικών με την ενημερωμένη λίστα του certifi (την ίδια με τον Firefox) και επιπλέον
    με του συστήματος (π.χ. antivirus που ελέγχει τις συνδέσεις). Η λίστα των Windows μόνη της μπορεί να
    έχει παλιές, ληγμένες εγγραφές· όταν υπάρχουν δύο, το OpenSSL προτιμά την έγκυρη."""
    if not url.startswith("wss://"):
        return None
    import ssl

    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        ctx.load_default_certs()
    except (ssl.SSLError, OSError):
        pass
    return ctx


def explain_connect_error(e: Exception, url: str) -> str:
    """Κατανοητή εξήγηση για αποτυχία σύνδεσης, αντί για σελίδες σφαλμάτων."""
    host = urlparse(url).hostname or url
    text = f"{e.__class__.__name__}: {e}"
    if "CERTIFICATE_VERIFY_FAILED" in text or "SSLCertVerification" in text:
        why = "έχει λήξει" if "expired" in text else "δεν είναι έγκυρο"
        return (f"Το πιστοποιητικό ασφαλείας του {host} {why}.\n"
                f"   α) Έλεγξε ότι η ημερομηνία και η ώρα του υπολογιστή είναι σωστές.\n"
                f"   β) Άνοιξε το https://{host} στον browser. Αν βγάζει προειδοποίηση ασφαλείας, το πρόβλημα "
                f"είναι του {host}: περίμενε να το διορθώσουν ή χρησιμοποίησε το PumpPortal (README, βήμα 2).")
    if "401" in text or "403" in text:
        return f"Ο {host} αρνήθηκε τη σύνδεση ({text[:120]}). Έλεγξε το κλειδί API στο .env."
    if isinstance(e, (OSError, TimeoutError)):
        return (f"Δεν απαντά ο {host} ({text[:120]}). Έλεγξε τη σύνδεση στο internet· "
                f"αν έχεις antivirus ή firewall, δες μήπως μπλοκάρει την Python.")
    return text[:300]


def classify(msg: dict) -> str:
    """create / trade / migration / info / error."""
    tx = str(msg.get("txType", "")).lower()
    if tx == "create":
        return "create"
    if tx in ("buy", "sell"):
        return "trade"
    if tx.startswith("migrat") or (msg.get("mint") and msg.get("signature") and not tx and "pool" in msg):
        return "migration"
    if "errors" in msg or "error" in msg:
        return "error"
    return "info"


class PumpPortalFeed:
    def __init__(self, url: str, api_key: str, log: Callable[[str], None] = print):
        self.url = url + (("&" if "?" in url else "?") + "api-key=" + api_key if api_key else "")
        self.log = log
        self.ws = None
        self.keys: set[str] = set()
        self.connected = asyncio.Event()
        self.last_msg_t = 0.0
        self.reconnects = 0

    async def _send(self, payload: dict) -> None:
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps(payload))
            except Exception as e:          # θα ξαναγίνει εγγραφή μετά την επανασύνδεση
                self.log(f"Ροή: αποτυχία αποστολής ({e.__class__.__name__})")

    async def subscribe(self, mints: list[str]) -> None:
        new = [m for m in mints if m not in self.keys]
        self.keys.update(new)
        for i in range(0, len(new), 50):
            await self._send({"method": "subscribeTokenTrade", "keys": new[i:i + 50]})

    async def unsubscribe(self, mints: list[str]) -> None:
        old = [m for m in mints if m in self.keys]
        self.keys.difference_update(old)
        for i in range(0, len(old), 50):
            await self._send({"method": "unsubscribeTokenTrade", "keys": old[i:i + 50]})

    async def run(self, handler: Handler, stop: asyncio.Event) -> None:
        import websockets

        delay = 1.0
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, ssl=ssl_context(self.url), ping_interval=20, ping_timeout=30,
                                              max_size=2 ** 22, open_timeout=20, close_timeout=5) as ws:
                    self.ws = ws
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    if self.keys:
                        keys, self.keys = list(self.keys), set()
                        await self.subscribe(keys)
                    self.connected.set()
                    self.log(f"Ροή: συνδέθηκε στο {urlparse(self.url).hostname}"
                             + (" (επανασύνδεση)" if self.reconnects else ""))
                    delay = 1.0
                    async for raw in ws:
                        t = time.time()
                        self.last_msg_t = t
                        try:
                            msg = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if isinstance(msg, dict):
                            await handler(classify(msg), msg, t)
                        if stop.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(f"Ροή: διακοπή σύνδεσης, νέα προσπάθεια σε {delay:.0f}″ · {explain_connect_error(e, self.url)}")
            finally:
                self.ws = None
                self.connected.clear()
            if stop.is_set():
                break
            self.reconnects += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 60)
