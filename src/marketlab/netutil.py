"""Neutral HTTP helpers shared by the broker adapter, exchange collectors and the research provider.

Kept separate so that components facing a language model never need to import the broker module.
"""
from __future__ import annotations

import time
from urllib.request import HTTPRedirectHandler

READ_DEADLINE = 90.0  # seconds for one complete response, however slowly it trickles in
CHUNK = 64 * 1024


class ResponseLimit(RuntimeError):
    """A response exceeded its size limit or read deadline."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ResponseLimit("Unexpected provider redirect refused")


def read_bounded(response, limit: int, deadline: float = READ_DEADLINE, clock=time.monotonic) -> bytes:
    """Read a whole response under a size limit and a total deadline (socket timeouts are per read)."""
    stop, parts, size = clock() + deadline, [], 0
    while True:
        if clock() > stop:
            raise ResponseLimit("Response exceeded the read deadline; no automatic retry")
        part = response.read(CHUNK)
        if not part:
            return b"".join(parts)
        size += len(part)
        if size > limit:
            raise ResponseLimit("Provider response exceeded the configured limit")
        parts.append(part)
