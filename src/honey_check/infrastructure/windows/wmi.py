"""Consultas WMI de lectura por COM nativo, sin PowerShell.

Implementa CimPort con las mismas filas que el adaptador de PowerShell: fechas en ISO 8601 UTC,
enteros sin signo corregidos y enteros de 64 bits como números. Así los recolectores no cambian
y Honey Check funciona aunque PowerShell esté bloqueado o en Constrained Language.
"""

from __future__ import annotations

import ctypes
import logging
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from honey_check.application.ports import (
    CancelToken,
    CimError,
    CimErrorKind,
    CimQuery,
    CimResult,
)

from .com import (
    GUID,
    Bstr,
    ComError,
    check,
    clear_variant,
    com_apartment,
    create_instance,
    method,
    new_variant,
    release,
    set_proxy_blanket,
    variant_from,
    variant_value,
)

log = logging.getLogger(__name__)

_CLSID_WBEM_LOCATOR = GUID.parse("{4590F811-1D3A-11D0-891F-00AA004B2E24}")
_IID_WBEM_LOCATOR = GUID.parse("{DC12A687-737F-11CF-884D-00AA004B2E24}")

_WBEM_FLAG_CONNECT_USE_MAX_WAIT = 0x80
_WBEM_FLAG_RETURN_IMMEDIATELY = 0x10
_WBEM_FLAG_FORWARD_ONLY = 0x20
_WBEM_S_TIMEDOUT = 0x40004
_BATCH = 64
_WAIT_MS = 400
_PER_CLASS_TIMEOUT_S = 25.0

# Índices de vtable (IUnknown ocupa 0-2).
_LOCATOR_CONNECT = 3
_SERVICES_EXEC_QUERY = 20
_ENUM_NEXT = 4
_OBJECT_GET = 4

_CIM_UINT32 = 19
_CIM_SINT64 = 20
_CIM_UINT64 = 21
_CIM_DATETIME = 101

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAMESPACE = re.compile(r"^[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*$")
_WHERE = re.compile(r"^[A-Za-z0-9_ <>=']+$")
_DMTF = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.(\d{6})([+-])(\d{3})$")

_ACCESS_DENIED = {0x80041003, 0x80070005}
_NOT_AVAILABLE = {0x8004100E, 0x80041010, 0x80041002, 0x8004100C, 0x80041013, 0x80041011}
_TRANSIENT = {0x800706BA, 0x800706BE, 0x80041006, 0x80010108, 0x800706BF, 0x8004101D, 0x80041045}
_TIMEOUT = {0x80043001}


class WmiTimeout(Exception):
    pass


def classify(hresult: int) -> CimErrorKind:
    code = hresult & 0xFFFFFFFF
    if code in _ACCESS_DENIED:
        return CimErrorKind.ACCESS_DENIED
    if code in _NOT_AVAILABLE:
        return CimErrorKind.NOT_AVAILABLE
    if code in _TIMEOUT:
        return CimErrorKind.TIMEOUT
    if code in _TRANSIENT:
        return CimErrorKind.TRANSIENT
    return CimErrorKind.FAILED


def dmtf_to_iso(text: str) -> str | None:
    """`20240101123045.000000-300` (hora local con desfase en minutos) a ISO 8601 en UTC."""
    match = _DMTF.match(text)
    if not match:
        return None  # intervalos, comodines o fechas incompletas
    year, month, day, hour, minute, second, micro, sign, offset = match.groups()
    try:
        minutes = int(offset) * (1 if sign == "+" else -1)
        moment = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            int(micro),
            tzinfo=timezone(timedelta(minutes=minutes)),
        )
    except ValueError:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def convert(value: Any, cim_type: int) -> Any:
    base = cim_type & 0x0FFF
    if isinstance(value, list):
        return [convert(item, base) for item in value]
    if value is None:
        return None
    if base == _CIM_UINT32 and isinstance(value, int) and value < 0:
        return value + 2**32
    if base in (_CIM_SINT64, _CIM_UINT64) and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if base == _CIM_DATETIME and isinstance(value, str):
        return dmtf_to_iso(value)
    return value


def _wql(query: CimQuery) -> str:
    if not _NAMESPACE.match(query.namespace) or not _IDENTIFIER.match(query.class_name):
        raise ValueError(f"consulta CIM no permitida: {query.source}")
    if not all(_IDENTIFIER.match(name) for name in query.properties):
        raise ValueError(f"propiedades CIM no permitidas: {query.source}")
    if query.where is not None and not _WHERE.match(query.where):
        raise ValueError(f"filtro CIM no permitido: {query.source}")
    # Solo identificadores y filtros ya validados con listas de caracteres permitidos.
    wql = f"SELECT {', '.join(query.properties)} FROM {query.class_name}"  # noqa: S608
    return f"{wql} WHERE {query.where}" if query.where else wql


