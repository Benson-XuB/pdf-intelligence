#!/usr/bin/env python3
"""CLI runner for EU / ESEF verified financials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.markets.eu.financials_service import EuFinancialsService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ESEF verified financials")
    parser.add_argument("lei", help="Issuer LEI (20 chars) or benchmark id (e.g. ASML)")
    parser.add_argument("--year", type=int, default=2024, dest="fiscal_year")
    parser.add_argument("--periods", type=int, default=2)
    parser.add_argument("--document", dest="document_path", default=None)
    parser.add_argument("--no-excel", action="store_true")
    parser.add_argument("--no-formula", action="store_true")
    args = parser.parse_args()

    from backend.markets.eu.filing_resolver import EuFilingResolver

    issuer = EuFilingResolver.benchmark_issuer(args.lei)
    lei = issuer["lei"] if issuer else args.lei
    fiscal_year = issuer["fiscal_year"] if issuer and args.fiscal_year == 2024 else args.fiscal_year

    result = EuFinancialsService().build_verified_financials(
        lei=lei,
        fiscal_year=fiscal_year,
        periods=args.periods,
        document_path=args.document_path,
        export_excel=not args.no_excel,
        export_formula_excel=not args.no_formula,
    )
    print(f"{result.company_name} ({result.market}) FY{fiscal_year}")
    print(f"  coverage periods: {result.pdf.periods}")
    print(f"  identity pass: {result.identity_report.pass_rate:.0%}")
    print(f"  errors: {len(result.errors)}")
    if result.excel_path:
        print(f"  verified: {result.excel_path}")
    if result.formula_excel_path:
        print(f"  formula:  {result.formula_excel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
