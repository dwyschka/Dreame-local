"""Persistente CA-Bridge fuer die Tasshack-Integration.

Die Integration prueft TLS gegen certifi. HA-Core-Updates ersetzen das
Container-Image und damit certifi. Diese Bridge laeuft als Custom Component
im HA-Core-Prozess, traegt die Add-on-CA bei jedem Start erneut ein und
setzt den TLS-Store-Cache der Integration zurueck.
"""
from __future__ import annotations

import sys
from pathlib import Path

CA_PATHS = (
    Path("/share/dreame-local-ca.pem"),
    Path("/config/dreame-local-ca.pem"),
)


def find_ca(paths: tuple[Path, ...] = CA_PATHS) -> bytes | None:
    """Liefert das erste lesbare PEM-Zertifikat aus paths."""
    for path in paths:
        try:
            data = path.read_bytes().strip()
        except OSError:
            continue
        if b"-----BEGIN CERTIFICATE-----" in data:
            return data
    return None


def install_ca(ca_pem: bytes | None = None, target: Path | None = None) -> bool:
    """Haengt die CA an certifi an. True, wenn die Datei geaendert wurde."""
    import certifi

    ca = (ca_pem or find_ca() or b"").strip()
    if not ca:
        return False

    path = target or Path(certifi.where())
    data = path.read_bytes()
    if ca in data:
        return False

    backup = path.with_name(path.name + ".bak")
    if not backup.exists():
        backup.write_bytes(data)

    separator = b"" if data.endswith(b"\n") else b"\n"
    path.write_bytes(data + separator + ca + b"\n")
    return True


def reset_dreame_store() -> bool:
    """Setzt den prozessweiten TLS-Store-Cache der Integration zurueck."""
    for name in (
        "custom_components.dreame_vacuum.dreame.protocol",
        "dreame_vacuum.dreame.protocol",
    ):
        module = sys.modules.get(name)
        if module is None:
            continue
        protocol = getattr(module, "DreameVacuumDreameHomeCloudProtocol", None)
        socket_cls = getattr(protocol, "DreameTLSSocket", None)
        if socket_cls is not None and getattr(socket_cls, "_store", None) is not None:
            socket_cls._store = None
            return True
    return False
