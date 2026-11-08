"""«Las directivas no se aplican»: diagnóstico, revisión y arreglo, con el dominio simulado."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.context import RunContext
from honey_check.application.support.ports import CommandOutput, SupportEnvironment
from honey_check.domain.support import CheckStatus
from honey_check.infrastructure.support.tools import domain, policies
from honey_check.infrastructure.windows.netdiag import DomainController

DC = DomainController(
    name="dc01.ficticio.local",
    address="10.0.0.10",
    domain="ficticio.local",
    forest="ficticio.local",
    site="Sede",
    client_site="Sede",
)

EVENT_1096 = (
    '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
    "<EventID>1096</EventID><TimeCreated SystemTime='{at}'/></System>"
    "<RenderingInfo><Message>Error al procesar. Archivo: "
    r"C:\Windows\System32\GroupPolicy\Machine\registry.pol"
    "</Message></RenderingInfo></Event>"
)


class Runner:
    """Responde a sc, nltest y wevtutil como un equipo de dominio ficticio."""

    def __init__(self, events: str = "", channel_ok: bool = True) -> None:
        self.events = events
        self.channel_ok = channel_ok
        self.calls: list[list[str]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        self.calls.append(list(args))
        program = Path(args[0]).name.lower()
        if program == "sc.exe":
            return CommandOutput(0, "STATE : 4  RUNNING", "")
        if program == "nltest.exe":
            ok = self.channel_ok
            return CommandOutput(0 if ok else 1, "0x0 NERR_Success" if ok else "0x5 ERROR", "")
        if program == "wevtutil.exe":
            return CommandOutput(0, self.events, "")
        return CommandOutput(0, "", "")


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Windows"
    (root / "System32" / "GroupPolicy" / "Machine").mkdir(parents=True)
    monkeypatch.setenv("SYSTEMROOT", str(root))
    return root


@pytest.fixture
def joined(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"dc": DC, "offset": 4.0, "ports": True, "sysvol": True}
    monkeypatch.setattr(domain, "membership", lambda: (True, "ficticio.local"))
    monkeypatch.setattr(
        domain, "last_machine_policy", lambda: datetime.now(UTC) - timedelta(days=2)
    )
    monkeypatch.setattr(
        policies,
        "find_domain_controller",
        lambda _d, **_k: (state["dc"], 0 if state["dc"] else 1355),
    )
    monkeypatch.setattr(policies, "remote_time_offset", lambda _s: state["offset"])
    monkeypatch.setattr(
        policies, "tcp_port_open", lambda _h, port, _t: state["ports"] or port == 88
    )

    def sysvol(name: str) -> policies.Finding:
        if state["sysvol"]:
            return policies._ok("sysvol", "SYSVOL", "Accesible")  # noqa: SLF001
        return policies.Finding("sysvol", "SYSVOL", CheckStatus.WARN, "x", fix="kerberos")

    monkeypatch.setattr(policies, "_sysvol", sysvol)
    yield state


def env(tmp_path: Path, runner: Runner, elevated: bool = False) -> SupportEnvironment:
    return SupportEnvironment(tmp_path, runner, elevated, None)


def test_header_of_registry_pol(tmp_path: Path) -> None:
    good = tmp_path / "bueno.pol"
    good.write_bytes(policies.REGISTRY_POL_HEADER + b"[datos]")
    bad = tmp_path / "malo.pol"
    bad.write_bytes(b"\x00" * 3)
    assert policies.pol_is_damaged(good) is False
    assert policies.pol_is_damaged(bad) is True
    assert policies.pol_is_damaged(tmp_path / "no-existe.pol") is False


def test_events_are_parsed_from_rendered_xml() -> None:
    events = policies.parse_events(EVENT_1096.format(at="2026-11-06T21:30:12.1234567Z"))
    assert [(e.id, e.at.hour) for e in events] == [(1096, 21)]
    assert "registry.pol" in events[0].message
    assert policies.parse_events("") == []
    assert policies.parse_events("<no es xml") == []


def test_healthy_domain_finds_no_cause(tmp_path: Path, system_root: Path, joined: Any) -> None:
    summary, checks, admin = policies._review({"target": "both"}, env(tmp_path, Runner(), True))  # noqa: SLF001
    assert admin
    assert summary.startswith("No se encontró una causa")
    assert all(c.status in (CheckStatus.OK, CheckStatus.INFO) for c in checks)


def test_skewed_clock_and_damaged_pol_are_fixed_causes(
    tmp_path: Path, system_root: Path, joined: Any
) -> None:
    joined["offset"] = 9 * 60
    (system_root / "System32" / "GroupPolicy" / "Machine" / "Registry.pol").write_bytes(b"basura")
    found = policies.diagnose(env(tmp_path, Runner(), True))
    assert {f.fix for f in found.fixes} == {"time", "pol_machine"}
    assert not found.blocking
    summary, checks, _ = policies._review({"target": "both"}, env(tmp_path, Runner(), True))  # noqa: SLF001
    assert "hora desfasada" in summary and "Registry.pol de equipo dañado" in summary
    # Lo que hay que corregir va primero en la lista.
    assert checks[0].status is CheckStatus.WARN


def test_event_1096_and_bad_header_make_a_single_row(
    tmp_path: Path, system_root: Path, joined: Any
) -> None:
    (system_root / "System32" / "GroupPolicy" / "Machine" / "Registry.pol").write_bytes(b"x")
    recent = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    found = policies.diagnose(env(tmp_path, Runner(events=EVENT_1096.format(at=recent)), True))
    assert [f.key for f in found.findings].count("pol_machine") == 1


def test_unreachable_domain_blocks_instead_of_trying(
    tmp_path: Path, system_root: Path, joined: Any
) -> None:
    joined["dc"] = None
    found = policies.diagnose(env(tmp_path, Runner(), True))
    assert found.blocking and found.blocking[0].key == "dc"
    assert found.blocking[0].link is not None
    joined["dc"] = DC
    joined["ports"] = False
    found = policies.diagnose(env(tmp_path, Runner(), True))
    assert [f.key for f in found.blocking] == ["ports"]
    assert "389" in found.blocking[0].detail


def test_secure_channel_is_checked_at_start_when_not_elevated(
    tmp_path: Path, system_root: Path, joined: Any
) -> None:
    runner = Runner(channel_ok=False)
    found = policies.diagnose(env(tmp_path, runner, False))
    channel = next(f for f in found.findings if f.key == "channel")
    assert channel.status is CheckStatus.INFO and channel.fix == "channel"
    assert not any(Path(c[0]).name == "nltest.exe" for c in runner.calls)


def test_damaged_pol_is_backed_up_and_renamed(tmp_path: Path, system_root: Path) -> None:
    pol = system_root / "System32" / "GroupPolicy" / "Machine" / "Registry.pol"
    pol.write_bytes(b"basura")
    context = RunContext(
        env(tmp_path / "datos", Runner(), True), CancelToken(), "prueba", lambda: None
    )
    (tmp_path / "datos").mkdir()
    outcome = policies._fix_pol("machine", context)  # noqa: SLF001
    assert outcome.status is CheckStatus.OK
    assert not pol.exists()
    renamed = list(pol.parent.glob("Registry.pol.dañado-*"))
    assert len(renamed) == 1 and renamed[0].read_bytes() == b"basura"
    assert Path(outcome.technical or "").read_bytes() == b"basura"
