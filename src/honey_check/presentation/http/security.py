"""Controles de la API local. Escuchar en 127.0.0.1 no basta: cualquier web abierta en el
navegador puede intentar peticiones a localhost, y DNS rebinding puede saltarse el origen."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

TICKET_TTL_SECONDS = 120
MAX_BODY_BYTES = 64 * 1024
CSRF_HEADER = "x-honey-check-csrf"
_PUBLIC_PATHS = ("/health",)
_ALLOWED_FETCH_SITES = {"same-origin", "none"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


@dataclass
class SessionGuard:
    """Secretos de una ejecución: nunca se escriben en disco ni en los logs."""

    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    instance_id: str = field(default_factory=lambda: secrets.token_hex(16))
    _tickets: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def issue_ticket(self) -> str:
        """Enlace de un solo uso para abrir la interfaz; la URL del navegador no da acceso luego."""
        ticket = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._tickets = {t: exp for t, exp in self._tickets.items() if exp > now}
            self._tickets[ticket] = now + TICKET_TTL_SECONDS
        return ticket

    def redeem_ticket(self, ticket: str) -> bool:
        with self._lock:
            expiry = self._tickets.pop(ticket, None)
        return expiry is not None and expiry > time.monotonic()

    def is_valid_session(self, value: str | None) -> bool:
        return value is not None and secrets.compare_digest(value, self.session_token)

    def is_valid_csrf(self, value: str | None) -> bool:
        return value is not None and secrets.compare_digest(value, self.csrf_token)


def _deny(status: int, code: str) -> Response:
    response = JSONResponse({"error": code}, status_code=status)
    return _harden(response)


def _harden(response: Response) -> Response:
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


NO_SESSION_PAGE = (
    "Honey Check: esta pestaña no tiene sesión.\n"
    "Abra la interfaz desde el icono de Honey Check en la bandeja del sistema."
)


def cookie_name(port: int) -> str:
    # Las cookies no distinguen puertos: el nombre evita pisar la de otra ejecución.
    return f"honey_check_session_{port}"


def build_gate(
    guard: SessionGuard, port: Callable[[], int]
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        bound_port = port()
        expected_host = f"127.0.0.1:{bound_port}"
        expected_origin = f"http://{expected_host}"

        # DNS rebinding: un dominio que apunte a 127.0.0.1 llega con otro Host.
        if request.headers.get("host") != expected_host:
            return _deny(403, "invalid_host")

        origin = request.headers.get("origin")
        if origin is not None and origin != expected_origin:
            return _deny(403, "invalid_origin")

        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site is not None and fetch_site not in _ALLOWED_FETCH_SITES:
            return _deny(403, "cross_site_request")

        path = request.url.path
        if path in _PUBLIC_PATHS:
            return _harden(await call_next(request))
        if path.startswith("/auth/"):
            if request.method != "GET":
                return _deny(405, "method_not_allowed")
            return _harden(await call_next(request))

        if not guard.is_valid_session(request.cookies.get(cookie_name(bound_port))):
            if path.startswith("/api/"):
                return _deny(401, "session_required")
            return _harden(PlainTextResponse(NO_SESSION_PAGE, status_code=401))

        if request.method in _UNSAFE_METHODS:
            if not guard.is_valid_csrf(request.headers.get(CSRF_HEADER)):
                return _deny(403, "invalid_csrf_token")
            # El Origin es obligatorio en cambios de estado: los navegadores siempre lo envían.
            if origin != expected_origin:
                return _deny(403, "origin_required")
            if request.headers.get("transfer-encoding"):
                return _deny(411, "content_length_required")
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return _deny(413, "body_too_large")
            content_type = request.headers.get("content-type", "")
            if int(length) > 0 and not content_type.startswith("application/json"):
                return _deny(415, "json_required")

        return _harden(await call_next(request))

    return gate
