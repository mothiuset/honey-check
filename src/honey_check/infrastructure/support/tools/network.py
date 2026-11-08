"""Red: diagnóstico por adaptador, ping, prueba de puerto, DNS, renovar IP y restablecer la pila."""

from __future__ import annotations

import socket
import winreg

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import ColumnKind, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.netdiag import (
    flush_dns_cache,
    ping,
    resolve_ipv4,
    tcp_port_open,
)

from ..base import (
    Params,
    SupportTool,
    check,
    col,
    fact,
    flag,
    link,
    number,
    step,
    table,
    text,
    tool,
)
from ..runner import tool_path
from ..winops import wmi_rows

IPCONFIG = tool_path("ipconfig.exe")
NETSH = tool_path("netsh.exe")
_HOST = r"[A-Za-z0-9._:-]{1,253}"
_INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _adapters() -> list[dict[str, object]]:
    return wmi_rows(
        CimQuery(
            "root/cimv2",
            "Win32_NetworkAdapterConfiguration",
            (
                "Index",
                "Description",
                "IPAddress",
                "IPSubnet",
                "DefaultIPGateway",
                "DNSServerSearchOrder",
                "DHCPEnabled",
                "DHCPServer",
                "MACAddress",
                "DNSDomain",
            ),
            where="IPEnabled=True",
        )
    )


def _proxy() -> str | None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS, 0, winreg.KEY_READ
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server = winreg.QueryValueEx(key, "ProxyServer")[0] if enabled else None
            try:
                script = winreg.QueryValueEx(key, "AutoConfigURL")[0]
            except OSError:
                script = None
    except OSError:
        return None
    if server:
        return f"Proxy {server}"
    return f"Script de configuración {script}" if script else None


def _ipv4(values: object) -> list[str]:
    if not isinstance(values, list | tuple):
        return []
    return [v for v in values if isinstance(v, str) and ":" not in v]


def _diagnose(params: Params, ctx: ToolContext) -> ToolResult:
    adapters = _adapters()
    checks = []
    rows = []
    for adapter in adapters:
        name = str(adapter.get("Description") or "Adaptador")
        addresses = _ipv4(adapter.get("IPAddress"))
        gateways = _ipv4(adapter.get("DefaultIPGateway"))
        dns = _ipv4(adapter.get("DNSServerSearchOrder"))
        apipa = any(a.startswith("169.254.") for a in addresses)
        rows.append(
            {
                "name": name,
                "ip": ", ".join(addresses),
                "gateway": ", ".join(gateways),
                "dns": ", ".join(dns),
                "dhcp": bool(adapter.get("DHCPEnabled")),
                "mac": adapter.get("MACAddress"),
                "domain": adapter.get("DNSDomain") or "",
            }
        )
        if apipa:
            checks.append(
                check(
                    f"{name}: dirección asignada",
                    False,
                    "Tiene una dirección 169.254.x.x: no recibió IP del DHCP",
                    link("network.renew_ip", "Renovar IP", Tone.WARN),
                )
            )
        for gateway in gateways:
            result = ping(gateway, 3)
            checks.append(
                check(
                    f"{name}: puerta de enlace {gateway}",
                    result.received > 0,
                    f"{result.received}/{result.sent} respuestas, {result.avg_ms} ms"
                    if result.received
                    else "Sin respuesta al ping (puede estar filtrado)",
                    warn=True,
                )
            )
        for server in dns[:2]:
            reachable = tcp_port_open(server, 53, 2) or ping(server, 2).received > 0
            checks.append(
                check(
                    f"{name}: servidor DNS {server}",
                    reachable,
                    None if reachable else "No responde",
                    link("network.flush_dns", "Vaciar caché DNS") if not reachable else None,
                    warn=True,
                )
            )
    if not adapters:
        checks.append(
            check("Hay un adaptador con IP", False, "Ningún adaptador tiene IP habilitada")
        )
    host = str(params.get("host") or "").strip()
    if host:
        address = resolve_ipv4(host)
        checks.append(
            check(
                f"Resolver {host}",
                address is not None,
                address or "El DNS no lo resolvió",
                link("network.flush_dns", "Vaciar caché DNS") if address is None else None,
            )
        )
        if address:
            result = ping(host, 3)
            checks.append(
                check(
                    f"Ping a {host}",
                    result.received > 0,
                    f"{result.avg_ms} ms" if result.received else "Sin respuesta",
                    warn=True,
                )
            )
    if params.get("internet"):
        online = tcp_port_open("1.1.1.1", 443, 3) or tcp_port_open("8.8.8.8", 443, 3)
        checks.append(check("Salida a Internet (puerto 443)", online))
        named = resolve_ipv4("www.microsoft.com") is not None
        checks.append(check("Resolución de nombres de Internet", named))
    proxy = _proxy()
    return ToolResult(
        summary=[
            fact("Nombre del equipo", socket.gethostname()),
            fact("Proxy del usuario", proxy or "Sin proxy"),
        ],
        checks=checks,
        tables=[
            table(
                "adaptadores",
                "Adaptadores con IP",
                [
                    col("name", "Adaptador"),
                    col("ip", "IPv4"),
                    col("gateway", "Puerta de enlace"),
                    col("dns", "DNS", priority=2),
                    col("dhcp", "DHCP", ColumnKind.BOOL, 2),
                    col("mac", "MAC", priority=3),
                    col("domain", "Sufijo DNS", priority=3),
                ],
                rows,
                "name",
            )
        ],
    )


