"""Consultas de lectura mediante Windows PowerShell 5.1 en subprocesos de vida corta.

Los scripts son constantes de este módulo y los datos viajan por stdin como JSON, de modo que
una ruta o un nombre tomados del Registro no pueden convertirse en código. No se usa
`-EncodedCommand` ni se altera la política de ejecución: el comando queda visible y auditable,
y si AppLocker o WDAC bloquean PowerShell el módulo lo declara en lugar de eludirlo.

La salida se emite solo en ASCII (con escapes \\uXXXX) porque en Constrained Language no se
puede cambiar `[Console]::OutputEncoding`; así el resultado no depende de la página de códigos.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from honey_check.application.ports import (
    AppxQueryError,
    CancelToken,
    CimError,
    CimErrorKind,
    CimQuery,
    CimResult,
    CollectionCancelled,
    SignatureResult,
)

from .process import OutputTooLarge, ProcessRunner, ProcessTimeout, system32_path

log = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAMESPACE = re.compile(r"^[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*$")
_WHERE = re.compile(r"^[A-Za-z0-9_ <>=']+$")
_MAX_RETRIES = 1
_RETRY_DELAY_S = 0.5
# Una clase colgada no debe consumir todo el presupuesto del módulo y dejar sin datos a las demás.
_PER_CLASS_TIMEOUT_S = 25

# Convierte el objeto en JSON ASCII sin usar tipos vetados en Constrained Language.
_EMIT = r"""
function Emit($value) {
  $json = ConvertTo-Json -InputObject $value -Depth 6 -Compress
  $chars = @([regex]::Matches($json, '[^\x00-\x7e]') | ForEach-Object { $_.Value } | Select-Object -Unique)
  foreach ($c in $chars) { $json = $json.Replace($c, ('\u{0:x4}' -f [int][char]$c)) }
  $json
}
"""

_CIM_SCRIPT = (
    r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$queries = ($input | Out-String) | ConvertFrom-Json
$results = @()
foreach ($q in $queries) {
  try {
    $params = @{ Namespace = $q.namespace; ClassName = $q.class; OperationTimeoutSec = [int]$q.timeout; ErrorAction = 'Stop' }
    if ($q.where) { $params.Filter = $q.where }
    $rows = @()
    foreach ($item in @(Get-CimInstance @params)) {
      $row = @{}
      foreach ($p in $q.properties) {
        $v = $item.$p
        if ($v -is [datetime]) { $v = $v.ToUniversalTime().ToString('o') }
        $row[$p] = $v
      }
      $rows += $row
    }
    $results += @{ ok = $true; rows = $rows }
  } catch {
    $results += @{ ok = $false; native = "$($_.Exception.NativeErrorCode)"; id = "$($_.FullyQualifiedErrorId)"; message = "$($_.Exception.Message)" }
  }
}
"""
    + _EMIT
    + r"""
Emit @{ results = $results }
"""
)

_SIGNATURE_SCRIPT = (
    r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$paths = ($input | Out-String) | ConvertFrom-Json
$results = @()
foreach ($path in $paths) {
  try {
    $s = Get-AuthenticodeSignature -LiteralPath $path
    $signer = $null
    if ($s.SignerCertificate) { $signer = "$($s.SignerCertificate.Subject)" }
    $results += @{ path = $path; status = "$($s.Status)"; signer = $signer }
  } catch {
    $results += @{ path = $path; status = 'UnknownError'; signer = $null }
  }
}
"""
    + _EMIT
    + r"""
Emit @{ results = $results }
"""
)

_APPX_SCRIPT = (
    r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$rows = @()
foreach ($p in @(Get-AppxPackage)) {
  $rows += @{
    Name = "$($p.Name)"; Publisher = "$($p.Publisher)"; Version = "$($p.Version)";
    Architecture = "$($p.Architecture)"; InstallLocation = "$($p.InstallLocation)";
    PackageFullName = "$($p.PackageFullName)"; SignatureKind = "$($p.SignatureKind)";
    IsFramework = [bool]$p.IsFramework; IsResourcePackage = [bool]$p.IsResourcePackage;
    IsBundle = [bool]$p.IsBundle; NonRemovable = [bool]$p.NonRemovable
  }
}
"""
    + _EMIT
    + r"""
Emit @{ rows = $rows }
"""
)

_LANGUAGE_MODE_SCRIPT = (
    'ConvertTo-Json -InputObject "$($ExecutionContext.SessionState.LanguageMode)" -Compress'
)

