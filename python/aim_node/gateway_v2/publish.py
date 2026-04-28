from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface, reject_payload_contract_fields


PUBLISH_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.PUBLISH]
PublishGovernanceState = Literal[
    "pending_review",
    "review_required",
    "abuse_blocked",
    "trust_requirement_unmet",
    "publish_denied",
    "published",
]


@dataclass(frozen=True)
class SignedReference:
    ref: str
    signer_identity: str
    signature_state: str
    verification_state: str
    artifact_hash: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class ListingMetadata:
    title: str
    summary: str
    tags: list[str] | None = None
    category: str | None = None


@dataclass(frozen=True)
class ListingPricing:
    model: str
    currency: str
    unit_amount_cents: int
    billing_unit: str


@dataclass(frozen=True)
class ListingSamplePolicy:
    preview_refs: list[SignedReference] | None = None
    summary: str | None = None
    row_count: int | None = None
    column_names: list[str] | None = None


@dataclass(frozen=True)
class LicenseTerms:
    terms_ref: SignedReference
    commercial_use: bool | None = None
    retention_days: int | None = None


@dataclass(frozen=True)
class PublishRequest:
    metadata: dict[str, Any]
    seller_id: str
    listing_metadata: ListingMetadata
    delivery_modes: list[str]
    pricing: ListingPricing
    license_terms: LicenseTerms
    sample_policy: ListingSamplePolicy | None = None
    trust_artifact_refs: list[SignedReference] | None = None
    seller_verification_ref: SignedReference | None = None
    listing_review_policy: str | None = None
    abuse_signals: list[str] | None = None


@dataclass(frozen=True)
class PatchListingRequest:
    metadata: dict[str, Any]
    listing_version_id: str | None = None
    listing_metadata: ListingMetadata | None = None
    delivery_modes: list[str] | None = None
    pricing: ListingPricing | None = None
    sample_policy: ListingSamplePolicy | None = None
    license_terms: LicenseTerms | None = None
    trust_artifact_refs: list[SignedReference] | None = None
    seller_verification_ref: SignedReference | None = None
    listing_review_policy: str | None = None
    abuse_signals: list[str] | None = None


@dataclass(frozen=True)
class PublishedListing:
    listing_id: str
    listing_version_id: str
    seller_id: str
    state: PublishGovernanceState
    discoverable: bool
    quote_eligible: bool
    listing_metadata: ListingMetadata
    delivery_modes: list[str]
    pricing: ListingPricing
    sample_policy: ListingSamplePolicy
    license_terms: LicenseTerms
    trust_artifact_refs: list[SignedReference]
    seller_verification_ref: SignedReference | None = None
    listing_review_policy: str | None = None
    governance_events: list[str] | None = None
    reason_code: str | None = None


class LocalPublishDraftCache:
    def __init__(self) -> None:
        self._drafts: dict[str, PublishRequest] = {}

    def save_draft(self, key: str, draft: PublishRequest) -> None:
        assert_publish_request_has_no_payload(draft)
        self._drafts[key] = draft

    def get_draft(self, key: str) -> PublishRequest | None:
        return self._drafts.get(key)

    def delete_draft(self, key: str) -> bool:
        return self._drafts.pop(key, None) is not None


class GatewayPublishClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()
        self.draft_cache = LocalPublishDraftCache()

    def publish(self, request: PublishRequest) -> PublishedListing:
        assert_publish_request_has_no_payload(request)
        response = self.client.post(
            f"{self.base_url}/v1/gateway/publish",
            json=_drop_none(asdict(request)),
            headers=self._headers(request.metadata),
        )
        response.raise_for_status()
        return _parse_published_listing(response.json())

    def patch_listing(
        self,
        listing_id: str,
        request: PatchListingRequest,
        if_match: str | None = None,
    ) -> PublishedListing:
        assert_no_payload_deep(asdict(request))
        headers = self._headers(request.metadata)
        if if_match:
            headers["if-match"] = if_match
        response = self.client.patch(
            f"{self.base_url}/v1/gateway/listings/{listing_id}",
            json=_drop_none(asdict(request)),
            headers=headers,
        )
        response.raise_for_status()
        return _parse_published_listing(response.json())

    def _headers(self, metadata: dict[str, Any]) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(metadata, "requestId", "request_id")),
        }
        idempotency_key = _pick(metadata, "idempotencyKey", "idempotency_key")
        if idempotency_key:
            headers["idempotency-key"] = str(idempotency_key)
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers


