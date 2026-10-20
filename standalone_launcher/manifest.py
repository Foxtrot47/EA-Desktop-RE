"""Parse EA DiP manifests and build conservative archive install plans."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from fnmatch import fnmatchcase
from dataclasses import dataclass
from typing import Iterable, Mapping


class DipManifestError(ValueError):
    pass


def normalize_archive_path(value: str) -> str:
    """Normalize a DiP/ZIP path for case-insensitive Windows matching."""
    return value.strip().replace("\\", "/").lstrip("/").casefold()


def _text(parent: ET.Element, path: str, default: str = "") -> str:
    found = parent.find(path)
    return (found.text or "").strip() if found is not None else default


def _bool_text(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes"}


@dataclass(frozen=True)
class RuntimeLauncher:
    uid: str
    names: Mapping[str, str]
    file_path: str
    parameters: str
    execute_elevated: bool
    requires_64_bit_os: bool
    trial: bool


@dataclass(frozen=True)
class ProgressiveChunk:
    index: int
    name: str
    requirement: str
    includes: tuple[str, ...]

    @property
    def required(self) -> bool:
        return self.requirement.casefold() == "required"


@dataclass(frozen=True)
class Touchup:
    file_path: str
    install_parameters: str
    update_parameters: str
    repair_parameters: str


@dataclass(frozen=True)
class DipManifest:
    schema_version: str
    game_version: str
    content_ids: tuple[str, ...]
    titles: Mapping[str, str]
    locales: tuple[str, ...]
    feature_flags: Mapping[str, bool]
    minimum_os_version: str
    requires_64_bit_os: bool
    launchers: tuple[RuntimeLauncher, ...]
    chunks: tuple[ProgressiveChunk, ...]
    locale_filters: Mapping[str, tuple[str, ...]]
    touchup: Touchup
    install_manifest_path: str
    uninstall_path: str


@dataclass(frozen=True)
class InstallPlanSummary:
    locale: str
    required_only: bool
    archive_file_count: int
    selected_file_count: int
    selected_compressed_bytes: int
    selected_installed_bytes: int
    selected_stored_files: int
    selected_deflated_files: int
    selected_other_compression_files: int
    omitted_locale_files: int
    omitted_locale_compressed_bytes: int
    omitted_recommended_files: int
    omitted_recommended_compressed_bytes: int
    omitted_patch_files: int
    omitted_patch_compressed_bytes: int
    unassigned_file_count: int
    unassigned_compressed_bytes: int
    invalid_path_count: int

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class InstallSelection:
    summary: InstallPlanSummary
    entries: tuple[zipfile.ZipInfo, ...]


def parse_dip_manifest(data: bytes | str) -> DipManifest:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise DipManifestError(f"invalid DiP XML: {exc}") from None
    if root.tag.rsplit("}", 1)[-1] != "DiPManifest":
        raise DipManifestError("document root is not DiPManifest")

    metadata = root.find("./installMetaData")
    if metadata is None:
        raise DipManifestError("DiP manifest has no installMetaData")

    locales = tuple(
        locale.strip()
        for locale in _text(metadata, "./locales").split(",")
        if locale.strip()
    )
    filters: dict[str, tuple[str, ...]] = {}
    for group in metadata.findall("./localeFilters/includes"):
        locale = group.get("locale", "").strip()
        if locale:
            filters[locale] = tuple(
                (node.text or "").strip()
                for node in group.findall("./include")
                if (node.text or "").strip()
            )

    chunks: list[ProgressiveChunk] = []
    for node in metadata.findall("./progressive/chunk"):
        try:
            index = int(node.get("index", ""))
        except ValueError:
            raise DipManifestError("progressive chunk has an invalid index") from None
        chunks.append(
            ProgressiveChunk(
                index=index,
                name=node.get("name", ""),
                requirement=node.get("required", ""),
                includes=tuple(
                    (include.text or "").strip()
                    for include in node.findall("./include")
                    if (include.text or "").strip()
                ),
            )
        )

    launchers: list[RuntimeLauncher] = []
    for node in root.findall("./runtime/launcher"):
        launchers.append(
            RuntimeLauncher(
                uid=node.get("uid", ""),
                names={
                    name.get("locale", ""): (name.text or "").strip()
                    for name in node.findall("./name")
                    if name.get("locale")
                },
                file_path=_text(node, "./filePath"),
                parameters=_text(node, "./parameters"),
                execute_elevated=_bool_text(_text(node, "./executeElevated")),
                requires_64_bit_os=_bool_text(_text(node, "./requires64BitOS")),
                trial=_bool_text(_text(node, "./trial")),
            )
        )

    build = root.find("./buildMetaData")
    features = build.find("./featureFlags") if build is not None else None
    requirements = build.find("./requirements") if build is not None else None
    version = build.find("./gameVersion") if build is not None else None
    touchup_node = root.find("./touchup")
    touchup = Touchup(
        file_path=_text(touchup_node, "./filePath") if touchup_node is not None else "",
        install_parameters=_text(touchup_node, "./parameters") if touchup_node is not None else "",
        update_parameters=_text(touchup_node, "./updateParameters") if touchup_node is not None else "",
        repair_parameters=_text(touchup_node, "./repairParameters") if touchup_node is not None else "",
    )

    return DipManifest(
        schema_version=root.get("version", ""),
        game_version=version.get("version", "") if version is not None else "",
        content_ids=tuple(
            (node.text or "").strip()
            for node in root.findall("./contentIDs/contentID")
            if (node.text or "").strip()
        ),
        titles={
            node.get("locale", ""): (node.text or "").strip()
            for node in root.findall("./gameTitles/gameTitle")
            if node.get("locale")
        },
        locales=locales,
        feature_flags={key: _bool_text(value) for key, value in (features.attrib if features is not None else {}).items()},
        minimum_os_version=requirements.get("osMinVersion", "") if requirements is not None else "",
        requires_64_bit_os=_bool_text(requirements.get("osReqs64Bit", "")) if requirements is not None else False,
        launchers=tuple(launchers),
        chunks=tuple(sorted(chunks, key=lambda chunk: chunk.index)),
        locale_filters=filters,
        touchup=touchup,
        install_manifest_path=_text(root, "./installManifest/filePath"),
        uninstall_path=_text(root, "./uninstall/path"),
    )


def _matches(path: str, pattern: str) -> bool:
    normalized = normalize_archive_path(pattern)
    if not normalized:
        return False
    if pattern.strip().replace("\\", "/").endswith("/"):
        return path.startswith(normalized.rstrip("/") + "/")
    if any(character in normalized for character in "*?["):
        return fnmatchcase(path, normalized)
    return path == normalized


def _safe_archive_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    return bool(normalized) and not normalized.startswith(("/", "\\")) and ":" not in parts[0] and ".." not in parts


def resolve_manifest_locale(manifest: DipManifest, requested: str) -> str:
    """Apply EA's exact, Chinese-group, language, then English fallback order."""
    if requested in manifest.locales:
        return requested
    folded = requested.casefold()
    if folded in {"zh_tw", "zh_hk"}:
        for candidate in ("zh_TW", "zh_HK"):
            if candidate in manifest.locales:
                return candidate
    language = folded.split("_", 1)[0].split("-", 1)[0]
    for candidate in manifest.locales:
        if candidate.casefold().split("_", 1)[0].split("-", 1)[0] == language:
            return candidate
    for candidate in manifest.locales:
        if candidate.casefold().split("_", 1)[0].split("-", 1)[0] == "en":
            return candidate
    raise DipManifestError(f"unsupported locale {requested!r} and no English fallback")


