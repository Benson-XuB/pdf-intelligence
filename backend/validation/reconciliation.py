from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.global_schema.registry import GLOBAL_FIELDS_V1

# 现金流支出项：XBRL 常报正数（支付额），PDF 现金流量表常报负数（流出）
MAGNITUDE_COMPARE_FIELDS = frozenset({"capex"})
# 拆股后 PDF 10-K 常保留旧每股数，XBRL companyfacts 已回溯调整
EPS_SPLIT_FACTORS = (2, 3, 4, 5, 6, 8, 10, 12, 20)


class MatchStatus(str, Enum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    XBRL_ONLY = "xbrl_only"
    PDF_ONLY = "pdf_only"
    BOTH_MISSING = "both_missing"
    SKIPPED = "skipped"


class TrustLevel(str, Enum):
    VERIFIED = "verified"
    REVIEW_REQUIRED = "review_required"
    UNVERIFIED = "unverified"
    MISSING = "missing"


@dataclass
class ReconciliationItem:
    field_id: str
    label_en: str
    label_zh: str
    period_end: str
    status: MatchStatus
    trust_level: TrustLevel
    xbrl_value: Optional[float]
    pdf_value: Optional[float]
    delta: Optional[float]
    delta_pct: Optional[float]
    authoritative_value: Optional[float]
    authoritative_source: str
    xbrl_tag: str = ""
    pdf_label: str = ""


@dataclass
class ReconciliationReport:
    ticker: str
    company_name: str
    items: List[ReconciliationItem] = field(default_factory=list)
    periods: List[str] = field(default_factory=list)
    pdf_source: str = ""
    pdf_source_type: str = ""
    pdf_only_mode: bool = False

    @property
    def total_checks(self) -> int:
        return len([i for i in self.items if i.status != MatchStatus.SKIPPED])

    @property
    def matched_count(self) -> int:
        return len([i for i in self.items if i.status == MatchStatus.MATCHED])

    @property
    def mismatch_count(self) -> int:
        return len([i for i in self.items if i.status == MatchStatus.MISMATCH])

    @property
    def verification_rate(self) -> float:
        if self.pdf_only_mode:
            return self.pdf_coverage_rate
        comparable = [
            i
            for i in self.items
            if i.status in (MatchStatus.MATCHED, MatchStatus.MISMATCH)
        ]
        if not comparable:
            return 0.0
        return self.matched_count / len(comparable)

    @property
    def trust_score(self) -> float:
        if self.total_checks == 0:
            return 0.0
        if self.pdf_only_mode:
            source_weight = {
                "hk_pdf_grid": 1.0,
                "pdf_grid": 1.0,
                "html_grid": 1.0,
                "hk_pdf": 1.0,
                "pdf_text": 1.0,
            }
            total_w = 0.0
            for item in self.items:
                if item.status == MatchStatus.SKIPPED:
                    continue
                if item.status == MatchStatus.PDF_ONLY:
                    src = item.authoritative_source or "hk_pdf"
                    total_w += source_weight.get(src, 0.75)
                elif item.status == MatchStatus.BOTH_MISSING:
                    total_w += 0.0
            return round(total_w / self.total_checks, 4)
        weights = {
            MatchStatus.MATCHED: 1.0,
            MatchStatus.MISMATCH: 0.0,
            MatchStatus.XBRL_ONLY: 0.7,
            MatchStatus.PDF_ONLY: 0.5,
            MatchStatus.BOTH_MISSING: 0.0,
        }
        total = sum(weights.get(i.status, 0.0) for i in self.items if i.status != MatchStatus.SKIPPED)
        return round(total / self.total_checks, 4)

    @property
    def pdf_coverage_rate(self) -> float:
        """PDF 提取覆盖率（与 verify 分母独立）。

        - XBRL 交叉校验：分母 = 有 XBRL 且未 skip 的单元格（含交叉上市仅 2 列资产负债）
        - PDF-only：分母 = 非 skip 单元格；分子 = 有 PDF 值
        """
        if self.pdf_only_mode:
            active = [i for i in self.items if i.status != MatchStatus.SKIPPED]
            if not active:
                return 0.0
            have_pdf = sum(1 for i in active if i.pdf_value is not None)
            return round(have_pdf / len(active), 4)

        in_scope = [
            i
            for i in self.items
            if i.xbrl_value is not None and i.status != MatchStatus.SKIPPED
        ]
        if not in_scope:
            return 0.0
        have_pdf = sum(1 for i in in_scope if i.pdf_value is not None)
        return round(have_pdf / len(in_scope), 4)


def _lookup(values: List[FieldValue]) -> Dict[str, Dict[str, FieldValue]]:
    table: Dict[str, Dict[str, FieldValue]] = {}
    for item in values:
        table.setdefault(item.field_id, {})[item.period_end] = item
    return table


def _within_tolerance(
    xbrl: float,
    pdf: float,
    scale: ValueScale,
    abs_tolerance: float,
    rel_tolerance: float,
    field_id: str = "",
) -> bool:
    delta = abs(xbrl - pdf)
    if scale == ValueScale.PER_SHARE:
        per_share_tol = max(abs_tolerance, 0.02)
        if delta <= per_share_tol:
            return True
        if field_id == "eps_basic":
            for factor in EPS_SPLIT_FACTORS:
                if abs(xbrl - pdf / factor) <= per_share_tol:
                    return True
                if abs(xbrl * factor - pdf) <= per_share_tol:
                    return True
        return False
    baseline = max(abs(xbrl), abs(pdf), 1.0)
    if delta <= max(abs_tolerance, baseline * rel_tolerance):
        return True
    if field_id in MAGNITUDE_COMPARE_FIELDS:
        return abs(abs(xbrl) - abs(pdf)) <= max(abs_tolerance, baseline * rel_tolerance)
    return False


class FinancialReconciler:
    def __init__(
        self,
        abs_tolerance_millions: float = 1.0,
        rel_tolerance: float = 0.001,
    ) -> None:
        self.abs_tolerance_millions = abs_tolerance_millions
        self.rel_tolerance = rel_tolerance

    def reconcile(
        self,
        xbrl: CompanyFinancials,
        pdf: CompanyFinancials,
        pdf_source: str = "",
        pdf_source_type: str = "",
        skipped_fields: Optional[Set[str]] = None,
        skipped_cells: Optional[Set[tuple]] = None,
    ) -> ReconciliationReport:
        xbrl_lookup = _lookup(xbrl.values)
        pdf_lookup = _lookup(pdf.values)
        periods = xbrl.periods or pdf.periods
        items: List[ReconciliationItem] = []
        skip_ids = skipped_fields or set()
        skip_cells = skipped_cells or set()

        for field_def in GLOBAL_FIELDS_V1:
            for period in periods:
                x_item = xbrl_lookup.get(field_def.field_id, {}).get(period)
                p_item = pdf_lookup.get(field_def.field_id, {}).get(period)
                x_val = x_item.value if x_item else None
                p_val = p_item.value if p_item else None

                if x_val is None and p_val is None:
                    if field_def.field_id in skip_ids or (field_def.field_id, period) in skip_cells:
                        status = MatchStatus.SKIPPED
                        trust = TrustLevel.MISSING
                        auth_val = None
                        auth_source = ""
                    else:
                        status = MatchStatus.BOTH_MISSING
                        trust = TrustLevel.MISSING
                        auth_val = None
                        auth_source = ""
                elif x_val is None:
                    if field_def.field_id in skip_ids or (field_def.field_id, period) in skip_cells:
                        status = MatchStatus.SKIPPED
                        trust = TrustLevel.MISSING
                        auth_val = None
                        auth_source = ""
                    else:
                        status = MatchStatus.PDF_ONLY
                        trust = TrustLevel.UNVERIFIED
                        auth_val = p_val
                        auth_source = "pdf_text"
                elif p_val is None:
                    if field_def.field_id in skip_ids or (field_def.field_id, period) in skip_cells:
                        status = MatchStatus.SKIPPED
                        trust = TrustLevel.MISSING
                        auth_val = None
                        auth_source = ""
                    else:
                        status = MatchStatus.XBRL_ONLY
                        trust = TrustLevel.UNVERIFIED
                        auth_val = x_val
                        auth_source = x_item.source if x_item else "xbrl"
                elif _within_tolerance(
                    x_val,
                    p_val,
                    field_def.scale,
                    self.abs_tolerance_millions,
                    self.rel_tolerance,
                    field_id=field_def.field_id,
                ):
                    status = MatchStatus.MATCHED
                    trust = TrustLevel.VERIFIED
                    auth_val = x_val
                    auth_source = "xbrl_verified"
                else:
                    status = MatchStatus.MISMATCH
                    trust = TrustLevel.REVIEW_REQUIRED
                    auth_val = x_val
                    auth_source = "xbrl_flagged"

                delta = None
                delta_pct = None
                if x_val is not None and p_val is not None:
                    delta = round(p_val - x_val, 4)
                    if x_val != 0:
                        delta_pct = round((p_val - x_val) / abs(x_val), 6)

                items.append(
                    ReconciliationItem(
                        field_id=field_def.field_id,
                        label_en=field_def.label_en,
                        label_zh=field_def.label_zh,
                        period_end=period,
                        status=status,
                        trust_level=trust,
                        xbrl_value=x_val,
                        pdf_value=p_val,
                        delta=delta,
                        delta_pct=delta_pct,
                        authoritative_value=auth_val,
                        authoritative_source=auth_source,
                        xbrl_tag=x_item.source_tag if x_item else "",
                        pdf_label=p_item.source_tag if p_item else "",
                    )
                )

        return ReconciliationReport(
            ticker=xbrl.ticker,
            company_name=xbrl.company_name,
            items=items,
            periods=periods,
            pdf_source=pdf_source,
            pdf_source_type=pdf_source_type,
        )

    def reconcile_pdf_only(
        self,
        pdf: CompanyFinancials,
        pdf_source: str = "",
        pdf_source_type: str = "",
        skipped_fields: Optional[Set[str]] = None,
        skipped_cells: Optional[Set[tuple]] = None,
    ) -> ReconciliationReport:
        """无 XBRL 交叉校验时，按 PDF 提取完整度计 trust。"""
        pdf_lookup = _lookup(pdf.values)
        periods = pdf.periods or []
        items: List[ReconciliationItem] = []
        skip_ids = skipped_fields or set()
        skip_cells = skipped_cells or set()

        for field_def in GLOBAL_FIELDS_V1:
            for period in periods:
                p_item = pdf_lookup.get(field_def.field_id, {}).get(period)
                p_val = p_item.value if p_item else None

                if field_def.field_id in skip_ids or (field_def.field_id, period) in skip_cells:
                    status = MatchStatus.SKIPPED
                    trust = TrustLevel.MISSING
                    auth_val = None
                    auth_source = ""
                elif p_val is None:
                    status = MatchStatus.BOTH_MISSING
                    trust = TrustLevel.MISSING
                    auth_val = None
                    auth_source = ""
                else:
                    status = MatchStatus.PDF_ONLY
                    trust = TrustLevel.VERIFIED
                    auth_val = p_val
                    auth_source = p_item.source if p_item else "pdf"

                items.append(
                    ReconciliationItem(
                        field_id=field_def.field_id,
                        label_en=field_def.label_en,
                        label_zh=field_def.label_zh,
                        period_end=period,
                        status=status,
                        trust_level=trust,
                        xbrl_value=None,
                        pdf_value=p_val,
                        delta=None,
                        delta_pct=None,
                        authoritative_value=auth_val,
                        authoritative_source=auth_source,
                        pdf_label=p_item.source_tag if p_item else "",
                    )
                )

        return ReconciliationReport(
            ticker=pdf.ticker,
            company_name=pdf.company_name,
            items=items,
            periods=periods,
            pdf_source=pdf_source,
            pdf_source_type=pdf_source_type,
            pdf_only_mode=True,
        )

    def apply_verification_flags(
        self,
        xbrl: CompanyFinancials,
        report: ReconciliationReport,
    ) -> CompanyFinancials:
        flags: Dict[str, Dict[str, bool]] = {}
        for item in report.items:
            if item.status == MatchStatus.MATCHED:
                flags.setdefault(item.field_id, {})[item.period_end] = True
            elif item.status == MatchStatus.MISMATCH:
                flags.setdefault(item.field_id, {})[item.period_end] = False

        for value in xbrl.values:
            value.pdf_verified = flags.get(value.field_id, {}).get(value.period_end)
        return xbrl
