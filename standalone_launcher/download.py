"""Resolve entitled EA content packages through the recovered JIT URL query."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

from .library import GraphQlError, QueryExecutor


JIT_URL_QUERY = r"""
query JitUrlRequest(
  $offerId: String!
  $cdnOverride: String
  $buildId: String
  $preferredLanguage: String = ""
  $patchFromVersion: String = ""
  $fetchSyncPackage: Boolean!
  $enableVersionUpdate: Boolean!
) {
  jitUrl: downloadUrl(offerId: $offerId, cdnOverride: $cdnOverride, buildId: $buildId) {
    url
    archiveSize
    syncUrl @include(if: $fetchSyncPackage)
    syncArchiveSize @include(if: $fetchSyncPackage)
    knownVersionUpdateInfo(
      preferredLanguage: $preferredLanguage
      patchFromVersion: $patchFromVersion
    ) @include(if: $enableVersionUpdate) {
      planUrl
      planArchiveSize
      baseStreamUrl
      baseStreamArchiveSize
      languageStreamUrl
      languageStreamArchiveSize
    }
  }
}
""".strip()


@dataclass(frozen=True)
class KnownVersionUpdateInfo:
    plan_url: str = field(repr=False)
    plan_archive_size: int
    base_stream_url: str = field(repr=False)
    base_stream_archive_size: int
    language_stream_url: str | None = field(default=None, repr=False)
    language_stream_archive_size: int | None = None


@dataclass(frozen=True)
class DownloadDescriptor:
    offer_id: str
    url: str = field(repr=False)
    archive_size: int
    sync_url: str | None = field(default=None, repr=False)
    sync_archive_size: int | None = None
    known_version_update: KnownVersionUpdateInfo | None = None

    def sanitized_summary(self) -> dict[str, object]:
        """Return useful metadata without disclosing signed URL paths/queries."""
        update = self.known_version_update
        return {
            "offer_id": self.offer_id,
            "cdn_host": urlsplit(self.url).hostname,
            "archive_size": self.archive_size,
            "has_sync_package": self.sync_url is not None,
            "sync_archive_size": self.sync_archive_size,
            "has_known_version_update": update is not None,
            "plan_archive_size": update.plan_archive_size if update else None,
            "base_stream_archive_size": update.base_stream_archive_size if update else None,
            "language_stream_archive_size": update.language_stream_archive_size if update else None,
        }


def _required_string(value: Mapping[str, Any], name: str) -> str:
    found = value.get(name)
    if not isinstance(found, str) or not found:
        raise GraphQlError(f"EA JIT URL response has no {name}")
    return found


def _required_size(value: Mapping[str, Any], name: str) -> int:
    found = value.get(name)
    if isinstance(found, bool) or not isinstance(found, (int, float)) or int(found) <= 0:
        raise GraphQlError(f"EA JIT URL response has invalid {name}")
    return int(found)


def _optional_size(value: Mapping[str, Any], name: str) -> int | None:
    found = value.get(name)
    if found is None:
        return None
    return _required_size(value, name)


def get_download_descriptor(
    client: QueryExecutor,
    offer_id: str,
    *,
    cdn_override: str | None = None,
    build_id: str | None = None,
    preferred_language: str = "",
    patch_from_version: str = "",
    fetch_sync_package: bool = False,
    enable_version_update: bool = False,
) -> DownloadDescriptor:
    """Resolve a short-lived package descriptor for an entitled offer.

    This only asks EA for metadata. It does not fetch a manifest or package.
    """
    if not offer_id:
        raise ValueError("offer_id is required")
    data = client.execute(
        JIT_URL_QUERY,
        {
            "offerId": offer_id,
            "cdnOverride": cdn_override,
            "buildId": build_id,
            "preferredLanguage": preferred_language,
            "patchFromVersion": patch_from_version,
            "fetchSyncPackage": fetch_sync_package,
            "enableVersionUpdate": enable_version_update,
        },
    )
    raw = data.get("jitUrl")
    if not isinstance(raw, Mapping):
        raise GraphQlError("EA JIT URL response has no descriptor")

    sync_url = raw.get("syncUrl")
    if sync_url is not None and not isinstance(sync_url, str):
        raise GraphQlError("EA JIT URL response has invalid syncUrl")

    update_raw = raw.get("knownVersionUpdateInfo")
    update: KnownVersionUpdateInfo | None = None
    if update_raw is not None:
        if not isinstance(update_raw, Mapping):
            raise GraphQlError("EA JIT URL response has invalid knownVersionUpdateInfo")
        language_url = update_raw.get("languageStreamUrl")
        if language_url is not None and not isinstance(language_url, str):
            raise GraphQlError("EA JIT URL response has invalid languageStreamUrl")
        update = KnownVersionUpdateInfo(
            plan_url=_required_string(update_raw, "planUrl"),
            plan_archive_size=_required_size(update_raw, "planArchiveSize"),
            base_stream_url=_required_string(update_raw, "baseStreamUrl"),
            base_stream_archive_size=_required_size(update_raw, "baseStreamArchiveSize"),
            language_stream_url=language_url or None,
            language_stream_archive_size=_optional_size(update_raw, "languageStreamArchiveSize"),
        )

    return DownloadDescriptor(
        offer_id=offer_id,
        url=_required_string(raw, "url"),
        archive_size=_required_size(raw, "archiveSize"),
        sync_url=sync_url or None,
        sync_archive_size=_optional_size(raw, "syncArchiveSize"),
        known_version_update=update,
    )
