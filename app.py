from __future__ import annotations

from launcher import ensure_runtime_dependencies

# Direct `python app.py` launches are self-healing: missing dependencies are
# installed into the project .venv and the app restarts inside that environment.
ensure_runtime_dependencies(direct_invocation=__name__ == "__main__")

import asyncio
import base64
import io
import json
import logging
import os
import signal
import socket
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import qrcode
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.diagnostics import RingLogHandler, configure_logging
from backend.file_watcher import FileWatcher
from backend.integrity import verify_integrity
from backend.network import choose_default_interface, detect_ipv4_interfaces, local_hostname
from backend.proxy import ProxyController
from backend.security import ALLOWED_METHODS, new_token, validate_loopback_target
from backend.sessions import SessionManager
from config import APP_DEVELOPER, APP_NAME, APP_ORGANIZATION, APP_VERSION, ConfigStore, Settings, settings_from_dict

logger = logging.getLogger("live-server")
BASE_DIR = Path(__file__).resolve().parent


class InstanceLock:
    """Small cross-platform single-instance lock using an atomic PID file."""

    def __init__(self) -> None:
        self.handle_fd: int | None = None
        self.path = Path.home() / ".cache" / "live-server.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pid_running(pid: int) -> bool:
        """Return whether *pid* appears to belong to a running process.

        Lock files can become stale or corrupted after an abrupt shutdown.
        In particular, a corrupted PID may be larger than the platform's
        native pid_t range, which makes os.kill() raise OverflowError. Treat
        such values as stale instead of crashing the whole application.
        """
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, OverflowError, ValueError):
            return False
        except PermissionError:
            # The process exists but we are not allowed to signal it.
            return True
        except OSError:
            # ESRCH and other platform-specific lookup failures mean the
            # recorded process is not safely considered active.
            return False
        return True

    def acquire(self) -> None:
        payload = f"{os.getpid()}\n".encode("ascii")
        for attempt in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, payload)
                os.fsync(fd)
                self.handle_fd = fd
                return
            except FileExistsError:
                try:
                    raw = self.path.read_text(encoding="ascii").strip()
                    pid = int(raw)
                except (OSError, ValueError):
                    pid = 0
                if pid and self._pid_running(pid):
                    raise RuntimeError("Another Live Server instance is already running")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                if attempt == 0:
                    continue
                raise RuntimeError("Could not recover the Live Server instance lock")

    def release(self) -> None:
        if self.handle_fd is not None:
            try:
                os.close(self.handle_fd)
            except OSError:
                pass
            self.handle_fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


