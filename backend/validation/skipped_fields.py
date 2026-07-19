from __future__ import annotations

from typing import Dict, List, Set, Tuple, Optional

from backend.global_schema.models import FieldValue, StatementType
from backend.global_schema.registry import GLOBAL_FIELDS_V1


def build_skipped_fields(xbrl_errors: List[str], pdf_errors: List[str]) -> Set[str]:
    """Determine fields to skip from trust/verification computation (all periods).

    - XBRL tag missing (e.g. bank gross_profit)
    - PDF field not extracted at all (no PDF value in any period)
    - Entire statement pages missing
    """
    skipped: Set[str] = set()

    for line in xbrl_errors:
        if line.startswith("Missing XBRL tag:"):
            skipped.add(line.replace("Missing XBRL tag: ", "").strip())

    missing_statements: Set[StatementType] = set()
    for line in pdf_errors:
        if line.startswith("Missing statement pages:"):
            stype = line.split(":", 1)[1].strip()
            try:
                missing_statements.add(StatementType(stype))
            except ValueError:
                continue
        elif line.startswith("PDF extraction failed for:"):
            skipped.add(line.replace("PDF extraction failed for: ", "").strip())

    if missing_statements:
        for field_def in GLOBAL_FIELDS_V1:
            if field_def.statement in missing_statements:
                skipped.add(field_def.field_id)

    return skipped


def build_skipped_cells(
    pdf_values: List[FieldValue],
    reconciliation_periods: List[str],
    skipped_fields: Set[str],
    xbrl_values: Optional[List[FieldValue]] = None,
) -> Set[Tuple[str, str]]:
    """PDF / XBRL 仅覆盖部分期间时，对缺失的 (field, period) 跳过对账。

    典型场景：
    - 资产负债表 PDF 仅 2 列，XBRL 有 3 个财年
    - PDF 有旧期 revenue，XBRL companyfacts 未保留该期
    """
    pdf_by_field: Dict[str, Set[str]] = {}
    for item in pdf_values:
        if item.value is None:
            continue
        pdf_by_field.setdefault(item.field_id, set()).add(item.period_end)

    xbrl_by_field: Dict[str, Set[str]] = {}
    if xbrl_values:
        for item in xbrl_values:
            if item.value is None:
                continue
            xbrl_by_field.setdefault(item.field_id, set()).add(item.period_end)

    skipped_cells: Set[Tuple[str, str]] = set()
    for field_def in GLOBAL_FIELDS_V1:
        field_id = field_def.field_id
        if field_id in skipped_fields:
            continue
        pdf_periods = pdf_by_field.get(field_id, set())
        pdf_years = {p[:4] for p in pdf_periods}
        xbrl_periods = xbrl_by_field.get(field_id, set())
        xbrl_years = {p[:4] for p in xbrl_periods}

        for period in reconciliation_periods:
            year = period[:4]
            pdf_has = period in pdf_periods or year in pdf_years
            xbrl_has = period in xbrl_periods or year in xbrl_years

            if pdf_periods and not pdf_has and (not xbrl_periods or xbrl_has):
                skipped_cells.add((field_id, period))
            elif xbrl_periods and not xbrl_has and pdf_has:
                skipped_cells.add((field_id, period))
            elif (pdf_periods or xbrl_periods) and not pdf_has and not xbrl_has:
                skipped_cells.add((field_id, period))
    return skipped_cells


def finalize_pdf_errors(
    values: List[FieldValue],
    errors: List[str],
    *,
    skip_field_ids: Optional[Set[str]] = None,
) -> List[str]:
    """Deduplicate and remove false positives for successfully extracted fields."""
    extracted_fields = {v.field_id for v in values if v.value is not None}
    missing_pages: Set[str] = set()
    for line in errors:
        if line.startswith("Missing statement pages:"):
            missing_pages.add(line.split(":", 1)[1].strip())

    suppressed: Set[str] = set(skip_field_ids or ())
    if missing_pages:
        for field_def in GLOBAL_FIELDS_V1:
            if field_def.statement.value in missing_pages:
                suppressed.add(field_def.field_id)

    seen: set[str] = set()
    finalized: List[str] = []

    for line in errors:
        if line.startswith("PDF extraction failed for:"):
            field_id = line.replace("PDF extraction failed for: ", "").strip()
            if field_id in extracted_fields or field_id in suppressed:
                continue
        if line in seen:
            continue
        seen.add(line)
        finalized.append(line)

    for field_def in GLOBAL_FIELDS_V1:
        if field_def.field_id in suppressed:
            continue
        line = f"PDF extraction failed for: {field_def.field_id}"
        if field_def.field_id not in extracted_fields and line not in seen:
            finalized.append(line)
            seen.add(line)

    return finalized
