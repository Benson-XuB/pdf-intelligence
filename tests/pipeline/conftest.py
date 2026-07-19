from pathlib import Path

import pytest

from tests.conftest import FIXTURES_DIR, ensure_fixtures


@pytest.fixture(scope="session", autouse=True)
def _setup_fixtures():
    ensure_fixtures()


@pytest.fixture
def sample_text_pdf() -> Path:
    return FIXTURES_DIR / "sample_text.pdf"


@pytest.fixture
def sample_scanned_pdf() -> Path:
    return FIXTURES_DIR / "sample_scanned.pdf"


@pytest.fixture
def sample_report_pdf() -> Path:
    return FIXTURES_DIR / "sample_report.pdf"