class LiveServerApp:
    def __init__(self) -> None:
        self.version = APP_VERSION
        self.store = ConfigStore()
        self.settings = self.store.load()
        if not self.settings.interface_ip:
            self.settings.interface_ip = choose_default_interface()
        self.logs: RingLogHandler = configure_logging()
        self.started_at = time.monotonic()
        self.sharing_started_at: float | None = None
        self.sessions = SessionManager()
        self.share_token: str | None = None
        self.dashboard_csrf = new_token(24)
        self.dashboard_clients: set = set()
        self.dashboard_server: uvicorn.Server | None = None
        self.proxy_server: uvicorn.Server | None = None
        self.dashboard_task: asyncio.Task | None = None
        self.proxy_task: asyncio.Task | None = None
        self.proxy_controller: ProxyController | None = None
        self.watcher: FileWatcher | None = None
        self.stop_event = asyncio.Event()
        self.lock = InstanceLock()
        self.dashboard_app = self._build_dashboard_app()

    @property
    def upstream_base(self) -> str:
        scheme = "https" if self.settings.upstream_port == 443 else "http"
        return f"{scheme}://{self.settings.upstream_host}:{self.settings.upstream_port}"

    @property
    def preview_url(self) -> str | None:
        if not self.share_token or not self.settings.interface_ip:
            return None
        return f"http://{self.settings.interface_ip}:{self.settings.share_port}/?ls_token={self.share_token}"

    def log_warning(self, message: str, *args) -> None:
        logger.warning(message, *args)

    def log_error(self, message: str, *args) -> None:
        logger.error(message, *args)

    def _csrf_required(self, request: Request) -> None:
        header = request.headers.get("x-live-server-csrf")
        if header != self.dashboard_csrf:
            raise HTTPException(status_code=403, detail="Dashboard action is not authorized")

    async def _listen_probe(self, host: str, port: int) -> bool:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._socket_probe, host, port)
            return True
        except OSError:
            return False

    @staticmethod
    def _socket_probe(host: str, port: int) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))

    async def discover_upstreams(self) -> list[dict]:
        ports = list(range(5500, 5511)) + [3000, 4173, 5173, 8080, 8081, 8000]

        async def probe(port: int) -> dict | None:
            url = f"http://127.0.0.1:{port}/"
            try:
                async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(0.8, connect=0.3)) as client:
                    response = await client.get(url)
                return {
                    "host": "127.0.0.1",
                    "port": port,
                    "url": url,
                    "http_status": response.status_code,
                    "server": response.headers.get("server", ""),
                    "likely_live_server": port >= 5500 and port <= 5510,
                }
            except Exception:
                return None

        results = await asyncio.gather(*(probe(port) for port in ports))
        return [item for item in results if item]

    async def test_upstream(self) -> dict:
        try:
            validate_loopback_target(self.settings.upstream_host)
        except ValueError as exc:
            return {"ok": False, "status": "invalid", "message": str(exc)}
        url = self.upstream_base + "/"
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(3.0, connect=1.5)) as client:
                response = await client.get(url)
            return {
                "ok": True,
                "status": "reachable",
                "http_status": response.status_code,
                "message": f"Upstream responded with HTTP {response.status_code}",
                "server": response.headers.get("server", ""),
            }
        except httpx.ConnectError as exc:
            return {"ok": False, "status": "unavailable", "message": "VS Code Live Server is not reachable on the configured host/port", "detail": str(exc)}
        except httpx.TimeoutException as exc:
            return {"ok": False, "status": "timeout", "message": "Upstream connection timed out", "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "status": "error", "message": "Upstream test failed", "detail": str(exc)}

    def _build_dashboard_app(self) -> FastAPI:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(BASE_DIR / "frontend" / "index.html")

        @app.get("/style.css")
        async def style() -> FileResponse:
            return FileResponse(BASE_DIR / "frontend" / "style.css", media_type="text/css")

        @app.get("/app.js")
        async def script() -> FileResponse:
            return FileResponse(BASE_DIR / "frontend" / "app.js", media_type="application/javascript")

        @app.get("/api/bootstrap")
        async def bootstrap() -> dict:
            return await self.status_payload()

        @app.get("/api/status")
        async def status() -> dict:
            return await self.status_payload()

        @app.get("/api/network")
        async def network() -> dict:
            return {"hostname": local_hostname(), "interfaces": detect_ipv4_interfaces()}

        @app.get("/api/logs")
        async def logs(limit: int = 120) -> dict:
            limit = max(1, min(limit, 300))
            return {"logs": self.logs.snapshot(limit)}

        @app.get("/api/sessions")
        async def sessions() -> dict:
            return {"sessions": self.sessions.snapshot(), "active_count": self.sessions.active_count()}

        @app.post("/api/upstream/test")
        async def upstream_test(request: Request) -> dict:
            self._csrf_required(request)
            return await self.test_upstream()

        @app.post("/api/upstream/discover")
        async def upstream_discover(request: Request) -> dict:
            self._csrf_required(request)
            return {"ok": True, "candidates": await self.discover_upstreams()}

        @app.post("/api/settings")
        async def save_settings(request: Request) -> dict:
            self._csrf_required(request)
            payload = await request.json()
            try:
                candidate = settings_from_dict(payload, self.settings)
                self._validate_settings(candidate)
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            changed_ports = (candidate.dashboard_port != self.settings.dashboard_port or candidate.dashboard_host != self.settings.dashboard_host)
            if changed_ports:
                raise HTTPException(status_code=400, detail="Dashboard host/port are intentionally fixed at runtime; edit config.json before launching if needed")
            self.settings = candidate
            self.store.save(self.settings)
            await self.notify_dashboard()
            return await self.status_payload()

        @app.post("/api/sharing/start")
        async def start(request: Request) -> dict:
            self._csrf_required(request)
            payload = await request.json()
            self.settings = settings_from_dict(payload, self.settings)
            try:
                self._validate_settings(self.settings)
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            result = await self.start_sharing()
            if not result["ok"]:
                raise HTTPException(status_code=400, detail=result["message"])
            self.store.save(self.settings)
            await self.notify_dashboard()
            return await self.status_payload()

        @app.post("/api/sharing/stop")
        async def stop(request: Request) -> dict:
            self._csrf_required(request)
            await self.stop_sharing()
            await self.notify_dashboard()
            return await self.status_payload()

        @app.post("/api/sessions/{session_id}/revoke")
        async def revoke(request: Request, session_id: str) -> dict:
            self._csrf_required(request)
            if not self.sessions.revoke(session_id):
                raise HTTPException(status_code=404, detail="Session not found")
            if self.proxy_controller:
                await self.proxy_controller.revoke_session(session_id)
            logger.info("Browser session revoked: %s", session_id[:10])
            await self.notify_dashboard()
            return {"ok": True, "action": "revoked", "session_id": session_id}

        @app.post("/api/sessions/{session_id}/restore")
        async def restore(request: Request, session_id: str) -> dict:
            self._csrf_required(request)
            if not self.sessions.restore(session_id):
                raise HTTPException(status_code=404, detail="Session not found")
            logger.info("Browser session restored: %s", session_id[:10])
            await self.notify_dashboard()
            return {"ok": True, "action": "restored", "session_id": session_id}

        @app.post("/api/sessions/revoke-all")
        async def revoke_all(request: Request) -> dict:
            self._csrf_required(request)
            changed = self.sessions.revoke_all()
            if self.proxy_controller:
                for session in self.sessions.snapshot():
                    if session["revoked"]:
                        await self.proxy_controller.revoke_session(session["session_id"])
            logger.info("Revoked %s browser sessions", changed)
            await self.notify_dashboard()
            return {"ok": True, "action": "revoke_all", "changed": changed}

        @app.post("/api/sessions/restore-all")
        async def restore_all(request: Request) -> dict:
            self._csrf_required(request)
            changed = self.sessions.restore_all()
            logger.info("Restored %s browser sessions", changed)
            await self.notify_dashboard()
            return {"ok": True, "action": "restore_all", "changed": changed}

        @app.get("/api/qr")
        async def qr() -> dict:
            url = self.preview_url
            if not url:
                return {"ok": False, "message": "Start sharing first"}
            try:
                image = qrcode.make(url)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                data = base64.b64encode(buffer.getvalue()).decode("ascii")
                return {"ok": True, "url": url, "image": f"data:image/png;base64,{data}"}
            except Exception as exc:
                logger.exception("QR generation failed")
                raise HTTPException(status_code=500, detail="QR generation failed") from exc

        @app.websocket("/api/ws")
        async def dashboard_ws(ws) -> None:
            await ws.accept()
            self.dashboard_clients.add(ws)
            try:
                await ws.send_json(await self.status_payload())
                while True:
                    message = await ws.receive_text()
                    if message == "ping":
                        await ws.send_text("pong")
            except Exception:
                pass
            finally:
                self.dashboard_clients.discard(ws)

        @app.get("/favicon.svg")
        async def favicon() -> Response:
            return Response("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='16' fill='#7c3aed'/><path d='M18 18h28v8H26v12h16v8H26v10h-8V18Z' fill='white'/></svg>", media_type="image/svg+xml")

        return app

    async def notify_dashboard(self) -> None:
        if not self.dashboard_clients:
            return
        payload = await self.status_payload()
        stale = []
        for ws in tuple(self.dashboard_clients):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.dashboard_clients.discard(ws)

    @staticmethod
    def _validate_settings(settings: Settings) -> None:
        validate_loopback_target(settings.upstream_host)
        if not (1 <= settings.upstream_port <= 65535):
            raise ValueError("Upstream port must be 1-65535")
        if not (1024 <= settings.share_port <= 65535):
            raise ValueError("Preview port must be 1024-65535")
        if settings.interface_ip not in {item["ip"] for item in detect_ipv4_interfaces()}:
            raise ValueError("Selected network interface address is no longer available")
        if settings.project_root:
            path = Path(settings.project_root).expanduser()
            if not path.is_dir():
                raise ValueError("Project root must be an existing directory")
        if not (50 <= settings.reload_debounce_ms <= 2000):
            raise ValueError("Reload debounce must be 50-2000 ms")

    async def status_payload(self) -> dict:
        sharing = self.proxy_server is not None and not self.proxy_server.should_exit
        upstream = await self.test_upstream()
        session_counts = self.sessions.counts()
        integrity = verify_integrity()
        return {
            "name": APP_NAME,
            "organization": APP_ORGANIZATION,
            "developer": APP_DEVELOPER,
            "version": self.version,
            "integrity": integrity,
            "csrf": self.dashboard_csrf,
            "platform": {"system": sys.platform, "python": sys.version.split()[0], "architecture": os.uname().machine if hasattr(os, "uname") else os.environ.get("PROCESSOR_ARCHITECTURE", "unknown")},
            "sharing": sharing,
            "upstream_base": self.upstream_base,
            "upstream_port": self.settings.upstream_port,
            "project_root": self.settings.project_root,
            "interface_ip": self.settings.interface_ip,
            "preview_url": self.preview_url,
            "share_port": self.settings.share_port,
            "reload_debounce_ms": self.settings.reload_debounce_ms,
            "ignored_paths": self.settings.ignored_paths,
            "watcher_enabled": self.settings.watcher_enabled,
            "connected_devices": session_counts["active"],
            "session_counts": session_counts,
            "sessions": self.sessions.snapshot(),
            "uptime_seconds": round(time.monotonic() - self.started_at, 1),
            "share_uptime_seconds": round(time.monotonic() - self.sharing_started_at, 1) if self.sharing_started_at else 0,
            "interfaces": detect_ipv4_interfaces(),
            "upstream": upstream,
            "watcher": {
                "enabled": self.settings.watcher_enabled,
                "running": bool(self.watcher and self.watcher.observer),
            },
            "logs": self.logs.snapshot(80),
        }

    async def start_sharing(self) -> dict:
        if self.proxy_server is not None and not self.proxy_server.should_exit:
            return {"ok": True, "message": "Sharing is already running"}

        health = await self.test_upstream()
        if not health.get("ok") and self.settings.upstream_host in {"127.0.0.1", "localhost"} and self.settings.upstream_port == 5500:
            candidates = await self.discover_upstreams()
            preferred = next((item for item in candidates if item.get("likely_live_server")), None) or (candidates[0] if candidates else None)
            if preferred:
                self.settings.upstream_host = preferred["host"]
                self.settings.upstream_port = preferred["port"]
                health = await self.test_upstream()
                logger.info("Auto-discovered local development server on port %s", preferred["port"])
        if not health.get("ok"):
            return {"ok": False, "message": health.get("message", "Upstream unavailable")}

        requested_port = self.settings.share_port
        selected_port = None
        for port in range(requested_port, min(requested_port + 12, 65535)):
            if await self._listen_probe(self.settings.interface_ip, port):
                selected_port = port
                break
        if selected_port is None:
            return {"ok": False, "message": f"No free preview port found near {requested_port} on {self.settings.interface_ip}"}
        if selected_port != requested_port:
            logger.warning("Preview port %s was busy; using %s instead", requested_port, selected_port)
            self.settings.share_port = selected_port

        self.share_token = new_token(32)
        self.proxy_controller = ProxyController(self)
        config = uvicorn.Config(
            self.proxy_controller.app,
            host=self.settings.interface_ip,
            port=self.settings.share_port,
            log_level="warning",
            access_log=False,
            server_header="LiveServer",
            date_header=False,
        )
        self.proxy_server = uvicorn.Server(config)
        self.proxy_task = asyncio.create_task(self.proxy_server.serve(), name="live-server-proxy")
        await asyncio.sleep(0.08)
        if self.proxy_server.started is not True:
            await self.stop_sharing()
            return {"ok": False, "message": "Preview listener failed to start"}

        self.sharing_started_at = time.monotonic()
        if self.settings.watcher_enabled and self.settings.project_root:
            try:
                self.watcher = FileWatcher(asyncio.get_running_loop(), self.proxy_controller.changed)
                self.watcher.set_debounce_ms(self.settings.reload_debounce_ms)
                self.watcher.start(self.settings.project_root, self.settings.ignored_paths)
            except Exception as exc:
                self.watcher = None
                logger.exception("File watcher failed to start")
                self.log_warning("Sharing is running, but file watcher could not start: %s", exc)
        logger.info("LAN sharing started on %s:%s", self.settings.interface_ip, self.settings.share_port)
        await self.notify_dashboard()
        return {"ok": True, "message": "LAN sharing started"}

    async def stop_sharing(self) -> None:
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if self.proxy_controller:
            await self.proxy_controller.close()
        if self.proxy_server:
            self.proxy_server.should_exit = True
        if self.proxy_task:
            try:
                await asyncio.wait_for(self.proxy_task, timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass
        self.proxy_controller = None
        self.proxy_server = None
        self.proxy_task = None
        self.share_token = None
        self.sharing_started_at = None
        logger.info("LAN sharing stopped")
        if self.dashboard_clients:
            await self.notify_dashboard()

    async def start(self) -> None:
        self.lock.acquire()
        self.store.save(self.settings)
        config = uvicorn.Config(
            self.dashboard_app,
            host=self.settings.dashboard_host,
            port=self.settings.dashboard_port,
            log_level="warning",
            access_log=False,
            server_header="LiveServerDashboard",
            date_header=False,
        )
        self.dashboard_server = uvicorn.Server(config)
        self.dashboard_task = asyncio.create_task(self.dashboard_server.serve(), name="live-server-dashboard")
        await asyncio.sleep(0.08)
        if self.dashboard_server.started is not True:
            raise RuntimeError(f"Dashboard could not start on http://{self.settings.dashboard_host}:{self.settings.dashboard_port}")
        logger.info("Dashboard ready at http://%s:%s", self.settings.dashboard_host, self.settings.dashboard_port)
        print(f"{APP_ORGANIZATION} · {APP_NAME} dashboard: http://{self.settings.dashboard_host}:{self.settings.dashboard_port}")
        print("Start LAN sharing from the dashboard after VS Code Live Server is running.")
        await self.stop_event.wait()

    async def shutdown(self) -> None:
        await self.stop_sharing()
        if self.dashboard_server:
            self.dashboard_server.should_exit = True
        if self.dashboard_task:
            try:
                await asyncio.wait_for(self.dashboard_task, timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass
        self.lock.release()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except NotImplementedError:
                pass
        try:
            await self.start()
        except Exception:
            logger.exception("Application failed to start")
            raise
        finally:
            await self.shutdown()


async def main() -> None:
    app = LiveServerApp()
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
