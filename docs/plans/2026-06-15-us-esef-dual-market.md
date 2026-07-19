# US 10-K + European ESEF Dual-Market Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a unified verified financials product for **US 10-K** and **European ESEF** annual reports — XBRL × document reconcile, accounting identity checks, and formula-linked Excel export — without building a generic "all PDFs" parser.

**Architecture:** Extract a **shared market kernel** (`backend/markets/shared/`) from existing US/HK code: inline-XBRL HTML grid, period alignment, reconciliation, and validation. US keeps SEC `companyfacts` + 10-K HTML; EU adds ESMA filing resolver + ESEF inline-XBRL instance parsing mapped through **`ifrs-full`** taxonomy. Both markets share `GLOBAL_FIELDS_V1`, `FinancialReconciler`, and a new `AccountingIdentityValidator` + `FormulaExcelExporter`.

**Tech Stack:** Python 3.11+, BeautifulSoup/lxml (inline iXBRL HTML), openpyxl (formula Excel), optional `ixbrl-parse` or subprocess Arelle for raw `.xhtml` instances, pytest benchmarks.

**Why dual-track works:** SEC 10-K and ESEF both use **inline XBRL embedded in HTML** — `html_grid_extractor.py` already handles US iXBRL tables. ESEF is structurally closer to US 10-K than to HK PDF scans. IFRS tag maps already exist in `xbrl_adapter.py`.

---

## Phase 0 — Shared Kernel (Week 1–2)

Both markets depend on this; do **before** EU-specific filing download.

### Task 0.1: Market abstraction interface

**Files:**
- Create: `backend/markets/shared/protocols.py`
- Create: `backend/markets/shared/__init__.py`
- Modify: `backend/markets/us/financials_service.py`
- Test: `tests/markets/test_market_protocols.py`

**Step 1: Write the failing test**

```python
# tests/markets/test_market_protocols.py
from backend.markets.shared.protocols import MarketFinancialsService

def test_us_service_implements_protocol():
    from backend.markets.us.financials_service import UsFinancialsService
    assert isinstance(UsFinancialsService(), MarketFinancialsService)
```

**Step 2: Run test — expect FAIL** (protocol not defined)

Run: `pytest tests/markets/test_market_protocols.py -v`

**Step 3: Define protocol**

```python
# backend/markets/shared/protocols.py
from typing import Protocol, Optional
from backend.services.verified_models import VerifiedFinancialsResult

class MarketFinancialsService(Protocol):
    def build_verified_financials(
        self,
        identifier: str,
        periods: int = 3,
        document_path: Optional[str] = None,
        export_excel: bool = True,
        output_dir: Optional[str] = None,
    ) -> VerifiedFinancialsResult: ...
```

**Step 4: Run test — expect PASS**

**Step 5: Commit** (only if user requests)

---

### Task 0.2: Extract shared inline-XBRL HTML grid path

**Files:**
- Create: `backend/markets/shared/inline_xbrl_grid.py` (move generic logic from US)
- Modify: `backend/markets/us/html_grid_extractor.py` (import from shared)
- Test: `tests/markets/test_html_grid_extractor.py` (must still pass)

**Step 1:** Move `_compact_html_statement_dataframe`, table scoring helpers that are taxonomy-agnostic into `inline_xbrl_grid.py`.

**Step 2:** Add `MarketContext` enum: `US_GAAP`, `IFRS`, `ESEF` — ESEF uses IFRS labels + ESMA-specific title patterns.

**Step 3:** Run existing tests:

```bash
pytest tests/markets/test_html_grid_extractor.py -v
```

Expected: all PASS (no regression).

---

### Task 0.3: Central IFRS / ESEF term registry

**Files:**
- Create: `backend/markets/shared/ifrs_term_registry.py`
- Modify: `backend/markets/us/statement_grid_extractor.py` (`FIELD_LABEL_ALIASES` → import IFRS block)
- Modify: `backend/markets/hk/statement_locator.py` (optional: import shared patterns)

**Content:** Map `GLOBAL_FIELDS_V1` field IDs to:
- English IFRS primary labels (`Revenue`, `Profit or loss`, `Equity attributable to owners`)
- Common EU locale variants (DE `Umsatzerlöse`, FR `Chiffre d'affaires`, NL `Omzet`) — start with EN-only, add locales incrementally
- ESEF `ifrs-full` concept local names (same as `IFRS_TAGS` in `xbrl_adapter.py`)

**Test:** `tests/markets/test_ifrs_term_registry.py` — every global field has ≥3 IFRS aliases.

---

### Task 0.4: Accounting identity validator (L3)

**Files:**
- Create: `backend/validation/accounting_identities.py`
- Create: `backend/validation/identity_models.py`
- Modify: `backend/markets/us/financials_service.py` (attach identity report to result)
- Modify: `backend/services/verified_models.py` (add `identity_report` field)
- Test: `tests/validation/test_accounting_identities.py`

