"""Ζωντανή λειτουργία: συνδέει ροή, engine, metadata, πραγματικές εντολές, ημερολόγιο και ειδοποιήσεις."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .config import JOURNAL, ROOT
from .curve import Costs, round_trip_cost_pct
from .engine import Engine, local_time
from .feed import PumpPortalFeed, explain_connect_error, is_pumpportal, ssl_context
from .journal import Journal
from .metadata import fetch_metadata
from .notify import notify
from .report import status_text


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def flag_file(name: str) -> bool:
    return (ROOT / name).exists() or (ROOT / f"{name}.txt").exists()


def keep_awake() -> None:
    """Windows: να μην «κοιμηθεί» ο υπολογιστής όσο τρέχει το bot (η οθόνη μπορεί να σβήνει).
    Στο Mac το ίδιο κάνει το caffeinate στο start_mac.command."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:
            pass


def feed_key(cfg: dict) -> str:
    """Το κλειδί του PumpPortal στέλνεται μόνο στο PumpPortal, ποτέ σε άλλη ροή."""
    if not is_pumpportal(cfg["feed"]["url"]):
        return ""
    key = os.environ.get("PUMPPORTAL_API_KEY", "").strip()
    if not key:
        raise SystemExit("Λείπει το PUMPPORTAL_API_KEY στο αρχείο .env.\n"
                         "Χωρίς αυτό το PumpPortal δίνει μόνο τα νέα tokens, όχι τις τιμές τους. "
                         "Δες το README, βήμα 2, ή τη δωρεάν ροή (FEED_URL).")
    return key


