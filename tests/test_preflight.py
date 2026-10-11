from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.config import ConfigError, ZoteroConfig, load_config
from hydrolitagent.cards.zotero import ZoteroClient, preflight

class StubHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, object, dict[str, str]]] = {}

    def do_GET(self) -> None:
        status, payload, headers = self.routes.get(
            self.path,
            (404, {"error": "not found"}, {}),
        )
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return

class ZoteroServer:
    def __init__(self, routes: dict[str, tuple[int, object, dict[str, str]]]):
        handler = type("ConfiguredStubHandler", (StubHandler,), {"routes": routes})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "ZoteroServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

class PreflightTests(unittest.TestCase):
    def test_successfully_reads_target_group(self) -> None:
        routes = {
            "/api/": (200, {"version": "7"}, {}),
            "/api/users/0/groups": (
                200,
                [{"id": 42, "data": {"id": 42, "name": "水利科研"}}],
                {},
            ),
            "/api/groups/42/items/top?limit=1": (200, [], {"Total-Results": "18"}),
        }
        with ZoteroServer(routes) as server:
            config = ZoteroConfig(base_url=server.base_url, group_id=42, timeout_seconds=1)
            result = preflight(
                config,
                client=ZoteroClient(config),
                process_checker=lambda: True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["group_name"], "水利科研")
        self.assertEqual(result["item_count"], 18)

    def test_reports_target_group_missing(self) -> None:
        routes = {
            "/api/": (200, {}, {}),
            "/api/users/0/groups": (
                200,
                [{"id": 7, "data": {"id": 7, "name": "其他群组"}}],
                {},
            ),
        }
        with ZoteroServer(routes) as server:
            config = ZoteroConfig(base_url=server.base_url, group_id=42, timeout_seconds=1)
            result = preflight(
                config,
                client=ZoteroClient(config),
                process_checker=lambda: True,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "GROUP_NOT_AVAILABLE")

    def test_reports_zotero_not_running_without_http_call(self) -> None:
        config = ZoteroConfig(group_id=42)
        result = preflight(config, process_checker=lambda: False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "ZOTERO_NOT_RUNNING")

    def test_reports_permission_denied(self) -> None:
        routes = {
            "/api/": (200, {}, {}),
            "/api/users/0/groups": (
                200,
                [{"id": 42, "data": {"id": 42, "name": "水利科研"}}],
                {},
            ),
            "/api/groups/42/items/top?limit=1": (403, {"error": "forbidden"}, {}),
        }
        with ZoteroServer(routes) as server:
            config = ZoteroConfig(base_url=server.base_url, group_id=42, timeout_seconds=1)
            result = preflight(
                config,
                client=ZoteroClient(config),
                process_checker=lambda: True,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "GROUP_PERMISSION_DENIED")

    def test_rejects_unconfigured_example_group_id(self) -> None:
        config_path = ASSETS_DIR / "config" / "config.example.json"
        with self.assertRaises(ConfigError):
            load_config(config_path)

if __name__ == "__main__":
    unittest.main()
