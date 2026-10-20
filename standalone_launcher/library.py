"""Standalone EA identity, entitlement, and catalog retrieval.

The GraphQL documents in this module are copied from EA Desktop 13.809.0.6322.
Credential-bearing headers and private response documents are never logged by
this layer.  Complete snapshots should be persisted with ``save_snapshot_dpapi``.
"""

from __future__ import annotations

import json
import ssl
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib import error, request

from .bootstrap import dpapi_protect, dpapi_unprotect


GRAPHQL_ENDPOINT = "https://service-aggregation-layer.juno.ea.com/graphql"

CURRENT_USER_QUERY = r"""
query getCurrentUser {
  requestCountry
  me {
    userId
    isUnderage
    isBanned
    banInfo { endDate }
    country
    personas {
      psd
      displayName
      name
      namespaceName
      showPersona
    }
    highestOrRecentSubscription {
      level
      status
      end
      type
    }
    subscriptions(status: ACTIVE, storefronts: [STEAM, EPIC]) {
      offerId
      recurring
      start
      end
      level
      status
      offer { offerName duration }
      platform
      type
      statusReasonCode
      acquisitionMethod
    }
  }
}
""".strip()

LEGACY_ENTITLEMENTS_QUERY = r"""
query getLegacyEntitlements($limit: Int, $next: String, $storeFronts: [UserLegacyEntitlementStorefront!]!) {
  me {
    legacyEntitlements(
      paging: {limit: $limit, next: $next},
      storefronts: $storeFronts,
      status: [ACTIVE, DISABLED]
    ) {
      next
      items {
        cdKey
        entitlementTag
        entitlementType
        externalType
        grantDate
        groupName
        id
        isSubscription
        isSubscriptionExpired
        lastModifiedDate
        originPermissions
        productId
        status
        statusReasonCode
        terminationDate
        trialTimeRemainingSeconds
        useCount
        version
      }
    }
  }
}
""".strip()

LEGACY_CATALOG_QUERY = r"""
query getLegacyCatalogDefs($offerIds: [String!]!, $locale: Locale) {
  legacyOffers(offerIds: $offerIds, locale: $locale) {
    offerId: id
    contentId
    basePlatform
    primaryMasterTitleId
    mdmProjectNumber
    achievementSetOverride
    gameLauncherURL
    gameLauncherURLClientID
    stagingKeyPath
    mdmTitleIds
    multiplayerId
    executePathOverride
    installationDirectory
    installCheckOverride
    monitorPlay
    displayName
    displayType
    igoBrowserDefaultUrl
    executeParameters
    softwareLocales
    dipManifestRelativePath
    metadataInstallLocation
    distributionSubType
    downloads {
      igoApiEnabled
      downloadType
      version
      executeElevated
      buildReleaseVersion
      buildLiveDate
      buildMetaData
      gameVersion
      treatUpdatesAsMandatory
      enableDifferentialUpdate
    }
    locale
    greyMarketControls
    isDownloadable
    isPreviewDownload
    downloadStartDate
    releaseDate
    useEndDate
    subscriptionUnlockDate
    subscriptionUseEndDate
    softwarePlatform
    softwareId
    downloadPackageType
    installerPath
    processorArchitecture
    macBundleID
    gameEditionTypeFacetKeyRankDesc
    appliedCountryCode
    cloudSaveConfigurationOverride
    firstParties { partner partnerId partnerIdType }
    suppressedOfferIds
  }
  gameProducts(offerIds: $offerIds, locale: $locale) {
    items {
      name
      originOfferId
      isAgeVerificationRequired
      baseItem {
        title
        baseGameSlug
        gameType
        regionalRatingV2 { ageRating { minAge } }
      }
      gameSlug
    }
  }
}
""".strip()


class GraphQlError(RuntimeError):
    pass


class QueryExecutor(Protocol):
    def execute(self, query: str, variables: Mapping[str, Any] | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GraphQlClient:
    access_token: str
    endpoint: str = GRAPHQL_ENDPOINT
    timeout: int = 60

    def execute(self, query: str, variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(
            {"query": query, "variables": dict(variables or {})},
            separators=(",", ":"),
        ).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "EA app/13.809.0.6322 Windows/10",
            },
            method="POST",
        )
        # The current Akamai edge accepts TLS 1.3, then repeatedly requests
        # renegotiation and never returns the HTTP response. EA's transport and
        # a TLS-1.2-only probe both complete normally, so pin the protocol here.
        tls = ssl.create_default_context()
        tls.maximum_version = ssl.TLSVersion.TLSv1_2
        try:
            with request.urlopen(http_request, timeout=self.timeout, context=tls) as response:
                document = json.load(response)
        except error.HTTPError as exc:
            raise GraphQlError(f"EA GraphQL request failed with HTTP {exc.code}") from None
        except (error.URLError, TimeoutError) as exc:
            raise GraphQlError(f"EA GraphQL request failed: {type(exc).__name__}") from None
        if not isinstance(document, dict):
            raise GraphQlError("EA GraphQL response is not an object")
        errors = document.get("errors")
        if errors:
            # Do not include the server response: GraphQL paths/extensions can
            # contain account or offer identifiers.
            count = len(errors) if isinstance(errors, list) else 1
            raise GraphQlError(f"EA GraphQL returned {count} error(s)")
        data = document.get("data")
        if not isinstance(data, dict):
            raise GraphQlError("EA GraphQL response has no data object")
        return data


