"""ORACLE Wilson confidence scorer — ported from FORGE scoring infrastructure."""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("oracle.query.confidence")

# Thresholds
ACCURACY_THRESHOLD = 0.7
COMPLETENESS_THRESHOLD = 0.5
CONFIDENCE_THRESHOLD = 0.6


@dataclass
class ConfidenceScore:
    """Three-axis confidence score for a response."""
    accuracy: float = 0.0       # How well claims match source material
    completeness: float = 0.0   # How much relevant source material was used
    confidence: float = 0.0     # Statistical confidence in the answer
    overall: float = 0.0        # Weighted composite
    requires_review: bool = False
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 3),
            "completeness": round(self.completeness, 3),
            "confidence": round(self.confidence, 3),
            "overall": round(self.overall, 3),
            "requires_review": self.requires_review,
            "details": self.details or {},
        }


class WilsonScorer:
    """Wilson score confidence intervals — ported from FORGE.

    Wilson score provides a lower bound on confidence that accounts
    for sample size, avoiding the problem of high confidence from
    small numbers of observations.
    """

    def __init__(self, z: float = 1.96):
        """
        Args:
            z: Z-score for confidence level (1.96 = 95%, 1.645 = 90%)
        """
        self.z = z

    def wilson_lower_bound(self, successes: int, total: int) -> float:
        """Calculate Wilson score lower bound.

        This is the core FORGE scoring function. It gives a conservative
        estimate of the true success rate given the observed data.
        """
        if total == 0:
            return 0.0

        p = successes / total
        z2 = self.z ** 2
        n = total

        numerator = p + z2 / (2 * n) - self.z * math.sqrt(
            (p * (1 - p) + z2 / (4 * n)) / n
        )
        denominator = 1 + z2 / n

        return max(0.0, numerator / denominator)

    def score_response(
        self,
        response_text: str,
        citations_found: int,
        total_claims: int,
        chunks_used: int,
        chunks_available: int,
        unmatched_claims: int,
    ) -> ConfidenceScore:
        """Score a response on accuracy, completeness, and confidence."""

        # --- Accuracy ---
        # What fraction of factual claims are supported by citations?
        if total_claims > 0:
            matched = total_claims - unmatched_claims
            accuracy = self.wilson_lower_bound(matched, total_claims)
        elif citations_found > 0:
            accuracy = 0.8  # Has citations but couldn't count claims
        else:
            accuracy = 0.3  # No citations at all

        # --- Completeness ---
        # What fraction of available relevant chunks were used?
        if chunks_available > 0:
            usage_ratio = min(chunks_used / chunks_available, 1.0)
            completeness = self.wilson_lower_bound(
                int(usage_ratio * 100), 100
            )
        else:
            completeness = 0.0

        # --- Confidence ---
        # Combined statistical confidence accounting for:
        # - citation coverage
        # - response length (very short = less confident)
        # - number of sources
        response_length = len(response_text)
        length_factor = min(response_length / 500, 1.0)

        source_factor = min(citations_found / 3, 1.0) if citations_found > 0 else 0.2

        raw_confidence = (accuracy * 0.5 + source_factor * 0.3 + length_factor * 0.2)
        confidence = self.wilson_lower_bound(
            int(raw_confidence * 100), 100
        )

        # --- Overall ---
        overall = accuracy * 0.5 + completeness * 0.2 + confidence * 0.3

        # --- Review flag ---
        requires_review = (
            accuracy < ACCURACY_THRESHOLD or
            unmatched_claims > 2 or
            citations_found == 0
        )

        # Handle edge case: "I cannot find this" is a valid response
        if "cannot find" in response_text.lower() or "not in the" in response_text.lower():
            accuracy = 0.9  # Honest about gaps
            requires_review = False
            overall = 0.85

        return ConfidenceScore(
            accuracy=accuracy,
            completeness=completeness,
            confidence=confidence,
            overall=overall,
            requires_review=requires_review,
            details={
                "citations_found": citations_found,
                "total_claims": total_claims,
                "unmatched_claims": unmatched_claims,
                "chunks_used": chunks_used,
                "chunks_available": chunks_available,
                "response_length": response_length,
            },
        )

    def count_factual_claims(self, text: str) -> int:
        """Count approximate number of factual claims in text."""
        import re
        # Factual claims contain specific data: numbers, part names, specs
        claim_patterns = [
            r"\b\d+\s*(MHz|GHz|KB|MB|GB|kHz|Hz|V|mA|mW|pin|bit|byte|baud)\b",
            r"\b(STM32|ARM|Cortex|RISC-V|MIPS)\w*\b",
            r"\b(SPI|I2C|UART|JTAG|SWD|USB|CAN|Ethernet|MODBUS)\b",
            r"\bversion\s+[\d.]+\b",
            r"\b[A-Z]{2,}\d{3,}\w*\b",  # Part number patterns
        ]

        claims = set()
        for pattern in claim_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                claims.add(match.start())

        return len(claims)
