"""Optional Langfuse tracing. No-op without keys or without the SDK.

Single responsibility: decide whether tracing is on and hand out decorators.
Graph nodes stay readable — one decorator each, zero behavior change when off.
Enabled-ness is evaluated per call, so long-lived processes honor key rotation.
"""
from __future__ import annotations

import functools
import os


def enabled() -> bool:
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def observe(name: str):
    """Decorator factory: Langfuse span when enabled, passthrough otherwise."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if not enabled():
                return fn(*args, **kwargs)
            try:
                from langfuse import observe as _observe
                return _observe(name=name)(fn)(*args, **kwargs)
            except Exception:
                return fn(*args, **kwargs)
        return inner
    return wrap


def score(trace_id: str, name: str, value: float, comment: str = "") -> None:
    """Attach a score to a trace. Never raises (observability can't break runs)."""
    if not enabled():
        return
    try:
        from langfuse import Langfuse
        Langfuse().score(trace_id=trace_id, name=name, value=value, comment=comment)
    except Exception:
        pass
