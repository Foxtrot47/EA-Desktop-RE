"""EA content-library reconciliation derived from EABackgroundService.

The GraphQL entitlement response is a history-like feed.  EA Desktop first
admits active records into its content store, then removes offers named by the
suppression metadata of owned content.  Keeping this step separate from the
lossless snapshot makes the raw account data available for diagnostics while
giving the launcher the same effective ownership view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# EABackgroundService 13.809.0.6322 inserts this offer into the suppression set
# unconditionally in ContentLibraryComponent::Impl::applyEntitlementFilters.
BUILTIN_SUPPRESSED_OFFER_IDS = frozenset({"OFB-EAST:109551057"})

# The native predicate skips suppression propagation for external storefront
# enum values 2, 3, and 4.  The GraphQL names observed for those integrations
# are Steam, Epic, and Microsoft.
PARTNER_EXTERNAL_TYPES = frozenset({"STEAM", "EPIC", "MICROSOFT"})


@dataclass(frozen=True)
class ReconciliationResult:
    active_entitlement_count: int
    active_offer_ids: frozenset[str]
    suppressed_offer_ids: frozenset[str]
    effective_offer_ids: frozenset[str]
    suppression_sources: Mapping[str, tuple[str, ...]]


def _catalog_offers(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    catalog = snapshot.get("catalog")
    values = catalog.get("legacyOffers", []) if isinstance(catalog, Mapping) else []
    return {
        value["offerId"]: value
        for value in values
        if isinstance(value, Mapping)
        and isinstance(value.get("offerId"), str)
        and value["offerId"]
    }


def _is_base_game(offer: Mapping[str, Any]) -> bool:
    # The normalized native catalog model stores a computed isBaseGame flag.
    # The public legacy catalog response exposes its source as displayType.
    return offer.get("displayType") in {"FullGame", "Game Only"}


def reconcile_library(snapshot: Mapping[str, Any]) -> ReconciliationResult:
    """Compute the effective owned-offer set used by EA's content store.

    This models the two relevant native passes:

    * only status enum 1 (``ACTIVE`` in GraphQL) enters the joined store;
    * active EA/subscription entitlements propagate ``suppressedOfferIds``
      when they are non-base content or use the ``ORIGIN_DOWNLOAD`` type;
    * the build's hard-coded offer suppression is then applied.

    QA-only suppression lists are intentionally absent because a standalone
    launcher has no EA QA configuration service.
    """
    entitlements = snapshot.get("entitlements", [])
    offers_by_id = _catalog_offers(snapshot)
    active: list[Mapping[str, Any]] = [
        value
        for value in entitlements
        if isinstance(value, Mapping)
        and value.get("status") == "ACTIVE"
        and isinstance(value.get("productId"), str)
        and value["productId"]
    ]
    active_offer_ids = frozenset(str(value["productId"]) for value in active)

    sources: dict[str, set[str]] = {
        target: {"builtin"} for target in BUILTIN_SUPPRESSED_OFFER_IDS
    }
    for entitlement in active:
        source_id = str(entitlement["productId"])
        offer = offers_by_id.get(source_id)
        if offer is None:
            continue
        external_type = str(entitlement.get("externalType") or "").upper()
        if external_type in PARTNER_EXTERNAL_TYPES:
            continue
        entitlement_type = str(entitlement.get("entitlementType") or "").upper()
        if _is_base_game(offer) and entitlement_type != "ORIGIN_DOWNLOAD":
            continue
        targets = offer.get("suppressedOfferIds")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if isinstance(target, str) and target:
                sources.setdefault(target, set()).add(source_id)

    suppressed = frozenset(sources)
    return ReconciliationResult(
        active_entitlement_count=len(active),
        active_offer_ids=active_offer_ids,
        suppressed_offer_ids=suppressed,
        effective_offer_ids=active_offer_ids - suppressed,
        suppression_sources={
            target: tuple(sorted(values)) for target, values in sorted(sources.items())
        },
    )
