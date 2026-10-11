"""Cancel an API-key request at its total deadline, including a trickling body."""

import asyncio
from time import monotonic as deadline_now

import httpx


def bounded_post(url, *, deadline, transport=None, **kwargs):
    """Synchronous agent entry point; no worker or paid retry survives a timeout."""
    return asyncio.run(_post(url, deadline=deadline, transport=transport, **kwargs))


async def _post(url, *, deadline, transport=None, **kwargs):
    remaining = deadline - deadline_now()
    if remaining <= 0:
        raise httpx.ReadTimeout("Model request deadline exhausted")
    async with httpx.AsyncClient(transport=transport, timeout=remaining) as client:
        request = asyncio.create_task(client.post(url, **kwargs))
        try:
            while not request.done():
                left = deadline - deadline_now()
                if left <= 0:
                    raise httpx.ReadTimeout("Model request total deadline exhausted")
                await asyncio.wait([request], timeout=min(left, 0.1))
            # A suspended process can wake with both the response and timer ready.
            if deadline_now() >= deadline:
                raise httpx.ReadTimeout("Model response arrived after its deadline")
            return request.result()
        finally:
            if not request.done():
                request.cancel()
            await asyncio.gather(request, return_exceptions=True)
