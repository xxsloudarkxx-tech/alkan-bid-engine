"""Commercial Pricebook database with strict BUDGET/QUOTE/VERIFIED governance and quote import."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import threading
from typing import Any

from openpyxl import load_workbook
from pypdf import PdfReader

from .security import SecurityContext, require_permission, sanitize_filename

PRICE_TYPES: tuple[str, ...] = ("BUDGET", "QUOTE", "HISTORICAL", "ALLOWANCE", "VERIFIED")
VERIFICATION_STATUSES: tuple[str, ...] = ("unverified", "pending_review", "verified", "expired", "rejected")


class PriceGovernanceError(ValueError):
    """Raised when price classification, promotion, or expiration rules are violated."""


def _d(val: Any, default: str = "0") -> Decimal:
    if val is None or val == "":
        return Decimal(default)
    return Decimal(str(val).replace("$", "").replace(",", "").strip())


def _money(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _today_iso() -> str:
    return date.today().isoformat()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass
class PriceRecord:
    id: str
    org_id: str
    material: str
    manufacturer: str = ""
    specification_std: str = ""
    dimensions: str = ""
    purchase_unit: str = "EA"
    estimate_unit: str = "EA"
    unit_conversion_factor: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    currency: str = "USD"
    price_type: str = "BUDGET"
    supplier: str = ""
    city: str = ""
    state: str = ""
    consulted_date: str = ""
    quoted_date: str = ""
    valid_until: str = ""
    availability: str = ""
    min_qty: Decimal = Decimal("1")
    freight: Decimal = Decimal("0")
    tax_rate_pct: Decimal = Decimal("0")
    original_document: str = ""
    original_document_sha256: str = ""
    source: str = ""
    verification_status: str = "unverified"
    verified_by: str = ""
    verified_at: str = ""
    price_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.price_type not in PRICE_TYPES:
            raise PriceGovernanceError(f"Invalid price_type {self.price_type!r}; must be one of {PRICE_TYPES}")
        if self.verification_status not in VERIFICATION_STATUSES:
            raise PriceGovernanceError(f"Invalid verification_status {self.verification_status!r}")
        self.unit_price = _d(self.unit_price)
        self.unit_conversion_factor = _d(self.unit_conversion_factor, "1")
        self.min_qty = _d(self.min_qty, "1")
        self.freight = _d(self.freight, "0")
        self.tax_rate_pct = _d(self.tax_rate_pct, "0")
        if self.unit_price < 0:
            raise PriceGovernanceError("unit_price cannot be negative")
        if self.unit_conversion_factor <= 0:
            raise PriceGovernanceError("unit_conversion_factor must be > 0")
        if self.min_qty <= 0:
            raise PriceGovernanceError("min_qty must be > 0")
        if self.price_type == "VERIFIED" and self.verification_status != "verified":
            raise PriceGovernanceError("VERIFIED price_type requires verification_status='verified' with human sign-off.")
        if self.verification_status == "verified" and not (self.verified_by.strip() and (self.source.strip() or self.original_document.strip())):
            raise PriceGovernanceError("Verified prices require verified_by and documentary source/original_document.")

    def is_expired(self, as_of: date | None = None) -> bool:
        ref = as_of or date.today()
        exp = _parse_iso_date(self.valid_until)
        return bool(exp is not None and exp < ref)

    def effective_unit_price_in_estimate_unit(self) -> Decimal:
        """Convert purchase_unit price into estimate_unit price cleanly."""
        return _money(self.unit_price / self.unit_conversion_factor)

    def landed_cost_for_qty(self, estimate_qty: Decimal) -> Decimal:
        """Calculate total material cost applying minimum order qty and freight."""
        qty = _d(estimate_qty)
        billable_qty = max(qty, self.min_qty * self.unit_conversion_factor) if qty > 0 else Decimal("0")
        mat = billable_qty * self.effective_unit_price_in_estimate_unit()
        return _money(mat + (self.freight if qty > 0 else Decimal("0")))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("unit_price", "unit_conversion_factor", "min_qty", "freight", "tax_rate_pct"):
            d[k] = str(getattr(self, k))
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PriceRecord:
        return cls(**raw)


class PricebookStore:
    """Multi-tenant commercial pricebook repository with price history and quote imports."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._lock = threading.RLock()

    def _org_dir(self, org_id: str) -> Path:
        return self.root / "data" / "orgs" / sanitize_filename(org_id or "default")

    def _db_path(self, org_id: str) -> Path:
        return self._org_dir(org_id) / "pricebook_v4.json"

    def _originals_dir(self, org_id: str) -> Path:
        return self._org_dir(org_id) / "pricebook_originals"

    def _load(self, org_id: str) -> dict[str, Any]:
        path = self._db_path(org_id)
        if not path.exists():
            return {"schema": "alkan-pricebook/4", "org_id": org_id, "records": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, org_id: str, data: dict[str, Any]) -> None:
        path = self._db_path(org_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    def upsert(self, record: PriceRecord, *, ctx: SecurityContext | None = None) -> PriceRecord:
        if ctx:
            perm = "pricebook:verify" if record.verification_status == "verified" else "pricebook:import"
            require_permission(ctx, perm, org_id=record.org_id)
        with self._lock:
            data = self._load(record.org_id)
            prev = data["records"].get(record.id)
            if prev:
                # Never allow silent auto-promotion from BUDGET to QUOTE or VERIFIED
                if prev.get("price_type") == "BUDGET" and record.price_type in ("QUOTE", "VERIFIED") and not record.verified_by:
                    raise PriceGovernanceError("Cannot auto-promote BUDGET price to QUOTE/VERIFIED without human verifier.")
                history = list(prev.get("price_history") or [])
                if str(prev.get("unit_price")) != str(record.unit_price) or prev.get("supplier") != record.supplier:
                    history.append({
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "unit_price": str(prev.get("unit_price")),
                        "price_type": prev.get("price_type"),
                        "supplier": prev.get("supplier"),
                        "city": prev.get("city"),
                        "state": prev.get("state"),
                        "quoted_date": prev.get("quoted_date"),
                    })
                record.price_history = history + [h for h in record.price_history if h not in history]
            data["records"][record.id] = record.to_dict()
            self._save(record.org_id, data)
            return record

    def verify_record(
        self,
        *,
        org_id: str,
        record_id: str,
        verifier: str,
        target_price_type: str = "VERIFIED",
        ctx: SecurityContext | None = None,
    ) -> PriceRecord:
        """Human verification promoting QUOTE/pending_review -> VERIFIED only with source document."""
        if ctx:
            require_permission(ctx, "pricebook:verify", org_id=org_id)
        if target_price_type not in ("QUOTE", "VERIFIED"):
            raise PriceGovernanceError("Verification target must be QUOTE or VERIFIED.")
        with self._lock:
            data = self._load(org_id)
            raw = data["records"].get(record_id)
            if not raw:
                raise KeyError(f"Unknown pricebook record: {record_id}")
            if raw["price_type"] == "BUDGET" and target_price_type == "VERIFIED" and not raw.get("original_document"):
                raise PriceGovernanceError(
                    "BUDGET reference cannot become VERIFIED without an attached supplier quote original_document."
                )
            rec = PriceRecord.from_dict({
                **raw,
                "price_type": target_price_type,
                "verification_status": "verified",
                "verified_by": verifier.strip(),
                "verified_at": datetime.now(timezone.utc).isoformat(),
            })
            if rec.is_expired():
                raise PriceGovernanceError(f"Cannot verify expired price (valid_until={rec.valid_until}).")
            data["records"][record_id] = rec.to_dict()
            self._save(org_id, data)
            return rec

    def get(self, org_id: str, record_id: str, *, ctx: SecurityContext | None = None) -> PriceRecord:
        if ctx:
            require_permission(ctx, "pricebook:read", org_id=org_id)
        data = self._load(org_id)
        raw = data["records"].get(record_id)
        if not raw:
            raise KeyError(f"Price record {record_id} not found in org {org_id}")
        return PriceRecord.from_dict(raw)

    def select_for_estimate(
        self,
        org_id: str,
        record_id: str,
        *,
        allow_expired: bool = False,
        as_of: date | None = None,
    ) -> dict[str, Any]:
        """Retrieve price record with mandatory expiration & BUDGET classification checks."""
        rec = self.get(org_id, record_id)
        expired = rec.is_expired(as_of=as_of)
        warnings: list[str] = []
        if expired:
            warnings.append(f"EXPIRED_PRICE_WARNING: quote expired on {rec.valid_until} (supplier={rec.supplier}).")
            if not allow_expired:
                raise PriceGovernanceError(warnings[0])
        if rec.price_type == "BUDGET":
            warnings.append("BUDGET_PRICE_WARNING: budgetary estimate only — not a verified supplier quote.")
        elif rec.price_type == "ALLOWANCE":
            warnings.append("ALLOWANCE_PRICE_WARNING: provisional allowance pending vendor confirmation.")
        return {"record": rec, "expired": expired, "warnings": warnings}

    def list_records(
        self,
        org_id: str,
        *,
        price_type: str | None = None,
        query: str = "",
        city: str = "",
        state: str = "",
        as_of: date | None = None,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        if ctx:
            require_permission(ctx, "pricebook:read", org_id=org_id)
        data = self._load(org_id)
        q = query.strip().lower()
        out: list[dict[str, Any]] = []
        for raw in data["records"].values():
            rec = PriceRecord.from_dict(raw)
            if price_type and rec.price_type != price_type:
                continue
            if city and rec.city.lower() != city.strip().lower():
                continue
            if state and rec.state.lower() != state.strip().lower():
                continue
            if q and q not in f"{rec.material} {rec.specification_std} {rec.supplier} {rec.manufacturer}".lower():
                continue
            row = rec.to_dict()
            row["expired"] = rec.is_expired(as_of=as_of)
            out.append(row)
        return sorted(out, key=lambda r: (r["material"].lower(), r["price_type"]))

    def compare_suppliers(
        self,
        org_id: str,
        material_query: str,
        *,
        quantity: Decimal | str | float = 1,
        as_of: date | None = None,
    ) -> list[dict[str, Any]]:
        """Compare supplier quotes/records for a material normalized to effective landed cost."""
        qty = _d(quantity, "1")
        matches = self.list_records(org_id, query=material_query, as_of=as_of)
        ranked: list[dict[str, Any]] = []
        for m in matches:
            rec = PriceRecord.from_dict({k: v for k, v in m.items() if k != "expired"})
            landed = rec.landed_cost_for_qty(qty)
            ranked.append({
                "id": rec.id,
                "material": rec.material,
                "supplier": rec.supplier or "(unspecified)",
                "city": rec.city,
                "state": rec.state,
                "price_type": rec.price_type,
                "verification_status": rec.verification_status,
                "unit_price": str(rec.unit_price),
                "estimate_unit": rec.estimate_unit,
                "freight": str(rec.freight),
                "landed_total": str(landed),
                "valid_until": rec.valid_until,
                "expired": rec.is_expired(as_of=as_of),
            })
        return sorted(ranked, key=lambda r: (r["expired"], Decimal(r["landed_total"])))

    def import_legacy_price_book(self, org_id: str, json_path: Path) -> int:
        """Bridge knowledge/price_book.json entries without auto-promoting BUDGET to VERIFIED."""
        rows = json.loads(Path(json_path).read_text(encoding="utf-8"))
        count = 0
        for idx, row in enumerate(rows, start=1):
            ptype = row.get("price_basis") or "BUDGET"
            if ptype == "CATALOG":
                ptype = "HISTORICAL"
            if ptype not in PRICE_TYPES:
                ptype = "BUDGET"
            rec = PriceRecord(
                id=f"PB-LEG-{idx:04d}",
                org_id=org_id,
                material=str(row.get("item") or ""),
                specification_std=str(row.get("spec") or ""),
                purchase_unit=str(row.get("unit") or "EA"),
                estimate_unit=str(row.get("unit") or "EA"),
                unit_price=_d(row.get("unit_price"), "0"),
                price_type="BUDGET" if ptype == "VERIFIED" else ptype,
                state="WA" if row.get("county") else "",
                city=str(row.get("county") or ""),
                consulted_date=str(row.get("date") or _today_iso()),
                source=str(row.get("source") or "Legacy price_book.json"),
                verification_status="unverified",
            )
            self.upsert(rec)
            count += 1
        return count

    def import_quote_file(
        self,
        *,
        org_id: str,
        file_path: Path | None = None,
        file_name: str = "",
        raw_bytes: bytes | None = None,
        supplier: str,
        city: str = "",
        state: str = "",
        quoted_date: str = "",
        valid_until: str = "",
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Import supplier quote from CSV, XLSX, or PDF, archive original, and stage for human review."""
        if ctx:
            require_permission(ctx, "pricebook:import", org_id=org_id)
        if raw_bytes is None:
            if not file_path:
                raise ValueError("Provide file_path or raw_bytes.")
            raw_bytes = Path(file_path).read_bytes()
            file_name = file_name or Path(file_path).name
        safe_name = sanitize_filename(file_name or "quote.csv")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        dest = self._originals_dir(org_id) / f"{digest[:12]}_{safe_name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw_bytes)

        ext = Path(safe_name).suffix.lower()
        if ext == ".csv":
            parsed = self._parse_csv(raw_bytes)
        elif ext in (".xlsx", ".xlsm"):
            parsed = self._parse_xlsx(raw_bytes)
        elif ext == ".pdf":
            parsed = self._parse_pdf(raw_bytes)
        else:
            raise ValueError(f"Unsupported quote import format: {ext!r}; use .csv, .xlsx, or .pdf.")

        imported_ids: list[str] = []
        for idx, row in enumerate(parsed, start=1):
            rec_id = f"PB-Q-{digest[:8].upper()}-{idx:03d}"
            rec = PriceRecord(
                id=rec_id,
                org_id=org_id,
                material=str(row["material"]).strip(),
                manufacturer=str(row.get("manufacturer") or "").strip(),
                specification_std=str(row.get("specification_std") or "").strip(),
                dimensions=str(row.get("dimensions") or "").strip(),
                purchase_unit=str(row.get("unit") or "EA").strip(),
                estimate_unit=str(row.get("unit") or "EA").strip(),
                unit_price=_d(row["unit_price"]),
                price_type="QUOTE",
                supplier=supplier.strip(),
                city=city.strip(),
                state=state.strip(),
                consulted_date=_today_iso(),
                quoted_date=quoted_date or _today_iso(),
                valid_until=valid_until,
                availability=str(row.get("availability") or "per quote"),
                min_qty=_d(row.get("min_qty"), "1"),
                freight=_d(row.get("freight"), "0"),
                original_document=str(dest),
                original_document_sha256=digest,
                source=f"Supplier Quote Import ({safe_name})",
                verification_status="pending_review",
            )
            self.upsert(rec)
            imported_ids.append(rec_id)
        return {
            "imported_count": len(imported_ids),
            "record_ids": imported_ids,
            "original_document": str(dest),
            "original_sha256": digest,
            "verification_status": "pending_review",
        }

    @staticmethod
    def _parse_csv(raw_bytes: bytes) -> list[dict[str, Any]]:
        text = raw_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict[str, Any]] = []
        for row in reader:
            norm = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
            mat = norm.get("material") or norm.get("item") or norm.get("description")
            price = norm.get("unit_price") or norm.get("price")
            if mat and price:
                rows.append({
                    "material": mat,
                    "specification_std": norm.get("spec") or norm.get("astm") or norm.get("specification") or "",
                    "unit": norm.get("unit") or "EA",
                    "unit_price": price,
                    "manufacturer": norm.get("manufacturer") or "",
                    "dimensions": norm.get("dimensions") or "",
                    "min_qty": norm.get("min_qty") or "1",
                    "freight": norm.get("freight") or "0",
                })
        return rows

    @staticmethod
    def _parse_xlsx(raw_bytes: bytes) -> list[dict[str, Any]]:
        wb = load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(c or "").strip().lower() for c in next(it, ())]
        rows: list[dict[str, Any]] = []
        for vals in it:
            if not any(vals):
                continue
            norm = {headers[i]: vals[i] for i in range(min(len(headers), len(vals)))}
            mat = norm.get("material") or norm.get("item") or norm.get("description")
            price = norm.get("unit_price") or norm.get("price")
            if mat and price is not None:
                rows.append({
                    "material": str(mat),
                    "specification_std": str(norm.get("spec") or norm.get("astm") or ""),
                    "unit": str(norm.get("unit") or "EA"),
                    "unit_price": str(price),
                    "manufacturer": str(norm.get("manufacturer") or ""),
                    "dimensions": str(norm.get("dimensions") or ""),
                    "min_qty": str(norm.get("min_qty") or "1"),
                    "freight": str(norm.get("freight") or "0"),
                })
        wb.close()
        return rows

    @staticmethod
    def _parse_pdf(raw_bytes: bytes) -> list[dict[str, Any]]:
        reader = PdfReader(io.BytesIO(raw_bytes))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        rows: list[dict[str, Any]] = []
        # Match lines ending with `<unit> $<price>` or `|<unit>|<price>`
        pat = re.compile(r"^\s*(?P<mat>.+?)\s+(?P<unit>EA|LF|SF|LB|TON|LS|LOT|BAG|CY)\s+\$?(?P<price>\d[\d,]*\.\d{2})\b", re.I)
        for line in text.splitlines():
            m = pat.match(line.strip())
            if m:
                rows.append({
                    "material": m.group("mat").strip(" |-"),
                    "unit": m.group("unit").upper(),
                    "unit_price": m.group("price").replace(",", ""),
                })
        return rows
