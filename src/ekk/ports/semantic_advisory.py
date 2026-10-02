"""Host-owned semantic advice boundary.

The application supplies only already-authorized, bounded candidate summaries.
Implementations may use a local model, but advice never owns authorization,
selection, persistence, or execution.
"""
from typing import Protocol


class SemanticAdvisor(Protocol):
    def advise(self, *, task: str, candidates: list[dict]) -> dict: ...

