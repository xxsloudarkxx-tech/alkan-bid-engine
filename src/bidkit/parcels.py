"""Optional official-source enrichment contract. Disabled until live verification."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ParcelSource:
    name: str
    endpoint: str | None = None
    enabled: bool = False
    verification_status: str = "PENDING_OFFICIAL_ENDPOINT_TERMS_FIELDS_AND_LIVE_TEST"

SOURCES = {key: ParcelSource(name) for key, name in {
    "washington": "Washington State Parcels", "king": "King County",
    "pierce": "Pierce County", "snohomish": "Snohomish County"}.items()}


def enrich(source: str, address: str):
    config = SOURCES[source]
    return {"source": config.name, "address_query": address, "status": "UNAVAILABLE_CONNECTOR_DISABLED",
            "endpoint_verified": False, "retrieved_at": None, "parcel_id": None,
            "land_area": None, "building_area": None, "tax_reference": None,
            "use_as_construction_measurement": False, "verification_status": config.verification_status}
