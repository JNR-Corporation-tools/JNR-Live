import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from backend.proxy import ProxyController
from config import APP_VERSION, Settings
from backend.sessions import SessionManager
from backend.security import new_token


class Owner:
    version = APP_VERSION
    settings = Settings(upstream_host="127.0.0.1", upstream_port=0)
    share_token = new_token()
    sessions = SessionManager()

    @property
    def upstream_base(self):
        return f"http://127.0.0.1:{self.settings.upstream_port}"

    def log_warning(self, *args):
        pass

    def log_error(self, *args):
        pass


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.seen_query = self.path
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<html><body>hello</body></html>")

    def log_message(self, *args):
        pass


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.owner = Owner()
        cls.owner.settings.upstream_port = cls.server.server_address[1]
        cls.controller = ProxyController(cls.owner)
        cls.client = TestClient(cls.controller.app, follow_redirects=False)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        import asyncio
        asyncio.run(cls.controller.close())
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def test_requires_token(self):
        self.client.cookies.clear()
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 403)


    def test_websocket_forwarding(self):
        import threading
        from websockets.sync.server import serve

        ready = threading.Event()
        holder = {}

        def upstream_handler(ws):
            ready.set()
            message = ws.recv()
            ws.send("echo:" + message)

        def run_upstream():
            with serve(upstream_handler, "127.0.0.1", 0) as server:
                holder["port"] = server.socket.getsockname()[1]
                ready.set()
                server.serve_forever()

        thread = threading.Thread(target=run_upstream, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2))
        self.owner.settings.upstream_port = holder["port"]
        self.client.cookies.set("ls_token", self.owner.share_token)
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text("hello")
            self.assertEqual(ws.receive_text(), "echo:hello")

    def test_http_proxy_and_pairing(self):
        response = self.client.get("/?ls_token=" + self.owner.share_token)
        self.assertEqual(response.status_code, 307)
        cookies = response.cookies
        follow = self.client.get("/?q=1", cookies=cookies)
        self.assertEqual(follow.status_code, 200)
        self.assertEqual(self.server.path if hasattr(self.server, "path") else self.server.seen_query, "/?q=1")
        self.assertIn("hello", follow.text)
        self.assertIn("data-live-server-fallback", follow.text)


if __name__ == "__main__":
    unittest.main()
