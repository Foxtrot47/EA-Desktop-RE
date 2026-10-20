"""Derived launcher view over the lossless private GraphQL snapshot."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .reconcile import reconcile_library


@dataclass(frozen=True)
class LibraryRecord:
    title: str
    offer_id: str
    active: bool
    suppressed: bool
    entitlement_statuses: tuple[str, ...]
    entitlement_types: tuple[str, ...]
    display_type: str | None
    downloadable: bool
    base_platform: str | None
    game_slug: str | None
    installation_directory: str | None
    execute_path: str | None
    installed: bool
    install_location: str | None
    local_source: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text_key(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _local_value(item: object, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def build_library_records(
    snapshot: Mapping[str, Any],
    installed_games: Iterable[object] = (),
) -> list[LibraryRecord]:
    """Join entitlements, catalog records, product titles, and local installs.

    The source snapshot remains the lossless representation. This function
    creates one convenient row per unique entitlement product ID.
    """
    entitlements = snapshot.get("entitlements", [])
    catalog = snapshot.get("catalog", {})
    offers = catalog.get("legacyOffers", []) if isinstance(catalog, Mapping) else []
    products = catalog.get("gameProducts", []) if isinstance(catalog, Mapping) else []
    offers_by_id = {
        value.get("offerId"): value
        for value in offers
        if isinstance(value, Mapping) and isinstance(value.get("offerId"), str)
    }
    products_by_id = {
        value.get("originOfferId"): value
        for value in products
        if isinstance(value, Mapping) and isinstance(value.get("originOfferId"), str)
    }
    entitlements_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for value in entitlements:
        if not isinstance(value, Mapping) or not isinstance(value.get("productId"), str):
            continue
        entitlements_by_id.setdefault(value["productId"], []).append(value)

    local = list(installed_games)
    reconciliation = reconcile_library(snapshot)
    consumed_local: set[int] = set()
    result: list[LibraryRecord] = []
    for offer_id, owned in entitlements_by_id.items():
        offer = offers_by_id.get(offer_id, {})
        product = products_by_id.get(offer_id, {})
        base_item = product.get("baseItem", {}) if isinstance(product.get("baseItem"), Mapping) else {}
        title = next(
            (
                str(value)
                for value in (base_item.get("title"), product.get("name"), offer.get("displayName"), offer_id)
                if value
            ),
            offer_id,
        )
        install_dir = offer.get("installationDirectory") if isinstance(offer.get("installationDirectory"), str) else None

        match_index: int | None = None
        for index, game in enumerate(local):
            if index in consumed_local:
                continue
            local_offer = _local_value(game, "offer_id") or _local_value(game, "launch_id")
            location = str(_local_value(game, "install_location") or "")
            local_name = str(_local_value(game, "name") or "")
            path_leaf = os.path.basename(os.path.normpath(location)) if location else ""
            if local_offer and str(local_offer).casefold() == offer_id.casefold():
                match_index = index
                break
            if install_dir and _text_key(path_leaf) == _text_key(install_dir):
                match_index = index
                break
            if title and local_name and _text_key(title) == _text_key(local_name):
                match_index = index
                break

        installed = match_index is not None
        install_location = local_source = None
        if match_index is not None:
            consumed_local.add(match_index)
            install_location = str(_local_value(local[match_index], "install_location") or "") or None
            local_source = str(_local_value(local[match_index], "source") or "") or None
        statuses = tuple(sorted({str(value.get("status")) for value in owned if value.get("status")}))
        entitlement_types = tuple(sorted({str(value.get("entitlementType")) for value in owned if value.get("entitlementType")}))
        result.append(
            LibraryRecord(
                title=title,
                offer_id=offer_id,
                active="ACTIVE" in statuses,
                suppressed=offer_id in reconciliation.suppressed_offer_ids,
                entitlement_statuses=statuses,
                entitlement_types=entitlement_types,
                display_type=str(offer.get("displayType")) if offer.get("displayType") is not None else None,
                downloadable=offer.get("isDownloadable") is True,
                base_platform=str(offer.get("basePlatform")) if offer.get("basePlatform") is not None else None,
                game_slug=str(product.get("gameSlug")) if product.get("gameSlug") is not None else None,
                installation_directory=install_dir,
                execute_path=str(offer.get("executePathOverride")) if offer.get("executePathOverride") else None,
                installed=installed,
                install_location=install_location,
                local_source=local_source,
            )
        )
    return sorted(result, key=lambda value: (not value.active, value.title.casefold(), value.offer_id.casefold()))


def visible_owned_games(records: Iterable[LibraryRecord]) -> list[LibraryRecord]:
    return [
        record
        for record in records
        if record.active
        and not record.suppressed
        and record.display_type in {"FullGame", "Game Only"}
    ]
