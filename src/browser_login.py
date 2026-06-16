"""Đăng nhập desktop qua trình duyệt (OAuth loopback)."""

from __future__ import annotations

import http.server
import logging
import secrets
import socket
import socketserver
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

from src.api_client import AccessResult, exchange_desktop_code
from src.api_config import ApiConfig, load_api_config
from src.login_help import web_base_from_api_url

logger = logging.getLogger(__name__)

CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT_SEC = 300


@dataclass
class _CallbackCapture:
    code: str = ""
    state: str = ""
    error: str = ""


@dataclass(frozen=True)
class BrowserLoginResult:
    ok: bool
    message: str
    access: Optional[AccessResult] = None


def _device_name() -> str:
    import platform

    host = (socket.gethostname() or "").strip()
    system = (platform.system() or "").strip()
    if host and system:
        return f"{host} ({system})"
    return host or system or "Desktop"


def _pick_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def desktop_auth_start_url(
    *,
    api_base_url: str,
    state: str,
    redirect_uri: str,
    device_name: str,
) -> str:
    base = web_base_from_api_url(api_base_url)
    query = urllib.parse.urlencode(
        {
            "state": state,
            "redirect_uri": redirect_uri,
            "device_name": device_name,
        }
    )
    return f"{base}/auth/desktop?{query}"


def _make_callback_handler(capture: _CallbackCapture) -> type[http.server.BaseHTTPRequestHandler]:
    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A003
            logger.debug("browser_login: " + format, *args)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)
                return

            params = parse_qs(parsed.query)
            code = (params.get("code") or [""])[0].strip()
            state = (params.get("state") or [""])[0].strip()
            error = (params.get("error") or [""])[0].strip()

            if error:
                capture.error = error
            else:
                capture.code = code
                capture.state = state

            body = (
                "<!DOCTYPE html><html lang='vi'><head><meta charset='utf-8'>"
                "<title>Táo Đen IMEI Tool</title></head><body style='font-family:sans-serif;"
                "text-align:center;padding:3rem'>"
                "<h2>Đăng nhập thành công</h2>"
                "<p>Bạn có thể đóng cửa sổ này và quay lại app.</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return CallbackHandler


def login_via_browser(
    config: Optional[ApiConfig] = None,
    *,
    timeout: float = LOGIN_TIMEOUT_SEC,
) -> BrowserLoginResult:
    """Mở trình duyệt → Google/web → nhận code loopback → đổi lấy Sanctum token."""
    cfg = config or load_api_config()
    if not (cfg.api_base_url or "").strip():
        return BrowserLoginResult(ok=False, message="Chưa cấu hình URL server.")

    capture = _CallbackCapture()
    state = secrets.token_urlsafe(32)
    port = _pick_loopback_port()
    redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
    device = _device_name()

    handler = _make_callback_handler(capture)
    socketserver.TCPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    server.timeout = 0.5

    auth_url = desktop_auth_start_url(
        api_base_url=cfg.api_base_url,
        state=state,
        redirect_uri=redirect_uri,
        device_name=device,
    )

    if not webbrowser.open(auth_url):
        server.server_close()
        return BrowserLoginResult(
            ok=False,
            message="Không mở được trình duyệt. Dán link vào Chrome/Safari:\n" + auth_url,
        )

    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            server.handle_request()

            if capture.error:
                return BrowserLoginResult(
                    ok=False,
                    message=f"Đăng nhập bị hủy: {capture.error}",
                )

            if capture.code:
                if capture.state != state:
                    return BrowserLoginResult(ok=False, message="State không khớp — thử lại.")
                access = exchange_desktop_code(
                    code=capture.code,
                    state=state,
                    redirect_uri=redirect_uri,
                    config=cfg,
                )
                if not access.valid:
                    return BrowserLoginResult(ok=False, message=access.message, access=access)
                return BrowserLoginResult(ok=True, message="OK", access=access)

        return BrowserLoginResult(
            ok=False,
            message="Hết thời gian chờ đăng nhập trình duyệt (5 phút). Thử lại.",
        )
    finally:
        server.server_close()
