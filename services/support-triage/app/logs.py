"""Structured log lines (JSON, one per event). Never pass request or ticket text in here."""
import json
import sys
import time


def log(event: str, **fields) -> None:
    print(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}), file=sys.stdout, flush=True)
