"""Un Windows simulado para probar los solucionadores en escenarios que este equipo no puede
reproducir (dominio, controlador inalcanzable, canal seguro roto…).

Responde a los mismos comandos y API que usa el código real, y cambia de estado cuando un arreglo
surte efecto: después de `w32tm /resync` la hora queda bien, después de `nltest /sc_reset` el
canal vuelve, y `gpupdate` solo funciona si las causas ya se corrigieron. Así una prueba verifica
el recorrido completo (diagnóstico → arreglo → aplicación → verificación), no solo piezas.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.ports import CommandOutput
from honey_check.domain.support import CheckStatus
from honey_check.infrastructure.support.tools import domain, policies
from honey_check.infrastructure.windows.netdiag import DomainController

GOOD_POL = b"PReg\x01\x00\x00\x00"


def policy_event(event_id: int, message: str, at: datetime | None = None) -> str:
    """Un evento de directivas como lo devuelve `wevtutil /f:RenderedXml`."""
    stamp = (at or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    return (
        '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
        f"<EventID>{event_id}</EventID><TimeCreated SystemTime='{stamp}'/></System>"
        f"<RenderingInfo><Message>{message}</Message></RenderingInfo></Event>"
    )


@dataclass
class SimulatedDomain:
    """Un equipo unido a `ficticio.local` con las fallas que pida el escenario."""

    system_root: Path
    joined: bool = True
    dc_reachable: bool = True
    ports_open: bool = True
    clock_offset_s: float = 4.0
    channel_ok: bool = True
    channel_repairable: bool = True
    sysvol_ok: bool = True
    machine_pol: bytes | None = GOOD_POL
    events: list[str] = field(default_factory=list)
    # Error que gpupdate deja en el registro aunque las causas estén corregidas (p. ej. una GPO).
    gpupdate_error: tuple[int, str] | None = None
    last_policy: datetime = field(default_factory=lambda: datetime.now(UTC) - timedelta(days=2))
    calls: list[str] = field(default_factory=list)

    dc = DomainController(
        name="dc01.ficticio.local",
        address="10.0.0.10",
        domain="ficticio.local",
        forest="ficticio.local",
        site="Sede",
        client_site="Sede",
    )

    # --- Estado en disco --------------------------------------------------------------------

    def __post_init__(self) -> None:
        folder = self.system_root / "System32" / "GroupPolicy" / "Machine"
        folder.mkdir(parents=True, exist_ok=True)
        if self.machine_pol is not None:
            (folder / "Registry.pol").write_bytes(self.machine_pol)

    @property
    def machine_pol_path(self) -> Path:
        return policies.registry_pol("Machine")

    def causes_fixed(self) -> bool:
        pol = self.machine_pol_path
        pol_ok = not pol.exists() or pol.read_bytes().startswith(GOOD_POL)
        return (
            self.dc_reachable
            and self.ports_open
            and abs(self.clock_offset_s) < 300
            and self.channel_ok
            and self.sysvol_ok
            and pol_ok
        )

    # --- Comandos ---------------------------------------------------------------------------

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        program = Path(args[0]).name.lower()
        line = " ".join([program, *args[1:]])
        self.calls.append(line)
        if program == "sc.exe":
            return CommandOutput(0, "STATE              : 4  RUNNING", "")
        if program == "nltest.exe":
            return self._nltest(args[1])
        if program == "w32tm.exe":
            if not self.dc_reachable:
                return CommandOutput(0x800705B4, "", "El equipo no se sincronizó")
            self.clock_offset_s = 2.0
            return CommandOutput(0, "El comando se completó correctamente.", "")
        if program == "klist.exe":
            # Tickets nuevos: si SYSVOL fallaba por tickets viejos, vuelve.
            self.sysvol_ok = self.dc_reachable and self.ports_open
            return CommandOutput(0, "Tickets eliminados", "")
        if program == "gpupdate.exe":
            return self._gpupdate(args)
        if program == "wevtutil.exe":
            return CommandOutput(0, "".join(self.events), "")
        if program == "powershell.exe":
            return CommandOutput(1, "", "Test-ComputerSecureChannel: acceso denegado")
        return CommandOutput(0, "", "")

    def _nltest(self, verb: str) -> CommandOutput:
        if verb.startswith(("/sc_query", "/sc_verify")):
            if self.channel_ok:
                return CommandOutput(0, "Estado de conexión = 0 0x0 NERR_Success", "")
            return CommandOutput(1, "ERROR_NO_TRUST_SAM_ACCOUNT 0x6fb", "")
        if verb.startswith("/sc_reset"):
            if self.channel_repairable:
                self.channel_ok = True
                return CommandOutput(0, "0x0 NERR_Success", "")
            return CommandOutput(1, "ERROR_NO_TRUST_SAM_ACCOUNT 0x6fb", "")
        return CommandOutput(0, "", "")

    def _gpupdate(self, args: Sequence[str]) -> CommandOutput:
        if not self.causes_fixed():
            self.events.insert(0, policy_event(1129, "Sin conexión con el controlador."))
            return CommandOutput(1, "", "No se pudo aplicar la directiva de equipo.")
        if self.gpupdate_error:
            event_id, message = self.gpupdate_error
            self.events.insert(0, policy_event(event_id, message))
            return CommandOutput(1, "", "La directiva se procesó con errores.")
        if "/target:computer" in args:
            self.last_policy = datetime.now(UTC) + timedelta(seconds=1)
        return CommandOutput(0, "La actualización de directivas finalizó correctamente.", "")

    # --- Instalación --------------------------------------------------------------------------

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedDomain:
        monkeypatch.setenv("SYSTEMROOT", str(self.system_root))
        membership = (True, "ficticio.local") if self.joined else (False, "WORKGROUP")
        find: Any = lambda _d, **_k: (self.dc, 0) if self.dc_reachable else (None, 1355)  # noqa: E731
        offset: Any = lambda _s: self.clock_offset_s  # noqa: E731
        for module in (domain, policies):
            monkeypatch.setattr(module, "find_domain_controller", find, raising=False)
            monkeypatch.setattr(module, "remote_time_offset", offset, raising=False)
        monkeypatch.setattr(domain, "membership", lambda: membership)
        monkeypatch.setattr(domain, "last_machine_policy", lambda: self.last_policy)
        monkeypatch.setattr(
            policies, "tcp_port_open", lambda _h, port, _t=2.0: self.ports_open or port == 88
        )
        monkeypatch.setattr(policies, "_sysvol", self._sysvol)
        # El canal seguro y gpupdate de usuario se comportan como en la sesión del técnico.
        monkeypatch.setattr(policies, "current_user_sid", lambda: None)
        return self

    def _sysvol(self, _domain: str) -> policies.Finding:
        if self.sysvol_ok:
            return policies.Finding("sysvol", "SYSVOL", CheckStatus.OK, "Accesible, 12 directivas")
        return policies.Finding(
            "sysvol",
            "SYSVOL",
            CheckStatus.WARN,
            "No se pudo leer la carpeta de directivas del dominio. Se renuevan los tickets de "
            "Kerberos del equipo y del usuario.",
            fix="kerberos",
        )


# --- Red ------------------------------------------------------------------------------------------


@dataclass
class SimulatedNetwork:
    """Un portátil con Wi-Fi y cable; cada falla se arregla solo con la acción que corresponde."""

    wifi_connected: bool = True
    wifi_disabled: bool = False
    cable_connected: bool = False
    dhcp_answers: bool = True  # el DHCP entrega dirección al renovar
    has_address: bool = True
    router_up: bool = True
    router_recovers_on_restart: bool = True
    dns_server_up: bool = True
    dns_cache_broken: bool = False
    upstream_internet: bool = True
    proxy: tuple[str, int] | None = None
    proxy_up: bool = True
    calls: list[str] = field(default_factory=list)

    def _adapters(self) -> list[Any]:
        from honey_check.infrastructure.support.tools.connectivity import Adapter

        return [
            Adapter(
                13,
                "Wi-Fi",
                "Wi-Fi ficticio AX200",
                True,
                True,
                self.wifi_connected and not self.wifi_disabled,
                self.wifi_disabled,
                866_000_000,
            ),
            Adapter(
                7,
                "Ethernet",
                "Ethernet ficticia",
                True,
                False,
                self.cable_connected,
                False,
                1_000_000_000,
            ),
            Adapter(37, "vEthernet (WSL)", "Hyper-V", False, False, True, False, 10_000_000_000),
        ]

    def _configs(self) -> dict[int, Any]:
        from honey_check.infrastructure.support.tools.connectivity import IpConfig

        address = "192.168.10.23" if self.has_address else "169.254.40.7"
        gateway = ("192.168.10.1",) if self.has_address else ()
        return {13: IpConfig((address,), gateway, ("192.168.10.1",), True)}

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        program = Path(args[0]).name.lower()
        script = " ".join(args[1:])
        self.calls.append(f"{program} {script} {stdin or ''}".strip())
        if program == "ipconfig.exe" and "/renew" in args:
            self.has_address = self.dhcp_answers
            return CommandOutput(0 if self.dhcp_answers else 1, "", "")
        if program == "ipconfig.exe" and "/flushdns" in args:
            self.dns_cache_broken = False
            return CommandOutput(0, "", "")
        if program == "powershell.exe" and "Enable-NetAdapter" in script:
            self.wifi_disabled = False
            return CommandOutput(0, "", "")
        if program == "powershell.exe" and "Restart-NetAdapter" in script:
            if self.router_recovers_on_restart:
                self.router_up = True
            self.has_address = self.dhcp_answers or self.has_address
            return CommandOutput(0, "", "")
        return CommandOutput(0, "", "")

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedNetwork:
        from honey_check.infrastructure.support.tools import connectivity

        online = lambda: self.upstream_internet and self.router_up and self.has_address  # noqa: E731
        monkeypatch.setattr(connectivity, "adapters", self._adapters)
        monkeypatch.setattr(connectivity, "ip_configs", self._configs)
        monkeypatch.setattr(connectivity, "arp_reachable", lambda _ip: self.router_up)
        monkeypatch.setattr(
            connectivity,
            "resolves",
            lambda _name, timeout_s=3.0: (
                online() and self.dns_server_up and not self.dns_cache_broken
            ),
        )
        monkeypatch.setattr(
            connectivity,
            "dns_answers",
            lambda server, name="", timeout_s=1.5: (
                online() and (self.dns_server_up or server in ("1.1.1.1", "8.8.8.8"))
            ),
        )
        monkeypatch.setattr(connectivity, "internet_reachable", online)
        monkeypatch.setattr(connectivity, "user_proxy", lambda: self.proxy)
        monkeypatch.setattr(connectivity, "proxy_reachable", lambda _p: self.proxy_up)
        # El API de caché DNS no existe en la simulación: se fuerza la vía de ipconfig.
        monkeypatch.setattr(connectivity, "flush_dns_cache", lambda: False)
        monkeypatch.setattr(connectivity, "_SETTLE_S", 0.5)
        monkeypatch.setattr(connectivity, "_pause", lambda _s: None)
        return self


# --- Impresoras -----------------------------------------------------------------------------------


@dataclass
class SimulatedPrinter:
    """Una impresora de red ficticia y el servicio de impresión, con las fallas del escenario."""

    name: str = "Oficina Láser (ficticia)"
    spooler_running: bool = True
    spooler_starts: bool = True
    offline: bool = False
    paused: bool = False
    error_state: int = 2  # 2: sin error
    reachable: bool = True
    stuck_jobs: int = 0
    jobs_removable: bool = True
    calls: list[str] = field(default_factory=list)
    test_pages: int = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedPrinter:
        from honey_check.infrastructure.support.tools import printing

        def printers() -> list[Any]:
            return [
                printing.Printer(
                    self.name,
                    "IP_10.0.0.50",
                    "Láser Ficticia PCL6",
                    self.offline,
                    self.error_state,
                    8 if self.paused else 3,
                    True,
                    False,
                ),
                printing.Printer(
                    "Microsoft Print to PDF",
                    "PORTPROMPT:",
                    "Microsoft Print To PDF",
                    False,
                    2,
                    3,
                    False,
                    False,
                ),
            ]

        def jobs(printer: str) -> list[Any]:
            if printer != self.name:
                return []
            return [
                printing.Job(i + 1, f"Factura {i + 1}.pdf", "Error", None)
                for i in range(self.stuck_jobs)
            ]

        monkeypatch.setattr(printing, "printers", printers)
        monkeypatch.setattr(printing, "jobs", jobs)
        monkeypatch.setattr(
            printing,
            "port_address",
            lambda port: ("10.0.0.50", 9100) if port.startswith("IP_") else None,
        )
        monkeypatch.setattr(printing, "port_reachable", lambda _a: self.reachable)
        monkeypatch.setattr(printing, "_pause", lambda _s: None)
        return self

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        program = Path(args[0]).name.lower()
        script = " ".join(args[1:])
        self.calls.append(f"{program} {script}".strip())
        if program == "sc.exe" and "query" in args:
            state = "4  RUNNING" if self.spooler_running else "1  STOPPED"
            return CommandOutput(0, f"STATE              : {state}", "")
        if program == "sc.exe" and "start" in args:
            self.spooler_running = self.spooler_starts
            return CommandOutput(0 if self.spooler_starts else 1053, "", "")
        if program == "powershell.exe":
            if "Start-Service" in script:
                self.spooler_running = self.spooler_starts
                return CommandOutput(0 if self.spooler_starts else 1, "", "")
            if "WorkOffline" in script:
                self.offline = False
                return CommandOutput(0, "", "")
            if "Resume" in script:
                self.paused = False
                return CommandOutput(0, "", "")
            if "Remove-PrintJob" in script:
                if self.jobs_removable:
                    self.stuck_jobs = 0
                    return CommandOutput(0, "", "")
                return CommandOutput(1, "", "Acceso denegado")
            if "PrintTestPage" in script:
                self.test_pages += 1
                return CommandOutput(0, "", "")
        return CommandOutput(0, "", "")


# --- Windows Update -------------------------------------------------------------------------------


@dataclass
class SimulatedUpdates:
    """Windows Update con la falla del escenario; la búsqueda falla con el código que esa falla da
    en Windows y vuelve a funcionar cuando se aplica el arreglo correcto."""

    system_root: Path
    services_disabled: bool = False
    disabled_by_policy: bool = False
    cache_broken: bool = False
    store_corrupt: bool = False
    online: bool = True
    free_gib: float = 80.0
    reboot_pending: bool = False
    wsus: str | None = None
    errors: list[tuple[int, str]] = field(default_factory=list)
    unknown_search_error: int | None = None
    pending: int = 4
    stopped: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for folder in ("SoftwareDistribution", "System32/catroot2"):
            (self.system_root / folder).mkdir(parents=True, exist_ok=True)

    def search_code(self) -> int:
        if self.services_disabled:
            return 0x80070422
        if self.cache_broken:
            return 0x80070002
        if self.store_corrupt:
            return 0x80073712
        if not self.online:
            return 0x8024402C
        return self.unknown_search_error or 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedUpdates:
        from honey_check.infrastructure.support.tools import updates

        monkeypatch.setenv("SYSTEMROOT", str(self.system_root))
        monkeypatch.setattr(
            updates,
            "service",
            lambda _env, name: updates.Service(
                name,
                not self.services_disabled and name not in self.stopped,
                self.services_disabled and name == "wuauserv",
            ),
        )
        monkeypatch.setattr(
            updates,
            "update_policy",
            lambda: updates.UpdatePolicy(
                wsus=self.wsus, automatic_disabled=self.disabled_by_policy
            ),
        )
        monkeypatch.setattr(
            updates, "pending_reboot", lambda: ["Windows Update"] if self.reboot_pending else []
        )
        monkeypatch.setattr(updates, "system_free_bytes", lambda: int(self.free_gib * 1024**3))
        monkeypatch.setattr(
            updates,
            "update_errors",
            lambda _env, days=7: [
                updates.UpdateError(code, title, datetime.now(UTC)) for code, title in self.errors
            ],
        )
        monkeypatch.setattr(
            updates,
            "endpoint_reachable",
            lambda policy: (policy.wsus or "servidores de Microsoft", self.online),
        )
        monkeypatch.setattr(updates, "_pause", lambda _s: None)
        return self

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        program = Path(args[0]).name.lower()
        line = " ".join([program, *args[1:]])
        self.calls.append(line)
        if program == "sc.exe" and args[1] == "config":
            self.services_disabled = False
        if program == "sc.exe" and args[1] == "stop":
            self.stopped.add(args[2])
        if program == "sc.exe" and args[1] == "start":
            self.stopped.discard(args[2])
        renewed = not (self.system_root / "SoftwareDistribution").exists()
        if program == "sc.exe" and args[1:3] == ["start", "wuauserv"] and renewed:
            self.cache_broken = False  # caché renovada: la carpeta vieja quedó renombrada
        if program == "dism.exe":
            self.store_corrupt = False
            return CommandOutput(0, "La operación de restauración se completó correctamente.", "")
        if program == "powershell.exe" and "CreateUpdateSearcher" in " ".join(args):
            code = self.search_code()
            body = {"ok": code == 0, "count": self.pending if code == 0 else 0, "code": code}
            return CommandOutput(0, json.dumps(body), "")
        return CommandOutput(0, "", "")


# --- Reparación de Windows (DISM y SFC) -----------------------------------------------------------


@dataclass
class SimulatedRepair:
    """Almacén de componentes y archivos del sistema con el daño del escenario. DISM y SFC
    imprimen su avance en vivo y SFC deja en CBS.log las mismas líneas «[SR]» que el real."""

    system_root: Path
    store: int = 0  # 0 sano, 1 reparable, 2 no reparable
    dism_has_source: bool = True
    damaged_files: int = 0  # los repara SFC si el almacén está sano
    unrepairable_files: int = 0  # SFC no puede hasta que DISM repara el almacén
    reboot_pending: bool = False
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        (self.system_root / "Logs" / "CBS").mkdir(parents=True, exist_ok=True)
        self.cbs.write_text(
            "2020-01-01 00:00:00, Info CSI [SR] Verify complete\n", encoding="utf-8"
        )

    @property
    def cbs(self) -> Path:
        return self.system_root / "Logs" / "CBS" / "CBS.log"

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedRepair:
        from honey_check.infrastructure.support.tools import repair

        monkeypatch.setenv("SYSTEMROOT", str(self.system_root))
        monkeypatch.setattr(
            repair, "pending_reboot", lambda: ["Windows Update"] if self.reboot_pending else []
        )
        monkeypatch.setattr(repair, "system_free_bytes", lambda: 60 * 1024**3)
        return self

    def write_cbs(self, *lines: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.cbs.open("a", encoding="utf-8") as log:
            for line in lines:
                log.write(f"{stamp}, Info                  CSI    00000001 [SR] {line}\n")

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        on_output: Any = None,
    ) -> CommandOutput:
        program = Path(args[0]).name.lower()
        self.calls.append(" ".join([program, *args[1:]]))
        if program == "powershell.exe" and "CheckHealth" in " ".join(args):
            return CommandOutput(0, f"{self.store}\r\n", "")
        if program == "dism.exe":
            for text in ("[=====     10.0%     ]", "[=========  62.3%  ]", "[======100.0%======]"):
                if on_output:
                    on_output(text)
            if self.dism_has_source:
                self.store = 0
                self.unrepairable_files = 0
                return CommandOutput(0, "La restauración se completó correctamente.", "")
            return CommandOutput(
                0x800F081F, "", "Error: 0x800f081f No se encontraron los archivos de origen."
            )
        if program == "sfc.exe":
            for text in ("Verificación 25% completada.", "Verificación 100% completada."):
                if on_output:
                    on_output(text)
            lines = [
                f"Repairing corrupted file C:/Windows/System32/f{i}.dll"
                for i in range(self.damaged_files)
            ]
            lines += [f"Cannot repair member file f{i}.sys" for i in range(self.unrepairable_files)]
            self.write_cbs(*lines, "Verify complete")
            self.damaged_files = 0
            return CommandOutput(0, "", "")
        return CommandOutput(0, "", "")


# --- Árbol de dispositivos --------------------------------------------------------------------------


@dataclass
class SimulatedDevices:
    """Nodos de dispositivo ficticios: `pnputil /remove-device` los quita de verdad del árbol,
    `/export-driver` deja un .inf en el respaldo y `/add-driver` lo cuenta como instalado."""

    nodes: list[Any]
    remove_fails: set[str] = field(default_factory=set)
    exports_fail: bool = False
    installed: list[str] = field(default_factory=list)
    forgotten: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def _find(self, instance: str) -> Any:
        return next((n for n in self.nodes if n.instance_id.upper() == instance.upper()), None)

    def is_present(self, instance: str) -> bool | None:
        node = self._find(instance)
        return None if node is None else bool(node.present)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedDevices:
        from honey_check.domain.peripherals import group_devices
        from honey_check.infrastructure.support.tools import devices

        monkeypatch.setattr(devices, "_live", lambda: group_devices(list(self.nodes)))
        monkeypatch.setattr(devices, "is_present", self.is_present)
        monkeypatch.setattr(devices, "uninstall", lambda _i: 13)  # la vía alternativa falla
        monkeypatch.setattr(devices.bluetooth, "forget", self._forget)
        monkeypatch.setattr(devices.time, "sleep", lambda _s: None)
        return self

    def _forget(self, mac: str) -> int:
        self.forgotten.append(mac)
        compact = mac.replace(":", "").upper()
        self.nodes = [n for n in self.nodes if compact not in n.instance_id.upper()]
        return 0

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        self.calls.append(" ".join([Path(args[0]).name.lower(), *args[1:]]))
        verb = args[1] if len(args) > 1 else ""
        if verb == "/remove-device":
            node = self._find(args[2])
            if node is None or node.present or args[2] in self.remove_fails:
                return CommandOutput(1, "", "No se pudo quitar")
            self.nodes.remove(node)
            return CommandOutput(0, "Dispositivo quitado.", "")
        if verb == "/export-driver":
            if self.exports_fail:
                return CommandOutput(1, "", "Acceso denegado")
            target = Path(args[3])
            target.mkdir(parents=True, exist_ok=True)
            (target / args[2]).write_text("; controlador ficticio", encoding="utf-8")
            return CommandOutput(0, "", "")
        if verb == "/add-driver":
            self.installed.append(Path(args[2]).name)
            return CommandOutput(0, "", "")
        return CommandOutput(0, "", "")


# --- Controladores ---------------------------------------------------------------------------------


@dataclass
class SimulatedDrivers:
    """Aparatos con su código de problema, una carpeta INF de Windows y pnputil: instalar un .inf
    que sirve le pone controlador al aparato; quitar un paquete lo borra de la carpeta INF."""

    nodes: list[Any]
    system: Path
    calls: list[str] = field(default_factory=list)
    install_fails: bool = False

    def install(self, monkeypatch: pytest.MonkeyPatch) -> SimulatedDrivers:
        from honey_check.infrastructure.support.tools import drivers

        (self.system / "INF").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(drivers, "_nodes", lambda: list(self.nodes))
        monkeypatch.setattr(drivers, "_SYSTEM", self.system)
        return self

    def _fix(self, inf_text: str) -> None:
        from dataclasses import replace

        upper = inf_text.upper()
        self.nodes = [
            replace(n, problem_code=0, driver_inf="oem90.inf")
            if any(h.upper() in upper for h in n.hardware_ids)
            else n
            for n in self.nodes
        ]

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        self.calls.append(" ".join([Path(args[0]).name.lower(), *args[1:]]))
        verb = args[1] if len(args) > 1 else ""
        if verb == "/add-driver":
            if self.install_fails:
                return CommandOutput(5, "", "Acceso denegado")
            self._fix(Path(args[2]).read_text(encoding="utf-8"))
            return CommandOutput(0, "", "")
        if verb == "/export-driver":
            source = self.system / "INF" / args[2]
            target = Path(args[3])
            target.mkdir(parents=True, exist_ok=True)
            for inf in [source] if args[2] != "*" else list((self.system / "INF").glob("oem*.inf")):
                (target / inf.stem).mkdir(exist_ok=True)
                (target / inf.stem / inf.name).write_text(inf.read_text(encoding="utf-8"), "utf-8")
            return CommandOutput(0, "", "")
        if verb == "/delete-driver":
            (self.system / "INF" / args[2]).unlink(missing_ok=True)
            return CommandOutput(0, "", "")
        if verb == "/remove-device":
            self._fix(
                " ".join(h for n in self.nodes if n.instance_id == args[2] for h in n.hardware_ids)
            )
            return CommandOutput(0, "", "")
        return CommandOutput(0, "", "")
