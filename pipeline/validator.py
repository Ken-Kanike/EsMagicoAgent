"""
Validation of an extracted payload.

Two kinds of findings:
  errors   -> the output is wrong or incomplete; trigger a corrective retry and,
              if they survive the retries, flag the document for human review.
  warnings -> plausible but suspicious; never retried on their own, but they
              flag the document for review.
"""
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.settings import settings
from pipeline.models import InvoiceSchema


@dataclass
class ValidationReport:
    obj: Optional[InvoiceSchema]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.obj is not None and not self.errors

    @property
    def all_issues(self) -> List[str]:
        return self.errors + self.warnings


class InvoiceValidator:
    def __init__(self, tolerance: Optional[float] = None):
        self.tolerance = tolerance if tolerance is not None else settings.arithmetic_tolerance

    def check(self, data: Any) -> ValidationReport:
        if not isinstance(data, dict):
            return ValidationReport(None, ["Output is not a JSON object."])
        if not isinstance(data.get("is_invoice"), bool):
            return ValidationReport(None, ["'is_invoice' must be true or false."])
        try:
            obj = InvoiceSchema(**data)
        except Exception as e:
            msgs = []
            for err in getattr(e, "errors", lambda: [])() or []:
                loc = ".".join(str(x) for x in err.get("loc", []))
                msgs.append(f"Schema error at '{loc}': {err.get('msg')}")
            return ValidationReport(None, msgs or [f"Schema validation error: {e}"])

        rep = ValidationReport(obj)
        if not obj.is_invoice:
            return rep

        # Required fields for an invoice
        for name in ("vendor", "invoice_number", "invoice_date", "currency", "total"):
            if getattr(obj, name) in (None, ""):
                rep.errors.append(f"'{name}' is missing; every invoice prints it - read it from the document.")
        if not obj.line_items:
            rep.errors.append("'line_items' is empty; capture every row of the item table.")
        if obj.tax_total is None:
            rep.errors.append("'tax_total' is null; use the sum of all tax lines, or 0 if the invoice shows no tax.")

        # Date sanity
        if obj.invoice_date:
            try:
                dt = datetime.date.fromisoformat(obj.invoice_date)
                if not (2000 <= dt.year <= datetime.date.today().year + 1):
                    rep.warnings.append(f"Unusual invoice date year: {obj.invoice_date}.")
            except ValueError:
                rep.errors.append(f"invoice_date '{obj.invoice_date}' is not a real calendar date.")

        # Issue date vs the helper due_date: catches misread years/months on scans (U05: 2026 read as 2025).
        due_raw = data.get("due_date")
        if obj.invoice_date and isinstance(due_raw, str):
            try:
                inv_d = datetime.date.fromisoformat(obj.invoice_date)
                due_d = datetime.date.fromisoformat(due_raw)
                gap = (due_d - inv_d).days
                if gap < 0:
                    rep.errors.append(
                        f"invoice_date {obj.invoice_date} is AFTER due_date {due_raw}. Re-read both dates "
                        f"(day/month order and the year); invoice_date must be the issue date.")
                elif gap > 120:
                    rep.errors.append(
                        f"invoice_date {obj.invoice_date} is {gap} days before due_date {due_raw}, which is "
                        f"implausible. Re-read the year and month of both dates.")
            except ValueError:
                pass

        # Arithmetic: sum(items) + tax == total
        if obj.line_items and obj.total is not None:
            line_sum = round(sum(i.amount for i in obj.line_items), 2)
            tax = obj.tax_total or 0.0
            diff = abs(line_sum + tax - obj.total)
            tol = max(self.tolerance, 0.01 * len(obj.line_items))  # allow per-row rounding
            if diff > tol:
                rep.errors.append(
                    f"Arithmetic mismatch: sum(line_items.amount)={line_sum:.2f} + tax_total={tax:.2f} = "
                    f"{line_sum + tax:.2f}, but total={obj.total:.2f} (difference {diff:.2f}). "
                    f"Check for missed or extra rows, missed tax lines, discount signs, or a misread number."
                )

        if obj.total is not None and obj.total <= 0:
            rep.warnings.append(f"Total is non-positive ({obj.total}).")
        if obj.tax_total is not None and obj.tax_total < 0:
            rep.errors.append(f"tax_total is negative ({obj.tax_total}).")

        # Row arithmetic with the helper unit_price (not part of the output schema)
        for idx, raw_it in enumerate(data.get("line_items") or [], start=1):
            if not isinstance(raw_it, dict):
                continue
            q, u, a = raw_it.get("quantity"), raw_it.get("unit_price"), raw_it.get("amount")
            if all(isinstance(x, (int, float)) for x in (q, u, a)) and q and u:
                if abs(q * u - a) > max(0.05, abs(a) * 0.01):
                    rep.errors.append(
                        f"Line item {idx}: quantity ({q:g}) x unit_price ({u:g}) = {q * u:.2f}, not amount ({a:.2f}). "
                        f"The quantity may come from a code column (HSN/SAC/SKU) or the wrong column."
                    )

        # Row-level plausibility
        for idx, it in enumerate(obj.line_items or [], start=1):
            if not it.description.strip():
                rep.warnings.append(f"Line item {idx} has an empty description.")
            if it.quantity is not None and it.amount and abs(it.quantity - it.amount) < 1e-9 and abs(it.amount) > 1:
                rep.errors.append(
                    f"Line item {idx}: quantity equals amount ({it.amount}); if the row has no quantity it must be null."
                )
            if it.quantity is not None and it.quantity < 0:
                rep.warnings.append(f"Line item {idx}: negative quantity ({it.quantity}).")
        return rep

    # Backwards-compatible API used by older callers/tests
    def validate(self, data: Dict[str, Any]):
        rep = self.check(data)
        return rep.obj, rep.all_issues
