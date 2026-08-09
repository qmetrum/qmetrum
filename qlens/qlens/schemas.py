from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List

STANCES = ("Buy", "Hold", "Sell")
CONVICTIONS = ("low", "medium", "high")


@dataclass
class Fact:
    idx: int
    source: str
    statement: str


@dataclass
class QLensVerdict:
    ticker: str
    as_of: str
    stance: str          # Buy | Hold | Sell
    conviction: str      # low | medium | high  (NOT a probability of being right)
    bull: List[str] = field(default_factory=list)
    bear: List[str] = field(default_factory=list)
    key_risks: List[str] = field(default_factory=list)
    what_would_change_my_mind: List[str] = field(default_factory=list)
    rationale: str = ""
    facts: List[dict] = field(default_factory=list)
    disclaimer: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
