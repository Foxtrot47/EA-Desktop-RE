"""Legacy OOA machine binding used by MOHPA's shipped ActivationUI.

Reconstructed from ActivationUI.exe:0x4310D0, 0x430D40, 0x431700. The
fingerprint is local hardware metadata; callers must not log it or the hash.
"""

from __future__ import annotations

import ctypes
import hashlib
import struct
from dataclasses import dataclass

from .machine import _bounded_wmi, _collect_cim_snapshot, _encode_legacy_utf8, _native_cpuid, _system_volume_serial


@dataclass(frozen=True)
class LegacyOoaInputs:
    baseboard_manufacturer: str
    baseboard_serial: str
    bios_manufacturer: str
    bios_serial: str
    system_volume_serial: int
    active_display_device_id: str
    cpu_vendor: str
    cpuid_leaf1_edx: int
    cpuid_leaf1_ecx: int
    cpu_brand: str


def build_legacy_ooa_fingerprint(inputs: LegacyOoaInputs) -> bytes:
    """Build ActivationUI's mode-3 byte stream, including final separators."""
    wmi = ";".join(
        (
            _bounded_wmi(inputs.baseboard_manufacturer, 100),
            _bounded_wmi(inputs.baseboard_serial, 100),
            _bounded_wmi(inputs.bios_manufacturer, 100),
            _bounded_wmi(inputs.bios_serial, 50),
        )
    ) + ";"
    suffix = (
        f"{inputs.system_volume_serial & 0xFFFFFFFF:x};"
        f"{inputs.active_display_device_id[:128]};"
        f"{inputs.cpu_vendor};"
        f"{inputs.cpuid_leaf1_edx & 0xFFFFFFFF:x};"
        f"{inputs.cpuid_leaf1_ecx & 0xFFFFFFFF:x};"
        f"{inputs.cpu_brand};"
    )
    return _encode_legacy_utf8(wmi) + suffix.encode("latin-1")


def legacy_ooa_machine_hash(fingerprint: bytes) -> str:
    """ActivationUI formats each SHA-1 byte with `%x`, without zero padding."""
    return "".join(f"{byte:x}" for byte in hashlib.sha1(fingerprint).digest())


def _active_display_device_id() -> str:
    if not hasattr(ctypes, "windll"):
        raise OSError("legacy OOA display collector requires Windows")
    enum = ctypes.windll.user32.EnumDisplayDevicesA
    enum.argtypes = (ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32)
    enum.restype = ctypes.c_int
    for index in range(256):
        display = ctypes.create_string_buffer(424)
        struct.pack_into("<I", display, 0, 424)
        if not enum(None, index, display, 0):
            break
        state_flags = struct.unpack_from("<I", display, 164)[0]
        if state_flags & 4:  # DISPLAY_DEVICE_PRIMARY_DEVICE
            return display.raw[168:296].split(b"\0", 1)[0].decode("latin-1")
    return ""


def collect_legacy_ooa_machine_hash() -> str:
    """Compute the MOHPA license binding without an EA process or cache."""
    snapshot = _collect_cim_snapshot()
    _, vendor_ebx, vendor_ecx, vendor_edx = _native_cpuid(0)
    cpu_vendor = struct.pack("<III", vendor_ebx, vendor_edx, vendor_ecx).split(b"\0", 1)[0].decode("latin-1")
    _, _, feature_ecx, feature_edx = _native_cpuid(1)
    max_extended, _, _, _ = _native_cpuid(0x80000000)
    cpu_brand = ""
    if max_extended >= 0x80000004:
        raw = b"".join(
            struct.pack("<IIII", *_native_cpuid(leaf))
            for leaf in range(0x80000002, 0x80000005)
        )
        cpu_brand = raw.split(b"\0", 1)[0].decode("latin-1")
    values = LegacyOoaInputs(
        baseboard_manufacturer=str(snapshot.get("baseboard_manufacturer") or ""),
        baseboard_serial=str(snapshot.get("baseboard_serial") or ""),
        bios_manufacturer=str(snapshot.get("bios_manufacturer") or ""),
        bios_serial=str(snapshot.get("bios_serial") or ""),
        system_volume_serial=_system_volume_serial(),
        active_display_device_id=_active_display_device_id(),
        cpu_vendor=cpu_vendor,
        cpuid_leaf1_edx=feature_edx,
        cpuid_leaf1_ecx=feature_ecx,
        cpu_brand=cpu_brand,
    )
    return legacy_ooa_machine_hash(build_legacy_ooa_fingerprint(values))
