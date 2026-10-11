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

    monkeypatch.setattr(runner, "JOURNAL", tmp_path)
    monkeypatch.setenv("PUMPPORTAL_API_KEY", "TESTKEY")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    asyncio.run(main())

    methods = [m.get("method") for m in received]
    assert methods[:2] == ["subscribeNewToken", "subscribeMigration"]
    assert {"method": "subscribeTokenTrade", "keys": ["AAA"]} in received
    trades = (tmp_path / "trades.csv").read_text(encoding="utf-8").splitlines()
    assert len(trades) == 2 and "baseline_all" in trades[1]
    assert "πούλησε ο δημιουργός" in trades[1] or "stop-loss" in trades[1]
    ticks = list((tmp_path / "ticks").glob("*.jsonl"))
    assert ticks and len(ticks[0].read_text().splitlines()) >= 13
    assert "PAPER" in (tmp_path / "status.md").read_text(encoding="utf-8")
