"""RFI draft generator, Supplier RFQ builder, quote comparator, and guarded communications log."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import threading
from typing import Any

from openpyxl import Workbook

from .package_method import Package
from .security import AuthorizationError, SecurityContext, require_permission, sanitize_spreadsheet_cell


class UnAuthorizedOutboundError(PermissionError):
    """Raised if outbound RFQ/RFI dispatch is attempted without explicit human authorization."""


@dataclass
class RFIDraft:
    rfi_id: str
    subject: str
    question: str
    reference_doc: str
    impact: str
    priority: str = "HIGH"  # LOW | MEDIUM | HIGH | CRITICAL
    status: str = "draft"   # draft | ready_for_review | authorized_to_send | sent | answered
    response_text: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupplierRFQ:
    rfq_id: str
    supplier_category: str
    supplier_name: str
    project_key: str
    due_date: str
    items: list[dict[str, Any]]
    status: str = "draft"  # draft | ready_for_review | authorized_to_send | sent | quoted
    authorized_by: str = ""
    authorized_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RFIRFQWorkspace:
    """Manages RFI drafts, Supplier RFQ packages, quote coverage comparisons, and comm logs."""

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"rfis": {}, "rfqs": {}, "received_quotes": {}, "communications": []}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def generate_rfis_from_gaps(
        self,
        *,
        takeoff_gaps: list[dict[str, Any]],
        revision_conflicts: list[dict[str, Any]] | None = None,
    ) -> list[RFIDraft]:
        """Generate numbered RFI drafts from unresolved takeoff measurements and document conflicts."""
        created: list[RFIDraft] = []
        with self._lock:
            data = self._load()
            next_num = len(data["rfis"]) + 1
            for gap in takeoff_gaps:
                rid = f"RFI-{next_num:03d}"
                next_num += 1
                draft = RFIDraft(
                    rfi_id=rid,
                    subject=f"Clarification required for {gap.get('code', 'scope item')}",
                    question=str(gap.get("message") or "Provide verified dimensions/quantities."),
                    reference_doc=str(gap.get("source_sheet") or "Plans/Specs"),
                    impact="Prevents firm lump-sum pricing; currently provisional/blocked.",
                    priority=str(gap.get("severity") or "HIGH"),
                )
                data["rfis"][rid] = draft.to_dict()
                created.append(draft)
            for conf in revision_conflicts or []:
                rid = f"RFI-{next_num:03d}"
                next_num += 1
                draft = RFIDraft(
                    rfi_id=rid,
                    subject=f"Resolve discrepancy on {conf.get('sheet_or_section', 'contract docs')}",
                    question=f"{conf.get('detail')} Base='{conf.get('base_value')}' vs Revised='{conf.get('revised_value')}'. Which governs?",
                    reference_doc=str(conf.get("sheet_or_section") or "Spec vs Drawings"),
                    impact="Scope & specification selection impact.",
                    priority=str(conf.get("severity") or "HIGH"),
                )
                data["rfis"][rid] = draft.to_dict()
                created.append(draft)
            self._save(data)
        return created

    def build_rfqs_from_package(
        self,
        pkg: Package,
        *,
        due_date: str = "",
        only_unquoted: bool = False,
    ) -> list[SupplierRFQ]:
        """Group package materials by trade/section into supplier-ready RFQ packages."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in pkg.materials:
            if only_unquoted and m.price_basis == "QUOTE":
                continue
            cat = m.section or "General Metals & Materials"
            groups.setdefault(cat, []).append({
                "line_id": m.id,
                "item": m.item,
                "spec": m.spec,
                "qty": str(m.qty),
                "unit": m.unit,
                "current_basis": m.price_basis,
                "reference_sheet": m.qty_source,
            })
        created: list[SupplierRFQ] = []
        with self._lock:
            data = self._load()
            next_num = len(data["rfqs"]) + 1
            for cat, items in groups.items():
                rfq_id = f"RFQ-{next_num:03d}"
                next_num += 1
                rfq = SupplierRFQ(
                    rfq_id=rfq_id,
                    supplier_category=cat,
                    supplier_name="To Be Assigned",
                    project_key=str(pkg.project.get("key") or pkg.estimate_id),
                    due_date=due_date or str(pkg.project.get("bid_date") or "TBD"),
                    items=items,
                )
                data["rfqs"][rfq_id] = rfq.to_dict()
                created.append(rfq)
            self._save(data)
        return created

    def export_rfq_xlsx(self, rfq_id: str, out_path: Path) -> Path:
        """Export a Supplier RFQ package to clean Excel (.xlsx) format with formula sanitization."""
        with self._lock:
            data = self._load()
            rfq = data["rfqs"].get(rfq_id)
            if not rfq:
                raise KeyError(f"Unknown RFQ: {rfq_id}")
        wb = Workbook()
        ws = wb.active
        ws.title = rfq_id
        ws.append(["RFQ ID", rfq["rfq_id"], "Project", sanitize_spreadsheet_cell(rfq["project_key"]), "Due Date", rfq["due_date"]])
        ws.append(["Category", sanitize_spreadsheet_cell(rfq["supplier_category"]), "Status", rfq["status"]])
        ws.append([])
        ws.append(["Line ID", "Item Description", "Specification", "Qty", "Unit", "Vendor Unit Price ($)", "Lead Time", "Notes"])
        for it in rfq["items"]:
            ws.append([
                sanitize_spreadsheet_cell(it["line_id"]),
                sanitize_spreadsheet_cell(it["item"]),
                sanitize_spreadsheet_cell(it["spec"]),
                float(Decimal(it["qty"])),
                sanitize_spreadsheet_cell(it["unit"]),
                "",
                "",
                sanitize_spreadsheet_cell(it.get("reference_sheet", "")),
            ])
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out_path)
        return out_path

    def record_supplier_quote(
        self,
        *,
        rfq_id: str,
        supplier_name: str,
        quoted_lines: list[dict[str, Any]],
        freight: Decimal | str = "0",
        notes: str = "",
    ) -> dict[str, Any]:
        """Store supplier quote lines against an RFQ for comparison."""
        with self._lock:
            data = self._load()
            if rfq_id not in data["rfqs"]:
                raise KeyError(f"Unknown RFQ: {rfq_id}")
            entry = {
                "supplier_name": supplier_name.strip(),
                "received_at": datetime.now(timezone.utc).isoformat(),
                "freight": str(Decimal(str(freight))),
                "notes": notes,
                "lines": quoted_lines,
            }
            data["received_quotes"].setdefault(rfq_id, []).append(entry)
            data["rfqs"][rfq_id]["status"] = "quoted"
            self._save(data)
            return entry

    def compare_quotes(self, rfq_id: str) -> dict[str, Any]:
        """Compare supplier responses, detect uncovered items, spec deviations, and total landed cost."""
        with self._lock:
            data = self._load()
            rfq = data["rfqs"].get(rfq_id)
            if not rfq:
                raise KeyError(f"Unknown RFQ: {rfq_id}")
            quotes = data["received_quotes"].get(rfq_id, [])

        required_ids = {it["line_id"]: it for it in rfq["items"]}
        comparisons: list[dict[str, Any]] = []
        for q in quotes:
            by_line = {ln["line_id"]: ln for ln in q["lines"]}
            uncovered = [lid for lid in required_ids if lid not in by_line]
            spec_diffs: list[dict[str, Any]] = []
            subtotal = Decimal("0")
            for lid, req_item in required_ids.items():
                if lid not in by_line:
                    continue
                ql = by_line[lid]
                up = Decimal(str(ql["unit_price"]))
                qty = Decimal(str(req_item["qty"]))
                subtotal += up * qty
                if ql.get("spec") and ql["spec"].strip().lower() != req_item.get("spec", "").strip().lower():
                    spec_diffs.append({"line_id": lid, "requested": req_item.get("spec"), "quoted": ql["spec"]})
            freight = Decimal(str(q.get("freight", "0")))
            comparisons.append({
                "supplier_name": q["supplier_name"],
                "covered_items": len(required_ids) - len(uncovered),
                "total_items": len(required_ids),
                "uncovered_line_ids": uncovered,
                "spec_deviations": spec_diffs,
                "material_subtotal": str(subtotal.quantize(Decimal("0.01"))),
                "freight": str(freight.quantize(Decimal("0.01"))),
                "total_landed": str((subtotal + freight).quantize(Decimal("0.01"))),
                "complete_coverage": len(uncovered) == 0,
            })
        comparisons.sort(key=lambda c: (not c["complete_coverage"], Decimal(c["total_landed"])))
        return {"rfq_id": rfq_id, "comparisons": comparisons}

    def authorize_dispatch(
        self,
        *,
        kind: str,  # "rfi" or "rfq"
        item_id: str,
        actor: str,
        channel: str,
        recipient: str,
        ctx: SecurityContext | None = None,
        explicit_human_approval: bool = False,
    ) -> dict[str, Any]:
        """Gate outbound supplier/RFI dispatch: NEVER auto-sends without human authorization."""
        if ctx:
            require_permission(ctx, "rfq:authorize_send")
        if not explicit_human_approval or not actor.strip():
            raise UnAuthorizedOutboundError(
                "Automatic outbound transmission blocked: explicit human authorization required."
            )
        with self._lock:
            data = self._load()
            bucket = "rfis" if kind == "rfi" else "rfqs"
            rec = data[bucket].get(item_id)
            if not rec:
                raise KeyError(f"Unknown {kind.upper()} {item_id}")
            rec["status"] = "authorized_to_send"
            rec["authorized_by"] = actor.strip()
            rec["authorized_at"] = datetime.now(timezone.utc).isoformat()
            comm = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "item_id": item_id,
                "actor": actor.strip(),
                "channel": channel,
                "recipient": recipient,
                "event": "authorized_for_manual_send",
            }
            data["communications"].append(comm)
            self._save(data)
            return comm

    def log_communication(self, *, kind: str, item_id: str, actor: str, direction: str, summary: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "item_id": item_id,
                "actor": actor.strip(),
                "direction": direction,
                "summary": summary.strip(),
            }
            data["communications"].append(entry)
            self._save(data)
            return entry

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._load()
