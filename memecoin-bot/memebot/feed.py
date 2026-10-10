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

Handler = Callable[[str, dict, float], Awaitable[None]]


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
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=30, max_size=2 ** 22,
                                              open_timeout=20, close_timeout=5) as ws:
                    self.ws = ws
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    if self.keys:
                        keys, self.keys = list(self.keys), set()
                        await self.subscribe(keys)
                    self.connected.set()
                    self.log("Ροή: συνδέθηκε στο PumpPortal" + (" (επανασύνδεση)" if self.reconnects else ""))
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
                self.log(f"Ροή: διακοπή σύνδεσης ({e.__class__.__name__}: {str(e)[:120]}), νέα προσπάθεια σε {delay:.0f}″")
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
