"""Bounded HTTP range access to EA's remote ZIP content archives."""

from __future__ import annotations

import io
import ssl
import threading
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable
from urllib import error, request


class RemoteArchiveError(RuntimeError):
    pass


RangeFetcher = Callable[[int, int], bytes]
UrlRenewer = Callable[[], str]


class HttpRangeFile(io.RawIOBase):
    """A seekable, block-cached view over one short-lived signed URL."""

    def __init__(
        self,
        url: str,
        size: int,
        *,
        block_size: int = 1024 * 1024,
        max_cached_blocks: int = 16,
        max_total_bytes: int = 64 * 1024 * 1024,
        fetcher: RangeFetcher | None = None,
        renew_url: UrlRenewer | None = None,
    ) -> None:
        if size <= 0 or block_size <= 0 or max_cached_blocks <= 0 or max_total_bytes <= 0:
            raise ValueError("range-file sizes and limits must be positive")
        self._url = url
        self._size = size
        self._position = 0
        self._block_size = block_size
        self._max_cached_blocks = max_cached_blocks
        self._max_total_bytes = max_total_bytes
        self._fetcher = fetcher or self._fetch_http
        self._renew_url = renew_url
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._counter_lock = threading.Lock()
        self._renew_lock = threading.Lock()
        self._reserved_bytes = 0
        self.request_count = 0
        self.bytes_fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._position + offset
        elif whence == io.SEEK_END:
            position = self._size + offset
        else:
            raise ValueError("unsupported seek mode")
        if position < 0:
            raise ValueError("negative seek position")
        self._position = min(position, self._size)
        return self._position

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._size - self._position
        size = min(size, self._size - self._position)
        if size <= 0:
            return b""
        start = self._position
        end = start + size
        chunks: list[bytes] = []
        while start < end:
            block_index = start // self._block_size
            block = self._get_block(block_index)
            block_start = block_index * self._block_size
            within = start - block_start
            take = min(len(block) - within, end - start)
            if take <= 0:
                raise RemoteArchiveError("range server returned a truncated block")
            chunks.append(block[within : within + take])
            start += take
        self._position = end
        return b"".join(chunks)

    def _get_block(self, index: int) -> bytes:
        cached = self._cache.pop(index, None)
        if cached is not None:
            self._cache[index] = cached
            return cached
        start = index * self._block_size
        end = min(start + self._block_size, self._size) - 1
        expected = end - start + 1
        value = self.fetch_range(start, end)
        self._cache[index] = value
        while len(self._cache) > self._max_cached_blocks:
            self._cache.popitem(last=False)
        return value

    def fetch_range(self, start: int, end: int) -> bytes:
        """Fetch an exact archive interval, safe for concurrent large-file reads."""
        if start < 0 or end < start or end >= self._size:
            raise RemoteArchiveError("remote archive range is out of bounds")
        expected = end - start + 1
        with self._counter_lock:
            if self.bytes_fetched + self._reserved_bytes + expected > self._max_total_bytes:
                raise RemoteArchiveError("remote archive read exceeded the configured byte limit")
            self._reserved_bytes += expected
        try:
            value = self._fetcher(start, end)
            if len(value) != expected:
                raise RemoteArchiveError("range server returned an unexpected byte count")
            with self._counter_lock:
                self.request_count += 1
                self.bytes_fetched += len(value)
            return value
        finally:
            with self._counter_lock:
                self._reserved_bytes -= expected

    def _fetch_http(self, start: int, end: int) -> bytes:
        for attempt in range(2):
            current_url = self._url
            http_request = request.Request(
                current_url,
                headers={
                    "Range": f"bytes={start}-{end}",
                    "Accept-Encoding": "identity",
                    "User-Agent": "EA app/13.809.0.6322 Windows/10",
                },
                method="GET",
            )
            tls = ssl.create_default_context()
            try:
                with request.urlopen(http_request, timeout=60, context=tls) as response:
                    if response.status != 206:
                        raise RemoteArchiveError(f"range request returned HTTP {response.status}")
                    content_range = response.headers.get("Content-Range", "")
                    expected_prefix = f"bytes {start}-{end}/"
                    if not content_range.startswith(expected_prefix):
                        raise RemoteArchiveError("range response has an unexpected Content-Range")
                    return response.read(end - start + 2)
            except error.HTTPError as exc:
                if attempt == 0 and exc.code in {401, 403} and self._renew_url is not None:
                    with self._renew_lock:
                        if self._url == current_url:
                            renewed = self._renew_url()
                            if not renewed:
                                raise RemoteArchiveError("signed archive URL renewal returned no URL") from None
                            self._url = renewed
                    continue
                raise RemoteArchiveError(f"range request returned HTTP {exc.code}") from None
            except (error.URLError, TimeoutError) as exc:
                raise RemoteArchiveError(f"range request failed: {type(exc).__name__}") from None
        raise RemoteArchiveError("signed archive URL renewal failed")


@dataclass(frozen=True)
class RemoteManifest:
    archive_member: str
    data: bytes
    archive_entry_count: int
    range_request_count: int
    bytes_fetched: int


def read_named_member(
    remote: HttpRangeFile,
    member_name: str,
    *,
    max_member_bytes: int = 16 * 1024 * 1024,
) -> bytes:
    """Read one named member case-insensitively and verify its ZIP CRC."""
    normalized = member_name.lstrip("/\\").replace("\\", "/").casefold()
    try:
        with zipfile.ZipFile(remote) as archive:
            selected = next(
                (
                    item
                    for item in archive.infolist()
                    if item.filename.replace("\\", "/").casefold() == normalized
                ),
                None,
            )
            if selected is None:
                raise RemoteArchiveError(f"archive member was not found: {member_name}")
            if selected.file_size > max_member_bytes:
                raise RemoteArchiveError("archive member exceeds the configured size limit")
            return archive.read(selected)
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        raise RemoteArchiveError("EA content archive is not a valid ZIP") from None


def read_dip_manifest(
    url: str,
    archive_size: int,
    *,
    max_manifest_bytes: int = 16 * 1024 * 1024,
    range_file: HttpRangeFile | None = None,
) -> RemoteManifest:
    """Read and CRC-check ``installerdata.xml`` without downloading the archive."""
    remote = range_file or HttpRangeFile(url, archive_size)
    try:
        with zipfile.ZipFile(remote) as archive:
            entries = archive.infolist()
            candidates = [
                item
                for item in entries
                if item.filename.replace("\\", "/").casefold().endswith("installerdata.xml")
            ]
            if not candidates:
                raise RemoteArchiveError("DiP installerdata.xml was not found in the archive")
            # EA selects the matching content-manifest entry. Prefer the exact
            # conventional path when a package contains more than one basename.
            candidates.sort(
                key=lambda item: (
                    item.filename.replace("\\", "/").casefold()
                    != "__installer/installerdata.xml".casefold(),
                    len(item.filename),
                )
            )
            selected = candidates[0]
            if selected.file_size > max_manifest_bytes:
                raise RemoteArchiveError("DiP manifest exceeds the configured size limit")
            data = archive.read(selected)
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise RemoteArchiveError(f"EA content archive is not a valid ZIP: {type(exc).__name__}") from None
    return RemoteManifest(
        archive_member=selected.filename,
        data=data,
        archive_entry_count=len(entries),
        range_request_count=remote.request_count,
        bytes_fetched=remote.bytes_fetched,
    )
