"""Actual loopback HTTP deadlines and cancellation, with no external calls."""

import asyncio
from collections import Counter
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import socketserver
import sys
import threading
from time import monotonic, sleep
import unittest
from unittest.mock import patch
import weakref
import urllib.error
import urllib.request

import aiodns

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from macro_agent.monitoring import sources
from macro_agent.providers import NanoGPT, ProviderError
from macro_agent.transport import http


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.do_GET()

    def do_GET(self):
        self.server.requests[(self.command, self.path)] += 1
        try:
            if self.path == "/disconnect":
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if self.path == "/slow-headers":
                # Bytes continue arriving faster than an inactivity timeout.
                for part in (b"HTTP/1.1 200 OK\r\n", b"X-Request-ID: fictional-request\r\n",
                             b"Content-Length: 2\r\n", b"Connection: close\r\n\r\n{}"):
                    for byte in part:
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                        sleep(0.015)
                return
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/sink")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/error":
                self.send_response(503)
                self.send_header("Content-Length", "1000000")
                self.end_headers()
                self.wfile.write(b"private provider error")
                self.wfile.flush()
                sleep(0.4)
                return
            self.send_response(200)
            self.send_header("X-Request-ID", "fictional-request")
            self.send_header("Connection", "close")
            self.close_connection = True
            if self.path == "/slow-body":
                self.send_header("Content-Length", "64")
                self.end_headers()
                for _ in range(64):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    sleep(0.03)
            elif self.path == "/overflow-length":
                self.send_header("Content-Length", "1000")
                self.end_headers()
                sleep(0.4)
            elif self.path == "/overflow-body":
                self.end_headers()
                self.wfile.write(b"x" * 1000)
            elif self.path == "/fragmented":
                self.send_header("Content-Length", "7")
                self.end_headers()
                for part in (b'{"', b'a":', b'1}'):
                    self.wfile.write(part)
                    self.wfile.flush()
                    sleep(0.02)
            elif self.path == "/rss":
                raw = b'<rss version="2.0"><channel/></rss>'
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class HTTPTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.requests = Counter()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, *, method="GET", timeout=0.25, limit=1024):
        request = urllib.request.Request(self.base + path,
            data=b"{}" if method == "POST" else None, method=method,
            headers={"Accept-Encoding": "identity"})
        return http.BoundedOpener().open(request, timeout=timeout, limit=limit)

    def test_total_deadline_stops_trickled_headers_and_body_for_get_and_post(self):
        for path in ("/slow-headers", "/slow-body"):
            for method in ("GET", "POST"):
                with self.subTest(path=path, method=method):
                    before = self.server.requests[(method, path)]
                    started = monotonic()
                    with self.assertRaises(http.TransportError) as raised:
                        self.request(path, method=method)
                    self.assertEqual(raised.exception.code, "timeout")
                    self.assertLess(monotonic() - started, 0.8)
                    self.assertEqual(self.server.requests[(method, path)], before + 1)

    def test_disconnect_makes_one_exchange_even_for_an_idempotent_get(self):
        for method in ("GET", "POST"):
            with self.subTest(method=method):
                before = self.server.requests[(method, "/disconnect")]
                with self.assertRaises(http.TransportError) as raised:
                    self.request("/disconnect", method=method)
                self.assertEqual(raised.exception.code, "unavailable")
                self.assertEqual(self.server.requests[(method, "/disconnect")], before + 1)

    def test_oversize_length_and_unknown_length_stream_are_bounded(self):
        for path in ("/overflow-length", "/overflow-body"):
            with self.subTest(path=path), self.assertRaises(http.TransportError) as raised:
                self.request(path, limit=16)
            self.assertEqual(raised.exception.code, "byte_limit")

    def test_fragmented_body_is_read_to_eof_and_response_closes(self):
        with self.request("/fragmented") as response:
            self.assertEqual(response.read(1025), b'{"a":1}')
            self.assertEqual(response.headers.get("x-request-id"), "fictional-request")
        self.assertTrue(response.closed)

    def test_redirect_and_environment_proxy_do_not_change_destination(self):
        before = self.server.requests[("GET", "/sink")]
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/redirect")
        self.assertEqual(raised.exception.code, 302)
        self.assertEqual(raised.exception.read(), b"")
        raised.exception.close()
        self.assertEqual(self.server.requests[("GET", "/sink")], before)
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            with self.request("/ok") as response:
                self.assertEqual(response.read(10), b"{}")

    def test_http_error_returns_without_consuming_remote_body(self):
        started = monotonic()
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/error")
        self.assertEqual(raised.exception.code, 503)
        self.assertEqual(raised.exception.read(), b"")
        raised.exception.close()
        self.assertNotIn("private", str(raised.exception))
        self.assertLess(monotonic() - started, 0.25)

    def test_provider_preserves_unknown_post_and_response_identity_on_timeout(self):
        provider = NanoGPT("test-only-not-real")
        for path in ("/slow-body", "/disconnect"):
            with self.subTest(path=path), self.assertRaises(ProviderError) as raised:
                provider._request(self.base + path, body=b"{}", limit=1024, timeout_seconds=0.25)
            self.assertEqual(raised.exception.code, "outcome_unknown")
            if path == "/slow-body":
                self.assertEqual(raised.exception.metadata["provider_request_id"], "fictional-request")

    def test_source_applies_elapsed_deadline_and_accepts_complete_response(self):
        for path in ("/slow-headers", "/slow-body", "/rss"):
            spec = replace(sources.source_specs["fed-press"], url=self.base + path, timeout_seconds=0.25)
            with self.subTest(path=path), patch.object(sources, "source_specs", {"fed-press": spec}):
                if path == "/rss":
                    self.assertEqual(sources.fetch_source("fed-press").items, ())
                else:
                    started = monotonic()
                    with self.assertRaises(sources.SourceError) as raised:
                        sources.fetch_source("fed-press")
                    self.assertEqual(raised.exception.code, "transport_error")
                    self.assertLess(monotonic() - started, 0.8)


