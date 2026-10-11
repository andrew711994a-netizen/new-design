"""Ολόκληρο το bot (ροή → engine → ημερολόγιο) απέναντι σε ψεύτικο server PumpPortal στο localhost."""

import asyncio
import json

import pytest

websockets = pytest.importorskip("websockets")
from websockets.asyncio.server import serve  # noqa: E402

from memebot import runner  # noqa: E402
from memebot.feed import classify  # noqa: E402

from sim import Market, base_config  # noqa: E402


def test_api_key_only_for_pumpportal(monkeypatch):
    from memebot.config import load_config
    from memebot.feed import PumpPortalFeed
    monkeypatch.setenv("PUMPPORTAL_API_KEY", "K")
    monkeypatch.delenv("FEED_URL", raising=False)
    monkeypatch.delenv("MEMEBOT_MODE", raising=False)
    cfg = load_config()
    assert PumpPortalFeed(cfg["feed"]["url"], runner.feed_key(cfg)).url.endswith("/api/data?api-key=K")
    assert cfg["costs"]["data_cost_sol_per_10k_trades"] > 0
    monkeypatch.setenv("FEED_URL", "wss://pumpdev.io/ws")
    cfg = load_config()
    assert runner.feed_key(cfg) == "" and PumpPortalFeed(cfg["feed"]["url"], "").url == "wss://pumpdev.io/ws"
    assert cfg["costs"]["data_cost_sol_per_10k_trades"] == 0 and cfg["feed"]["max_watching"] == 25


def test_classify():
    assert classify({"txType": "create"}) == "create"
    assert classify({"txType": "buy"}) == "trade"
    assert classify({"txType": "migrate", "mint": "x"}) == "migration"
    assert classify({"errors": "Invalid API key"}) == "error"
    assert classify({"message": "Successfully subscribed"}) == "info"


def test_full_bot_against_fake_pumpportal(tmp_path, monkeypatch):
    mkt = Market()
    received = []

    async def handler(ws):
        assert "api-key" not in ws.request.path       # το κλειδί του PumpPortal δεν πάει σε άλλη ροή
        await ws.send(json.dumps({"message": "Successfully subscribed to token creation events."}))
        subscribed = asyncio.Event()

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                received.append(msg)
                if msg.get("method") == "subscribeTokenTrade":
                    subscribed.set()

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.2)
        await ws.send(json.dumps(mkt.create("AAA", dev="D1")))
        await asyncio.wait_for(subscribed.wait(), 3)
        for i in range(6):
            await ws.send(json.dumps(mkt.buy("AAA", f"B{i}", 0.6)))
            await asyncio.sleep(0.3)
        for i in range(6):
            await ws.send(json.dumps(mkt.sell("AAA", f"B{i}")))
            await asyncio.sleep(0.2)
        await ws.send(json.dumps(mkt.sell("AAA", "D1")))
        await asyncio.sleep(6)
        task.cancel()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            cfg = base_config("baseline_all")
            cfg["feed"]["url"] = f"ws://127.0.0.1:{port}"
            s = cfg["strategies"][-1]
            s["entry"] = {"min_age_s": 1, "max_age_s": 3}
            s["exit"]["stop_loss_pct"] = 20
            bot = asyncio.create_task(runner.run(cfg))
            await asyncio.sleep(7)
            bot.cancel()
            await asyncio.gather(bot, return_exceptions=True)

    sent = []
    monkeypatch.setattr(runner, "JOURNAL", tmp_path)
    monkeypatch.setattr(runner, "notify", lambda title, body, *a: sent.append((title, body)))
    monkeypatch.setenv("PUMPPORTAL_API_KEY", "TESTKEY")
    asyncio.run(main())

    titles = [s[0] for s in sent]
    assert "Meme bot ξεκίνησε (εικονικά)" in titles and "Meme bot σταμάτησε" in titles
    assert "baseline_all: 1 συναλλαγές" in dict(sent)["Meme bot σταμάτησε"]

    methods = [m.get("method") for m in received]
    assert methods[:2] == ["subscribeNewToken", "subscribeMigration"]
    assert {"method": "subscribeTokenTrade", "keys": ["AAA"]} in received
    trades = (tmp_path / "trades.csv").read_text(encoding="utf-8").splitlines()
    assert len(trades) == 2 and "baseline_all" in trades[1]
    assert "πούλησε ο δημιουργός" in trades[1] or "stop-loss" in trades[1]
    ticks = list((tmp_path / "ticks").glob("*.jsonl"))
    assert ticks and len(ticks[0].read_text().splitlines()) >= 13
    assert "PAPER" in (tmp_path / "status.md").read_text(encoding="utf-8")


def test_tls_uses_certifi_and_errors_are_explained():
    import ssl

    from memebot.feed import explain_connect_error, ssl_context
    assert isinstance(ssl_context("wss://pumpdev.io/ws"), ssl.SSLContext)
    assert ssl_context("ws://127.0.0.1:1") is None
    err = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                                          "certificate has expired (_ssl.c:1144)")
    msg = explain_connect_error(err, "wss://pumpdev.io/ws")
    assert "pumpdev.io" in msg and "έχει λήξει" in msg and "ημερομηνία" in msg
    assert "Δεν απαντά" in explain_connect_error(ConnectionRefusedError(111, "refused"), "wss://x.io/ws")


def test_check_reports_ok_and_failure(monkeypatch, capsys):
    mkt = Market()

    async def handler(ws):
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("method") == "subscribeNewToken":
                for i in range(3):
                    await ws.send(json.dumps(mkt.create(f"K{i}", dev=f"D{i}")))
            elif msg.get("method") == "subscribeTokenTrade":
                await ws.send(json.dumps(mkt.buy(msg["keys"][0], "b", 0.2)))

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            cfg = base_config()
            cfg["feed"]["url"] = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            await runner.check(cfg)
        cfg["feed"]["url"] = "ws://127.0.0.1:9"              # κανείς δεν ακούει εκεί
        await runner.check(cfg)

    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    asyncio.run(main())
    out = capsys.readouterr().out
    first, second = out.split("1) Σύνδεση", 2)[1:]
    assert "νέα tokens: OK · συναλλαγές: OK" in first and "Όλα έτοιμα" in first
    assert "ΑΠΟΤΥΧΙΑ: Δεν απαντά" in second and "Κάτι λείπει" in second


def test_only_one_bot_at_a_time(tmp_path):
    first = runner.single_instance(tmp_path)
    with pytest.raises(SystemExit, match="τρέχει ήδη"):
        runner.single_instance(tmp_path)
    first.close()
    runner.single_instance(tmp_path).close()            # μετά το κλείσιμο ξεκινά κανονικά
