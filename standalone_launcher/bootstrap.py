"""Version-pinned extraction and DPAPI storage for standalone auth secrets.

The values recovered here are embedded application credentials.  Callers must
not log or serialize the plaintext result except through ``save_dpapi``.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SHA256 = "6EC60C4D45A0A6CDE311A0DD26C529026E0384E7F05BC9877D7A56AC53B1840B"


@dataclass(frozen=True)
class ObfuscatedValue:
    va: int
    size: int
    seed: int


@dataclass(frozen=True)
class BuildAdapter:
    sha256: str
    aes_key: ObfuscatedValue
    aes_iv: ObfuscatedValue
    production_pc_sign: tuple[ObfuscatedValue, ...]
    nonproduction_pc_sign: tuple[ObfuscatedValue, ...]
    client_secret_by_environment: dict[int, ObfuscatedValue]


EA_DESKTOP_13_809 = BuildAdapter(
    sha256=SUPPORTED_SHA256,
    aes_key=ObfuscatedValue(0x1415CA6B0, 32, 4018141244),
    aes_iv=ObfuscatedValue(0x1415CA6D0, 16, 4068474101),
    production_pc_sign=(
        ObfuscatedValue(0x1415CA5D0, 32, 1886648156),
        ObfuscatedValue(0x1415CA5F0, 32, 1903425775),
    ),
    nonproduction_pc_sign=(
        ObfuscatedValue(0x1415CA630, 32, 2138753726),
        ObfuscatedValue(0x1415CA650, 32, 2121976107),
        ObfuscatedValue(0x1415CA670, 32, 2105198488),
        ObfuscatedValue(0x1415CA690, 32, 2088420869),
    ),
    client_secret_by_environment={
        0: ObfuscatedValue(0x1416157A0, 80, 3154731906),
        1: ObfuscatedValue(0x1416157A0, 80, 3154731906),
        2: ObfuscatedValue(0x1416157F0, 80, 3288114215),
        3: ObfuscatedValue(0x1416157F0, 80, 3288114215),
        4: ObfuscatedValue(0x141615840, 64, 3237781358),
    },
)


class PeImage:
    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE image")
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_offset : pe_offset + 4] != b"PE\0\0":
            raise ValueError("invalid PE signature")
        coff = pe_offset + 4
        section_count = struct.unpack_from("<H", data, coff + 2)[0]
        optional_size = struct.unpack_from("<H", data, coff + 16)[0]
        optional = coff + 20
        if struct.unpack_from("<H", data, optional)[0] != 0x20B:
            raise ValueError("expected a PE32+ image")
        self.image_base = struct.unpack_from("<Q", data, optional + 24)[0]
        section_table = optional + optional_size
        self.sections: list[tuple[int, int, int, int]] = []
        for index in range(section_count):
            header = section_table + index * 40
            virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, header + 8)
            self.sections.append((rva, max(virtual_size, raw_size), raw_offset, raw_size))

    @classmethod
    def load(cls, path: Path) -> "PeImage":
        return cls(path.read_bytes())

    def read_va(self, va: int, size: int) -> bytes:
        rva = va - self.image_base
        for section_rva, span, raw_offset, raw_size in self.sections:
            if section_rva <= rva and rva + size <= section_rva + span:
                relative = rva - section_rva
                if relative + size > raw_size:
                    raise ValueError("requested VA extends beyond raw section data")
                return self.data[raw_offset + relative : raw_offset + relative + size]
        raise ValueError(f"unmapped virtual address {va:#x}")


def decode_embedded_value(data: bytes, seed: int) -> bytes:
    """Reproduce EADesktop's rolling FNV byte deobfuscator."""
    output = bytearray(len(data))
    written = 0
    accumulator = 0
    for index, byte in enumerate(data):
        accumulator = byte | ((accumulator << 8) & 0xFFFFFFFF)
        if (index + 1) & 3 == 0:
            accumulator ^= seed
            while written <= index:
                decoded = accumulator >> (8 * (index - written)) & 0xFF
                output[written] = decoded
                seed = 16777619 * (seed ^ decoded) & 0xFFFFFFFF
                written += 1
    accumulator ^= seed
    while written < len(data):
        output[written] = accumulator >> (8 * (len(data) - written) - 8) & 0xFF
        written += 1
    return bytes(output)


def _nt_success(status: int) -> bool:
    return ctypes.c_long(status).value >= 0