class DNSCancellationTests(unittest.TestCase):
    def test_real_async_dns_timeout_releases_resolvers_without_executor_threads(self):
        packets, references = [], []

        class Sink(socketserver.BaseRequestHandler):
            def handle(self):
                packets.append(self.request[0])

        server = socketserver.UDPServer(("127.0.0.1", 0), Sink)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
        thread.start()
        original_async, original_dns = http.aiohttp.AsyncResolver, aiodns.DNSResolver

        def async_resolver():
            return original_async(nameservers=["127.0.0.1"], udp_port=server.server_address[1])

        def dns_resolver(*args, **kwargs):
            resolver = original_dns(*args, **kwargs)
            references.append(weakref.ref(resolver))
            return resolver

        try:
            with patch.object(http.aiohttp, "AsyncResolver", async_resolver), \
                    patch.object(aiodns, "DNSResolver", dns_resolver), \
                    patch.object(asyncio.BaseEventLoop, "run_in_executor",
                        side_effect=AssertionError("DNS must not use executor threads")):
                for _ in range(3):
                    started = monotonic()
                    with self.assertRaises(http.TransportError) as raised:
                        http.BoundedOpener().open(
                            urllib.request.Request("http://fictional-stalled-dns.test/"),
                            timeout=0.15, limit=16)
                    self.assertEqual(raised.exception.code, "timeout")
                    self.assertLess(monotonic() - started, 0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertGreater(len(packets), 0)
        self.assertEqual(len(references), 3)
        self.assertTrue(all(reference() is None for reference in references))

    def test_repeated_dns_timeouts_close_resolver_and_cancel_tasks_without_executor(self):
        resolvers = []

        class StalledResolver:
            def __init__(self):
                self.started = self.cancelled = self.closed = False
                self.task = None
                resolvers.append(self)

            async def resolve(self, host, port=0, family=socket.AF_INET):
                self.started, self.task = True, asyncio.current_task()
                try:
                    await asyncio.Future()
                finally:
                    self.cancelled = True

            async def close(self):
                self.closed = True

        request = urllib.request.Request("http://fictional-dns-stall.invalid/")
        with patch.object(http.aiohttp, "AsyncResolver", StalledResolver), \
                patch.object(asyncio.BaseEventLoop, "run_in_executor",
                    side_effect=AssertionError("DNS must not use the default executor")):
            for _ in range(5):
                started = monotonic()
                with self.assertRaises(http.TransportError) as raised:
                    http.BoundedOpener().open(request, timeout=0.03, limit=16)
                self.assertEqual(raised.exception.code, "timeout")
                self.assertLess(monotonic() - started, 0.3)
        self.assertEqual(len(resolvers), 5)
        self.assertTrue(all(row.started and row.cancelled and row.closed and row.task.done()
            for row in resolvers))

    def test_running_event_loop_is_rejected_without_detached_transport(self):
        async def active():
            with patch.object(http, "_exchange") as exchange:
                with self.assertRaisesRegex(RuntimeError, "synchronous caller"):
                    http.BoundedOpener().open(urllib.request.Request("http://127.0.0.1/"),
                        timeout=1, limit=16)
                exchange.assert_not_called()

        asyncio.run(active())


if __name__ == "__main__":
    unittest.main()
