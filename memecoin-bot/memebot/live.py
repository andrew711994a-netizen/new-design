"""Πραγματικές εντολές στο Solana μέσω PumpPortal.

Δύο τρόποι (live.broker στο config.json):
  local      (προτείνεται) Το PumpPortal φτιάχνει τη συναλλαγή, την υπογράφει το bot με το δικό σου
             κλειδί στον υπολογιστή σου και τη στέλνει από το δικό σου RPC. Χρέωση 0,5%.
  lightning  Το PumpPortal υπογράφει και στέλνει από το πορτοφόλι που σου έφτιαξε (δεν χρειάζεται
             ιδιωτικό κλειδί στον υπολογιστή, αλλά το κλειδί το έχει και το PumpPortal). Χρέωση 1%.

Μεταβλητές περιβάλλοντος (.env):
  PUMPPORTAL_API_KEY            κλειδί API (το ίδιο για δεδομένα και για lightning)
  WALLET_PRIVATE_KEY            ιδιωτικό κλειδί του ξεχωριστού πορτοφολιού του bot (local)
  PUMPPORTAL_WALLET_PUBLIC_KEY  δημόσια διεύθυνση του πορτοφολιού PumpPortal (lightning)
  RPC_URL                       π.χ. το δωρεάν του Helius· αλλιώς το δημόσιο του Solana
  MEMEBOT_I_ACCEPT_RISK         πρέπει να είναι yes για να γίνουν πραγματικές εντολές
"""

from __future__ import annotations

import base64
import json
import os
import time

import requests

from .curve import Costs
from .engine import LiveResult, Order

LAMPORTS = 1_000_000_000
PORTAL = "https://pumpportal.fun/api"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


class TradeRejected(Exception):
    """Το PumpPortal αρνήθηκε την εντολή (π.χ. άγνωστο token, ανεπαρκές υπόλοιπο)."""


class RPCError(Exception):
    pass


class RPC:
    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()

    def call(self, method: str, params: list):
        r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                              timeout=15)
        data = r.json()
        if "error" in data:
            raise RPCError(f"{method}: {data['error']}")
        return data.get("result")

    def balance(self, pubkey: str) -> float:
        return self.call("getBalance", [pubkey, {"commitment": "confirmed"}])["value"] / LAMPORTS

    def send(self, raw: bytes) -> str:
        return self.call("sendTransaction", [base64.b64encode(raw).decode(),
                                             {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}])

    def status(self, sig: str) -> dict | None:
        return (self.call("getSignatureStatuses", [[sig]]) or {}).get("value", [None])[0]

    def transaction(self, sig: str) -> dict | None:
        return self.call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                                  "commitment": "confirmed"}])

    def token_accounts(self, owner: str, mint: str) -> list:
        return self.call("getTokenAccountsByOwner", [owner, {"mint": mint},
                                                     {"encoding": "jsonParsed", "commitment": "confirmed"}])["value"]

    def latest_blockhash(self) -> str:
        return self.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]


def parse_fill(tx: dict, owner: str, mint: str) -> tuple[float, float, object]:
    """(αλλαγή SOL, αλλαγή tokens, σφάλμα) του πορτοφολιού μας σε μια επιβεβαιωμένη συναλλαγή."""
    meta = tx.get("meta") or {}
    keys = list(tx["transaction"]["message"]["accountKeys"])
    loaded = meta.get("loadedAddresses") or {}
    keys += list(loaded.get("writable", [])) + list(loaded.get("readonly", []))
    keys = [k if isinstance(k, str) else k.get("pubkey", "") for k in keys]
    i = keys.index(owner) if owner in keys else 0
    sol = (meta["postBalances"][i] - meta["preBalances"][i]) / LAMPORTS

    def held(balances) -> float:
        total = 0.0
        for b in balances or []:
            if b.get("owner") == owner and b.get("mint") == mint:
                ui = b["uiTokenAmount"]
                total += int(ui["amount"]) / 10 ** int(ui["decimals"])
        return total

    return sol, held(meta.get("postTokenBalances")) - held(meta.get("preTokenBalances")), meta.get("err")


def load_keypair(secret: str):
    from solders.keypair import Keypair

    s = secret.strip()
    if s.startswith("["):                       # μορφή Solana CLI (id.json)
        return Keypair.from_bytes(bytes(json.loads(s)))
    return Keypair.from_base58_string(s)        # μορφή Phantom / Solflare