async def run(cfg: dict) -> None:
    api_key = feed_key(cfg)
    keep_awake()
    try:                                  # VPS (systemd stop): ομαλό κλείσιμο, όπως με Ctrl+C
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    except (NotImplementedError, RuntimeError, AttributeError):
        pass
    live_cfg = cfg.get("live", {})
    live = cfg["mode"] == "live"
    costs = Costs.from_dict(cfg.get("costs"))
    broker = None
    if live:
        if os.environ.get("MEMEBOT_I_ACCEPT_RISK", "").strip().lower() != "yes":
            raise SystemExit("Για πραγματικές συναλλαγές βάλε MEMEBOT_I_ACCEPT_RISK=yes στο .env "
                             "(αφού διαβάσεις το ANALYSIS.md).")
        from .live import LiveBroker
        broker = LiveBroker(live_cfg, costs, log)
        bal = await asyncio.to_thread(broker.startup_check, live_cfg)
        log(f"LIVE · πορτοφόλι {broker.pubkey} · υπόλοιπο {bal:.4f} SOL · στρατηγική {live_cfg.get('strategy')}")

    journal = Journal(JOURNAL, record_ticks=bool(cfg.get("feed", {}).get("record_ticks", True)))
    engine = Engine(cfg, journal, live_variant=live_cfg.get("strategy") if live else None,
                    own_wallet=broker.pubkey if broker else "")
    if broker:
        saved = journal.load_json("live_positions.json", []) or []
        keep = []
        for s in saved:
            try:
                held = await asyncio.to_thread(broker.token_balance, s["mint"])
            except Exception:
                held = s["tokens"]
            if held > 0:
                s["tokens"] = held
                keep.append(s)
            else:
                log(f"Η θέση {s.get('symbol')} δεν υπάρχει πια στο πορτοφόλι (έκλεισε εκτός bot).")
        engine.restore_live(keep, time.time())
        if keep:
            log(f"Συνεχίζω τη διαχείριση {len(keep)} πραγματικών θέσεων από την προηγούμενη εκτέλεση.")

    feed = PumpPortalFeed(cfg["feed"]["url"], api_key, log)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    mcfg = cfg.get("metadata", {})
    workers = int(mcfg.get("workers", 6))
    pool = ThreadPoolExecutor(max_workers=workers)
    meta_inflight: set[str] = set()
    tasks: set[asyncio.Task] = set()
    started = time.time()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def apply_actions() -> None:
        a = engine.take_actions()
        if a.subscribe:
            await feed.subscribe(a.subscribe)
        if a.unsubscribe:
            await feed.unsubscribe(a.unsubscribe)
        for mint, uri in a.meta:
            if len(meta_inflight) < workers * 4:
                meta_inflight.add(mint)
                spawn(fetch_meta(mint, uri))
            else:
                engine.on_meta(mint, None, time.time())
        for o in a.live_orders:
            spawn(run_live(o))
        for title, body in a.notes:
            log(f"{title} · {body.splitlines()[0]}")
            if live and cfg.get("notify", {}).get("live_trades", True):
                loop.run_in_executor(None, notify, title, body)

    async def fetch_meta(mint: str, uri: str) -> None:
        try:
            meta = await loop.run_in_executor(pool, fetch_metadata, uri, float(mcfg.get("timeout_s", 3.0)))
        finally:
            meta_inflight.discard(mint)
        t = time.time()
        journal.tick("meta", {"mint": mint, "meta": meta}, t)
        engine.on_meta(mint, meta, t)
        await apply_actions()

    async def run_live(o) -> None:
        log(f"LIVE {'αγορά' if o.kind == 'buy' else 'πώληση'} {o.symbol} ({o.reason})")
        res = await asyncio.to_thread(broker.execute, o)
        t = time.time()
        journal.order({"time": local_time(t), "variant": o.variant, "kind": o.kind, "mint": o.mint,
                       "symbol": o.symbol, "amount": o.amount_sol if o.kind == "buy" else o.frac, "ok": int(res.ok),
                       "sol_delta": round(res.sol_delta, 6), "token_delta": res.token_delta,
                       "signature": res.signature, "error": res.error, "reason": o.reason})
        if not res.ok:
            log(f"LIVE αποτυχία {o.symbol}: {res.error}")
        engine.on_live_result(o, res, t)
        journal.save_json("live_positions.json", engine.live_state())
        await apply_actions()

    errors_seen = 0

    async def handle(kind: str, msg: dict, t: float) -> None:
        nonlocal errors_seen
        if kind == "create":
            journal.tick("c", msg, t)
            engine.on_create(msg, t)
        elif kind == "trade":
            journal.tick("t", msg, t)
            engine.on_trade(msg, t)
        elif kind == "migration":
            journal.tick("m", msg, t)
            journal.migration(str(msg.get("mint", "")), local_time(t))
            engine.on_migration(msg, t)
        elif kind == "error":
            errors_seen += 1
            if errors_seen <= 5:
                log(f"PumpPortal: {json.dumps(msg, ensure_ascii=False)[:300]}")
        await apply_actions()

    async def ticker() -> None:
        last_status = last_summary = time.time()
        summary_every = float(cfg.get("notify", {}).get("paper_summary_every_hours", 12)) * 3600
        while not stop.is_set():
            await asyncio.sleep(1)
            t = time.time()
            engine.guard.stop_file = flag_file("STOP")
            if live and flag_file("SELL_ALL") and not engine.guard.halted:
                engine.guard.halted = "αρχείο SELL_ALL"
                n = engine.force_exit_live(t, "χειροκίνητο SELL_ALL")
                log(f"SELL_ALL: πουλάω {n} πραγματικές θέσεις και σταματώ τις αγορές.")
                loop.run_in_executor(None, notify, "🛑 SELL_ALL", f"Πώληση {n} θέσεων, οι αγορές σταμάτησαν.")
            engine.on_tick(t)
            await apply_actions()
            if feed.connected.is_set() and feed.last_msg_t and t - feed.last_msg_t > 120 and feed.ws is not None:
                log("Ροή: κανένα μήνυμα για 2′, επανασύνδεση.")
                feed.last_msg_t = t
                spawn(feed.ws.close())
            if t - last_status >= 60:
                last_status = t
                journal.flush()
                text = status_text(engine, cfg, started, t, feed.connected.is_set())
                journal.write_text("status.md", text)
                s = engine.summary()
                log(f"Παρακολουθούνται {engine.watching_count()} · νέα {engine.stats['νέα tokens']} · "
                    + " · ".join(f"{r['variant']}: {r['closed']} κλεισ., {r['pnl_sol']:+.3f} SOL" for r in s))
            if not live and t - last_summary >= summary_every:
                last_summary = t
                s = engine.summary()
                body = "\n".join(f"{r['variant']}: {r['closed']} συναλλαγές, {r['pnl_sol']:+.3f} SOL" for r in s)
                loop.run_in_executor(None, notify, "Meme bot (εικονικά) · σύνοψη", body)

    rt = round_trip_cost_pct(float(live_cfg.get("trade_sol", 0.05)) if live else 0.1, costs)
    from . import __version__
    log(f"Έκδοση bot: {__version__}")
    log(f"Ξεκινώ σε λειτουργία {'LIVE (πραγματικά χρήματα)' if live else 'PAPER (εικονικά)'} · "
        f"στρατηγικές: {', '.join(engine.variants)} · κόστος αγοράς+πώλησης ≈ {rt:.1f}%")
    if live:
        loop.run_in_executor(None, notify, "Meme bot LIVE ξεκίνησε",
                             f"Στρατηγική {live_cfg.get('strategy')} · {live_cfg.get('trade_sol')} SOL ανά αγορά")
    try:
        await asyncio.gather(feed.run(handle, stop), ticker())
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        t = time.time()
        if live and live_cfg.get("sell_on_shutdown", True) and engine.live_state():
            log("Κλείσιμο: πουλάω τις πραγματικές θέσεις πριν σταματήσω (έως 90″)...")
            engine.force_exit_live(t, "τερματισμός bot")
            orders = engine.take_actions().live_orders
            try:
                await asyncio.wait_for(asyncio.gather(*(run_live(o) for o in orders)), timeout=90)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                log("Δεν πρόλαβα να πουλήσω όλες τις θέσεις· θα τις συνεχίσω στην επόμενη εκκίνηση.")
        engine.shutdown_paper(time.time())
        journal.write_text("status.md", status_text(engine, cfg, started, time.time(), False))
        if broker:
            journal.save_json("live_positions.json", engine.live_state())
        journal.close()
        pool.shutdown(wait=False, cancel_futures=True)
        log("Το bot σταμάτησε. Αναφορά: python -m memebot report")