**Rules to implement:**

| Market | Rule ID | Formula | Tolerance |
|--------|---------|---------|-----------|
| US-GAAP | `balance_equation` | `total_assets ≈ total_liabilities + total_equity` | 0.01% of assets |
| IFRS/ESEF | `balance_equation` | same | same |
| IFRS/ESEF | `equity_nci` | `total_equity ≈ parent_equity + nci` | optional when NCI fields present |
| US-GAAP | `net_income_bridge` | `net_income ≈ operating_income + non_op - tax` | 1% rel (requires schema v2 fields) |

**Phase 0 scope:** Implement `balance_equation` only (uses existing 13 fields). Defer `net_income_bridge` to Phase 1 schema expansion.

**Step 1: Failing test**

```python
def test_balance_equation_passes_when_balanced():
    from backend.validation.accounting_identities import AccountingIdentityValidator
    fv = make_financials(total_assets=1000, total_liabilities=600, total_equity=400)
    report = AccountingIdentityValidator().validate(fv, standard="US-GAAP")
    assert report.all_passed
```

**Step 2–4:** Implement, run `pytest tests/validation/test_accounting_identities.py -v`

---

### Task 0.5: Formula Excel exporter

**Files:**
- Create: `backend/export/formula_excel.py`
- Modify: `backend/export/verified_excel.py` (optional flag `include_formulas=True`)
- Modify: `backend/markets/us/financials_service.py` (write formula workbook alongside verified)
- Test: `tests/export/test_formula_excel.py`

**Sheet layout:**

| Sheet | Content |
|-------|---------|
| `Validation` | Balance check `=IF(ABS(B2-(C2+D2))<0.01*B2,"PASS","FAIL")` per period |
| `Balance Sheet` | Line items from grid + `Total Assets =SUM(...)` |
| `Income Statement` | Same pattern |
| `Cash Flow` | Same pattern |
| `Sources` | XBRL tag, PDF row ref, reconcile status |

**Step 1:** Test opens xlsx, asserts cell `Balance Sheet!B20` starts with `=SUM(`.

**Dependency:** Requires grid row metadata — extend `StatementGrid` with `row_index` + `excel_row_map` when exporting.

---

## Phase 1 — US 10-K Hardening (Week 2–4)

Parallel with Phase 2 once Task 0.2 done.

### Task 1.1: Fix remaining benchmark misses

**Priority order (from latest benchmark):**

| Ticker | Issue | File to touch |
|--------|-------|---------------|
| GOOGL | Balance column swap | `html_grid_extractor.py` |
| MSFT | Wrong cashflow table | `html_grid_extractor.py` (reuse UNH pattern) |
| AMD | cfo/cfi mismatch | `html_grid_extractor.py` |
| AMZN, MA | col1 None balance | `period_parser.py`, `statement_grid_extractor.py` |
| META | col1 None OI/EPS | `html_grid_extractor.py` |

**Step 1:** Add failing test per ticker in `tests/markets/test_html_grid_extractor.py`.

**Step 2:** Fix, run benchmark:

```bash
python scripts/run_verified_accuracy_benchmark.py
```

**Target:** PDF extract ≥97%, Verify ≥98%, 18+/20 at 100%.

---

### Task 1.2: Expand US schema for NI bridge (optional v2)

**Files:**
- Modify: `backend/global_schema/registry.py` — add `income_tax_expense`, `non_operating_income` (optional fields)
- Modify: `backend/markets/us/xbrl_adapter.py` — tag maps
- Modify: `backend/validation/accounting_identities.py` — enable `net_income_bridge`

Only add fields with ≥15/20 benchmark coverage; mark others `skipped` in export.

---

### Task 1.3: Wire L3 + Formula export into US API

**Files:**
- Modify: `backend/api/v1/routes.py` — query param `?formula_excel=true`
- Modify: `backend/services/verified_models.py` — response includes `identity_report`
- Test: `tests/markets/test_verified_financials_integration.py`

---

## Phase 2 — European ESEF (Week 2–6)

### Task 2.1: ESEF filing resolver

**Files:**
- Create: `backend/markets/eu/__init__.py`
- Create: `backend/markets/eu/filing_resolver.py`
- Create: `backend/markets/eu/constants.py`
- Create: `backend/markets/eu/esma_client.py`
- Test: `tests/markets/eu/test_filing_resolver.py`

**Identifier:** LEI (20-char) or `(country, ticker)` → LEI lookup table for benchmark issuers.

**Data sources (pick one primary, one fallback):**

1. **filings.xbrl.org** — free ESMA mirror, API + bulk download
2. **ESMA European Single Access Point (ESAP)** — when stable API available
3. Local cache: `data/filings/eu/{lei}_{year}.xhtml`

