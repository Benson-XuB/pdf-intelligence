from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmark.financial_10k.corpus import CORPUS_20, available_entries, missing_entries


def test_corpus_targets_twenty():
    assert len(CORPUS_20) == 20


@pytest.mark.integration
def test_corpus_files_present():
    missing = missing_entries()
    assert not missing, f"缺少语料: {[m['id'] for m in missing]}"