async def check(cfg: dict) -> None:
    """Γρήγορος έλεγχος εγκατάστασης: ροή, κλειδί API, metadata, ειδοποιήσεις, (και πορτοφόλι στο live)."""
    import websockets

    from . import __version__
    print(f"Έκδοση bot: {__version__}")
    url = PumpPortalFeed(cfg["feed"]["url"], feed_key(cfg)).url
    ok = True
    print(f"1) Σύνδεση στη ροή {cfg['feed']['url']} ...")
    creates, trades, errors = [], 0, []
    try:
        async with websockets.connect(url, ssl=ssl_context(url), open_timeout=20) as ws:
            await ws.send(json.dumps({"method": "subscribeNewToken"}))
            end = time.time() + 90
            while time.time() < end and (len(creates) < 3 or trades < 1):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(end - time.time(), 0.1))
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                kind = str(msg.get("txType", "")).lower()
                if kind == "create" and len(creates) < 3:
                    creates.append(msg)
                    print(f"   νέο token: {msg.get('symbol')} · κεφ/ση {float(msg.get('marketCapSol', 0)):.1f} SOL")
                    await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [msg.get("mint")]}))
                elif kind in ("buy", "sell"):
                    trades += 1
                    missing = [k for k in ("vSolInBondingCurve", "vTokensInBondingCurve", "traderPublicKey",
                                           "solAmount", "tokenAmount") if k not in msg]
                    if missing and trades == 1:
                        print(f"   ΠΡΟΣΟΧΗ: λείπουν πεδία από τις συναλλαγές: {', '.join(missing)} "
                              f"(στείλε αυτό το μήνυμα στο Claude)")
                        errors.append(missing)
                elif "errors" in msg or "error" in msg:
                    errors.append(msg)
                    print(f"   μήνυμα σφάλματος: {json.dumps(msg, ensure_ascii=False)[:200]}")
    except Exception as e:
        print("   ΑΠΟΤΥΧΙΑ: " + explain_connect_error(e, cfg["feed"]["url"]))
    print(f"   νέα tokens: {'OK' if creates else 'ΟΧΙ'} · συναλλαγές: {'OK' if trades else 'ΟΧΙ'}")
    ok &= bool(creates) and trades > 0 and not any(isinstance(e, list) for e in errors)
    if creates and cfg.get("metadata", {}).get("fetch", True):
        print("2) Metadata (social links)...")
        meta = await asyncio.to_thread(fetch_metadata, str(creates[0].get("uri", "")), 5.0)
        print(f"   {'OK: ' + json.dumps(meta, ensure_ascii=False) if meta is not None else 'απέτυχε (δεν σταματά το bot)'}")
    print("3) Ειδοποίηση στο κινητό...")
    if os.environ.get("NTFY_TOPIC"):
        await asyncio.to_thread(notify, "Meme bot: δοκιμή", "Αν το βλέπεις, οι ειδοποιήσεις δουλεύουν.")
        print("   στάλθηκε· έλεγξε το κινητό")
    else:
        print("   δεν έχει οριστεί NTFY_TOPIC (προαιρετικό)")
    if cfg["mode"] == "live":
        print("4) Πορτοφόλι live...")
        from .live import LiveBroker
        broker = LiveBroker(cfg.get("live", {}), Costs.from_dict(cfg.get("costs")), log)
        bal = await asyncio.to_thread(broker.rpc.balance, broker.pubkey)
        print(f"   {broker.pubkey}: {bal:.4f} SOL")
    print("\nΌλα έτοιμα." if ok else "\nΚάτι λείπει: δες τα μηνύματα παραπάνω και το README.")
