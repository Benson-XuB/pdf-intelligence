# ESEF benchmark corpus

European annual reports (inline XHTML) for the EU verified pipeline.

## Download

```bash
# List issuers and local file status
.venv/bin/python scripts/download_esef_benchmark_corpus.py --list

# Download all 10 issuers (~200MB each, may take 30+ min)
.venv/bin/python scripts/download_esef_benchmark_corpus.py

# Download one issuer
.venv/bin/python scripts/download_esef_benchmark_corpus.py --id LVMH
```

Files are cached under `data/filings/eu/` and copied to `tests/benchmark/financial_esef/{id}_annual.xhtml`.

## Benchmark

```bash
.venv/bin/python scripts/run_esef_verified_benchmark.py
```

Report: `tests/benchmark/financial_esef/verified_accuracy_report.json`

## API

```bash
GET  /api/v1/markets/eu/{lei}/verify?fiscal_year=2025&periods=2
POST /api/v1/markets/eu/{lei}/verify?fiscal_year=2025  (upload .xhtml)
GET  /api/v1/markets/eu/{lei}/verify/download?fiscal_year=2025&file_type=formula
```

Benchmark ids (resolve to LEI): `ASML`, `AIRBUS`, `SANOFI`, `TTE`, `OR`, `SU`, `PHIA`, `ADYEN`, `HEIO`, `LVMH` (French-only).