def assert_publish_request_has_no_payload(request: PublishRequest) -> None:
    assert_no_payload_deep(asdict(request))


def assert_no_payload_deep(value: Any) -> None:
    if isinstance(value, dict):
        reject_payload_contract_fields(value.keys())
        for child in value.values():
            assert_no_payload_deep(child)
    elif isinstance(value, list | tuple):
        for child in value:
            assert_no_payload_deep(child)


def _parse_published_listing(data: dict[str, Any]) -> PublishedListing:
    return PublishedListing(
        listing_id=str(_pick_required(data, "listing_id", "listingId")),
        listing_version_id=str(_pick_required(data, "listing_version_id", "listingVersionId")),
        seller_id=str(_pick_required(data, "seller_id", "sellerId")),
        state=str(_pick_required(data, "state")),
        discoverable=bool(_pick_required(data, "discoverable")),
        quote_eligible=bool(_pick_required(data, "quote_eligible", "quoteEligible")),
        listing_metadata=_parse_listing_metadata(_pick_required(data, "listing_metadata", "listingMetadata")),
        delivery_modes=list(_pick_required(data, "delivery_modes", "deliveryModes")),
        pricing=_parse_pricing(_pick_required(data, "pricing")),
        sample_policy=_parse_sample_policy(_pick_required(data, "sample_policy", "samplePolicy")),
        license_terms=_parse_license_terms(_pick_required(data, "license_terms", "licenseTerms")),
        trust_artifact_refs=[
            _parse_signed_reference(item) for item in _pick(data, "trust_artifact_refs", "trustArtifactRefs") or []
        ],
        seller_verification_ref=_parse_optional_signed_reference(
            _pick(data, "seller_verification_ref", "sellerVerificationRef")
        ),
        listing_review_policy=_pick(data, "listing_review_policy", "listingReviewPolicy"),
        governance_events=_pick(data, "governance_events", "governanceEvents"),
        reason_code=_pick(data, "reason_code", "reasonCode"),
    )


def _parse_signed_reference(data: dict[str, Any]) -> SignedReference:
    return SignedReference(
        ref=data["ref"],
        artifact_hash=_pick(data, "artifact_hash", "artifactHash"),
        signer_identity=str(_pick_required(data, "signer_identity", "signerIdentity")),
        signature_state=str(_pick_required(data, "signature_state", "signatureState")),
        verification_state=str(_pick_required(data, "verification_state", "verificationState")),
        expires_at=_pick(data, "expires_at", "expiresAt"),
    )


def _parse_optional_signed_reference(data: dict[str, Any] | None) -> SignedReference | None:
    return _parse_signed_reference(data) if data else None


def _parse_listing_metadata(data: dict[str, Any]) -> ListingMetadata:
    return ListingMetadata(
        title=data["title"],
        summary=data["summary"],
        tags=data.get("tags"),
        category=data.get("category"),
    )


def _parse_pricing(data: dict[str, Any]) -> ListingPricing:
    return ListingPricing(
        model=data["model"],
        currency=data["currency"],
        unit_amount_cents=int(_pick_required(data, "unit_amount_cents", "unitAmountCents")),
        billing_unit=str(_pick_required(data, "billing_unit", "billingUnit")),
    )


def _parse_sample_policy(data: dict[str, Any]) -> ListingSamplePolicy:
    return ListingSamplePolicy(
        preview_refs=[_parse_signed_reference(item) for item in _pick(data, "preview_refs", "previewRefs") or []],
        summary=data.get("summary"),
        row_count=_pick(data, "row_count", "rowCount"),
        column_names=_pick(data, "column_names", "columnNames"),
    )


def _parse_license_terms(data: dict[str, Any]) -> LicenseTerms:
    return LicenseTerms(
        terms_ref=_parse_signed_reference(_pick_required(data, "terms_ref", "termsRef")),
        commercial_use=_pick(data, "commercial_use", "commercialUse"),
        retention_days=_pick(data, "retention_days", "retentionDays"),
    )


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _pick_required(data: dict[str, Any], *keys: str) -> Any:
    value = _pick(data, *keys)
    if value is None:
        raise KeyError(keys[0])
    return value


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _drop_none(value) if isinstance(value, dict) else value
        for key, value in data.items()
        if value is not None
    }
