from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IdentityCheckItem:
    rule_id: str
    label: str
    period_end: str
    passed: bool
    lhs_value: Optional[float] = None
    rhs_value: Optional[float] = None
    delta: Optional[float] = None
    delta_rel: Optional[float] = None
    message: str = ""


@dataclass
class IdentityReport:
    standard: str
    items: List[IdentityCheckItem] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.items) and all(item.passed for item in self.items)

    @property
    def pass_count(self) -> int:
        return sum(1 for item in self.items if item.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for item in self.items if not item.passed)

    @property
    def pass_rate(self) -> float:
        if not self.items:
            return 0.0
        return self.pass_count / len(self.items)
