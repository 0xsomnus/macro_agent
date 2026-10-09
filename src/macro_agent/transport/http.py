"""One bounded HTTP exchange using established HTTP, TLS and asynchronous DNS.

Callers own the endpoint allowlist and error/accounting policy. This synchronous
bridge is for synchronous services only. No detached HTTP work or default
executor DNS lookup can outlive its return. Each exchange owns and closes its
session, connector and explicit asynchronous resolver; connection pooling is a
separate runtime decision.
"""

import asyncio
from email.message import Message
import io
import math
import re
import urllib.error

import aiohttp


class TransportError(RuntimeError):
    """Safe category and response headers only, never remote exception text/body."""

    def __init__(self, code, *, headers=None):
        self.code = code
        self.headers = headers if headers is not None else Message()
        super().__init__(f"HTTP exchange failed ({code}).")


class _Response(io.BytesIO):
    def __init__(self, body, *, url, status, headers):
        super().__init__(body)
        self.url, self.status, self.headers = url, status, headers

    def geturl(self):
        return self.url


async def _exchange(request, *, timeout, limit):
    headers = Message()
    # Supplying AsyncResolver explicitly prevents ThreadedResolver fallback.
    # Closing a caller-supplied resolver is the caller's responsibility.
    resolver = aiohttp.AsyncResolver()
    try:
        connector = aiohttp.TCPConnector(
            resolver=resolver, limit=1, limit_per_host=1, force_close=True,
            timeout_ceil_threshold=math.inf,
        )
        attempts = 0

        async def one_exchange(req, handler):
            nonlocal attempts
            # aiohttp may internally retry an idempotent GET after disconnect.
            # Public middleware runs on each attempt, before connect/send.
            if attempts:
                raise TransportError("unavailable", headers=headers)
            attempts += 1
            return await handler(req)

        async with aiohttp.ClientSession(
            connector=connector, trust_env=False, auto_decompress=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            timeout=aiohttp.ClientTimeout(total=timeout, ceil_threshold=math.inf),
            middlewares=(one_exchange,),
        ) as session:
            async with session.request(
                request.get_method(), request.full_url, data=request.data,
                headers=dict(request.header_items()), allow_redirects=False, ssl=True,
            ) as response:
                for name, value in response.headers.items():
                    headers[name] = value
                if response.status != 200:
                    # Deliberately do not consume, retain or expose error bodies.
                    response.close()
                    if 200 <= response.status < 300:
                        raise TransportError("invalid_response", headers=headers)
                    raise urllib.error.HTTPError(
                        request.full_url, response.status, "HTTP status rejected", headers, None,
                    )
                if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                    raise TransportError("invalid_response", headers=headers)
                length = response.headers.get("Content-Length")
                if length is not None:
                    if not re.fullmatch(r"[0-9]{1,20}", length):
                        raise TransportError("invalid_response", headers=headers)
                    if int(length) > limit:
                        raise TransportError("byte_limit", headers=headers)
                raw = bytearray()
                while True:
                    # Reads may return fewer bytes than requested. Continue to
                    # EOF under the same total deadline, retaining at most N+1.
                    chunk = await response.content.read(min(65_536, limit + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise TransportError("byte_limit", headers=headers)
                if length is not None and len(raw) != int(length):
                    raise TransportError("incomplete_response", headers=headers)
                return _Response(bytes(raw), url=str(response.url), status=response.status, headers=headers)
    except urllib.error.HTTPError:
        raise
    except TimeoutError:
        raise TransportError("timeout", headers=headers) from None
    except aiohttp.ClientPayloadError:
        raise TransportError("incomplete_response", headers=headers) from None
    except (aiohttp.ClientError, OSError):
        raise TransportError("unavailable", headers=headers) from None
    finally:
        await resolver.close()


class BoundedOpener:
    """Small injectable compatibility boundary around a complete bounded read."""

    def open(self, request, *, timeout, limit):
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
                or type(limit) is not int or limit < 1):
            raise ValueError("invalid HTTP exchange bounds")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("synchronous HTTP exchange requires a synchronous caller")
        return asyncio.run(_exchange(request, timeout=timeout, limit=limit))
