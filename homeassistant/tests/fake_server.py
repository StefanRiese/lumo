"""A fake Lumo server (aiohttp) with invented data, for the tests of the client and coordinator."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

PASSWORD = "demo"

ACCOUNT_INFO = {
    "schoolId": 6128,
    "username": "max.muster",
    "accountType": "student",
    "features": ["timetable", "substitutions", "calendar", "lessons"],
}


class FakeLumo:
    """In-memory server. `data[key]` is the `data` field of the data endpoint `key`."""

    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.accounts = [
            {
                "id": "k3x9ab",
                "name": "Max",
                "schoolId": 6128,
                "username": "max.muster",
                "caseda": None,
                "untis": None,
            },
            {
                "id": "p7q2mz",
                "name": "Anna",
                "schoolId": 6128,
                "username": "anna.muster",
                "caseda": None,
                "untis": None,
            },
        ]
        self.data: dict[str, Any] = {
            "account": ACCOUNT_INFO,
            "timetable": {"currentWeek": None, "slots": [], "lessons": []},
            "substitutions": [{"date": "2026-11-10", "entries": [], "notices": []}],
            "calendar": [],
            "homework": [],
            "grades": [],
        }
        self.status: dict[str, Any] = {
            "checkedAt": "2026-11-10T10:00:00Z",
            "accounts": [
                {
                    "id": "k3x9ab",
                    "name": "Max",
                    "services": [
                        {
                            "key": "schulportal",
                            "name": "Schulportal",
                            "state": "ok",
                            "detail": "Verbunden",
                            "lastSuccess": "2026-11-10T09:55:00Z",
                            "failures": 0,
                        },
                    ],
                },
                {
                    "id": "p7q2mz",
                    "name": "Anna",
                    "services": [
                        {
                            "key": "schulportal",
                            "name": "Schulportal",
                            "state": "warn",
                            "detail": "wird erneut versucht",
                            "lastSuccess": None,
                            "failures": 1,
                        },
                    ],
                },
            ],
            "services": [
                {
                    "key": "updates",
                    "name": "Update-Server (GitHub)",
                    "state": "ok",
                    "detail": "Verbunden",
                    "lastSuccess": None,
                    "failures": 0,
                },
            ],
        }
        self.update: dict[str, Any] = {
            "current": "v0.25.6",
            "latest": "v0.26.0",
            "available": True,
            "url": "https://github.com/StefanRiese/lumo/releases/tag/v0.26.0",
        }
        self.calendar_queries: list[dict[str, str]] = []
        self.requests: list[tuple[str, str]] = []  # (method, path) of the data requests
        self.logins = 0
        self.events: asyncio.Queue[str | None] = asyncio.Queue()
        self.event_streams = 0
        self.fail_paths: dict[str, int] = {}  # path suffix -> status code
        self.homework_puts: list[tuple[str, str, bool]] = []
        self.stale = False
        self.server: TestServer | None = None

    # --- helpers --------------------------------------------------------------------

    @staticmethod
    def _error(status: int, code: str, **headers: str) -> web.Response:
        return web.json_response(
            {"error": {"code": code, "message": code}}, status=status, headers=headers
        )

    def _authed(self, request: web.Request) -> bool:
        return request.cookies.get("sph_session") in self.sessions

    def expire_sessions(self) -> None:
        self.sessions.clear()

    def push(self, event: str, data: dict[str, Any]) -> None:
        self.events.put_nowait(f"event: {event}\ndata: {json.dumps(data)}\n\n")

    def close_streams(self) -> None:
        self.events.put_nowait(None)

    # --- handlers -------------------------------------------------------------------

    async def login(self, request: web.Request) -> web.Response:
        body = await request.json()
        if body.get("password") != PASSWORD:
            return self._error(401, "invalid_password")
        self.logins += 1
        token = f"tok{self.logins}"
        self.sessions.add(token)
        resp = web.json_response({"authenticated": True})
        resp.set_cookie("sph_session", token, path="/")
        return resp

    async def healthz(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "app": "lumo"})

    async def list_accounts(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return self._error(401, "unauthorized")
        return web.json_response({"accounts": self.accounts})

    async def server_endpoint(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return self._error(401, "unauthorized")
        body = self.status if request.path == "/api/status" else self.update
        if request.path in self.fail_paths:
            return self._error(self.fail_paths[request.path], "sph_unavailable")
        return web.json_response(body)

    async def account_endpoint(self, request: web.Request) -> web.StreamResponse:
        if not self._authed(request):
            return self._error(401, "unauthorized")
        account_id = request.match_info["account"]
        if account_id not in {a["id"] for a in self.accounts}:
            return self._error(404, "unknown_account")
        path = request.match_info["path"]
        for suffix, status in self.fail_paths.items():
            if path == suffix:
                return self._error(status, "sph_unavailable")
        if path == "events":
            return await self._stream(request)
        if request.method == "POST" and path == "refresh":
            self.requests.append(("POST", path))
            return web.json_response({"refreshing": True}, status=202)
        if request.method == "PUT" and path.startswith("courses/"):
            _, course, _, entry, _ = path.split("/")
            body = await request.json()
            self.homework_puts.append((course, entry, body["done"]))
            return web.json_response({"done": body["done"]})
        self.requests.append((request.method, path))
        if path == "calendar" and request.query:
            self.calendar_queries.append(dict(request.query))
        if path not in self.data:
            return self._error(404, "feature_disabled")
        return web.json_response(
            {
                "data": self.data[path],
                "key": path,
                "fetchedAt": "2026-11-10T10:00:00.000Z",
                "cached": True,
                "stale": self.stale,
                "refreshing": False,
            }
        )

    async def _stream(self, request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"content-type": "text/event-stream; charset=utf-8"})
        await resp.prepare(request)
        self.event_streams += 1
        await resp.write(b'retry: 5000\n\nevent: sync\ndata: {"running": false}\n\n')
        try:
            while True:
                item = await self.events.get()
                if item is None:
                    break
                await resp.write(item.encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    # --- lifecycle ------------------------------------------------------------------

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/auth/login", self.login)
        app.router.add_get("/healthz", self.healthz)
        app.router.add_get("/api/accounts", self.list_accounts)
        app.router.add_get("/api/status", self.server_endpoint)
        app.router.add_get("/api/update", self.server_endpoint)
        app.router.add_route("*", "/api/accounts/{account}/{path:.+}", self.account_endpoint)
        return app

    async def start(self) -> str:
        self.server = TestServer(self.app())
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def stop(self) -> None:
        self.close_streams()
        if self.server is not None:
            await self.server.close()
