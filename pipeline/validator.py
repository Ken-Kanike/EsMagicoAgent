import datetime
from typing import Tuple, List, Optional, Dict, Any
from config.settings import settings
from pipeline.models import InvoiceSchema

class InvoiceValidator:
    """
    Validates extracted invoice payloads against JSON schema,
    verifies arithmetic balance, and flags data anomalies.
    """

    def __init__(self, tolerance: float = None):
        self.tolerance = tolerance if tolerance is not None else settings.arithmetic_tolerance

    def validate(self, data: Dict[str, Any]) -> Tuple[Optional[InvoiceSchema], List[str]]:
        """
        Validate raw dictionary against InvoiceSchema and business arithmetic rules.
        Returns:
            Tuple[Optional[InvoiceSchema], List[str]]: (validated_instance, list_of_issues)
        """
        issues: List[str] = []

        if not isinstance(data, dict):
            return None, ["Extracted output is not a JSON object/dictionary."]

        # 1. Pydantic schema validation
        try:
            validated_obj = InvoiceSchema(**data)
        except Exception as e:
            issues.append(f"Schema validation error: {str(e)}")
            return None, issues

        # 2. If it's not an invoice, check that all other 7 fields are null
        if not validated_obj.is_invoice:
            for field in ["vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"]:
                if getattr(validated_obj, field) is not None:
                    issues.append(f"Non-invoice has non-null field '{field}'.")
            return validated_obj, issues

        # 3. Arithmetic balance verification: sum(line_items) + tax_total ~= total
        if validated_obj.line_items is not None and validated_obj.total is not None:
            line_sum = sum(item.amount for item in validated_obj.line_items)
            tax = validated_obj.tax_total or 0.0
            expected_total = line_sum + tax
            diff = abs(expected_total - validated_obj.total)

            if diff > self.tolerance:
                issues.append(
                    f"Arithmetic mismatch: sum(items)={line_sum:.2f} + tax={tax:.2f} = {expected_total:.2f}, "
                    f"which differs from reported total={validated_obj.total:.2f} by {diff:.2f} (tolerance={self.tolerance})."
                )

        # 4. Date sanity check
        if validated_obj.invoice_date:
            try:
                dt = datetime.date.fromisoformat(validated_obj.invoice_date)
                if dt.year < 2000 or dt.year > 2035:
                    issues.append(f"Suspicious invoice date year: {validated_obj.invoice_date}")
            except ValueError:
                issues.append(f"Invoice date is not valid ISO YYYY-MM-DD: {validated_obj.invoice_date}")

        # 5. Total must be positive for valid invoices
        if validated_obj.total is not None and validated_obj.total <= 0:
            issues.append(f"Reported total ({validated_obj.total}) is non-positive.")

        return validated_obj, issues
