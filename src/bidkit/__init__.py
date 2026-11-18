"""BidKit: reproducible, source-backed public construction bid workpapers."""
from __future__ import annotations

from .alkan_method import (
    BASE_MARKUP,
    PROJECT_STATES,
    ProjectEstimate,
    QuoteLineItem,
    ScopeItem,
    SupplierQuote,
    apply_contractor_adjustment,
    apply_supplier_quote,
    calculate_preestimate,
    finalize_project_estimate,
    generate_project_pdfs,
    transition_project_state,
)
from .contractor import (
    ComplianceRequirement,
    ContractorIdentity,
    format_compliance_summary,
    get_blocking_requirements,
    load_compliance_requirements,
    load_contractor_identity,
)

__version__ = "3.7.0"

__all__ = [
    "__version__",
    "BASE_MARKUP",
    "PROJECT_STATES",
    "ComplianceRequirement",
    "ContractorIdentity",
    "ProjectEstimate",
    "QuoteLineItem",
    "ScopeItem",
    "SupplierQuote",
    "apply_contractor_adjustment",
    "apply_supplier_quote",
    "calculate_preestimate",
    "finalize_project_estimate",
    "format_compliance_summary",
    "generate_project_pdfs",
    "get_blocking_requirements",
    "load_compliance_requirements",
    "load_contractor_identity",
    "transition_project_state",
]
