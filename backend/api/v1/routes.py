from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel, Field

from backend.api.auth import ApiKeyRecord, require_api_access
from backend.config import settings
from backend.markets.eu.financials_service import EuFinancialsService
from backend.markets.hk.financials_service import HkFinancialsService
from backend.markets.us.financials_service import UsFinancialsService
from backend.services.batch_service import BatchVerificationService

router = APIRouter(prefix="/api/v1", tags=["v1"])

us_service = UsFinancialsService()
hk_service = HkFinancialsService()
eu_service = EuFinancialsService()
batch_service = BatchVerificationService()


class ReconciliationItemResponse(BaseModel):
    field_id: str
    label_en: str
    label_zh: str
    period_end: str
    status: str
    trust_level: str
    xbrl_value: Optional[float]
    pdf_value: Optional[float]
    delta: Optional[float]
    authoritative_value: Optional[float]
    authoritative_source: str


class IdentityCheckResponse(BaseModel):
    rule_id: str
    label: str
    period_end: str
    passed: bool
    lhs_value: Optional[float] = None
    rhs_value: Optional[float] = None
    delta: Optional[float] = None
    delta_rel: Optional[float] = None
    message: str = ""


class VerifiedFinancialsResponse(BaseModel):
    ticker: str
    company_name: str
    market: str
    cik: str = ""
    periods: list[str]
    trust_score: float
    verification_rate: float
    pdf_coverage_rate: float = 0.0
    production_ready: bool
    matched_count: int
    mismatch_count: int
    pdf_source: Optional[str]
    pdf_source_type: Optional[str]
    excel_path: Optional[str]
    formula_excel_path: Optional[str] = None
    cross_list_ticker: Optional[str] = None
    errors: list[str] = []
    reconciliation: list[ReconciliationItemResponse]
    identity_standard: str = ""
    identity_all_passed: bool = False
    identity_pass_rate: float = 0.0
    identity_checks: list[IdentityCheckResponse] = []


class BatchJobSpec(BaseModel):
    market: str
    ticker: str


class BatchVerifyRequest(BaseModel):
    jobs: List[BatchJobSpec] = Field(..., min_length=1, max_length=50)
    periods: int = Field(default=3, ge=1, le=5)
    export_excel: bool = True


class BatchVerifyItemResponse(BaseModel):
    market: str
    ticker: str
    success: bool
    company_name: str = ""
    trust_score: float = 0.0
    verification_rate: float = 0.0
    pdf_coverage_rate: float = 0.0
    production_ready: bool = False
    matched_count: int = 0
    mismatch_count: int = 0
    excel_path: Optional[str] = None
    error: str = ""
    errors: list[str] = []


class BatchVerifyResponse(BaseModel):
    markets: list[str]
    tickers: list[str]
    periods: int
    success_count: int
    production_ready_count: int
    avg_trust_score: float
    portfolio_excel_path: Optional[str]
    items: list[BatchVerifyItemResponse]


def _to_response(result) -> VerifiedFinancialsResponse:
    return VerifiedFinancialsResponse(
        ticker=result.ticker,
        company_name=result.company_name,
        market=result.market,
        cik=result.cik,
        periods=result.xbrl.periods or result.pdf.periods,
        trust_score=result.trust_score,
        verification_rate=result.verification_rate,
        pdf_coverage_rate=result.pdf_coverage_rate,
        production_ready=result.is_production_ready,
        matched_count=result.reconciliation.matched_count,
        mismatch_count=result.reconciliation.mismatch_count,
        pdf_source=result.filing.local_path if result.filing else None,
        pdf_source_type=result.reconciliation.pdf_source_type,
        excel_path=result.excel_path,
        formula_excel_path=result.formula_excel_path,
        cross_list_ticker=result.cross_list_ticker,
        errors=result.errors,
        reconciliation=[
            ReconciliationItemResponse(
                field_id=item.field_id,
                label_en=item.label_en,
                label_zh=item.label_zh,
                period_end=item.period_end,
                status=item.status.value,
                trust_level=item.trust_level.value,
                xbrl_value=item.xbrl_value,
                pdf_value=item.pdf_value,
                delta=item.delta,
                authoritative_value=item.authoritative_value,
                authoritative_source=item.authoritative_source,
            )
            for item in result.reconciliation.items
        ],
        identity_standard=result.identity_report.standard,
        identity_all_passed=result.identity_report.all_passed,
        identity_pass_rate=result.identity_report.pass_rate,
        identity_checks=[
            IdentityCheckResponse(
                rule_id=item.rule_id,
                label=item.label,
                period_end=item.period_end,
                passed=item.passed,
                lhs_value=item.lhs_value,
                rhs_value=item.rhs_value,
                delta=item.delta,
                delta_rel=item.delta_rel,
                message=item.message,
            )
            for item in result.identity_report.items
        ],
    )