**`EuFilingDocument` fields:**

```python
@dataclass
class EuFilingDocument:
    lei: str
    company_name: str
    fiscal_year: int
    local_path: Path          # inline XHTML or PDF
    xbrl_instance_path: Optional[Path]  # detached instance if packaged
    taxonomy: str             # "ifrs-full" + extension URLs
    language: str             # "en", "de", ...
    filing_date: date
```

**Benchmark corpus (10 issuers, diverse):**

| LEI | Company | Country | Notes |
|-----|---------|---------|-------|
| 529900ODI3047E2L041 | SAP SE | DE | English ESEF |
| 213800LKDGOCQMED8T23 | ASML | NL | Large cap |
| 96950077LHD59WALKF32 | LVMH | FR | French primary |
| 213800WAVVOPS85N220 | Unilever PLC | GB/NL | Dual listed |
| 5493000JODSOBIHKJ336 | Nestlé | CH/EU | Multi-locale |
| … | add 5 more | DE/FR/IT/ES | Bank + industrial mix |

Store under `tests/benchmark/financial_esef/`.

---

### Task 2.2: ESEF inline-XBRL extractor

**Files:**
- Create: `backend/markets/eu/inline_xbrl_extractor.py`
- Create: `backend/markets/eu/xbrl_adapter.py`
- Reuse: `backend/markets/shared/inline_xbrl_grid.py`
- Reuse: `backend/markets/us/html_grid_extractor.py` with `MarketContext.ESEF`
- Test: `tests/markets/eu/test_inline_xbrl_extractor.py`

**Two-path strategy (YAGNI order):**

1. **Path A (MVP):** Parse ESEF `.xhtml` with existing HTML grid extractor — most ESEF primary statements render as `<table>` with `ix:nonFraction` tags (same as SEC iXBRL).

2. **Path B (fallback):** Parse detached `reports/*.xhtml` instance with lightweight ixbrl fact extraction:

```python
# Option: add dependency ixbrl-parse>=0.3 to pyproject.toml
from ixbrl_parse import parse_ixbrl
```

Map facts → `CompanyFinancials` via `IFRS_TAGS` + ESEF extension concept fallbacks.

**ESEF-specific handling:**
- **Block tagging:** Some line items are `ix:nonNumeric` text blocks — grid path still works for rendered tables.
- **Scale/decimals:** Respect `scale` attribute on `ix:nonFraction` (same as SEC).
- **Consolidated vs separate:** Prefer consolidated `[ifrs-full:Consolidated]` context if detectable.
- **NCI:** Map `ProfitLossAttributableToNoncontrollingInterests` + `EquityAttributableToOwnersOfParent` for identity check.

---

### Task 2.3: EuFinancialsService orchestrator

**Files:**
- Create: `backend/markets/eu/financials_service.py`
- Pattern: mirror `HkFinancialsService` but **XBRL-primary** (ESEF mandates tagged data)

**Flow:**

```
EuFilingResolver → EsefInlineXbrlExtractor (authoritative)
                 → HtmlGridExtractor (document cross-check, same file!)
                 → FinancialReconciler
                 → AccountingIdentityValidator
                 → VerifiedExcelExporter + FormulaExcelExporter
```

Note: For ESEF, **same XHTML file** feeds both "XBRL" and "document" paths — reconcile validates grid rendering vs tagged facts (internal consistency), not two separate sources like US SEC API vs PDF.

**Test:** `tests/markets/eu/test_eu_financials_integration.py`

---

### Task 2.4: ESEF XBRL adapter (detached instance)

**Files:**
- Create: `backend/markets/eu/xbrl_instance_parser.py`
- Modify: `backend/markets/eu/xbrl_adapter.py`

When filing package contains `*.xbrl` / `*reports*.xhtml`:
- Parse contexts (instant vs duration, consolidated member)
- Pick annual FY contexts (360–370 day duration or FY label)
- Map via extended `IFRS_TAGS` + `_pick_tag_entries` logic reused from `UsSecXbrlAdapter`

Extract shared `_pick_tag_entries`, `_normalize_value` into `backend/markets/shared/xbrl_utils.py`.

---

### Task 2.5: EU API routes + CLI

**Files:**
- Modify: `backend/api/v1/routes.py`
- Create: `scripts/run_eu_verified_financials.py`
- Create: `scripts/run_esef_accuracy_benchmark.py`

```python
@router.get("/markets/eu/{lei}/verify")
@router.get("/markets/eu/{lei}/verify/download")
```

**CLI:**

```bash
python scripts/run_eu_verified_financials.py --lei 529900ODI3047E2L041 --year 2024
python scripts/run_esef_accuracy_benchmark.py
```

---

### Task 2.6: ESEF benchmark + ground truth