def aes256_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    if len(key) != 32 or len(iv) != 16 or len(ciphertext) % 16:
        raise ValueError("AES-256-CBC requires a 32-byte key, 16-byte IV, and full blocks")
    bcrypt = ctypes.WinDLL("bcrypt.dll")
    void_p = ctypes.c_void_p
    ulong = ctypes.c_ulong
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(void_p), ctypes.c_wchar_p, ctypes.c_wchar_p, ulong]
    bcrypt.BCryptOpenAlgorithmProvider.restype = ctypes.c_long
    bcrypt.BCryptSetProperty.argtypes = [void_p, ctypes.c_wchar_p, void_p, ulong, ulong]
    bcrypt.BCryptSetProperty.restype = ctypes.c_long
    bcrypt.BCryptGetProperty.argtypes = [void_p, ctypes.c_wchar_p, void_p, ulong, ctypes.POINTER(ulong), ulong]
    bcrypt.BCryptGetProperty.restype = ctypes.c_long
    bcrypt.BCryptGenerateSymmetricKey.argtypes = [void_p, ctypes.POINTER(void_p), void_p, ulong, void_p, ulong, ulong]
    bcrypt.BCryptGenerateSymmetricKey.restype = ctypes.c_long
    bcrypt.BCryptDecrypt.argtypes = [void_p, void_p, ulong, void_p, void_p, ulong, void_p, ulong, ctypes.POINTER(ulong), ulong]
    bcrypt.BCryptDecrypt.restype = ctypes.c_long

    algorithm = void_p()
    key_handle = void_p()
    status = bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "AES", None, 0)
    if not _nt_success(status):
        raise OSError(f"BCryptOpenAlgorithmProvider failed: {status:#x}")
    try:
        mode = ctypes.create_unicode_buffer("ChainingModeCBC")
        status = bcrypt.BCryptSetProperty(
            algorithm, "ChainingMode", ctypes.cast(mode, void_p), ctypes.sizeof(mode), 0
        )
        if not _nt_success(status):
            raise OSError(f"BCryptSetProperty failed: {status:#x}")
        object_length = ulong()
        received = ulong()
        status = bcrypt.BCryptGetProperty(
            algorithm, "ObjectLength", ctypes.byref(object_length), ctypes.sizeof(object_length), ctypes.byref(received), 0
        )
        if not _nt_success(status):
            raise OSError(f"BCryptGetProperty failed: {status:#x}")
        key_object = ctypes.create_string_buffer(object_length.value)
        key_buffer = ctypes.create_string_buffer(key, len(key))
        status = bcrypt.BCryptGenerateSymmetricKey(
            algorithm,
            ctypes.byref(key_handle),
            key_object,
            object_length.value,
            key_buffer,
            len(key),
            0,
        )
        if not _nt_success(status):
            raise OSError(f"BCryptGenerateSymmetricKey failed: {status:#x}")
        source = ctypes.create_string_buffer(ciphertext, len(ciphertext))
        output = ctypes.create_string_buffer(len(ciphertext))
        produced = ulong()
        iv_buffer = ctypes.create_string_buffer(iv, len(iv))
        status = bcrypt.BCryptDecrypt(
            key_handle,
            source,
            len(ciphertext),
            None,
            iv_buffer,
            len(iv),
            output,
            len(output),
            ctypes.byref(produced),
            0,
        )
        if not _nt_success(status):
            raise OSError(f"BCryptDecrypt failed: {status:#x}")
        return output.raw[: produced.value]
    finally:
        if key_handle:
            bcrypt.BCryptDestroyKey(key_handle)
        bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)


@dataclass(frozen=True)
class StandaloneSecrets:
    source_sha256: str
    production_pc_sign_keys: tuple[bytes, ...]
    nonproduction_pc_sign_keys: tuple[bytes, ...]
    client_secret_by_environment: dict[int, str]

    def to_private_json(self) -> bytes:
        document = {
            "schema": 1,
            "source_sha256": self.source_sha256,
            "production_pc_sign_keys": [base64.b64encode(value).decode("ascii") for value in self.production_pc_sign_keys],
            "nonproduction_pc_sign_keys": [base64.b64encode(value).decode("ascii") for value in self.nonproduction_pc_sign_keys],
            "client_secret_by_environment": self.client_secret_by_environment,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_private_json(cls, data: bytes) -> "StandaloneSecrets":
        document = json.loads(data)
        if document.get("schema") != 1:
            raise ValueError("unsupported secret-store schema")
        return cls(
            source_sha256=document["source_sha256"],
            production_pc_sign_keys=tuple(base64.b64decode(value) for value in document["production_pc_sign_keys"]),
            nonproduction_pc_sign_keys=tuple(base64.b64decode(value) for value in document["nonproduction_pc_sign_keys"]),
            client_secret_by_environment={int(key): value for key, value in document["client_secret_by_environment"].items()},
        )


def extract_secrets(path: Path, adapter: BuildAdapter = EA_DESKTOP_13_809) -> StandaloneSecrets:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest().upper()
    if digest != adapter.sha256:
        raise ValueError(f"unsupported EADesktop build {digest}")
    image = PeImage(data)

    def decoded(spec: ObfuscatedValue) -> bytes:
        return decode_embedded_value(image.read_va(spec.va, spec.size), spec.seed)

    aes_key = decoded(adapter.aes_key)
    aes_iv = decoded(adapter.aes_iv)
    production = tuple(aes256_cbc_decrypt(decoded(spec), aes_key, aes_iv) for spec in adapter.production_pc_sign)
    nonproduction = tuple(aes256_cbc_decrypt(decoded(spec), aes_key, aes_iv) for spec in adapter.nonproduction_pc_sign)
    clients = {environment: decoded(spec).decode("ascii") for environment, spec in adapter.client_secret_by_environment.items()}
    if any(len(value) != 32 for value in (*production, *nonproduction)):
        raise ValueError("unexpected recovered pc_sign key length")
    return StandaloneSecrets(digest, production, nonproduction, clients)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value, len(value))
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def dpapi_protect(value: bytes, description: str = "EA standalone launcher bootstrap") -> bytes:
    source, keepalive = _blob_from_bytes(value)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def dpapi_unprotect(value: bytes) -> bytes:
    source, keepalive = _blob_from_bytes(value)
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def save_dpapi(path: Path, secrets: StandaloneSecrets) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dpapi_protect(secrets.to_private_json()))


def load_dpapi(path: Path) -> StandaloneSecrets:
    return StandaloneSecrets.from_private_json(dpapi_unprotect(path.read_bytes()))
