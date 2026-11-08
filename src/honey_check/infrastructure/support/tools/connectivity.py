"""«Sin red o sin internet»: recorre las capas en orden y la primera que falla es la causa.

Adaptador (cable, Wi-Fi, deshabilitado) → dirección IP (DHCP, 169.254) → puerta de enlace (por
ARP: un router que filtra el ping igual contesta) → DNS (consulta directa a cada servidor, para
distinguir un servidor caído de una caché local mala) → salida a internet (TCP 443 a direcciones
IP, sin depender del DNS) → proxy del usuario. Las capas de arriba de la que falla quedan como
«depende de la anterior»: no se culpa al DNS cuando el cable está desconectado.

Se corrige solo lo que se puede desde el equipo (habilitar el adaptador, renovar la IP,
reiniciar el adaptador, vaciar la caché DNS) y se vuelve a recorrer todo para verificar. Lo que
depende del router, del proveedor o de la red corporativa se dice con claridad y no se intenta.
"""

from __future__ import annotations

import ctypes
import random
import socket
import struct
import time
import winreg
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from ctypes import wintypes
from dataclasses import dataclass, field

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.support import Check, CheckStatus, Risk, ToolResult
from honey_check.infrastructure.windows.netdiag import flush_dns_cache, tcp_port_open

from ..base import Params, SupportTool, fact, step, tool
from ..runner import tool_path
from ..winops import powershell, wmi_rows

