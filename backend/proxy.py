from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from starlette.background import BackgroundTask
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from websockets.asyncio.client import connect as ws_connect

from .security import ALLOWED_METHODS, HOP_BY_HOP_HEADERS, constant_time_equal, safe_target_url

logger = logging.getLogger("live-server.proxy")


class ReloadHub:
    """Small in-process WebSocket hub for instant browser updates."""

    def __init__(self) -> None:
        self.clients: dict[WebSocket, str] = {}
        self.lock = asyncio.Lock()

    async def add(self, ws: WebSocket, session_id: str) -> None:
        async with self.lock:
            self.clients[ws] = session_id

    async def remove(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.pop(ws, None)

    async def close_session(self, session_id: str) -> None:
        async with self.lock:
            targets = [ws for ws, sid in self.clients.items() if sid == session_id]
        for ws in targets:
            try:
                await ws.close(code=4001, reason="Session revoked")
            except Exception:
                pass
            await self.remove(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":"))
        async with self.lock:
            targets = list(self.clients)
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.remove(ws)


class ProxyController:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.hub = ReloadHub()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=3.0),
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=80, max_connections=200, keepalive_expiry=30.0),
            trust_env=False,
        )
        self._session_sockets: dict[WebSocket, str] = {}
        self._socket_lock = asyncio.Lock()
        self.app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        self._register_routes()

    def _base(self) -> str:
        return self.owner.upstream_base

    def _preview_origin(self, request: Request) -> str:
        return f"{request.url.scheme}://{request.headers.get('host', '')}"

    def _authorized(self, request: Request) -> tuple[bool, str | None, bool]:
        token = request.cookies.get("ls_token")
        query_token = request.query_params.get("ls_token")
        used_query = False
        if not constant_time_equal(token, self.owner.share_token):
            if not constant_time_equal(query_token, self.owner.share_token):
                return False, None, False
            token = query_token
            used_query = True
        session_id = request.cookies.get("ls_device_id")
        if session_id and self.owner.sessions.is_revoked(session_id):
            return False, session_id, used_query
        return True, session_id, used_query

    def _authorized_ws(self, ws: WebSocket) -> tuple[bool, str | None]:
        token = ws.cookies.get("ls_token") or ws.query_params.get("ls_token")
        if not constant_time_equal(token, self.owner.share_token):
            return False, None
        sid = ws.cookies.get("ls_device_id")
        if sid and self.owner.sessions.is_revoked(sid):
            return False, sid
        return True, sid

    async def _register_session_socket(self, ws: WebSocket, session_id: str) -> None:
        async with self._socket_lock:
            self._session_sockets[ws] = session_id

    async def _unregister_session_socket(self, ws: WebSocket) -> None:
        async with self._socket_lock:
            self._session_sockets.pop(ws, None)

    async def revoke_session(self, session_id: str) -> None:
        await self.hub.close_session(session_id)
        async with self._socket_lock:
            targets = [ws for ws, sid in self._session_sockets.items() if sid == session_id]
        for ws in targets:
            try:
                await ws.close(code=4001, reason="Session revoked")
            except Exception:
                pass
            await self._unregister_session_socket(ws)

    @staticmethod
    def _filtered_request_headers(request: Request, base: str, client_ip: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in request.headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower in {"host", "content-length", "cookie"}:
                continue
            headers[key] = value
        headers["host"] = urlsplit(base).netloc
        headers["x-forwarded-for"] = client_ip
        headers["x-forwarded-host"] = request.headers.get("host", "")
        headers["x-forwarded-proto"] = request.url.scheme
        if request.headers.get("cookie"):
            cookies = []
            for pair in request.headers["cookie"].split(";"):
                if "=" not in pair:
                    continue
                name, value = pair.strip().split("=", 1)
                if name not in {"ls_token", "ls_device_id"}:
                    cookies.append(f"{name}={value}")
            if cookies:
                headers["cookie"] = "; ".join(cookies)
        return headers

    def _register_routes(self) -> None:
        @self.app.get("/__live_server__/health")
        async def health() -> dict:
            return {"ok": True, "upstream": self._base()}

        @self.app.websocket("/__live_server__/ws")
        async def reload_socket(ws: WebSocket) -> None:
            authorized, sid = self._authorized_ws(ws)
            if not authorized:
                await ws.close(code=4403)
                return
            await ws.accept()
            ip = ws.client.host if ws.client else "unknown"
            ua = ws.headers.get("user-agent", "unknown")
            sid, _ = self.owner.sessions.touch(sid, ip, ua, str(ws.url))
            await ws.send_json({"type": "connected", "version": self.owner.version})
            await self.hub.add(ws, sid)
            await self._register_session_socket(ws, sid)
            try:
                while True:
                    try:
                        message = await asyncio.wait_for(ws.receive_text(), timeout=45)
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            data = {"type": "ping"}
                        self.owner.sessions.touch_existing(sid, ip, ua, str(ws.url))
                        if data.get("type") == "ping":
                            await ws.send_json({"type": "pong"})
                    except asyncio.TimeoutError:
                        await ws.send_json({"type": "ping"})
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            except Exception:
                logger.debug("Reload socket closed", exc_info=True)
            finally:
                await self.hub.remove(ws)
                await self._unregister_session_socket(ws)

        @self.app.websocket("/{path:path}")
        async def upstream_websocket(ws: WebSocket, path: str) -> None:
            if path.startswith("__live_server__/"):
                await ws.close(code=4403)
                return
            authorized, sid = self._authorized_ws(ws)
            if not authorized:
                await ws.close(code=4403)
                return
            await ws.accept()
            client_ip = ws.client.host if ws.client else "unknown"
            user_agent = ws.headers.get("user-agent", "unknown")
            sid, _ = self.owner.sessions.touch(sid, client_ip, user_agent, str(ws.url))
            await self._register_session_socket(ws, sid)
            query = ws.url.query
            target_path = "/" + path if path else "/"
            target_http = safe_target_url(self._base(), target_path, query)
            target = target_http.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
            headers = {}
            for key, value in ws.headers.items():
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS or lower in {"host", "cookie", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "content-length"}:
                    continue
                headers[key] = value
            headers["host"] = urlsplit(self._base()).netloc
            headers["x-forwarded-for"] = client_ip
            headers["x-forwarded-host"] = ws.headers.get("host", "")
            try:
                protocols = ws.headers.get("sec-websocket-protocol")
                async with ws_connect(
                    target,
                    additional_headers=headers,
                    subprotocols=[item.strip() for item in protocols.split(",") if item.strip()] if protocols else None,
                    proxy=None,
                    open_timeout=8,
                    ping_interval=20,
                    ping_timeout=20,
                ) as upstream_ws:
                    async def client_to_upstream() -> None:
                        while True:
                            message = await ws.receive()
                            if message.get("type") == "websocket.disconnect":
                                break
                            if message.get("type") == "websocket.receive":
                                if message.get("text") is not None:
                                    await upstream_ws.send(message["text"])
                                elif message.get("bytes") is not None:
                                    await upstream_ws.send(message["bytes"])

                    async def upstream_to_client() -> None:
                        async for message in upstream_ws:
                            if isinstance(message, bytes):
                                await ws.send_bytes(message)
                            else:
                                await ws.send_text(message)

                    await asyncio.gather(client_to_upstream(), upstream_to_client(), return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.owner.log_warning("WebSocket proxy closed: %s", exc)
                try:
                    await ws.close(code=1011)
                except Exception:
                    pass
            finally:
                await self._unregister_session_socket(ws)

        @self.app.api_route("/{path:path}", methods=sorted(ALLOWED_METHODS))
        async def proxy(request: Request, path: str) -> Response:
            authorized, sid, used_query = self._authorized(request)
            if not authorized:
                return JSONResponse({"error": "Preview authorization required"}, status_code=403)

            if used_query:
                params = [(k, v) for k, v in request.query_params.multi_items() if k != "ls_token"]
                parsed = urlsplit(str(request.url))
                clean_query = urlencode(params, doseq=True)
                clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", clean_query, parsed.fragment))
                response = RedirectResponse(clean_url, status_code=307)
                response.set_cookie("ls_token", self.owner.share_token, httponly=True, samesite="lax", max_age=86400)
                if sid is None:
                    sid, _ = self.owner.sessions.touch(None, request.client.host if request.client else "unknown", request.headers.get("user-agent", "unknown"), clean_url)
                    response.set_cookie("ls_device_id", sid, httponly=True, samesite="lax", max_age=86400)
                return response

            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            sid, _ = self.owner.sessions.touch(sid, client_ip, user_agent, str(request.url))
            if path.startswith("__live_server__/"):
                return JSONResponse({"error": "Reserved path"}, status_code=404)

            query_items = [(key, value) for key, value in request.query_params.multi_items() if key != "ls_token"]
            query = urlencode(query_items, doseq=True)
            target = safe_target_url(self._base(), "/" + path if path else "/", query)
            headers = self._filtered_request_headers(request, self._base(), client_ip)

            # The rewrite layer needs uncompressed text; binary assets can stay compressed.
            is_document_request = path == "" or path.endswith(("/", ".html", ".htm"))
            if is_document_request:
                headers["accept-encoding"] = "identity"

            try:
                body = await request.body() if request.method not in {"GET", "HEAD"} else None
                upstream_request = self.client.build_request(request.method, target, content=body, headers=headers)
                upstream = await self.client.send(upstream_request, stream=True)
            except httpx.TimeoutException:
                self.owner.log_warning("Upstream timeout: %s", target)
                return JSONResponse({"error": "Upstream connection timed out", "target": self._base()}, status_code=504)
            except httpx.HTTPError as exc:
                self.owner.log_error("Proxy failure: %s", exc)
                return JSONResponse({"error": "Upstream proxy connection failed"}, status_code=502)

            content_type = upstream.headers.get("content-type", "").lower()
            needs_rewrite = (
                request.method != "HEAD"
                and upstream.status_code not in {204, 304}
                and ("text/html" in content_type or "text/css" in content_type or "javascript" in content_type or "application/json" in content_type or "application/xml" in content_type or "text/xml" in content_type)
            )

            if needs_rewrite:
                try:
                    content = await upstream.aread()
                finally:
                    await upstream.aclose()
                content = self._rewrite_text(content, content_type, request)
                response_headers = self._response_headers(upstream.headers, request)
                response = Response(content=content, status_code=upstream.status_code, headers=response_headers, media_type=None)
            else:
                response_headers = self._response_headers(upstream.headers, request)
                response = StreamingResponse(
                    upstream.aiter_raw(),
                    status_code=upstream.status_code,
                    headers=response_headers,
                    media_type=None,
                    background=BackgroundTask(upstream.aclose),
                )

            response.set_cookie("ls_device_id", sid, httponly=True, samesite="lax", max_age=86400)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            return response

    def _response_headers(self, upstream_headers: httpx.Headers, request: Request) -> dict[str, str]:
        response_headers: dict[str, str] = {}
        for key, value in upstream_headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower in {"content-length", "content-encoding"}:
                continue
            if lower == "location":
                value = self._rewrite_location(value, request)
            response_headers[key] = value
        content_type = upstream_headers.get("content-type", "").lower()
        if "text/html" in content_type:
            response_headers["cache-control"] = "no-store"
        elif "text/css" in content_type or "javascript" in content_type:
            response_headers["cache-control"] = "no-cache"
        return response_headers

    def _rewrite_location(self, location: str, request: Request) -> str:
        parsed = urlsplit(location)
        upstream = urlsplit(self._base())
        if parsed.scheme in {"http", "https"} and parsed.hostname == upstream.hostname and parsed.port == upstream.port:
            return urlunsplit((request.url.scheme, request.headers.get("host", ""), parsed.path or "/", parsed.query, parsed.fragment))
        return location

    def _rewrite_text(self, content: bytes, content_type: str, request: Request) -> bytes:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return content
        upstream_origin = self._base().rstrip("/")
        public_origin = self._preview_origin(request).rstrip("/")
        text = text.replace(upstream_origin, public_origin)
        if "text/html" in content_type:
            text = self._inject_reload_bridge(text)
        return text.encode("utf-8")

    def _inject_reload_bridge(self, html: str) -> str:
        markers = ("__live_server__", "livereload", "LiveReload", "live-server", "socket = new WebSocket")
        if any(marker in html for marker in markers):
            return html
        script = r'''<script data-live-server-fallback>
(() => {
  let socket;
  let retry = 0;
  let reconnectTimer;
  let closedByServer = false;
  const connect = () => {
    clearTimeout(reconnectTimer);
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(`${proto}://${location.host}/__live_server__/ws`);
    socket.addEventListener('open', () => { retry = 0; socket.send(JSON.stringify({type:'hello'})); });
    socket.addEventListener('message', (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'ping') { socket.send(JSON.stringify({type:'ping'})); return; }
        if (msg.type === 'css') {
          document.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
            const url = new URL(link.href, location.href);
            url.searchParams.set('__ls', String(Date.now()));
            link.href = url.href;
          });
          return;
        }
        if (msg.type === 'reload') {
          if (!closedByServer) location.reload();
          return;
        }
        if (msg.type === 'shutdown' || msg.type === 'revoked') closedByServer = true;
      } catch (_) {}
    });
    socket.addEventListener('close', () => {
      if (closedByServer) return;
      retry = Math.min(retry + 1, 6);
      reconnectTimer = setTimeout(connect, Math.min(1000 * retry, 5000));
    });
  };
  connect();
})();
</script>'''
        if re.search(r"</body\s*>", html, flags=re.I):
            return re.sub(r"</body\s*>", script + "</body>", html, count=1, flags=re.I)
        return html + script

    async def changed(self, path: str, kind: str) -> None:
        payload = {"type": "css" if kind == "css" else "reload", "path": path}
        await self.hub.broadcast(payload)
        await self.owner.notify_dashboard()

    async def close(self) -> None:
        await self.hub.broadcast({"type": "shutdown"})
        await self.client.aclose()
