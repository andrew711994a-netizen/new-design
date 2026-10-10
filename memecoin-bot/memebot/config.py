"""Ρυθμίσεις: config.json, προαιρετικά config.local.json από πάνω, και μυστικά από το .env."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "journal"


def load_env(path: Path = ROOT / ".env") -> None:
    """Διαβάζει γραμμές ΚΛΕΙΔΙ=τιμή. Ό,τι έχει ήδη οριστεί στο περιβάλλον έχει προτεραιότητα."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path | None = None) -> dict:
    cfg = json.loads((path or ROOT / "config.json").read_text(encoding="utf-8"))
    local = ROOT / "config.local.json"
    if path is None and local.exists():
        cfg = deep_merge(cfg, json.loads(local.read_text(encoding="utf-8")))
    mode = os.environ.get("MEMEBOT_MODE", "").strip().lower()
    if mode:
        cfg["mode"] = mode
    if cfg.get("mode") not in ("paper", "live"):
        raise SystemExit(f"Άγνωστη λειτουργία «{cfg.get('mode')}»: βάλε paper ή live.")
    return cfg