IPCONFIG = tool_path("ipconfig.exe")
NETSH = tool_path("netsh.exe")
_PROBE_NAME = "www.microsoft.com"
_PUBLIC_DNS = ("1.1.1.1", "8.8.8.8")
_INTERNET = (("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443))
_SETTLE_S = 20.0  # tras reiniciar el adaptador o renovar, la red tarda en volver

# --- Lo que se lee del equipo (funciones de módulo: las pruebas las simulan) -------------------


@dataclass(frozen=True)
class Adapter:
    index: int
    name: str
    description: str
    physical: bool
    wifi: bool
    connected: bool
    disabled: bool
    speed_bps: int = 0


@dataclass(frozen=True)
class IpConfig:
    addresses: tuple[str, ...] = ()
    gateways: tuple[str, ...] = ()
    dns: tuple[str, ...] = ()
    dhcp: bool = True


def adapters() -> list[Adapter]:
    rows = wmi_rows(
        CimQuery(
            "root/StandardCimv2",
            "MSFT_NetAdapter",
            (
                "Name",
                "InterfaceDescription",
                "InterfaceIndex",
                "MediaConnectState",
                "State",
                "HardwareInterface",
                "Virtual",
                "NdisPhysicalMedium",
                "Speed",
            ),
        )
    )
    return [
        Adapter(
            index=_number(row.get("InterfaceIndex")),
            name=str(row.get("Name") or ""),
            description=str(row.get("InterfaceDescription") or ""),
            physical=bool(row.get("HardwareInterface")) and not row.get("Virtual"),
            wifi=row.get("NdisPhysicalMedium") == 9,
            connected=row.get("MediaConnectState") == 1,
            disabled=row.get("State") == 3,
            speed_bps=_number(row.get("Speed")),
        )
        for row in rows
    ]


def _number(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _ipv4(values: object) -> tuple[str, ...]:
    if not isinstance(values, list | tuple):
        return ()
    return tuple(v for v in values if isinstance(v, str) and ":" not in v)


def ip_configs() -> dict[int, IpConfig]:
    rows = wmi_rows(
        CimQuery(
            "root/cimv2",
            "Win32_NetworkAdapterConfiguration",
            (
                "InterfaceIndex",
                "IPAddress",
                "DefaultIPGateway",
                "DNSServerSearchOrder",
                "DHCPEnabled",
            ),
            where="IPEnabled=True",
        )
    )
    return {
        _number(row.get("InterfaceIndex")): IpConfig(
            addresses=_ipv4(row.get("IPAddress")),
            gateways=_ipv4(row.get("DefaultIPGateway")),
            dns=_ipv4(row.get("DNSServerSearchOrder")),
            dhcp=bool(row.get("DHCPEnabled")),
        )
        for row in rows
    }


_iphlpapi = ctypes.WinDLL("iphlpapi")
_iphlpapi.SendARP.argtypes = (
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.ULONG),
)


def arp_reachable(address: str) -> bool:
    """El equipo con esa IP contestó por ARP: está en la red local aunque filtre el ping."""
    mac = (ctypes.c_ubyte * 8)()
    length = wintypes.ULONG(len(mac))
    target = struct.unpack("<I", socket.inet_aton(address))[0]
    return _iphlpapi.SendARP(target, 0, mac, ctypes.byref(length)) == 0 and length.value > 0


def resolves(name: str, timeout_s: float = 3.0) -> bool:
    """Resolución con el DNS del sistema (y su caché), con límite de tiempo."""
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(socket.getaddrinfo, name, 443, socket.AF_INET)
        try:
            return bool(future.result(timeout=timeout_s))
        except (OSError, FutureTimeout):
            return False


def dns_answers(server: str, name: str = _PROBE_NAME, timeout_s: float = 1.5) -> bool:
    """Pregunta directamente a un servidor DNS, sin pasar por la caché del equipo."""
    query_id = random.randint(0, 0xFFFF)  # noqa: S311 - identificador de consulta, no seguridad
    header = struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    question = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"
    packet = header + question + struct.pack(">HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout_s)
        try:
            sock.sendto(packet, (server, 53))
            reply, _ = sock.recvfrom(1500)
        except OSError:
            return False
    if len(reply) < 12:
        return False
    reply_id, flags, _qd, answers = struct.unpack(">HHHH", reply[:8])
    return bool(reply_id == query_id and (flags & 0x000F) == 0 and answers > 0)


def internet_reachable() -> bool:
    with ThreadPoolExecutor(len(_INTERNET)) as pool:
        return any(pool.map(lambda target: tcp_port_open(target[0], target[1], 2.0), _INTERNET))


def user_proxy() -> tuple[str, int] | None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return None
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0])
    except OSError:
        return None
    # «host:puerto» o «http=host:puerto;https=…»: se prueba el de https o el primero.
    entries: dict[str, str] = {}
    for part in filter(None, server.split(";")):
        scheme, _, address = part.rpartition("=")
        entries[scheme] = address
    chosen = entries.get("https") or entries.get("") or next(iter(entries.values()), "")
    host, _, port = chosen.rpartition(":")
    return (host, int(port)) if host and port.isdigit() else None


def proxy_reachable(proxy: tuple[str, int]) -> bool:
    return tcp_port_open(proxy[0], proxy[1], 2.0)


# --- Diagnóstico por capas -----------------------------------------------------------------------


@dataclass
class Layer:
    key: str
    label: str
    status: CheckStatus
    detail: str
    fix: str | None = None  # «enable:<nombre>», «renew:<nombre>», «restart:<nombre>», «flush»

    def check(self) -> Check:
        return Check(label=self.label, status=self.status, detail=self.detail)


@dataclass
class Diagnosis:
    layers: list[Layer] = field(default_factory=list)
    adapter: Adapter | None = None

    @property
    def cause(self) -> Layer | None:
        return next(
            (lay for lay in self.layers if lay.status in (CheckStatus.FAIL, CheckStatus.WARN)),
            None,
        )

    @property
    def online(self) -> bool:
        return any(lay.key == "internet" and lay.status is CheckStatus.OK for lay in self.layers)


_ORDER = ["adapter", "ip", "gateway", "dns", "internet", "proxy"]
# Para la frase de la causa: «La causa está en el adaptador de red».
_IN_SENTENCE = {
    "adapter": "el adaptador de red",
    "ip": "la dirección IP",
    "gateway": "la puerta de enlace",
    "dns": "el DNS",
    "internet": "la salida a internet",
    "proxy": "el proxy",
}
_LABELS = {
    "adapter": "Adaptador de red",
    "ip": "Dirección IP",
    "gateway": "Puerta de enlace",
    "dns": "DNS",
    "internet": "Salida a internet",
    "proxy": "Proxy",
}


def _speed(bps: int) -> str:
    return f"{bps / 1e9:.1f} Gb/s" if bps >= 1e9 else f"{bps / 1e6:.0f} Mb/s"


def diagnose() -> Diagnosis:
    found = Diagnosis()

    def add(key: str, status: CheckStatus, detail: str, fix: str | None = None) -> bool:
        found.layers.append(Layer(key, _LABELS[key], status, detail, fix))
        return status in (CheckStatus.OK, CheckStatus.INFO)

    def rest_depends(after: str) -> Diagnosis:
        for key in _ORDER[_ORDER.index(after) + 1 :]:
            if key != "proxy":
                found.layers.append(
                    Layer(key, _LABELS[key], CheckStatus.SKIPPED, "Depende de la capa anterior")
                )
        return found

    physical = [a for a in adapters() if a.physical]
    connected = [a for a in physical if a.connected and not a.disabled]
    configs = ip_configs()
    # El adaptador que lleva el tráfico: el conectado que tiene puerta de enlace, si hay.
    connected.sort(key=lambda a: (not configs.get(a.index, IpConfig()).gateways, not a.wifi))
    if connected:
        adapter = connected[0]
        found.adapter = adapter
        kind = "Wi-Fi" if adapter.wifi else "Cable"
        name = kind if adapter.name.lower() == kind.lower() else f"{kind}: {adapter.name}"
        add("adapter", CheckStatus.OK, f"{name}, {_speed(adapter.speed_bps)}")
    else:
        disabled = [a for a in physical if a.disabled]
        if disabled:
            add(
                "adapter",
                CheckStatus.WARN,
                f"{disabled[0].name} ({disabled[0].description}) está deshabilitado. Se habilita.",
                fix=f"enable:{disabled[0].name}",
            )
        else:
            wifi = any(a.wifi for a in physical)
            add(
                "adapter",
                CheckStatus.FAIL,
                "Ningún adaptador tiene conexión: "
                + ("conéctese a una red Wi-Fi o " if wifi else "")
                + "revise el cable. Esto no se arregla desde el equipo.",
            )
        return rest_depends("adapter")

    config = configs.get(adapter.index, IpConfig())
    usable = [a for a in config.addresses if not a.startswith("169.254.")]
    if not usable:
        why = (
            "Tiene 169.254.x.x: no recibió dirección del servidor DHCP"
            if config.addresses
            else "No tiene dirección IPv4"
        )
        add("ip", CheckStatus.WARN, f"{why}. Se renueva.", fix=f"renew:{adapter.name}")
        return rest_depends("ip")
    add("ip", CheckStatus.OK, f"{usable[0]} {'por DHCP' if config.dhcp else '(fija)'}")

    if not config.gateways:
        add(
            "gateway",
            CheckStatus.WARN if config.dhcp else CheckStatus.FAIL,
            "No hay puerta de enlace: "
            + ("se renueva la IP." if config.dhcp else "la IP fija está incompleta."),
            fix=f"renew:{adapter.name}" if config.dhcp else None,
        )
        return rest_depends("gateway")
    gateway = config.gateways[0]
    if not arp_reachable(gateway):
        add(
            "gateway",
            CheckStatus.WARN,
            f"El router {gateway} no contesta"
            + (" (señal Wi-Fi débil o router caído)" if adapter.wifi else "")
            + ". Se reinicia el adaptador.",
            fix=f"restart:{adapter.name}",
        )
        return rest_depends("gateway")
    add("gateway", CheckStatus.OK, f"El router {gateway} contesta")

    online = internet_reachable()
    if resolves(_PROBE_NAME):
        add("dns", CheckStatus.OK, "Resuelve nombres de internet")
    elif any(dns_answers(server) for server in config.dns):
        add(
            "dns",
            CheckStatus.WARN,
            "El servidor DNS contesta, pero el equipo no resuelve: caché local. Se vacía.",
            fix="flush",
        )
    elif online and any(dns_answers(server) for server in _PUBLIC_DNS):
        servers = ", ".join(config.dns) or "ninguno"
        add(
            "dns",
            CheckStatus.FAIL,
            f"El servidor DNS configurado ({servers}) no responde, pero internet sí funciona. "
            + (
                "Renovar la IP puede traer otro servidor." if config.dhcp else "Revise el DNS fijo."
            ),
            fix=f"renew:{adapter.name}" if config.dhcp else None,
        )
    else:
        add("dns", CheckStatus.SKIPPED, "Depende de la salida a internet")

    if online:
        add("internet", CheckStatus.OK, "Hay salida a internet")
    else:
        add(
            "internet",
            CheckStatus.FAIL,
            "La red local funciona, pero no sale a internet: router, proveedor o firewall de la "
            "red. Esto no se arregla desde el equipo.",
        )

    proxy = user_proxy()
    if proxy:
        if proxy_reachable(proxy):
            add("proxy", CheckStatus.OK, f"{proxy[0]}:{proxy[1]} responde")
        else:
            add(
                "proxy",
                CheckStatus.FAIL,
                f"El proxy configurado ({proxy[0]}:{proxy[1]}) no responde: los navegadores no "
                "cargan páginas. Lo configura la red o el administrador.",
            )
    return found


# --- Revisión y ejecución ----------------------------------------------------------------------


def _review(_params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    found = diagnose()
    checks = [layer.check() for layer in found.layers]
    cause = found.cause
    if cause is None:
        return "La conexión funciona: hay salida a internet y el DNS responde.", checks, False
    if cause.fix:
        verb = {
            "enable": "habilitar el adaptador",
            "renew": "renovar la IP",
            "restart": "reiniciar el adaptador",
            "flush": "vaciar la caché DNS",
        }[cause.fix.split(":", 1)[0]]
        summary = (
            f"La causa está en {_IN_SENTENCE[cause.key]}. Se va a {verb} y después se comprueba "
            "la conexión de nuevo."
        )
        return summary, checks, cause.fix != "flush"
    return f"{cause.detail.split('.')[0]}.", checks, False


def _apply(fix: str, ctx: ToolContext) -> Check:
    action, _, name = fix.partition(":")
    if action == "flush":
        way = first_that_works(
            ctx,
            [
                Attempt("API DnsFlushResolverCache", flush_dns_cache),
                Attempt(
                    "ipconfig /flushdns",
                    lambda: ctx.command([IPCONFIG, "/flushdns"], timeout_s=30).ok,
                ),
            ],
        )
        return Check(
            label="Caché DNS",
            status=CheckStatus.OK if way else CheckStatus.FAIL,
            detail=f"Vaciada ({way})" if way else "No se pudo vaciar",
        )
    script = {
        "enable": "Enable-NetAdapter -Name ([Console]::In.ReadToEnd().Trim()) -Confirm:$false",
        "restart": "Restart-NetAdapter -Name ([Console]::In.ReadToEnd().Trim()) -Confirm:$false",
    }
    attempts = []
    if action == "renew":
        attempts.append(
            Attempt(
                f"ipconfig /renew {name}",
                lambda: ctx.command([IPCONFIG, "/renew", name], timeout_s=90).ok,
            )
        )
        action = "restart"  # si DHCP no contesta, reiniciar el adaptador fuerza otra solicitud
    attempts.append(
        Attempt(
            f"{script[action].split(' ', 1)[0]} {name}",
            lambda: powershell(ctx, script[action], stdin=name, timeout_s=60).ok,
        )
    )
    attempts.append(
        Attempt(
            f"netsh interface set interface {name}",
            lambda: all(
                ctx.command(
                    [NETSH, "interface", "set", "interface", f"name={name}", f"admin={state}"],
                    timeout_s=30,
                ).ok
                for state in (("disabled", "enabled") if action == "restart" else ("enabled",))
            ),
        )
    )
    way = first_that_works(ctx, attempts)
    label = {"enable": "Habilitar", "restart": "Reiniciar", "renew": "Renovar IP de"}[
        fix.split(":", 1)[0]
    ]
    return Check(
        label=f"{label} {name}",
        status=CheckStatus.OK if way else CheckStatus.FAIL,
        detail=f"Hecho ({way})" if way else "Windows no lo permitió por ninguna vía",
    )


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _connectivity(_params: Params, ctx: ToolContext) -> ToolResult:
    found = diagnose()
    applied: list[Check] = []
    tried: set[str] = set()
    # Cada arreglo puede destapar la causa siguiente (habilitar el adaptador y luego renovar la
    # IP): se repite mientras haya una causa con arreglo nuevo, hasta tres veces.
    for _round in range(3):
        cause = found.cause
        if cause is None or not cause.fix or cause.fix in tried:
            break
        tried.add(cause.fix)
        ctx.info(f"Causa: {cause.label}. {cause.detail}")
        applied.append(_apply(cause.fix, ctx))
        if cause.fix != "flush":
            deadline = time.monotonic() + _SETTLE_S
            ctx.info("Esperando a que la red vuelva…")
            while time.monotonic() < deadline:
                ctx.cancel.raise_if_cancelled()
                found = diagnose()
                if found.cause is None or found.cause.key != cause.key:
                    break
                _pause(2)
        else:
            found = diagnose()
    after = [layer.check() for layer in found.layers]
    return ToolResult(
        summary=[
            fact("Conexión", "Con internet" if found.online else "Sin internet"),
            *([fact("Adaptador", found.adapter.name)] if found.adapter else []),
        ],
        checks=[*applied, *after],
        verified=found.online and found.cause is None,
    )


connectivity = SupportTool(
    tool(
        "network.connectivity",
        "Red",
        "Sin red o sin internet",
        "Recorre en segundos adaptador, IP, router, DNS, salida a internet y proxy; la primera "
        "capa que falla es la causa. Corrige solo esa y vuelve a comprobar.",
        Risk.CHANGE,
        network=True,
        action="Corregir la conexión",
    ),
    lambda _p, _e: [
        step("Adaptador conectado y habilitado", "Get-NetAdapter"),
        step("Dirección IP y DHCP", "ipconfig /all"),
        step("Router por ARP (aunque filtre el ping)", "arp -a <puerta de enlace>"),
        step(
            "DNS del sistema y consulta directa a cada servidor", "nslookup www.microsoft.com <dns>"
        ),
        step("Salida a internet por TCP 443", "Test-NetConnection 1.1.1.1 -Port 443"),
        step("Proxy del usuario", "netsh winhttp show proxy"),
        step("Corregir solo la causa: habilitar, renovar, reiniciar el adaptador o vaciar DNS"),
        step("Volver a comprobar todas las capas"),
    ],
    _connectivity,
    warnings=lambda _p, _e: [
        "Renovar la IP o reiniciar el adaptador corta la red unos segundos (también un escritorio "
        "remoto)."
    ],
    review=_review,
)

TOOLS = [connectivity]