_ACCESS_DENIED = ("accessdenied", "0x80041003", "0x80070005", "access denied", "acceso denegado")
_NOT_AVAILABLE = (
    "0x8004100e",  # espacio de nombres inválido
    "0x80041010",  # clase inválida
    "0x80041002",  # no encontrado
    "invalidclass",
    "invalidnamespace",
    "notfound",
    "not supported",
    "notsupported",
    "0x8004100c",
)
_TRANSIENT = ("0x800706ba", "0x800706be", "0x80041033", "0x80041032", "0x80041006", "rpc server")
_TIMEOUT = ("timeout", "timed out", "0x80338029", "0x80338126")


def classify_cim_error(native: str, identifier: str, message: str) -> CimErrorKind:
    text = f"{native} {identifier} {message}".lower()
    for markers, kind in (
        (_ACCESS_DENIED, CimErrorKind.ACCESS_DENIED),
        (_NOT_AVAILABLE, CimErrorKind.NOT_AVAILABLE),
        (_TIMEOUT, CimErrorKind.TIMEOUT),
        (_TRANSIENT, CimErrorKind.TRANSIENT),
    ):
        if any(marker in text for marker in markers):
            return kind
    # Windows PowerShell devuelve el código 3 (espacio de nombres inválido) sin texto estable.
    if native.strip() == "3":
        return CimErrorKind.NOT_AVAILABLE
    return CimErrorKind.FAILED


def _short(text: str, limit: int = 240) -> str:
    return " ".join(text.split())[:limit]


class PowerShellFailure(Exception):
    def __init__(self, kind: CimErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class PowerShell:
    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner
        self._exe = str(system32_path("WindowsPowerShell", "v1.0", "powershell.exe"))
        self._cwd = system32_path()
        # PowerShell 5.1 hereda PSModulePath: si el proceso padre lo apuntó a los módulos de
        # PowerShell 7, los módulos de sistema dejan de cargar. Sin la variable usa los suyos.
        self._env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}

    def run_json(self, script: str, payload: Any, cancel: CancelToken, timeout_s: float) -> Any:
        stdin = json.dumps(payload, ensure_ascii=True).encode("ascii")
        args = [self._exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script]
        try:
            result = self._runner.run(
                args, stdin=stdin, timeout_s=timeout_s, cancel=cancel, cwd=self._cwd, env=self._env
            )
        except ProcessTimeout as error:
            raise PowerShellFailure(CimErrorKind.TIMEOUT, "PowerShell superó el límite") from error
        except OutputTooLarge as error:
            raise PowerShellFailure(CimErrorKind.FAILED, "salida demasiado grande") from error
        except PermissionError as error:
            raise PowerShellFailure(
                CimErrorKind.ACCESS_DENIED, "la directiva del equipo no permite iniciar PowerShell"
            ) from error
        except OSError as error:
            # WinError 1260: AppLocker/WDAC bloqueó el programa. Se informa; no se elude.
            kind = (
                CimErrorKind.ACCESS_DENIED
                if getattr(error, "winerror", None) in (5, 1260)
                else CimErrorKind.FAILED
            )
            raise PowerShellFailure(
                kind, f"no se pudo iniciar PowerShell ({type(error).__name__})"
            ) from error

        if result.returncode != 0:
            detail = _short(result.stderr.decode("ascii", "replace"))
            raise PowerShellFailure(
                CimErrorKind.TRANSIENT, f"PowerShell terminó con {result.returncode}: {detail}"
            )
        text = result.stdout.decode("ascii", "replace").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise PowerShellFailure(CimErrorKind.TRANSIENT, "salida JSON inválida") from error


def _validated(query: CimQuery) -> dict[str, Any]:
    if not _NAMESPACE.match(query.namespace) or not _IDENTIFIER.match(query.class_name):
        raise ValueError(f"consulta CIM no permitida: {query.source}")
    if not all(_IDENTIFIER.match(name) for name in query.properties):
        raise ValueError(f"propiedades CIM no permitidas: {query.source}")
    if query.where is not None and not _WHERE.match(query.where):
        raise ValueError(f"filtro CIM no permitido: {query.source}")
    return {
        "namespace": query.namespace,
        "class": query.class_name,
        "properties": list(query.properties),
        "where": query.where,
    }