def get_current_user(client: QueryExecutor) -> dict[str, Any]:
    return client.execute(CURRENT_USER_QUERY)


def get_legacy_entitlements(
    client: QueryExecutor,
    *,
    page_size: int = 100,
    storefronts: Iterable[str] = ("EA", "EPIC", "STEAM"),
) -> tuple[list[dict[str, Any]], int]:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    pages = 0
    while True:
        data = client.execute(
            LEGACY_ENTITLEMENTS_QUERY,
            {"limit": page_size, "next": cursor, "storeFronts": list(storefronts)},
        )
        try:
            page = data["me"]["legacyEntitlements"]
            page_items = page["items"]
        except (KeyError, TypeError) as exc:
            raise GraphQlError("unexpected entitlement response shape") from exc
        if not isinstance(page_items, list):
            raise GraphQlError("entitlement items is not an array")
        items.extend(item for item in page_items if isinstance(item, dict))
        pages += 1
        next_cursor = page.get("next")
        if not next_cursor:
            return items, pages
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise GraphQlError("invalid or repeated entitlement cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _batches(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def get_legacy_catalog(
    client: QueryExecutor,
    offer_ids: Iterable[str],
    *,
    batch_size: int = 16,
    max_parallel: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if batch_size < 1 or max_parallel < 1:
        raise ValueError("batch_size and max_parallel must be positive")
    unique_ids = list(dict.fromkeys(value for value in offer_ids if value))
    batches = _batches(unique_ids, batch_size)

    def fetch(batch: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        data = client.execute(LEGACY_CATALOG_QUERY, {"offerIds": batch, "locale": "DEFAULT"})
        offers = data.get("legacyOffers")
        products = data.get("gameProducts", {}).get("items") if isinstance(data.get("gameProducts"), dict) else None
        if not isinstance(offers, list) or not isinstance(products, list):
            raise GraphQlError("unexpected catalog response shape")
        return (
            [value for value in offers if isinstance(value, dict)],
            [value for value in products if isinstance(value, dict)],
        )

    offers_by_batch: dict[int, list[dict[str, Any]]] = {}
    products_by_batch: dict[int, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(fetch, batch): index for index, batch in enumerate(batches)}
        for future in as_completed(futures):
            index = futures[future]
            offers_by_batch[index], products_by_batch[index] = future.result()
    offers = [item for index in range(len(batches)) for item in offers_by_batch[index]]
    products = [item for index in range(len(batches)) for item in products_by_batch[index]]
    return offers, products, len(batches)


def retrieve_library(
    client: QueryExecutor,
    progress: Callable[[str, Mapping[str, int]], None] | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _stage, _counts: None)
    report("current_user", {})
    identity = get_current_user(client)
    report("entitlements", {})
    entitlements, entitlement_pages = get_legacy_entitlements(client)
    product_ids = [
        item["productId"]
        for item in entitlements
        if isinstance(item.get("productId"), str) and item["productId"]
    ]
    report("catalog", {"unique_product_ids": len(set(product_ids))})
    offers, products, catalog_batches = get_legacy_catalog(client, product_ids)
    report(
        "complete",
        {
            "entitlements": len(entitlements),
            "legacy_offers": len(offers),
            "game_products": len(products),
        },
    )
    return {
        "schema": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "entitlements": entitlements,
        "catalog": {"legacyOffers": offers, "gameProducts": products},
        "retrieval": {
            "entitlement_pages": entitlement_pages,
            "catalog_batches": catalog_batches,
            "unique_product_ids": len(set(product_ids)),
        },
    }


def save_snapshot_dpapi(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(dpapi_protect(plaintext, "EA standalone launcher private library snapshot"))


def load_snapshot_dpapi(path: Path) -> dict[str, Any]:
    value = json.loads(dpapi_unprotect(path.read_bytes()))
    if not isinstance(value, dict):
        raise ValueError("library snapshot is not an object")
    return value


def sanitized_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    entitlements = snapshot.get("entitlements", [])
    catalog = snapshot.get("catalog", {})
    identity = snapshot.get("identity", {})
    me = identity.get("me", {}) if isinstance(identity, dict) else {}
    offers = catalog.get("legacyOffers", []) if isinstance(catalog, dict) else []
    products = catalog.get("gameProducts", []) if isinstance(catalog, dict) else []
    statuses = Counter(
        str(item.get("status"))
        for item in entitlements
        if isinstance(item, dict) and item.get("status") is not None
    )
    return {
        "schema": snapshot.get("schema"),
        "captured_at_utc": snapshot.get("captured_at_utc"),
        "current_user_present": isinstance(me, dict) and bool(me.get("userId")),
        "persona_count": len(me.get("personas", [])) if isinstance(me, dict) and isinstance(me.get("personas"), list) else 0,
        "subscription_count": len(me.get("subscriptions", [])) if isinstance(me, dict) and isinstance(me.get("subscriptions"), list) else 0,
        "entitlement_count": len(entitlements) if isinstance(entitlements, list) else 0,
        "entitlement_status_counts": dict(sorted(statuses.items())),
        "legacy_offer_count": len(offers) if isinstance(offers, list) else 0,
        "game_product_count": len(products) if isinstance(products, list) else 0,
        "retrieval": snapshot.get("retrieval", {}),
    }