class LiveBroker:
    def __init__(self, live_cfg: dict, costs: Costs, log=print):
        self.kind = str(live_cfg.get("broker", "local")).lower()
        self.costs = costs
        self.reserve = float(live_cfg.get("min_reserve_sol", 0.03))
        self.log = log
        self.rpc = RPC(os.environ.get("RPC_URL", "").strip() or PUBLIC_RPC)
        self.api_key = os.environ.get("PUMPPORTAL_API_KEY", "").strip()
        self.kp = None
        if self.kind == "local":
            secret = os.environ.get("WALLET_PRIVATE_KEY", "").strip()
            if not secret:
                raise SystemExit("Λείπει το WALLET_PRIVATE_KEY στο αρχείο .env (ξεχωριστό πορτοφόλι μόνο για το bot).")
            try:
                self.kp = load_keypair(secret)
            except ImportError:
                raise SystemExit("Λείπει η βιβλιοθήκη solders: pip install -r requirements-live.txt")
            except Exception:
                raise SystemExit("Το WALLET_PRIVATE_KEY δεν είναι έγκυρο ιδιωτικό κλειδί Solana.")
            self.pubkey = str(self.kp.pubkey())
        elif self.kind == "lightning":
            self.pubkey = os.environ.get("PUMPPORTAL_WALLET_PUBLIC_KEY", "").strip()
            if not self.pubkey or not self.api_key:
                raise SystemExit("Για lightning χρειάζονται PUMPPORTAL_API_KEY και PUMPPORTAL_WALLET_PUBLIC_KEY στο .env.")
        else:
            raise SystemExit(f"Άγνωστο live.broker «{self.kind}»: βάλε local ή lightning.")

    # ── έλεγχοι ──
    def startup_check(self, live_cfg: dict) -> float:
        try:
            bal = self.rpc.balance(self.pubkey)
        except Exception as e:
            raise SystemExit(f"Δεν απαντά το RPC ({e.__class__.__name__}). Έλεγξε το RPC_URL στο .env.")
        cap = float(live_cfg.get("max_wallet_sol", 1.5))
        need = float(live_cfg.get("trade_sol", 0.05)) + self.reserve
        if bal > cap:
            raise SystemExit(f"Το πορτοφόλι του bot έχει {bal:.3f} SOL, πάνω από το όριο {cap} SOL (live.max_wallet_sol).\n"
                             "Για ασφάλεια το bot δουλεύει μόνο με ξεχωριστό πορτοφόλι με λίγα χρήματα. "
                             "Μετέφερε τα υπόλοιπα αλλού ή αύξησε συνειδητά το όριο.")
        if bal < need:
            raise SystemExit(f"Το πορτοφόλι έχει {bal:.4f} SOL· χρειάζονται τουλάχιστον {need:.3f} SOL.")
        return bal

    def token_balance(self, mint: str) -> float:
        total = 0.0
        for a in self.rpc.token_accounts(self.pubkey, mint):
            ui = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            total += int(ui["amount"]) / 10 ** int(ui["decimals"])
        return total

    # ── εντολές ──
    def _build_local(self, action: str, mint: str, amount, in_sol: bool, slippage: int) -> bytes:
        from solders.transaction import VersionedTransaction

        r = requests.post(f"{PORTAL}/trade-local", timeout=10, data={
            "publicKey": self.pubkey, "action": action, "mint": mint, "amount": amount,
            "denominatedInSol": "true" if in_sol else "false", "slippage": slippage,
            "priorityFee": self.costs.priority_fee_sol, "pool": "auto"})
        if r.status_code != 200:
            raise TradeRejected(f"PumpPortal {r.status_code}: {r.text[:200]}")
        tx = VersionedTransaction.from_bytes(r.content)
        return bytes(VersionedTransaction(tx.message, [self.kp]))

    def _lightning(self, action: str, mint: str, amount, in_sol: bool, slippage: int) -> str:
        r = requests.post(f"{PORTAL}/trade", params={"api-key": self.api_key}, timeout=20, json={
            "action": action, "mint": mint, "amount": amount, "denominatedInSol": "true" if in_sol else "false",
            "slippage": slippage, "priorityFee": self.costs.priority_fee_sol, "pool": "auto"})
        try:
            data = r.json()
        except ValueError:
            raise TradeRejected(f"PumpPortal {r.status_code}: {r.text[:200]}")
        if data.get("errors") or not data.get("signature"):
            raise TradeRejected(f"PumpPortal: {str(data.get('errors') or data)[:200]}")
        return data["signature"]

    def _confirm(self, sig: str, timeout: float = 45) -> tuple[bool, object]:
        end = time.time() + timeout
        while time.time() < end:
            try:
                st = self.rpc.status(sig)
            except Exception:
                st = None
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return True, st.get("err")
            time.sleep(1.5)
        return False, "timeout"

    def _fill(self, sig: str, mint: str):
        for _ in range(10):
            try:
                tx = self.rpc.transaction(sig)
            except Exception:
                tx = None
            if tx:
                return parse_fill(tx, self.pubkey, mint)
            time.sleep(1)
        return None

    def _close_account(self, mint: str) -> float:
        """Κλείνει τον άδειο λογαριασμό token και παίρνει πίσω την εγγύηση (~0,002 SOL)."""
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.message import MessageV0
        from solders.pubkey import Pubkey
        from solders.transaction import VersionedTransaction

        gained = 0.0
        me = self.kp.pubkey()
        for a in self.rpc.token_accounts(self.pubkey, mint):
            if int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) != 0:
                continue
            ix = Instruction(Pubkey.from_string(a["account"]["owner"]), bytes([9]),
                             [AccountMeta(Pubkey.from_string(a["pubkey"]), False, True),
                              AccountMeta(me, False, True), AccountMeta(me, True, False)])
            msg = MessageV0.try_compile(me, [ix], [], Hash.from_string(self.rpc.latest_blockhash()))
            sig = self.rpc.send(bytes(VersionedTransaction(msg, [self.kp])))
            landed, err = self._confirm(sig, 30)
            if landed and not err:
                fill = self._fill(sig, mint)
                gained += fill[0] if fill else self.costs.token_account_rent_sol - self.costs.base_fee_sol
        return gained

    def execute(self, o: Order) -> LiveResult:
        """Εκτελεί μία εντολή και περιμένει επιβεβαίωση. Τρέχει σε ξεχωριστό νήμα."""
        sig = ""
        try:
            if o.kind == "buy":
                if self.rpc.balance(self.pubkey) - o.amount_sol - 0.01 < self.reserve:
                    return LiveResult(False, error="ανεπαρκές υπόλοιπο SOL", exception=True)
                amount, in_sol = o.amount_sol, True
            else:
                amount, in_sol = ("100%" if o.final else f"{round(o.frac * 100)}%"), False
            slippage = int(round(o.slippage_pct))
            if self.kind == "local":
                sig = self.rpc.send(self._build_local(o.kind, o.mint, amount, in_sol, slippage))
            else:
                sig = self._lightning(o.kind, o.mint, amount, in_sol, slippage)
            landed, err = self._confirm(sig)
            if not landed:
                if o.kind == "buy":
                    held = self.token_balance(o.mint)
                    if held > 0:      # προσγειώθηκε τελικά· κόστος κατ' εκτίμηση
                        est = o.amount_sol * (1 + self.costs.portal_fee_pct / 100) + self.costs.network_fee \
                            + self.costs.token_account_rent_sol
                        return LiveResult(True, -est, held, sig, "επιβεβαίωση με καθυστέρηση")
                return LiveResult(False, signature=sig, error="δεν επιβεβαιώθηκε (το δίκτυο δεν την πήρε)")
            sol, tokens, tx_err = self._fill(sig, o.mint) or (0.0, 0.0, err)
            if err or tx_err:
                return LiveResult(False, sol, tokens, sig, f"η συναλλαγή απορρίφθηκε (συνήθως slippage): {err or tx_err}")
            if o.kind == "sell" and o.final and self.kind == "local" and self.costs.close_token_accounts:
                try:
                    sol += self._close_account(o.mint)
                except Exception as e:
                    self.log(f"Κλείσιμο λογαριασμού token απέτυχε ({e.__class__.__name__}), δεν πειράζει.")
            return LiveResult(True, sol, tokens, sig)
        except TradeRejected as e:
            return LiveResult(False, signature=sig, error=str(e))
        except Exception as e:
            return LiveResult(False, signature=sig, error=f"{e.__class__.__name__}: {str(e)[:200]}", exception=True)