def build_install_selection(
    manifest: DipManifest,
    entries: Iterable[zipfile.ZipInfo],
    *,
    locale: str,
    required_only: bool = False,
) -> InstallSelection:
    """Select archive files without writing them.

    Entries not named by any progressive chunk are retained. This conservative
    rule prevents an incomplete install when an EA manifest only assigns the
    streamable CAS subset to chunks.
    """
    locale = resolve_manifest_locale(manifest, locale)

    locale_patterns = {
        key: tuple(value) for key, value in manifest.locale_filters.items()
    }
    required_patterns = tuple(
        include for chunk in manifest.chunks if chunk.required for include in chunk.includes
    )
    recommended_patterns = tuple(
        include for chunk in manifest.chunks if not chunk.required for include in chunk.includes
    )

    archive_count = selected_count = selected_compressed = selected_installed = 0
    selected_entries: list[zipfile.ZipInfo] = []
    stored = deflated = other = 0
    omitted_locale_count = omitted_locale_bytes = 0
    omitted_recommended_count = omitted_recommended_bytes = 0
    omitted_patch_count = omitted_patch_bytes = 0
    unassigned_count = unassigned_bytes = invalid_count = 0

    for entry in entries:
        if entry.is_dir():
            continue
        archive_count += 1
        path = normalize_archive_path(entry.filename)
        if not _safe_archive_path(entry.filename):
            invalid_count += 1
            continue
        if ".eapatch" in path:
            omitted_patch_count += 1
            omitted_patch_bytes += entry.compress_size
            continue

        matched_locales = {
            candidate
            for candidate, patterns in locale_patterns.items()
            if any(_matches(path, pattern) for pattern in patterns)
        }
        if matched_locales and locale not in matched_locales:
            omitted_locale_count += 1
            omitted_locale_bytes += entry.compress_size
            continue

        is_required = any(_matches(path, pattern) for pattern in required_patterns)
        is_recommended = any(_matches(path, pattern) for pattern in recommended_patterns)
        if not is_required and not is_recommended:
            unassigned_count += 1
            unassigned_bytes += entry.compress_size
        if required_only and is_recommended and not is_required:
            omitted_recommended_count += 1
            omitted_recommended_bytes += entry.compress_size
            continue

        selected_count += 1
        selected_entries.append(entry)
        selected_compressed += entry.compress_size
        selected_installed += entry.file_size
        if entry.compress_type == zipfile.ZIP_STORED:
            stored += 1
        elif entry.compress_type == zipfile.ZIP_DEFLATED:
            deflated += 1
        else:
            other += 1

    summary = InstallPlanSummary(
        locale=locale,
        required_only=required_only,
        archive_file_count=archive_count,
        selected_file_count=selected_count,
        selected_compressed_bytes=selected_compressed,
        selected_installed_bytes=selected_installed,
        selected_stored_files=stored,
        selected_deflated_files=deflated,
        selected_other_compression_files=other,
        omitted_locale_files=omitted_locale_count,
        omitted_locale_compressed_bytes=omitted_locale_bytes,
        omitted_recommended_files=omitted_recommended_count,
        omitted_recommended_compressed_bytes=omitted_recommended_bytes,
        omitted_patch_files=omitted_patch_count,
        omitted_patch_compressed_bytes=omitted_patch_bytes,
        unassigned_file_count=unassigned_count,
        unassigned_compressed_bytes=unassigned_bytes,
        invalid_path_count=invalid_count,
    )
    return InstallSelection(summary=summary, entries=tuple(selected_entries))


def plan_install(
    manifest: DipManifest,
    entries: Iterable[zipfile.ZipInfo],
    *,
    locale: str,
    required_only: bool = False,
) -> InstallPlanSummary:
    return build_install_selection(
        manifest, entries, locale=locale, required_only=required_only
    ).summary
