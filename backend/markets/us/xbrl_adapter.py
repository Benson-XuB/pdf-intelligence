from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from backend.global_schema.models import CompanyFinancials, FieldValue, ValueScale
from backend.global_schema.registry import GLOBAL_FIELDS_V1
from backend.markets.us.sec_client import SecEdgarClient

US_GAAP_TAGS: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "cfi": ["NetCashProvidedByUsedInInvestingActivities"],
    "cff": ["NetCashProvidedByUsedInFinancingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}

INSTANT_FIELDS = {"total_assets", "total_liabilities", "total_equity", "cash"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A"}

IFRS_TAGS: Dict[str, List[str]] = {
    "revenue": [
        "Revenue",
        "RevenueFromContractsWithCustomers",
        "RevenueAndOperatingIncome",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["ProfitLossFromOperatingActivities", "OperatingProfitLoss"],
    "net_income": ["ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "eps_basic": ["BasicEarningsLossPerShare"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": ["Equity"],
    "cash": ["CashAndCashEquivalents"],
    "cfo": ["CashFlowsFromUsedInOperatingActivities"],
    "cfi": ["CashFlowsFromUsedInInvestingActivities"],
    "cff": ["CashFlowsFromUsedInFinancingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipment"],
}

TAXONOMY_TAG_MAPS: Dict[str, Dict[str, List[str]]] = {
    "us-gaap": US_GAAP_TAGS,
    "ifrs-full": IFRS_TAGS,
}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _duration_days(entry: dict) -> Optional[int]:
    start = entry.get("start")
    end = entry.get("end")
    if not start or not end:
        return None
    return (_parse_date(end) - _parse_date(start)).days


def _is_annual_duration(entry: dict) -> bool:
    days = _duration_days(entry)
    return days is not None and 340 <= days <= 400


def _normalize_value(raw: float, scale: ValueScale) -> float:
    if scale == ValueScale.PER_SHARE:
        return raw
    return raw / 1_000_000


def _pick_unit_entries(
    tag_data: dict,
    scale: ValueScale,
    preferred_currency: Optional[str] = None,
    field_id: str = "",
) -> List[dict]:
    units = tag_data.get("units", {})
    pref = preferred_currency.upper() if preferred_currency else None
    if pref == "RMB":
        pref = "CNY"

    def _annual(entries: List[dict]) -> List[dict]:
        return _filter_annual(entries, field_id)

    if scale == ValueScale.PER_SHARE:
        keys: List[str] = []
        if pref:
            keys.append(f"{pref}/shares")
        keys.extend(["USD/shares", "CNY/shares", "HKD/shares", "USD", "CNY", "HKD", "pure"])
        for key in keys:
            if key in units:
                return units[key]
        return next(iter(units.values()), [])

    currency_order: List[str] = []
    if pref:
        currency_order.append(pref)
    currency_order.extend(["CNY", "USD", "HKD", "EUR", "GBP"])
    seen: set[str] = set()
    for key in currency_order:
        if key in seen:
            continue
        seen.add(key)
        if key in units:
            return units[key]
    return next(iter(units.values()), [])


def _filter_annual(entries: List[dict], field_id: str) -> List[dict]:
    filtered: List[dict] = []
    for entry in entries:
        if entry.get("form") not in ANNUAL_FORMS:
            continue
        if entry.get("fp") not in (None, "FY"):
            continue
        if field_id in INSTANT_FIELDS:
            if "start" in entry:
                continue
            filtered.append(entry)
        else:
            if "start" not in entry:
                continue
            if field_id == "eps_basic" or _is_annual_duration(entry):
                filtered.append(entry)
    return filtered


def _dedupe_by_period(entries: List[dict]) -> List[dict]:
    best: Dict[str, dict] = {}
    for entry in entries:
        period_end = entry["end"]
        filed = entry.get("filed", "")
        current = best.get(period_end)
        if current is None or filed > current.get("filed", ""):
            best[period_end] = entry
    return sorted(best.values(), key=lambda x: x["end"], reverse=True)


# 口径更广的总计类 tag 在并列时取较大值；其余字段优先更窄、更靠前的 tag
MAX_VALUE_TAG_FIELDS = frozenset({"revenue"})


def _pick_tag_entries(
    gaap: dict,
    tags: List[str],
    field_id: str,
    scale: ValueScale,
    periods: int,
    preferred_currency: Optional[str] = None,
) -> List[Tuple[str, dict]]:
    """在多个候选 US-GAAP 标签中选取最新、口径最广的一组。"""
    candidates: List[Tuple[str, List[dict]]] = []
    for tag in tags:
        if tag not in gaap:
            continue
        entries = _dedupe_by_period(
            _filter_annual(_pick_unit_entries(gaap[tag], scale, preferred_currency, field_id), field_id)
        )
        if entries:
            candidates.append((tag, entries))

    if not candidates:
        return []

    latest_ends = [entries[0]["end"] for _, entries in candidates]
    newest = max(latest_ends)
    newest_year = int(newest[:4])
    candidates = [
        (tag, entries)
        for tag, entries in candidates
        if newest_year - int(entries[0]["end"][:4]) <= 8
    ]
    if not candidates:
        return []

    latest_end = max(entries[0]["end"] for _, entries in candidates)
    tied = [(tag, entries) for tag, entries in candidates if entries[0]["end"] == latest_end]
    if len(tied) == 1:
        tag, entries = tied[0]
    elif field_id in MAX_VALUE_TAG_FIELDS:
        tag, entries = max(tied, key=lambda item: abs(float(item[1][0]["val"])))
    else:
        tag_order = {t: i for i, t in enumerate(tags)}
        tag, entries = min(tied, key=lambda item: tag_order.get(item[0], 999))

    unit_key = preferred_currency or "USD"
    for key in (preferred_currency, "CNY", "USD", "HKD", "EUR", "GBP"):
        if not key:
            continue
        if key in gaap[tag].get("units", {}):
            unit_key = key
            break
    else:
        unit_key = next(iter(gaap[tag].get("units", {})), "USD")

    return [
        (tag, {**row, "_unit": unit_key})
        for row in entries[:periods]
    ]


def _currency_from_unit(unit_key: str) -> str:
    base = unit_key.split("/")[0].upper()
    if base in {"USD", "CNY", "HKD", "EUR", "GBP"}:
        return base
    return "USD"


def _standard_from_taxonomy(taxonomy: str) -> str:
    if taxonomy == "ifrs-full":
        return "IFRS"
    return "US-GAAP"


class UsSecXbrlAdapter:
    def __init__(self, client: Optional[SecEdgarClient] = None) -> None:
        self.client = client or SecEdgarClient()
        self._gaap_cache: Dict[str, dict] = {}

    def fetch(
        self,
        ticker: str,
        periods: int = 3,
        preferred_currency: Optional[str] = None,
    ) -> CompanyFinancials:
        facts_payload = self.client.fetch_company_facts(ticker)
        cik = self.client.resolve_cik(ticker)
        facts_root = facts_payload.get("facts", {})
        pref = preferred_currency
        if pref == "RMB":
            pref = "CNY"

        period_ends: List[str] = []
        values: List[FieldValue] = []
        errors: List[str] = []
        used_taxonomy = "us-gaap"
        used_currency = pref or "USD"

        for taxonomy in ("us-gaap", "ifrs-full"):
            tag_map = TAXONOMY_TAG_MAPS.get(taxonomy, {})
            gaap = facts_root.get(taxonomy, {})
            if not gaap:
                continue
            period_ends, values, errors, used_currency = self._extract_from_taxonomy(
                gaap, tag_map, taxonomy, periods, preferred_currency=pref
            )
            if period_ends:
                used_taxonomy = taxonomy
                self._gaap_cache[ticker.upper()] = gaap
                break

        unique_periods = sorted(set(period_ends), reverse=True)[:periods]

        return CompanyFinancials(
            ticker=ticker.upper(),
            company_name=facts_payload.get("entityName", ticker.upper()),
            market="US",
            cik=cik,
            standard=_standard_from_taxonomy(used_taxonomy),
            values=values,
            periods=unique_periods,
            errors=errors,
        )

    def _extract_from_taxonomy(
        self,
        gaap: dict,
        tag_map: Dict[str, List[str]],
        taxonomy: str,
        periods: int,
        preferred_currency: Optional[str] = None,
    ) -> Tuple[List[str], List[FieldValue], List[str], str]:
        period_ends: List[str] = []
        values: List[FieldValue] = []
        errors: List[str] = []
        component_cache: Dict[str, Dict[str, float]] = {}
        currency = "USD"

        for field_def in GLOBAL_FIELDS_V1:
            tags = tag_map.get(field_def.field_id, [])
            picked = _pick_tag_entries(
                gaap, tags, field_def.field_id, field_def.scale, periods, preferred_currency
            )

            if not picked and field_def.field_id == "total_liabilities" and taxonomy == "us-gaap":
                picked = self._derive_total_liabilities(gaap, periods, component_cache)

            if not picked:
                errors.append(f"Missing XBRL tag: {field_def.field_id}")
                continue

            for tag, entry in picked:
                raw = float(entry["val"])
                normalized = _normalize_value(raw, field_def.scale)
                period_end = entry["end"]
                period_ends.append(period_end)
                unit_key = entry.get("_unit", "USD")
                currency = _currency_from_unit(unit_key)
                values.append(
                    FieldValue(
                        field_id=field_def.field_id,
                        period_end=period_end,
                        fiscal_year=entry.get("fy"),
                        value=normalized,
                        currency=currency,
                        scale=field_def.scale,
                        standard=_standard_from_taxonomy(taxonomy),
                        source="xbrl" if not tag.startswith("derived:") else "xbrl_derived",
                        source_tag=tag if tag.startswith("derived:") else f"{taxonomy}:{tag}",
                        source_form=entry.get("form", ""),
                        filed_date=entry.get("filed", ""),
                    )
                )

        return period_ends, values, errors, currency

    def _derive_total_liabilities(
        self,
        gaap: dict,
        periods: int,
        component_cache: Dict[str, Dict[str, float]],
    ) -> List[Tuple[str, dict]]:
        current = self._component_values(gaap, "LiabilitiesCurrent", component_cache)
        noncurrent = self._component_values(gaap, "LiabilitiesNoncurrent", component_cache)
        if not current or not noncurrent:
            return []

        picked: List[Tuple[str, dict]] = []
        for period_end in sorted(set(current) & set(noncurrent), reverse=True)[:periods]:
            total = current[period_end] + noncurrent[period_end]
            picked.append(
                (
                    "derived:LiabilitiesCurrent+LiabilitiesNoncurrent",
                    {
                        "end": period_end,
                        "val": total,
                        "fy": None,
                        "form": "10-K",
                        "filed": "",
                    },
                )
            )
        return picked

    def _component_values(
        self,
        gaap: dict,
        tag: str,
        cache: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        if tag in cache:
            return cache[tag]
        if tag not in gaap:
            return {}
        entries = _filter_annual(_pick_unit_entries(gaap[tag], ValueScale.MILLIONS), "total_liabilities")
        values: Dict[str, float] = {}
        for entry in _dedupe_by_period(entries):
            values[entry["end"]] = float(entry["val"])
        cache[tag] = values
        return values