**Files:**
- Create: `tests/benchmark/financial_esef/ground_truth.json`
- Create: `tests/benchmark/financial_esef/README.md`

Ground truth sources:
- Manual spot-check from published annual reports
- Cross-verify against consolidated PDF totals in ESEF package
- Public APIs (yfinance only for sanity, not authoritative)

**Target:** 10 issuers, ≥90% field verify, 100% balance equation pass.

---

## Phase 3 — Unified Product Surface (Week 5–7)

### Task 3.1: Single dashboard entry

**Files:**
- Modify: `frontend/dashboard.html` — market selector: US | EU
- Modify: `backend/api/v1/routes.py` — `POST /api/v1/markets/verify` with body `{market, identifier, year?}`

---

### Task 3.2: Batch portfolio export (US + EU)

**Files:**
- Modify: `backend/export/batch_excel.py` — mixed market batch
- Test: `tests/export/test_batch_excel.py`

---

### Task 3.3: Docker offline bundle

**Files:**
- Modify: `docker-compose.yml` — volume for `data/filings/us` + `data/filings/eu`
- Modify: `README.md` — US + ESEF quickstart

No outbound network required when filings pre-cached.

---

## Shared Component Map

```
backend/
├── markets/
│   ├── shared/
│   │   ├── protocols.py           # MarketFinancialsService
│   │   ├── inline_xbrl_grid.py    # HTML table extraction (US + ESEF)
│   │   ├── ifrs_term_registry.py  # IFRS/ESEF label aliases
│   │   └── xbrl_utils.py          # tag picking, scale, period filter
│   ├── us/                        # existing SEC pipeline
│   └── eu/                        # NEW ESEF pipeline
├── validation/
│   ├── reconciliation.py          # existing L2
│   └── accounting_identities.py   # NEW L3
└── export/
    ├── verified_excel.py          # existing
    └── formula_excel.py           # NEW differentiated output
```

---

## Dependencies to Add

```toml
# pyproject.toml [project.optional-dependencies]
esef = [
  "ixbrl-parse>=0.3",   # inline XBRL fact extraction fallback
  "lxml>=5.0",          # faster XHTML parse if not already present
]
```

Arelle CLI optional for CI taxonomy validation — not runtime dependency for MVP.

---

## Testing Strategy

| Layer | US | ESEF |
|-------|-----|------|
| Unit | `test_html_grid_extractor`, `test_us_xbrl_adapter` | `test_inline_xbrl_extractor`, `test_xbrl_instance_parser` |
| Integration | `test_verified_financials_integration` | `test_eu_financials_integration` |
| Benchmark | 20-ticker `financial_10k` | 10-issuer `financial_esef` |
| Identity | `test_accounting_identities` | same tests, `standard="IFRS"` |

**CI gate:** US verify ≥98%, ESEF verify ≥90%, all balance equations pass.

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| ESEF national extensions (DEI, UKSEF) | Start with `ifrs-full` core; extension concept fallback list |
| Non-English primary reports | Phase 2 EN-only; Phase 3 locale aliases in registry |
| ESEF PDF-only issuers (rare post-2020) | Skip or PDF grid fallback; mark `source=pdf_only` |
| Same file reconcile trivially passes | Add **fact vs rendered cell** compare (ix tag value vs table text) |
| GOOGL/MSFT US tails block demo | Phase 1 Task 1.1 before sales demo |

---

## Execution Order (Recommended)

```
Week 1:  0.2 shared HTML grid → 0.3 IFRS registry → 0.4 balance identity
Week 2:  0.5 formula Excel + 1.1 GOOGL/MSFT fixes (parallel)
Week 3:  2.1 ESEF resolver + download benchmark corpus
Week 4:  2.2–2.3 ESEF extractor + EuFinancialsService
Week 5:  2.5 API/CLI + 2.6 benchmark tuning
Week 6:  1.2 NI bridge schema + 3.1 dashboard
Week 7:  3.2 batch + 3.3 docker docs
```

US and ESEF share **Tasks 0.2–0.5** — doing them first prevents duplicate work.

---

## Out of Scope (YAGNI)

- A-share / CAS module
- Japan EDINET / Korea DART
- Full Arelle calculation linkbase validation
- Multi-document quarterly (10-Q / interim ESEF)
- Automatic LEI discovery from free-text company name (manual benchmark map first)

---

## Success Criteria

1. **US:** 20-ticker benchmark ≥98% verify; formula Excel with working `=SUM` totals; balance identity PASS on all complete balance sheets.
2. **ESEF:** 10-issuer benchmark ≥90% verify; same Excel output format as US (analysts use one template).
3. **API:** `/markets/us/{ticker}/verify` and `/markets/eu/{lei}/verify` return identical response shape.
4. **Demo story:** "Upload SAP 2024 ESEF + AAPL 10-K → get formula-linked, identity-checked Excel in one workflow."