class _Connection:
    """IWbemServices de un espacio de nombres, con la seguridad de proxy de WMI."""

    def __init__(self, locator: ctypes.c_void_p, namespace: str) -> None:
        self.pointer = ctypes.c_void_p()
        connect = method(
            locator,
            _LOCATOR_CONNECT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        with Bstr(namespace.replace("/", "\\")) as path:
            check(
                connect(
                    path,
                    None,
                    None,
                    None,
                    _WBEM_FLAG_CONNECT_USE_MAX_WAIT,
                    None,
                    None,
                    ctypes.byref(self.pointer),
                ),
                "ConnectServer",
            )
        set_proxy_blanket(self.pointer)

    def close(self) -> None:
        release(self.pointer)

    def rows(self, query: CimQuery, cancel: CancelToken, deadline: float) -> list[dict[str, Any]]:
        enumerator = ctypes.c_void_p()
        execute = method(
            self.pointer,
            _SERVICES_EXEC_QUERY,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        with Bstr("WQL") as language, Bstr(_wql(query)) as text:
            check(
                execute(
                    language,
                    text,
                    _WBEM_FLAG_RETURN_IMMEDIATELY | _WBEM_FLAG_FORWARD_ONLY,
                    None,
                    ctypes.byref(enumerator),
                ),
                "ExecQuery",
            )
        try:
            return self._drain(enumerator, query.properties, cancel, deadline)
        finally:
            release(enumerator)

    @staticmethod
    def _drain(
        enumerator: ctypes.c_void_p,
        properties: Sequence[str],
        cancel: CancelToken,
        deadline: float,
    ) -> list[dict[str, Any]]:
        objects = (ctypes.c_void_p * _BATCH)()
        returned = ctypes.c_ulong()
        next_batch = method(
            enumerator,
            _ENUM_NEXT,
            ctypes.c_long,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        )
        rows: list[dict[str, Any]] = []
        while True:
            cancel.raise_if_cancelled()
            if time.monotonic() > deadline:
                raise WmiTimeout
            hr = next_batch(_WAIT_MS, _BATCH, objects, ctypes.byref(returned))
            if hr < 0:
                raise ComError(hr, "IEnumWbemClassObject::Next")
            for index in range(returned.value):
                item = ctypes.c_void_p(objects[index])
                try:
                    rows.append(_read(item, properties))
                finally:
                    release(item)
            if hr == _WBEM_S_TIMEDOUT:
                continue
            if returned.value < _BATCH:
                return rows


def _read(item: ctypes.c_void_p, properties: Sequence[str]) -> dict[str, Any]:
    get = method(
        item,
        _OBJECT_GET,
        ctypes.c_wchar_p,
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_long),
        ctypes.c_void_p,
    )
    row: dict[str, Any] = {}
    for name in properties:
        variant = new_variant()
        cim_type = ctypes.c_long()
        try:
            hr = get(name, 0, ctypes.byref(variant), ctypes.byref(cim_type), None)
            row[name] = convert(variant_value(variant), cim_type.value) if hr >= 0 else None
        finally:
            clear_variant(variant)
    return row


class WmiCim:
    """Implementa CimPort por COM. Una clase que falla no afecta a las demás del lote."""

    def query(
        self, queries: Sequence[CimQuery], cancel: CancelToken, timeout_s: float
    ) -> list[CimResult]:
        deadline = time.monotonic() + timeout_s
        results: list[CimResult] = []
        with com_apartment():
            locator = create_instance(_CLSID_WBEM_LOCATOR, _IID_WBEM_LOCATOR)
            connections: dict[str, _Connection] = {}
            try:
                for query in queries:
                    results.append(self._one(locator, connections, query, cancel, deadline))
            finally:
                for connection in connections.values():
                    connection.close()
                release(locator)
        return results

    @staticmethod
    def _one(
        locator: ctypes.c_void_p,
        connections: dict[str, _Connection],
        query: CimQuery,
        cancel: CancelToken,
        deadline: float,
    ) -> CimResult:
        class_deadline = min(deadline, time.monotonic() + _PER_CLASS_TIMEOUT_S)
        if time.monotonic() >= class_deadline:
            return CimResult(error=CimError(CimErrorKind.TIMEOUT, "sin tiempo para la consulta"))
        try:
            connection = connections.get(query.namespace)
            if connection is None:
                connection = _Connection(locator, query.namespace)
                connections[query.namespace] = connection
            return CimResult(rows=tuple(connection.rows(query, cancel, class_deadline)))
        except WmiTimeout:
            return CimResult(error=CimError(CimErrorKind.TIMEOUT, f"{query.source}: sin respuesta"))
        except ComError as error:
            log.debug("WMI %s: %s", query.source, error)
            return CimResult(error=CimError(classify(error.hresult), str(error)))


# Una clase inexistente o sin permisos daría lo mismo por la otra vía: no se reintenta.
_RETRYABLE = {CimErrorKind.FAILED, CimErrorKind.TIMEOUT, CimErrorKind.TRANSIENT}


class CimWithFallback:
    """Cada consulta por la vía principal; la que falle se repite, sola, por la alternativa.

    Las dos vías implementan CimPort (WMI por COM y PowerShell). Si la principal no arranca
    (COM bloqueado), todo el lote va por la alternativa.
    """

    def __init__(self, primary: Any, fallback: Any) -> None:
        self._primary = primary
        self._fallback = fallback

    def query(
        self, queries: Sequence[CimQuery], cancel: CancelToken, timeout_s: float
    ) -> list[CimResult]:
        deadline = time.monotonic() + timeout_s
        try:
            results = list(self._primary.query(queries, cancel, timeout_s))
        except (ComError, OSError) as error:
            log.info("Vía principal de WMI no disponible (%s): se usa la alternativa", error)
            remaining = max(1.0, deadline - time.monotonic())
            return list(self._fallback.query(queries, cancel, remaining))
        retry = [
            index
            for index, result in enumerate(results)
            if result.error is not None and result.error.kind in _RETRYABLE
        ]
        remaining = deadline - time.monotonic()
        if retry and remaining > 1.0:
            cancel.raise_if_cancelled()
            try:
                again = self._fallback.query([queries[i] for i in retry], cancel, remaining)
            except OSError as error:
                log.info("Vía alternativa de WMI no disponible: %s", type(error).__name__)
                return results
            for index, result in zip(retry, again, strict=True):
                if result.ok:
                    results[index] = result
        return results


# --- Métodos WMI (acciones de soporte) ---------------------------------------------------------

_SERVICES_GET_OBJECT = 6
_SERVICES_EXEC_METHOD = 24
_OBJECT_PUT = 5
_OBJECT_SPAWN_INSTANCE = 15
_OBJECT_GET_METHOD = 19
_PATH = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+=(\"[^\"\\]{0,256}\"|'[^'\\]{0,256}'|\d+))?$")


def call_method(
    namespace: str,
    object_path: str,
    method_name: str,
    arguments: dict[str, object] | None = None,
    outputs: tuple[str, ...] = ("ReturnValue",),
) -> dict[str, object]:
    """Ejecuta un método WMI (p. ej. `Win32_Service.Name="Spooler"`, `StopService`).

    Devuelve los parámetros de salida (incluido ReturnValue). Lanza ComError si WMI rechaza la
    llamada; la ruta del objeto se valida para que la petición no pueda formar otra consulta.
    """
    if not _NAMESPACE.match(namespace) or not _IDENTIFIER.match(method_name):
        raise ValueError("método WMI no permitido")
    if not _PATH.match(object_path):
        raise ValueError("ruta de objeto WMI no permitida")
    class_name = object_path.split(".", 1)[0]
    with com_apartment():
        locator = create_instance(_CLSID_WBEM_LOCATOR, _IID_WBEM_LOCATOR)
        connection = _Connection(locator, namespace)
        pointers: list[ctypes.c_void_p] = []
        try:
            services = connection.pointer
            get_object = method(
                services,
                _SERVICES_GET_OBJECT,
                ctypes.c_void_p,
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_void_p,
            )
            klass = ctypes.c_void_p()
            with Bstr(class_name) as name:
                check(get_object(name, 0, None, ctypes.byref(klass), None), "GetObject")
            pointers.append(klass)
            in_params = ctypes.c_void_p()
            if arguments:
                signature = ctypes.c_void_p()
                get_method = method(
                    klass,
                    _OBJECT_GET_METHOD,
                    ctypes.c_wchar_p,
                    ctypes.c_long,
                    ctypes.POINTER(ctypes.c_void_p),
                    ctypes.POINTER(ctypes.c_void_p),
                )
                check(get_method(method_name, 0, ctypes.byref(signature), None), "GetMethod")
                pointers.append(signature)
                spawn = method(
                    signature,
                    _OBJECT_SPAWN_INSTANCE,
                    ctypes.c_long,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                check(spawn(0, ctypes.byref(in_params)), "SpawnInstance")
                pointers.append(in_params)
                put = method(
                    in_params,
                    _OBJECT_PUT,
                    ctypes.c_wchar_p,
                    ctypes.c_long,
                    ctypes.c_void_p,
                    ctypes.c_long,
                )
                for key, value in arguments.items():
                    if not _IDENTIFIER.match(key):
                        raise ValueError("parámetro WMI no permitido")
                    variant = variant_from(value)
                    try:
                        check(put(key, 0, ctypes.byref(variant), 0), f"Put {key}")
                    finally:
                        clear_variant(variant)
            out_params = ctypes.c_void_p()
            execute = method(
                services,
                _SERVICES_EXEC_METHOD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_void_p,
            )
            with Bstr(object_path) as path, Bstr(method_name) as name:
                check(
                    execute(
                        path,
                        name,
                        0,
                        None,
                        in_params if arguments else None,
                        ctypes.byref(out_params),
                        None,
                    ),
                    f"ExecMethod {method_name}",
                )
            pointers.append(out_params)
            return _read(out_params, outputs) if out_params else {}
        finally:
            for pointer in reversed(pointers):
                release(pointer)
            connection.close()
            release(locator)