diagnose = SupportTool(
    tool(
        "network.diagnose",
        "Red",
        "Diagnóstico de red",
        "Revisa cada adaptador (IP, puerta de enlace, DNS), resuelve y hace ping a un equipo y, si se pide, comprueba la salida a Internet.",
        Risk.READ,
        params=[
            text("host", "Equipo o servidor a probar (opcional)", pattern=_HOST),
            flag("internet", "Comprobar también la salida a Internet"),
        ],
        network=True,
        hidden=True,
    ),
    lambda p, _e: [
        step("Leer adaptadores, IP, puerta de enlace y DNS", "ipconfig /all"),
        step("Ping a la puerta de enlace y al DNS", "ping <puerta de enlace>"),
        *(
            [step(f"Resolver y hacer ping a {p['host']}", f"ping {p['host']}")]
            if p.get("host")
            else []
        ),
        *(
            [step("Conectar a 1.1.1.1:443", "Test-NetConnection 1.1.1.1 -Port 443")]
            if p.get("internet")
            else []
        ),
    ],
    _diagnose,
)


def _ping(params: Params, ctx: ToolContext) -> ToolResult:
    result = ping(params["host"], int(params["count"]))
    ctx.info(f"{result.received}/{result.sent} respuestas")
    return ToolResult(
        summary=[
            fact("Dirección", result.address),
            fact(
                "Respuestas",
                f"{result.received} de {result.sent}",
                Tone.OK if result.received == result.sent and result.sent else Tone.BAD,
            ),
            fact(
                "Tiempo (mín/prom/máx)",
                f"{result.min_ms}/{result.avg_ms}/{result.max_ms} ms" if result.received else None,
            ),
            fact("Error", result.error),
        ],
        verified=result.received > 0,
    )


ping_tool = SupportTool(
    tool(
        "network.ping",
        "Red",
        "Ping",
        "Envía ecos ICMP a un equipo o servidor.",
        Risk.READ,
        params=[
            text("host", "Equipo o IP", required=True, pattern=_HOST),
            number("count", "Cantidad", default=4),
        ],
        network=True,
    ),
    lambda p, _e: [step(f"Ping a {p['host']}", f"ping -n {p['count']} {p['host']}")],
    _ping,
)


def _port(params: Params, _ctx: ToolContext) -> ToolResult:
    port = int(params["port"])
    ok = tcp_port_open(params["host"], port, 3)
    return ToolResult(
        checks=[check(f"{params['host']}:{port}", ok, "Abierto" if ok else "Cerrado o filtrado")],
        verified=ok,
    )


