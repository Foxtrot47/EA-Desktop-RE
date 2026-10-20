"""Transactional ZIP extraction primitives for standalone EA installs."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zipfile
import zlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


class InstallError(RuntimeError):
    pass


_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def safe_relative_path(name: str) -> Path:
    """Convert an archive name into a safe relative Windows path."""
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or pure.is_absolute():
        raise InstallError(f"unsafe absolute archive path: {name!r}")
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise InstallError(f"unsafe archive path component: {name!r}")
    for part in parts:
        if "\x00" in part or ":" in part or part.endswith((" ", ".")):
            raise InstallError(f"unsafe Windows archive path component: {name!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise InstallError(f"reserved Windows archive path component: {name!r}")
    return Path(*parts)


def validate_selected_entries(entries: Iterable[zipfile.ZipInfo]) -> tuple[zipfile.ZipInfo, ...]:
    selected = tuple(entry for entry in entries if not entry.is_dir())
    seen: set[str] = set()
    for entry in selected:
        relative = safe_relative_path(entry.filename)
        key = str(relative).replace("\\", "/").casefold()
        if key in seen:
            raise InstallError(f"duplicate case-insensitive archive target: {entry.filename!r}")
        seen.add(key)
        unix_mode = entry.external_attr >> 16
        if unix_mode & 0o170000 == 0o120000:
            raise InstallError(f"symbolic-link archive entry is not allowed: {entry.filename!r}")
    return selected


def selection_fingerprint(
    entries: Iterable[zipfile.ZipInfo], *, locale: str, game_version: str
) -> str:
    digest = hashlib.sha256()
    digest.update(locale.encode("utf-8") + b"\0" + game_version.encode("utf-8") + b"\0")
    for entry in validate_selected_entries(entries):
        digest.update(entry.filename.replace("\\", "/").casefold().encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.CRC.to_bytes(4, "little"))
        digest.update(entry.file_size.to_bytes(8, "little"))
        digest.update(entry.compress_size.to_bytes(8, "little"))
    return digest.hexdigest().upper()


@dataclass(frozen=True)
class ExtractionResult:
    extracted_files: int
    skipped_files: int
    written_bytes: int
    completed_files: int


@dataclass(frozen=True)
class AdoptionResult:
    verified_files: int
    incomplete_files: int
    pruned_files: int
    verified_bytes: int


def _load_journal(path: Path, fingerprint: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"invalid install journal: {type(exc).__name__}") from None
    if document.get("schema") != 1 or document.get("selection_fingerprint") != fingerprint:
        raise InstallError("install journal belongs to a different package selection")
    completed = document.get("completed", [])
    if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
        raise InstallError("install journal has an invalid completed-file list")
    return set(completed)


def _save_journal(path: Path, fingerprint: str, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema": 1,
                "selection_fingerprint": fingerprint,
                "completed": sorted(completed),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _file_crc32(path: Path, buffer_size: int = 4 * 1024 * 1024) -> int:
    checksum = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(buffer_size), b""):
            checksum = zlib.crc32(block, checksum)
    return checksum & 0xFFFFFFFF


def _stored_member_data_offset(archive: zipfile.ZipFile, entry: zipfile.ZipInfo) -> int:
    """Locate stored payload bytes using and validating the ZIP local header."""
    source = archive.fp
    if source is None:
        raise InstallError("archive is closed")
    source.seek(entry.header_offset)
    header = source.read(30)
    if len(header) != 30 or struct.unpack_from("<I", header)[0] != 0x04034B50:
        raise InstallError(f"invalid local ZIP header: {entry.filename!r}")
    name_length, extra_length = struct.unpack_from("<HH", header, 26)
    local_name = source.read(name_length)
    expected_name = entry.filename.encode("utf-8" if entry.flag_bits & 0x800 else "cp437")
    if local_name != expected_name:
        raise InstallError(f"local ZIP name differs from central directory: {entry.filename!r}")
    if entry.flag_bits & 1 or entry.file_size != entry.compress_size:
        raise InstallError(f"stored ZIP entry is encrypted or has inconsistent size: {entry.filename!r}")
    return entry.header_offset + 30 + name_length + extra_length


def _extract_stored_parallel(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    temporary: Path,
    *,
    workers: int,
    chunk_size: int,
    progress: Callable[[str, int, int], None] | None,
) -> int:
    remote = archive.fp
    if remote is None or not hasattr(remote, "fetch_range"):
        raise InstallError("archive source cannot fetch parallel ranges")
    offset = _stored_member_data_offset(archive, entry)
    ranges = [
        (relative, min(chunk_size, entry.file_size - relative))
        for relative in range(0, entry.file_size, chunk_size)
    ]

    def fetch(piece: tuple[int, int]) -> tuple[int, bytes]:
        relative, size = piece
        return relative, remote.fetch_range(offset + relative, offset + relative + size - 1)

    written = 0
    with temporary.open("wb+") as output, ThreadPoolExecutor(max_workers=workers) as pool:
        output.truncate(entry.file_size)
        pending = set()
        next_piece = iter(ranges)
        for _ in range(min(workers * 2, len(ranges))):
            pending.add(pool.submit(fetch, next(next_piece)))
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                relative, data = future.result()
                output.seek(relative)
                output.write(data)
                written += len(data)
                if progress:
                    progress(entry.filename, written, entry.file_size)
                piece = next(next_piece, None)
                if piece is not None:
                    pending.add(pool.submit(fetch, piece))
        output.flush()
        os.fsync(output.fileno())
    if written != entry.file_size or _file_crc32(temporary) != entry.CRC:
        raise InstallError(f"CRC verification failed for {entry.filename!r}")
    return written


def adopt_existing_selection(
    entries: Iterable[zipfile.ZipInfo],
    destination: Path,
    *,
    locale: str,
    game_version: str,
    archive_entries: Iterable[zipfile.ZipInfo] | None = None,
    prune_unselected: bool = False,
    journal_path: Path | None = None,
) -> AdoptionResult:
    """CRC-check existing selected files and optionally remove known excluded entries."""
    selected = validate_selected_entries(entries)
    selected_keys = {
        str(safe_relative_path(entry.filename)).replace("\\", "/").casefold()
        for entry in selected
    }
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    completed: set[str] = set()
    verified_bytes = 0
    for entry in selected:
        relative = safe_relative_path(entry.filename)
        key = str(relative).replace("\\", "/").casefold()
        target = (destination / relative).resolve()
        try:
            target.relative_to(destination)
        except ValueError:
            raise InstallError(f"local path escapes install root: {entry.filename!r}") from None
        if (
            target.is_file()
            and target.stat().st_size == entry.file_size
            and _file_crc32(target) == entry.CRC
        ):
            completed.add(key)
            verified_bytes += entry.file_size

    pruned = 0
    if prune_unselected:
        if archive_entries is None:
            raise ValueError("archive_entries is required when pruning")
        for entry in validate_selected_entries(archive_entries):
            relative = safe_relative_path(entry.filename)
            key = str(relative).replace("\\", "/").casefold()
            if key in selected_keys:
                continue
            target = (destination / relative).resolve()
            try:
                target.relative_to(destination)
            except ValueError:
                raise InstallError(f"local path escapes install root: {entry.filename!r}") from None
            if target.is_file():
                target.unlink()
                pruned += 1

    fingerprint = selection_fingerprint(selected, locale=locale, game_version=game_version)
    _save_journal(
        journal_path or destination / ".ea-standalone-install.json",
        fingerprint,
        completed,
    )
    return AdoptionResult(
        verified_files=len(completed),
        incomplete_files=len(selected) - len(completed),
        pruned_files=pruned,
        verified_bytes=verified_bytes,
    )


def extract_selection(
    archive: zipfile.ZipFile,
    entries: Iterable[zipfile.ZipInfo],
    destination: Path,
    *,
    locale: str,
    game_version: str,
    journal_path: Path | None = None,
    copy_buffer_size: int = 4 * 1024 * 1024,
    parallel_stored_workers: int = 1,
    parallel_chunk_size: int = 8 * 1024 * 1024,
    progress: Callable[[str, int, int], None] | None = None,
) -> ExtractionResult:
    """Extract selected entries atomically and resume at verified file boundaries."""
    if copy_buffer_size <= 0 or parallel_chunk_size <= 0 or parallel_stored_workers <= 0:
        raise ValueError("copy buffer, parallel chunk and worker count must be positive")
    selected = validate_selected_entries(entries)
    fingerprint = selection_fingerprint(selected, locale=locale, game_version=game_version)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    journal = journal_path or destination / ".ea-standalone-install.json"
    completed = _load_journal(journal, fingerprint)
    extracted = skipped = written = 0

    for entry in selected:
        relative = safe_relative_path(entry.filename)
        key = str(relative).replace("\\", "/").casefold()
        target = (destination / relative).resolve()
        try:
            target.relative_to(destination)
        except ValueError:
            raise InstallError(f"archive path escapes install root: {entry.filename!r}") from None

        if key in completed and target.is_file() and target.stat().st_size == entry.file_size:
            skipped += 1
            continue
        completed.discard(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".ea-part")
        try:
            written_for_file = 0
            if progress:
                progress(entry.filename, 0, entry.file_size)
            if (
                parallel_stored_workers > 1
                and entry.compress_type == zipfile.ZIP_STORED
                and entry.file_size >= 64 * 1024 * 1024
                and hasattr(archive.fp, "fetch_range")
            ):
                written_for_file = _extract_stored_parallel(
                    archive, entry, temporary,
                    workers=parallel_stored_workers,
                    chunk_size=parallel_chunk_size,
                    progress=progress,
                )
            else:
                with archive.open(entry, "r") as source, temporary.open("wb") as output:
                    while True:
                        block = source.read(copy_buffer_size)
                        if not block:
                            break
                        output.write(block)
                        written_for_file += len(block)
                        if progress:
                            progress(entry.filename, written_for_file, entry.file_size)
                    output.flush()
                    os.fsync(output.fileno())
            if written_for_file != entry.file_size:
                raise InstallError(f"size verification failed for {entry.filename!r}")
            # ZipExtFile verifies the central-directory CRC when EOF is read.
            os.replace(temporary, target)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, InstallError):
                raise
            raise InstallError(f"failed to extract {entry.filename!r}: {type(exc).__name__}") from None
        completed.add(key)
        _save_journal(journal, fingerprint, completed)
        extracted += 1
        written += written_for_file

    return ExtractionResult(
        extracted_files=extracted,
        skipped_files=skipped,
        written_bytes=written,
        completed_files=len(completed),
    )
