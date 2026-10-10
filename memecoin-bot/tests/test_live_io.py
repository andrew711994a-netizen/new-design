"""Live broker χωρίς δίκτυο: ψεύτικο PumpPortal και ψεύτικο RPC."""

import json

import pytest

solders = pytest.importorskip("solders")
from solders.hash import Hash  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.message import MessageV0  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.signature import Signature  # noqa: E402
from solders.system_program import TransferParams, transfer  # noqa: E402
from solders.transaction import VersionedTransaction  # noqa: E402

from memebot import live  # noqa: E402
from memebot.curve import Costs  # noqa: E402
from memebot.engine import Order  # noqa: E402

MINT = "Mint1111111111111111111111111111111111111pump"


def tx_json(owner, pre_sol, post_sol, pre_tok, post_tok, err=None):
    def bal(x):
        return [] if x is None else [{"owner": owner, "mint": MINT,
                                       "uiTokenAmount": {"amount": str(int(x * 1e6)), "decimals": 6}}]
    return {"meta": {"err": err, "preBalances": [int(pre_sol * 1e9), 5], "postBalances": [int(post_sol * 1e9), 5],
                     "preTokenBalances": bal(pre_tok), "postTokenBalances": bal(post_tok),
                     "loadedAddresses": {"writable": [], "readonly": []}},
            "transaction": {"message": {"accountKeys": [owner, "Other"]}}}


def test_parse_fill():
    sol, tok, err = live.parse_fill(tx_json("ME", 1.0, 0.9465, None, 1234.5), "ME", MINT)
    assert sol == pytest.approx(-0.0535) and tok == pytest.approx(1234.5) and err is None


def test_keypair_formats():
    kp = Keypair()
    assert str(live.load_keypair(str(kp)).pubkey()) == str(kp.pubkey())
    assert str(live.load_keypair(json.dumps(list(bytes(kp)))).pubkey()) == str(kp.pubkey())


class FakeRPC:
    def __init__(self, owner):
        self.owner, self.sent, self.txs = owner, [], {}
        self.holding = 0.0

    def balance(self, pubkey):
        return 1.0

    def send(self, raw):
        tx = VersionedTransaction.from_bytes(raw)
        assert all(tx.verify_with_results()), "η συναλλαγή δεν είναι σωστά υπογεγραμμένη"
        sig = f"sig{len(self.sent)}"
        self.sent.append(tx)
        return sig

    def status(self, sig):
        return {"confirmationStatus": "confirmed", "err": None}

    def transaction(self, sig):
        return self.txs.get(sig)

    def token_accounts(self, owner, mint):
        return [{"pubkey": str(Pubkey.new_unique()),
                 "account": {"owner": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
                             "data": {"parsed": {"info": {"tokenAmount": {"amount": str(int(self.holding * 1e6)),
                                                                          "decimals": 6}}}}}}]

    def latest_blockhash(self):
        return str(Hash.default())


@pytest.fixture
def broker(monkeypatch):
    kp = Keypair()
    monkeypatch.setenv("WALLET_PRIVATE_KEY", str(kp))
    b = live.LiveBroker({"broker": "local", "min_reserve_sol": 0.03}, Costs())
    b.rpc = FakeRPC(b.pubkey)
    calls = []

    class Resp:
        status_code = 200

        def __init__(self, content):
            self.content = content

    def fake_post(url, data=None, **kw):
        calls.append(data)
        ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=Pubkey.default(), lamports=1))
        msg = MessageV0.try_compile(kp.pubkey(), [ix], [], Hash.default())
        return Resp(bytes(VersionedTransaction.populate(msg, [Signature.default()])))

    monkeypatch.setattr(live.requests, "post", fake_post)
    monkeypatch.setattr(live.time, "sleep", lambda s: None)
    b.calls = calls
    return b


def test_buy_signs_sends_and_reads_fill(broker):
    broker.rpc.txs["sig0"] = tx_json(broker.pubkey, 1.0, 0.9465, None, 1500.0)
    o = Order(1, "buy", "v@live", MINT, "FROG", 0, 1e-7, amount_sol=0.05, live=True, slippage_pct=15)
    res = broker.execute(o)
    assert res.ok and res.sol_delta == pytest.approx(-0.0535) and res.token_delta == pytest.approx(1500)
    req = broker.calls[0]
    assert req["action"] == "buy" and req["denominatedInSol"] == "true" and req["publicKey"] == broker.pubkey
    assert req["slippage"] == 15 and req["pool"] == "auto"


def test_final_sell_closes_token_account(broker):
    broker.rpc.txs["sig0"] = tx_json(broker.pubkey, 0.9, 0.97, 1500.0, 0.0)
    broker.rpc.txs["sig1"] = tx_json(broker.pubkey, 0.97, 0.972034, 0.0, 0.0)
    o = Order(2, "sell", "v@live", MINT, "FROG", 0, 1e-7, frac=1.0, final=True, live=True, slippage_pct=30)
    res = broker.execute(o)
    assert res.ok and res.token_delta == pytest.approx(-1500)
    assert res.sol_delta == pytest.approx(0.07 + 0.002034)          # πώληση + επιστροφή εγγύησης
    assert broker.calls[0]["amount"] == "100%" and broker.calls[0]["denominatedInSol"] == "false"
    assert len(broker.rpc.sent) == 2


def test_partial_sell_uses_percentage_and_failed_tx_is_reported(broker):
    broker.rpc.txs["sig0"] = tx_json(broker.pubkey, 0.9, 0.8995, 1500.0, 1500.0, err={"InstructionError": [3, 6003]})
    o = Order(3, "sell", "v@live", MINT, "FROG", 0, 1e-7, frac=0.5, final=False, live=True, slippage_pct=30)
    res = broker.execute(o)
    assert broker.calls[0]["amount"] == "50%"
    assert not res.ok and not res.exception and "slippage" in res.error
    assert res.sol_delta == pytest.approx(-0.0005)


def test_wallet_cap_refuses_big_wallets(broker):
    broker.rpc.balance = lambda pk: 5.0
    with pytest.raises(SystemExit, match="πάνω από το όριο"):
        broker.startup_check({"max_wallet_sol": 1.5, "trade_sol": 0.05})
