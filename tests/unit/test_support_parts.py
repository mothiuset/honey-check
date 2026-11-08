"""Piezas del soporte: catálogo, procesos de instalación, SNMP, recorrido de archivos y Registro."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.params import validate
from honey_check.application.support.procedures import ProcedureNotFound, ProcedureService
from honey_check.composition import support_tools
from honey_check.domain.procedures import TEMPLATES, ProcedureStep, StepKind, StepState
from honey_check.domain.support import Risk
from honey_check.infrastructure.support import snmp
from honey_check.infrastructure.support.filesystem import is_folder, iter_files
from honey_check.infrastructure.support.procedure_store import FileProcedureStore
from honey_check.infrastructure.support.tools.registry import is_policy, split
from honey_check.infrastructure.support.winops import split_command_line


class Ctx:
    def __init__(self) -> None:
        self.cancel = CancelToken()
        self.log: list[str] = []
        self.steps: list[tuple[int, int]] = []

    def info(self, text: str) -> None:
        self.log.append(text)

    warn = error = info

    def progress(self, done: int, total: int, label: str | None = None) -> None:
        self.steps.append((done, total))


@pytest.fixture
def procedures(tmp_path: Path) -> ProcedureService:
    return ProcedureService(FileProcedureStore(lambda: tmp_path))


# --- Catálogo ------------------------------------------------------------------------------------


def test_catalog_ids_are_unique_and_destructive_tools_say_what_they_back_up(
    procedures: ProcedureService,
) -> None:
    tools = support_tools(procedures)
    ids = [t.definition.id for t in tools]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 55
    for item in tools:
        definition = item.definition
        assert definition.title and definition.description, definition.id
        assert definition.risk in Risk


def test_template_tool_steps_are_valid_calls_to_the_catalog(procedures: ProcedureService) -> None:
    catalog = {t.definition.id: t.definition for t in support_tools(procedures)}
    for template in TEMPLATES:
        for step in template.steps:
            if step.kind is StepKind.TOOL:
                definition = catalog[step.params["tool"]]
                params = {k: v for k, v in step.params["tool_params"].items() if v != ""}
                validate(definition, params)


# --- Procesos ------------------------------------------------------------------------------------


def test_saving_a_procedure_creates_versions_and_never_overwrites(
    procedures: ProcedureService, tmp_path: Path
) -> None:
    document = {
        "slug": "puesto-ficticio",
        "name": "Puesto ficticio",
        "steps": [{"id": "a", "kind": "manual", "title": "Revisar el cableado"}],
    }
    first = procedures.save(document)
    second = procedures.save({**document, "name": "Puesto ficticio (revisado)"})
    assert (first.version, second.version) == (1, 2)
    assert [p.version for p in procedures.versions("puesto-ficticio")] == [2, 1]
    assert procedures.get("puesto-ficticio", 1).name == "Puesto ficticio"
    assert sorted(p.name for p in (tmp_path / "procesos" / "puesto-ficticio").iterdir()) == [
        "v0001.json",
        "v0002.json",
    ]
    assert procedures.remove("puesto-ficticio") == 2
    assert any((tmp_path / "papelera").rglob("v0002.json"))
    with pytest.raises(ProcedureNotFound):
        procedures.versions("puesto-ficticio")


def test_templates_are_listed_until_a_saved_version_replaces_them(
    procedures: ProcedureService,
) -> None:
    slugs = {p.slug for p in procedures.catalog()}
    assert {"equipo-nuevo", "oficina", "firma-digital"} <= slugs
    template = procedures.get("oficina")
    saved = procedures.save(template.model_dump(by_alias=True) | {"name": "Oficina del área"})
    names = [p.name for p in procedures.catalog() if p.slug == "oficina"]
    assert names == ["Oficina del área"]
    assert saved.template is False


@pytest.mark.parametrize(
    "document",
    [
        {"slug": "Mayúsculas", "name": "x", "steps": [{"id": "a", "kind": "manual", "title": "t"}]},
        {"slug": "valido", "name": "x", "steps": []},
        {
            "slug": "valido",
            "name": "x",
            "steps": [
                {"id": "a", "kind": "manual", "title": "t"},
                {"id": "a", "kind": "manual", "title": "u"},
            ],
        },
        {
            "slug": "valido",
            "name": "x",
            "steps": [{"id": "a", "kind": "borrar-todo", "title": "t"}],
        },
    ],
)
def test_invalid_procedures_are_rejected(procedures: ProcedureService, document: dict) -> None:
    with pytest.raises(ValueError):
        procedures.save(document)


class ScriptedExecutor:
    def __init__(self, outcomes: dict[str, bool]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def execute(self, step: ProcedureStep, ctx: Ctx) -> tuple[bool, str]:
        self.calls.append(step.id)
        return self.outcomes.get(step.id, True), f"resultado de {step.id}"


def _procedure(procedures: ProcedureService) -> None:
    procedures.save(
        {
            "slug": "prueba",
            "name": "Prueba",
            "steps": [
                {
                    "id": "instalar",
                    "kind": "install",
                    "title": "Instalar",
                    "params": {"file": "x.msi"},
                },
                {"id": "opcional", "kind": "verify_file", "title": "Opcional", "optional": True},
                {"id": "manual", "kind": "manual", "title": "Revisar"},
                {"id": "servicio", "kind": "verify_service", "title": "Servicio"},
                {"id": "reinicio", "kind": "reboot", "title": "Reiniciar"},
            ],
        }
    )


def test_run_stops_at_manual_step_and_resumes_after_marking(procedures: ProcedureService) -> None:
    _procedure(procedures)
    run = procedures.begin(procedures.get("prueba"), "EQUIPO-FICTICIO")
    executor = ScriptedExecutor({"opcional": False})
    ctx = Ctx()
    run = procedures.advance(run, executor, ctx)  # type: ignore[arg-type]
    states = {r.step: r.state for r in run.steps}
    assert states == {
        "instalar": StepState.OK,
        "opcional": StepState.SKIPPED,  # opcional que falla: omitido con su motivo
        "manual": StepState.WAITING,
        "servicio": StepState.PENDING,
        "reinicio": StepState.PENDING,
    }
    assert not run.finished
    procedures.mark(run.id, "manual", True, None)
    run = procedures.advance(procedures.run(run.id), executor, ctx)  # type: ignore[arg-type]
    assert executor.calls == ["instalar", "opcional", "servicio"]  # lo hecho no se repite
    assert run.record("reinicio").state is StepState.WAITING
    run = procedures.mark(run.id, "reinicio", True, "Reiniciado por el técnico")
    assert run.finished
    assert procedures.runs()[0].finished


def test_required_failure_stops_and_retry_is_explicit(procedures: ProcedureService) -> None:
    _procedure(procedures)
    run = procedures.begin(procedures.get("prueba"), None)
    executor = ScriptedExecutor({"instalar": False})
    ctx = Ctx()
    run = procedures.advance(run, executor, ctx)  # type: ignore[arg-type]
    assert run.record("instalar").state is StepState.FAILED
    assert run.record("opcional").state is StepState.PENDING
    run = procedures.advance(run, executor, ctx)  # type: ignore[arg-type]
    assert executor.calls == ["instalar"]  # sin reintento explícito no se repite
    executor.outcomes["instalar"] = True
    run = procedures.advance(run, executor, ctx, retry_failed=True)  # type: ignore[arg-type]
    assert run.record("instalar").state is StepState.OK
    with pytest.raises(ProcedureNotFound):
        procedures.mark(run.id, "no-existe", True, None)


# --- SNMP ----------------------------------------------------------------------------------------


def _response(request_id: int, bindings: list[tuple[str, int, bytes]]) -> bytes:
    body = b"".join(
        snmp._tlv(0x30, snmp._oid(oid) + snmp._tlv(tag, raw)) for oid, tag, raw in bindings
    )
    pdu = snmp._tlv(
        0xA2,
        snmp._integer(request_id) + snmp._integer(0) + snmp._integer(0) + snmp._tlv(0x30, body),
    )
    return snmp._tlv(0x30, snmp._integer(1) + snmp._tlv(0x04, b"public") + pdu)


def test_snmp_request_and_response_round_trip() -> None:
    request = snmp._request(0xA0, "public", ["1.3.6.1.2.1.43.10.2.1.4.1.1"], 4242)
    assert request[0] == 0x30 and b"public" in request
    serial = "1.3.6.1.2.1.43.5.1.1.17.1"
    pages = "1.3.6.1.2.1.43.10.2.1.4.1.1"
    mac_oid = "1.3.6.1.2.1.2.2.1.6.2"
    data = _response(
        4242,
        [
            (serial, 0x04, b"SN-FICTICIO-0001\x00"),
            (pages, 0x41, (123456).to_bytes(3, "big")),
            (mac_oid, 0x04, bytes([0x00, 0x11, 0x22, 0x33, 0x44, 0x55])),
            ("1.3.6.1.2.1.1.5.0", 0x81, b""),
        ],
    )
    values = dict(snmp._parse(data, 4242))
    assert snmp.text(values[serial]) == "SN-FICTICIO-0001"
    assert values[pages] == 123456
    assert snmp.mac(values[mac_oid]) == "00:11:22:33:44:55"
    assert values["1.3.6.1.2.1.1.5.0"] is None
    with pytest.raises(snmp.SnmpError):
        snmp._parse(data, 1)


def test_snmp_long_lengths_and_large_oid_parts() -> None:
    oid = "1.3.6.1.4.1.11.2.3.9.4.2.1.1.3.3.0"
    assert snmp._decode_oid(snmp._oid(oid)[2:]) == oid
    assert snmp._decode_oid(snmp._oid("1.3.6.1.4.1.367.3")[2:]) == "1.3.6.1.4.1.367.3"
    long_text = b"x" * 300
    tag, value, end = snmp._read(snmp._tlv(0x04, long_text), 0)
    assert (tag, value, end) == (0x04, long_text, 304)


# --- Archivos ------------------------------------------------------------------------------------


def test_iter_files_filters_and_does_not_follow_junctions(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "uno.tmp").write_bytes(b"1")
    (tmp_path / "a" / "b" / "dos.tmp").write_bytes(b"22")
    (tmp_path / "a" / "b" / "tres.log").write_bytes(b"333")
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "ajeno.tmp").write_bytes(b"ajeno")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(tmp_path / "a" / "union"), str(outside)],
        check=True,
        capture_output=True,
    )
    ctx = Ctx()
    names = sorted(p.name for p, _ in iter_files(tmp_path / "a", ctx))  # type: ignore[arg-type]
    assert names == ["dos.tmp", "tres.log", "uno.tmp"]
    tmp_only = sorted(p.name for p, _ in iter_files(tmp_path / "a", ctx, pattern="*.TMP"))  # type: ignore[arg-type]
    assert tmp_only == ["dos.tmp", "uno.tmp"]
    flat = [p.name for p, _ in iter_files(tmp_path / "a", ctx, recursive=False)]  # type: ignore[arg-type]
    assert flat == ["uno.tmp"]
    assert is_folder(tmp_path / "a") and not is_folder(tmp_path / "no-existe")
    (tmp_path / "a" / "union").rmdir()


# --- Registro y comandos -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (r"HKLM\SOFTWARE\Policies\Microsoft\Windows", True),
        (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", True),
        (r"hkcu\software\policies", True),
        (r"HKCU\Software\PoliciesFicticias\App", False),
        (r"HKCU\Software\Fabrikam\Programa", False),
    ],
)
def test_policy_keys_are_recognized(key: str, expected: bool) -> None:
    assert is_policy(key) is expected


def test_registry_paths_accept_long_and_short_hive_names() -> None:
    import winreg

    assert split(r"HKEY_CURRENT_USER\Software\Fabrikam")[:2] == (
        winreg.HKEY_CURRENT_USER,
        r"Software\Fabrikam",
    )
    assert split(r"HKLM\SOFTWARE\Fabrikam\\")[2].upper() == r"HKLM\SOFTWARE\FABRIKAM"
    with pytest.raises(ValueError):
        split(r"HKXX\Software")


def test_command_lines_from_the_registry_are_split_without_a_shell() -> None:
    assert split_command_line('"C:\\Program Files\\Fabrikam\\unins000.exe" /SILENT') == [
        r"C:\Program Files\Fabrikam\unins000.exe",
        "/SILENT",
    ]
    assert (
        split_command_line("MsiExec.exe /X{11111111-2222-3333-4444-555555555555}")[0]
        .lower()
        .endswith(r"system32\msiexec.exe")
    )
    assert split_command_line("") == []
