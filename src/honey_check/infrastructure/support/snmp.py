"""Cliente SNMP v2c mínimo (GET y GETNEXT) para consultar impresoras de red.

Solo lectura; se usa a pedido del técnico contra la IP que él indica.
"""

from __future__ import annotations

import secrets
import socket
from typing import Any

_INTEGER, _OCTETS, _NULL, _OID, _SEQUENCE = 0x02, 0x04, 0x05, 0x06, 0x30
_GET, _GETNEXT, _RESPONSE = 0xA0, 0xA1, 0xA2
_APPLICATION = {0x40: "ip", 0x41: "counter", 0x42: "gauge", 0x43: "ticks", 0x46: "counter64"}
_NO_VALUE = (0x80, 0x81, 0x82)


class SnmpError(Exception):
    pass


def _length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _length(len(value)) + value


def _integer(n: int) -> bytes:
    raw = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True)
    return _tlv(_INTEGER, raw)


def _oid(text: str) -> bytes:
    parts = [int(p) for p in text.split(".")]
    body = bytearray([40 * parts[0] + parts[1]])
    for part in parts[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append(0x80 | (part & 0x7F))
            part >>= 7
        body.extend(reversed(chunk))
    return _tlv(_OID, bytes(body))


def _request(kind: int, community: str, oids: list[str], request_id: int) -> bytes:
    bindings = b"".join(_tlv(_SEQUENCE, _oid(o) + _tlv(_NULL, b"")) for o in oids)
    pdu = _tlv(kind, _integer(request_id) + _integer(0) + _integer(0) + _tlv(_SEQUENCE, bindings))
    return _tlv(_SEQUENCE, _integer(1) + _tlv(_OCTETS, community.encode()) + pdu)


def _read(data: bytes, offset: int) -> tuple[int, bytes, int]:
    tag = data[offset]
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    return tag, data[offset : offset + length], offset + length


def _decode_oid(raw: bytes) -> str:
    parts = [raw[0] // 40, raw[0] % 40]
    value = 0
    for byte in raw[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(str(p) for p in parts)


def _value(tag: int, raw: bytes) -> Any:
    if tag in _NO_VALUE or tag == _NULL:
        return None
    if tag == _INTEGER or tag in (0x41, 0x42, 0x43, 0x46):
        return int.from_bytes(raw, "big", signed=tag == _INTEGER)
    if tag == _OID:
        return _decode_oid(raw)
    if tag == 0x40:
        return ".".join(str(b) for b in raw)
    return raw  # OCTET STRING: texto o bytes (MAC)


def _parse(data: bytes, request_id: int) -> list[tuple[str, Any]]:
    _, message, _ = _read(data, 0)
    offset = 0
    _, _version, offset = _read(message, offset)
    _, _community, offset = _read(message, offset)
    tag, pdu, _ = _read(message, offset)
    if tag != _RESPONSE:
        raise SnmpError("respuesta inesperada")
    offset = 0
    _, rid, offset = _read(pdu, offset)
    if int.from_bytes(rid, "big", signed=True) != request_id:
        raise SnmpError("respuesta de otra consulta")
    _, status, offset = _read(pdu, offset)
    _, _index, offset = _read(pdu, offset)
    if int.from_bytes(status, "big"):
        raise SnmpError(f"error SNMP {int.from_bytes(status, 'big')}")
    _, bindings, _ = _read(pdu, offset)
    results = []
    offset = 0
    while offset < len(bindings):
        _, binding, offset = _read(bindings, offset)
        _, oid_raw, inner = _read(binding, 0)
        tag, raw, _ = _read(binding, inner)
        results.append((_decode_oid(oid_raw), _value(tag, raw)))
    return results


class SnmpClient:
    def __init__(self, host: str, community: str, timeout_s: float = 2.0, retries: int = 1) -> None:
        self._host = host
        self._community = community
        self._timeout = timeout_s
        self._retries = retries

    def _exchange(self, kind: int, oids: list[str]) -> list[tuple[str, Any]]:
        request_id = secrets.randbelow(2**30)
        packet = _request(kind, self._community, oids, request_id)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self._timeout)
            for _ in range(self._retries + 1):
                sock.sendto(packet, (self._host, 161))
                try:
                    data, _ = sock.recvfrom(65535)
                    return _parse(data, request_id)
                except TimeoutError:
                    continue
        raise SnmpError("la impresora no respondió por SNMP (UDP 161)")

    def get(self, oids: list[str]) -> dict[str, Any]:
        return dict(self._exchange(_GET, oids))

    def walk(self, prefix: str, limit: int = 64) -> list[tuple[str, Any]]:
        found: list[tuple[str, Any]] = []
        current = prefix
        for _ in range(limit):
            (oid, value), *_ = self._exchange(_GETNEXT, [current])
            if not oid.startswith(prefix + ".") or value is None:
                break
            found.append((oid, value))
            current = oid
        return found


def text(value: Any) -> str | None:
    if isinstance(value, bytes):
        cleaned = value.replace(b"\x00", b"").strip()
        try:
            return cleaned.decode("utf-8")
        except UnicodeDecodeError:
            return cleaned.decode("latin-1")
    return None if value is None else str(value)


def mac(value: Any) -> str | None:
    if isinstance(value, bytes) and len(value) == 6 and any(value):
        return ":".join(f"{b:02X}" for b in value)
    return None