port_tool = SupportTool(
    tool(
        "network.port",
        "Red",
        "Probar puerto",
        "Comprueba si un puerto TCP responde (impresora 9100, SQL 1433, RDP 3389…).",
        Risk.READ,
        params=[
            text("host", "Equipo o IP", required=True, pattern=_HOST),
            number("port", "Puerto TCP", default=443),
        ],
        network=True,
    ),
    lambda p, _e: [
        step(
            f"Conectar a {p['host']}:{p['port']}",
            f"Test-NetConnection {p['host']} -Port {p['port']}",
        )
    ],
    _port,
)


def _flush(_params: Params, ctx: ToolContext) -> ToolResult:
    way = first_that_works(
        ctx,
        [
            Attempt("API DnsFlushResolverCache", flush_dns_cache),
            Attempt(
                "ipconfig /flushdns", lambda: ctx.command([IPCONFIG, "/flushdns"], timeout_s=30).ok
            ),
        ],
    )
    return ToolResult(
        checks=[check("Caché DNS vaciada", way is not None)], verified=way is not None
    )


flush_dns = SupportTool(
    tool(
        "network.flush_dns",
        "Red",
        "Vaciar caché DNS",
        "Descarta las resoluciones de nombres guardadas.",
        Risk.CHANGE,
        hidden=True,
        instant=True,
    ),
    lambda _p, _e: [step("Vaciar caché DNS", "ipconfig /flushdns")],
    _flush,
)


def _renew(_params: Params, ctx: ToolContext) -> ToolResult:
    ctx.command([IPCONFIG, "/release"], timeout_s=60)
    renew = ctx.command([IPCONFIG, "/renew"], timeout_s=120)
    addresses = [a for row in _adapters() for a in _ipv4(row.get("IPAddress"))]
    good = [a for a in addresses if not a.startswith("169.254.")]
    return ToolResult(
        summary=[fact("Direcciones ahora", ", ".join(addresses) or None)],
        checks=[check("IP renovada por DHCP", renew.ok and bool(good))],
        verified=bool(good),
    )


renew_ip = SupportTool(
    tool(
        "network.renew_ip",
        "Red",
        "Renovar IP (DHCP)",
        "Libera y vuelve a pedir la dirección IP al DHCP.",
        Risk.CHANGE,
        hidden=True,
    ),
    lambda _p, _e: [step("Liberar", "ipconfig /release"), step("Renovar", "ipconfig /renew")],
    _renew,
    warnings=lambda _p, _e: [
        "La red se corta unos segundos; si trabaja por escritorio remoto, perderá la conexión."
    ],
)


def _reset_stack(_params: Params, ctx: ToolContext) -> ToolResult:
    winsock = ctx.command([NETSH, "winsock", "reset"], timeout_s=120)
    ip = ctx.command([NETSH, "int", "ip", "reset"], timeout_s=120)
    flush_dns_cache()
    return ToolResult(
        checks=[
            check("Winsock restablecido", winsock.ok),
            check("Pila TCP/IP restablecida", ip.ok),
        ],
        summary=[
            fact(
                "Siguiente paso", "Reinicie el equipo para completar el restablecimiento", Tone.WARN
            )
        ],
        verified=winsock.ok and ip.ok,
    )


reset_stack = SupportTool(
    tool(
        "network.reset_stack",
        "Red",
        "Restablecer la pila de red",
        "Restablece Winsock y TCP/IP a sus valores de fábrica (requiere reiniciar).",
        Risk.CHANGE,
        admin=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Restablecer Winsock", "netsh winsock reset"),
        step("Restablecer TCP/IP", "netsh int ip reset"),
        step("Vaciar DNS", "ipconfig /flushdns"),
    ],
    _reset_stack,
    warnings=lambda _p, _e: [
        "Se pierden las IP fijas y la configuración de red personalizada. Hay que reiniciar después."
    ],
)

TOOLS = [diagnose, ping_tool, port_tool, flush_dns, renew_ip, reset_stack]