def _validate_periods(periods: int) -> None:
    if periods < 1 or periods > 5:
            raise HTTPException(400, "periods must be between 1-5")


def _validate_fiscal_year(fiscal_year: int) -> None:
    if fiscal_year < 2019 or fiscal_year > 2030:
            raise HTTPException(400, "fiscal_year must be between 2019-2030")


async def _save_upload(ticker: str, market: str, file: UploadFile) -> str:
    if not file.filename:
        raise HTTPException(400, "Please upload an annual report PDF or HTML file")
    suffix = Path(file.filename).suffix.lower()
    allowed = {".pdf", ".htm", ".html", ".xhtml"} if market.lower() == "eu" else {".pdf", ".htm", ".html"}
    if suffix not in allowed:
            raise HTTPException(400, "Only PDF / HTML / XHTML filings are supported")
    upload_dir = Path(settings.upload_dir) / "filings" / market.lower()
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{ticker.lower()}_{file.filename}"
    saved_path.write_bytes(await file.read())
    return str(saved_path)


@router.get("/markets/us/{ticker}/verify", response_model=VerifiedFinancialsResponse)
def verify_us(
    ticker: str,
    periods: int = 3,
    export_excel: bool = True,
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_periods(periods)
    try:
        result = us_service.build_verified_financials(ticker=ticker, periods=periods, export_excel=export_excel)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _to_response(result)


@router.post("/markets/us/{ticker}/verify", response_model=VerifiedFinancialsResponse)
async def verify_us_upload(
    ticker: str,
    periods: int = 3,
    export_excel: bool = True,
    file: UploadFile = File(...),
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_periods(periods)
    saved_path = await _save_upload(ticker, "us", file)
    try:
        result = us_service.build_verified_financials(
            ticker=ticker,
            periods=periods,
            document_path=saved_path,
            export_excel=export_excel,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _to_response(result)


@router.get("/markets/us/{ticker}/verify/download")
def download_us_verify(ticker: str, periods: int = 3, _: ApiKeyRecord = Depends(require_api_access)):
    _validate_periods(periods)
    try:
        result = us_service.build_verified_financials(ticker=ticker, periods=periods, export_excel=True)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not result.excel_path or not Path(result.excel_path).exists():
        raise HTTPException(404, "Excel file not found")
    return FileResponse(
        result.excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{ticker.lower()}_verified_financials.xlsx",
    )


@router.get("/markets/hk/{ticker}/verify", response_model=VerifiedFinancialsResponse)
def verify_hk(
    ticker: str,
    periods: int = 3,
    export_excel: bool = True,
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_periods(periods)
    try:
        result = hk_service.build_verified_financials(ticker=ticker, periods=periods, export_excel=export_excel)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return _to_response(result)


@router.post("/markets/hk/{ticker}/verify", response_model=VerifiedFinancialsResponse)
async def verify_hk_upload(
    ticker: str,
    periods: int = 3,
    export_excel: bool = True,
    file: UploadFile = File(...),
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_periods(periods)
    saved_path = await _save_upload(ticker, "hk", file)
    try:
        result = hk_service.build_verified_financials(
            ticker=ticker,
            periods=periods,
            document_path=saved_path,
            export_excel=export_excel,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return _to_response(result)


@router.get("/markets/hk/{ticker}/verify/download")
def download_hk_verify(ticker: str, periods: int = 3, _: ApiKeyRecord = Depends(require_api_access)):
    _validate_periods(periods)
    try:
        result = hk_service.build_verified_financials(ticker=ticker, periods=periods, export_excel=True)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    if not result.excel_path or not Path(result.excel_path).exists():
        raise HTTPException(404, "Excel file not found")
    return FileResponse(
        result.excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"hk_{ticker.lower()}_verified_financials.xlsx",
    )


@router.get("/markets/eu/{lei}/verify", response_model=VerifiedFinancialsResponse)
def verify_eu(
    lei: str,
    fiscal_year: int = 2024,
    periods: int = 2,
    export_excel: bool = True,
    export_formula_excel: bool = True,
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_fiscal_year(fiscal_year)
    _validate_periods(periods)
    try:
        result = eu_service.build_verified_financials(
            lei=lei,
            fiscal_year=fiscal_year,
            periods=periods,
            export_excel=export_excel,
            export_formula_excel=export_formula_excel,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return _to_response(result)


@router.post("/markets/eu/{lei}/verify", response_model=VerifiedFinancialsResponse)
async def verify_eu_upload(
    lei: str,
    fiscal_year: int = 2024,
    periods: int = 2,
    export_excel: bool = True,
    export_formula_excel: bool = True,
    file: UploadFile = File(...),
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_fiscal_year(fiscal_year)
    _validate_periods(periods)
    saved_path = await _save_upload(lei, "eu", file)
    try:
        result = eu_service.build_verified_financials(
            lei=lei,
            fiscal_year=fiscal_year,
            periods=periods,
            document_path=saved_path,
            export_excel=export_excel,
            export_formula_excel=export_formula_excel,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return _to_response(result)


@router.get("/markets/eu/{lei}/verify/download")
def download_eu_verify(
    lei: str,
    fiscal_year: int = 2024,
    periods: int = 2,
    file_type: str = "verified",
    _: ApiKeyRecord = Depends(require_api_access),
):
    _validate_fiscal_year(fiscal_year)
    _validate_periods(periods)
    if file_type not in {"verified", "formula"}:
            raise HTTPException(400, "file_type must be 'verified' or 'formula'")
    try:
        result = eu_service.build_verified_financials(
            lei=lei,
            fiscal_year=fiscal_year,
            periods=periods,
            export_excel=True,
            export_formula_excel=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc

    if file_type == "formula":
        path = result.formula_excel_path
        filename = f"{lei.lower()}_{fiscal_year}_formula_model.xlsx"
    else:
        path = result.excel_path
        filename = f"{lei.lower()}_{fiscal_year}_verified.xlsx"
    if not path or not Path(path).exists():
        raise HTTPException(404, "Excel file not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@router.post("/batch/verify", response_model=BatchVerifyResponse)
def batch_verify(body: BatchVerifyRequest, _: ApiKeyRecord = Depends(require_api_access)):
    jobs = [(j.market, j.ticker) for j in body.jobs]
    report = batch_service.run(jobs=jobs, periods=body.periods, export_excel=body.export_excel)
    return BatchVerifyResponse(
        markets=report.markets,
        tickers=report.tickers,
        periods=report.periods,
        success_count=report.success_count,
        production_ready_count=report.production_ready_count,
        avg_trust_score=report.avg_trust_score,
        portfolio_excel_path=report.portfolio_excel_path,
        items=[
            BatchVerifyItemResponse(
                market=i.market,
                ticker=i.ticker,
                success=i.success,
                company_name=i.company_name,
                trust_score=i.trust_score,
                verification_rate=i.verification_rate,
                production_ready=i.production_ready,
                matched_count=i.matched_count,
                mismatch_count=i.mismatch_count,
                excel_path=i.excel_path,
                error=i.errors[0] if i.errors else "",
                errors=i.errors,
            )
            for i in report.items
        ],
    )


@router.get("/batch/portfolio/download")
def download_portfolio(path: str, _: ApiKeyRecord = Depends(require_api_access)):
    file_path = Path(path)
    output_root = Path(settings.output_dir).resolve()
    try:
        resolved = file_path.resolve()
    except OSError as exc:
        raise HTTPException(400, "Invalid path") from exc
    if output_root not in resolved.parents and resolved != output_root:
        raise HTTPException(403, "Access denied")
    if not resolved.exists() or resolved.suffix.lower() != ".xlsx":
        raise HTTPException(404, "Portfolio report not found")
    return FileResponse(
        resolved,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=resolved.name,
    )


@router.get("/usage")
def api_usage(_: ApiKeyRecord = Depends(require_api_access)):
    from backend.api.auth import usage_tracker

    return usage_tracker.summary()
