"""Lets the plain tests call the async handler as a function; real concurrency is tested in test_concurrency.py."""
import asyncio

from app.handler import handle as _handle


def handle(*args, **kwargs) -> str:
    return asyncio.run(_handle(*args, **kwargs))
