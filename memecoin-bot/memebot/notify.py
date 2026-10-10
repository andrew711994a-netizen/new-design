"""Ειδοποιήσεις στο κινητό μέσω ntfy.sh (η ίδια δωρεάν εφαρμογή «ntfy» με το bot των μετοχών)."""

from __future__ import annotations

import os

import requests


def notify(title: str, body: str, priority: int = 3) -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        requests.post("https://ntfy.sh/", json={"topic": topic, "title": title, "message": body,
                                                "priority": priority, "tags": ["frog"]}, timeout=10)
    except Exception as e:  # η ειδοποίηση δεν πρέπει ποτέ να σταματήσει το bot
        print(f"Η ειδοποίηση απέτυχε: {e}")