class PowerShellCim:
    """Implementa CimPort. Una clase que falla no afecta a las demás del mismo lote."""

    def __init__(self, powershell: PowerShell) -> None:
        self._ps = powershell

    def query(
        self, queries: Sequence[CimQuery], cancel: CancelToken, timeout_s: float
    ) -> list[CimResult]:
        payload = [_validated(query) for query in queries]
        results: list[CimResult | None] = [None] * len(queries)
        pending = list(range(len(queries)))
        deadline = time.monotonic() + timeout_s
        for attempt in range(_MAX_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                break
            batch = [
                {**payload[i], "timeout": max(1, min(_PER_CLASS_TIMEOUT_S, int(remaining)))}
                for i in pending
            ]
            retry: list[int] = []
            try:
                answer = self._ps.run_json(_CIM_SCRIPT, batch, cancel, remaining)
                rows = answer.get("results") if isinstance(answer, dict) else None
                if not isinstance(rows, list) or len(rows) != len(pending):
                    raise PowerShellFailure(CimErrorKind.TRANSIENT, "respuesta incompleta")
            except PowerShellFailure as failure:
                error = CimError(failure.kind, _short(failure.message))
                for index in pending:
                    results[index] = CimResult(error=error, retries=attempt)
                if failure.kind is not CimErrorKind.TRANSIENT:
                    return [self._finish(r) for r in results]
                retry = list(pending)
            else:
                for index, row in zip(pending, rows, strict=True):
                    outcome = self._parse(row, attempt)
                    results[index] = outcome
                    if outcome.error and outcome.error.kind is CimErrorKind.TRANSIENT:
                        retry.append(index)
            if not retry:
                break
            pending = retry
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_S)
        return [self._finish(r) for r in results]

    @staticmethod
    def _finish(result: CimResult | None) -> CimResult:
        if result is None:
            return CimResult(error=CimError(CimErrorKind.TIMEOUT, "sin tiempo para la consulta"))
        return result

    @staticmethod
    def _parse(row: Mapping[str, Any], attempt: int) -> CimResult:
        if row.get("ok"):
            data = row.get("rows") or []
            rows = data if isinstance(data, list) else [data]
            return CimResult(rows=tuple(rows), retries=attempt)
        message = _short(str(row.get("message") or "consulta fallida"))
        kind = classify_cim_error(str(row.get("native") or ""), str(row.get("id") or ""), message)
        return CimResult(error=CimError(kind, message), retries=attempt)


_SIGNATURE_STATUS = {
    "Valid": "valid",
    "NotSigned": "not_signed",
    "HashMismatch": "hash_mismatch",
    "NotTrusted": "not_trusted",
    "NotSupportedFileFormat": "not_supported",
    "UnknownError": "unknown_error",
}
_SIGNATURE_BATCH = 40


class PowerShellSignatures:
    """Verifica firmas por lotes dentro de un presupuesto de tiempo; lo demás queda sin revisar."""

    def __init__(self, powershell: PowerShell) -> None:
        self._ps = powershell

    def inspect(
        self, paths: Sequence[str], cancel: CancelToken, timeout_s: float
    ) -> dict[str, SignatureResult]:
        found: dict[str, SignatureResult] = {}
        deadline = time.monotonic() + timeout_s
        for start in range(0, len(paths), _SIGNATURE_BATCH):
            cancel.raise_if_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                break
            batch = list(paths[start : start + _SIGNATURE_BATCH])
            try:
                answer = self._ps.run_json(_SIGNATURE_SCRIPT, batch, cancel, remaining)
            except PowerShellFailure as failure:
                log.info("Lote de firmas sin completar: %s", failure.kind)
                if failure.kind in (CimErrorKind.ACCESS_DENIED, CimErrorKind.TIMEOUT):
                    break
                continue
            rows = answer.get("results") if isinstance(answer, dict) else None
            for row in rows if isinstance(rows, list) else []:
                status = _SIGNATURE_STATUS.get(str(row.get("status")), "unknown_error")
                found[str(row.get("path"))] = SignatureResult(status, row.get("signer"))
        return found


class PowerShellAppx:
    def __init__(self, powershell: PowerShell) -> None:
        self._ps = powershell

    def packages(self, cancel: CancelToken, timeout_s: float) -> list[Mapping[str, Any]]:
        try:
            answer = self._ps.run_json(_APPX_SCRIPT, None, cancel, timeout_s)
        except PowerShellFailure as failure:
            raise AppxQueryError(failure.kind, failure.message) from failure
        rows = answer.get("rows") if isinstance(answer, dict) else None
        if rows is None:
            return []
        return rows if isinstance(rows, list) else [rows]


class PowerShellInfo:
    def __init__(self, powershell: PowerShell) -> None:
        self._ps = powershell

    def language_mode(self, cancel: CancelToken, timeout_s: float) -> str | None:
        try:
            value = self._ps.run_json(_LANGUAGE_MODE_SCRIPT, None, cancel, timeout_s)
        except (PowerShellFailure, CollectionCancelled):
            return None
        return value if isinstance(value, str) else None
