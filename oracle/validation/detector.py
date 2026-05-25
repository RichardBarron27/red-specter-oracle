"""ORACLE Response Validator — 7-subsystem hallucination detection ported from M40."""

from __future__ import annotations

import json
import math
import re
import time
import uuid
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from oracle.core.crypto import CryptoEngine
from oracle.db.database import Database
from oracle.validation.patterns import (
    HALLUCINATION_PATTERNS, SEVERITY_WEIGHTS,
    CONTRADICTION_PAIRS, HEDGING_PHRASES, CERTAINTY_PHRASES,
)

logger = logging.getLogger("oracle.validation")


# ============================================================
# Data classes
# ============================================================

@dataclass
class Detection:
    """A single hallucination detection."""
    detection_id: str
    pattern_id: str
    pattern_name: str
    category: str
    severity: str
    matched_text: str
    description: str


@dataclass
class ValidationResult:
    """Full validation result from all 7 subsystems."""
    # Subsystem scores
    pattern_score: float = 1.0       # 1.0 = no patterns found (good)
    consistency_score: float = 1.0   # 1.0 = fully consistent with sources
    contradiction_score: float = 1.0 # 1.0 = no contradictions
    confidence_score: float = 0.5    # Hedging vs certainty
    fact_check_score: float = 1.0    # 1.0 = all facts verified
    drift_score: float = 1.0        # 1.0 = no drift detected
    accuracy_grade: str = "B"        # A-F grade

    # Composite
    overall_score: float = 0.0
    status: str = "GREEN"           # GREEN, AMBER, RED, INCOMPLETE
    status_reason: str = ""
    incomplete: bool = False
    requires_review: bool = False

    # Details
    detections: list[Detection] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    drift_events: list[dict[str, Any]] = field(default_factory=list)

    # Signing
    signature: str = ""
    signed_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_score": round(self.pattern_score, 3),
            "consistency_score": round(self.consistency_score, 3),
            "contradiction_score": round(self.contradiction_score, 3),
            "confidence_score": round(self.confidence_score, 3),
            "fact_check_score": round(self.fact_check_score, 3),
            "drift_score": round(self.drift_score, 3),
            "accuracy_grade": self.accuracy_grade,
            "overall_score": round(self.overall_score, 3),
            "status": self.status,
            "status_reason": self.status_reason,
            "incomplete": self.incomplete,
            "requires_review": self.requires_review,
            "detections": [
                {"pattern_id": d.pattern_id, "category": d.category,
                 "severity": d.severity, "matched_text": d.matched_text[:100],
                 "description": d.description}
                for d in self.detections
            ],
            "unverified_claims": self.unverified_claims[:10],
            "conflicts": self.conflicts[:5],
            "drift_events": self.drift_events[:5],
            "signed": bool(self.signature),
        }


# ============================================================
# 7 Subsystems
# ============================================================

class PatternMatcher:
    """Subsystem 1: Detect hallucination patterns in LLM output."""

    def __init__(self):
        self._compiled = []
        for pat_id, name, cat, sev, regex, desc in HALLUCINATION_PATTERNS:
            try:
                self._compiled.append((pat_id, name, cat, sev, re.compile(regex), desc))
            except re.error:
                pass

    def scan(self, text: str) -> tuple[float, list[Detection]]:
        detections = []
        total_severity = 0.0

        for pat_id, name, cat, sev, pattern, desc in self._compiled:
            for match in pattern.finditer(text):
                detections.append(Detection(
                    detection_id=str(uuid.uuid4()),
                    pattern_id=pat_id,
                    pattern_name=name,
                    category=cat,
                    severity=sev,
                    matched_text=match.group()[:200],
                    description=desc,
                ))
                total_severity += SEVERITY_WEIGHTS.get(sev, 0.3)

        # Score: 1.0 = clean, 0.0 = heavily contaminated
        score = max(0.0, 1.0 - (total_severity / max(len(self._compiled), 1)))
        return score, detections


class ConsistencyChecker:
    """Subsystem 2: Check response is grounded in source context."""

    _stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "as", "and", "but", "or", "not", "no",
        "that", "this", "it", "its", "they", "them", "their",
    }

    def check(self, response: str, context: str) -> float:
        """Return 0-1 score of how grounded the response is in context."""
        if not context.strip():
            return 0.3

        resp_tokens = self._tokenize(response)
        ctx_tokens = self._tokenize(context)

        if not resp_tokens:
            return 1.0

        # TF-IDF weighted overlap
        ctx_tf = Counter(ctx_tokens)
        resp_tf = Counter(resp_tokens)

        overlap = sum(min(resp_tf[w], ctx_tf[w]) for w in resp_tf if w in ctx_tf)
        total = sum(resp_tf.values())

        tfidf_score = overlap / total if total > 0 else 0

        # Token overlap (simpler metric)
        ctx_set = set(ctx_tokens)
        resp_set = set(resp_tokens)
        token_overlap = len(resp_set & ctx_set) / len(resp_set) if resp_set else 0

        return 0.7 * tfidf_score + 0.3 * token_overlap

    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r"\b[a-z]+\b", text.lower())
        return [w for w in words if w not in self._stop_words and len(w) > 2]


class ContradictionDetector:
    """Subsystem 3: Detect contradictions within response and against sources."""

    def detect(self, response: str, source_text: str = "") -> tuple[float, list[dict[str, Any]]]:
        contradictions = []
        sentences = re.split(r"(?<=[.!?])\s+", response)

        # Internal contradictions
        for i, s1 in enumerate(sentences):
            w1 = set(re.findall(r"\b[a-z]+\b", s1.lower()))
            for j, s2 in enumerate(sentences[i+1:i+4], start=i+1):
                w2 = set(re.findall(r"\b[a-z]+\b", s2.lower()))
                for wa, wb in CONTRADICTION_PAIRS:
                    shared = w1 & w2 - {"the", "a", "is", "are", "was", "it"}
                    if len(shared) >= 2:
                        if (wa in w1 and wb in w2) or (wb in w1 and wa in w2):
                            contradictions.append({
                                "type": "internal",
                                "sentence_a": s1[:150],
                                "sentence_b": s2[:150],
                                "pair": (wa, wb),
                            })

        # Contradictions against source material
        if source_text:
            src_sentences = re.split(r"(?<=[.!?])\s+", source_text)
            for resp_sent in sentences:
                rw = set(re.findall(r"\b[a-z]+\b", resp_sent.lower()))
                for src_sent in src_sentences[:50]:
                    sw = set(re.findall(r"\b[a-z]+\b", src_sent.lower()))
                    shared = rw & sw - {"the", "a", "is", "are", "was", "it"}
                    if len(shared) >= 3:
                        for wa, wb in CONTRADICTION_PAIRS:
                            if (wa in rw and wb in sw) or (wb in rw and wa in sw):
                                contradictions.append({
                                    "type": "source_conflict",
                                    "response": resp_sent[:150],
                                    "source": src_sent[:150],
                                    "pair": (wa, wb),
                                })

        score = max(0.0, 1.0 - len(contradictions) * 0.2)
        return score, contradictions


class ConfidenceAnalyser:
    """Subsystem 4: Analyse hedging vs overconfidence language."""

    def analyse(self, text: str) -> float:
        text_lower = text.lower()
        hedging = sum(1 for p in HEDGING_PHRASES if p in text_lower)
        certainty = sum(1 for p in CERTAINTY_PHRASES if p in text_lower)

        # Hedging is good (model is uncertain), overconfidence is bad
        if certainty > 2 and hedging == 0:
            return 0.3  # Overconfident
        elif hedging > 0 and certainty == 0:
            return 0.9  # Appropriately uncertain
        elif hedging > certainty:
            return 0.7
        elif certainty > hedging:
            return 0.4
        else:
            return 0.6  # Neutral


class FactChecker:
    """Subsystem 5: Check claims against a registry of verified facts."""

    def __init__(self):
        self._facts: dict[str, dict[str, Any]] = {}

    def register_fact(self, key: str, value: str, source: str, confidence: float = 0.9) -> None:
        self._facts[key.lower()] = {
            "value": value, "source": source, "confidence": confidence,
        }

    def register_facts_from_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Extract and register facts from retrieved chunks."""
        count = 0
        for chunk in chunks:
            text = chunk.get("text", "")
            meta = chunk.get("metadata", {})
            source = meta.get("source_file", "unknown")

            # Extract key-value facts (simple patterns)
            # Part numbers
            for match in re.finditer(r"\b([A-Z]\w{2,}(?:\d\w*)?)\b", text):
                name = match.group(1)
                if len(name) >= 4 and any(c.isdigit() for c in name):
                    self._facts[name.lower()] = {
                        "value": name, "source": source, "confidence": 0.8,
                    }
                    count += 1

            # Numeric specs
            for match in re.finditer(r"(\d+)\s*(MHz|GHz|KB|MB|GB|V|mA)\b", text):
                key = f"{match.group(1)}{match.group(2)}"
                self._facts[key.lower()] = {
                    "value": key, "source": source, "confidence": 0.85,
                }
                count += 1

        return count

    def check(self, response: str) -> tuple[float, list[str]]:
        """Check response against registered facts. Returns (score, unverified_list)."""
        if not self._facts:
            return 0.5, []

        unverified = []
        verified = 0
        total_checked = 0

        # Check part numbers and specs in response
        for match in re.finditer(r"\b([A-Z]\w{2,}(?:\d\w*)?)\b", response):
            name = match.group(1).lower()
            if len(name) >= 4 and any(c.isdigit() for c in name):
                total_checked += 1
                if name in self._facts:
                    verified += 1
                else:
                    unverified.append(match.group(1))

        if total_checked == 0:
            return 0.7, []

        score = verified / total_checked
        return score, unverified[:10]


class DriftMonitor:
    """Subsystem 6: Monitor response quality drift across a session."""

    def __init__(self):
        self._history: list[dict[str, float]] = []

    def record(self, scores: dict[str, float]) -> None:
        self._history.append({**scores, "timestamp": time.time()})

    def check_drift(self) -> tuple[float, list[dict[str, Any]]]:
        """Check for quality drift. Returns (score, drift_events)."""
        if len(self._history) < 3:
            return 1.0, []

        events = []
        recent = self._history[-3:]
        earlier = self._history[:-3]

        if not earlier:
            return 1.0, []

        # Compare recent average to earlier average
        for metric in ("pattern_score", "consistency_score"):
            recent_avg = sum(r.get(metric, 0) for r in recent) / len(recent)
            earlier_avg = sum(r.get(metric, 0) for r in earlier) / len(earlier)

            if earlier_avg - recent_avg > 0.15:
                events.append({
                    "metric": metric,
                    "earlier_avg": round(earlier_avg, 3),
                    "recent_avg": round(recent_avg, 3),
                    "drop": round(earlier_avg - recent_avg, 3),
                })

        score = max(0.0, 1.0 - len(events) * 0.3)
        return score, events


class AccuracyGrader:
    """Subsystem 7: Final accuracy grade on the full response."""

    def grade(self, overall_score: float) -> str:
        if overall_score >= 0.9:
            return "A"
        elif overall_score >= 0.8:
            return "B"
        elif overall_score >= 0.7:
            return "C"
        elif overall_score >= 0.5:
            return "D"
        else:
            return "F"


# ============================================================
# Orchestrator
# ============================================================

class ResponseValidator:
    """Orchestrator — runs all 7 subsystems on every response."""

    def __init__(self, db: Database, crypto: CryptoEngine | None = None):
        self.db = db
        self.crypto = crypto or CryptoEngine()
        self.pattern_matcher = PatternMatcher()
        self.consistency_checker = ConsistencyChecker()
        self.contradiction_detector = ContradictionDetector()
        self.confidence_analyser = ConfidenceAnalyser()
        self.fact_checker = FactChecker()
        self.drift_monitor = DriftMonitor()
        self.accuracy_grader = AccuracyGrader()

    def validate(
        self,
        response_text: str,
        source_context: str = "",
        source_chunks: list[dict[str, Any]] | None = None,
    ) -> ValidationResult:
        """Run all 7 subsystems and return a validation result."""
        # Precondition: empty / whitespace response cannot be validated
        if not response_text or not response_text.strip():
            result = ValidationResult()
            result.incomplete = True
            result.overall_score = 0.0
            result.status = "INCOMPLETE"
            result.status_reason = "RED — Response Not Generated"
            result.accuracy_grade = "F"
            result.requires_review = True
            result_data = {
                "overall_score": 0.0,
                "status": "INCOMPLETE",
                "grade": "F",
                "timestamp": time.time(),
                "incomplete": True,
            }
            canonical, sig = self.crypto.sign_json(result_data)
            result.signed_hash = CryptoEngine.hash_data(canonical.encode())
            result.signature = sig
            self.db.add_audit_entry(
                "response_validated",
                json.dumps({"status": "INCOMPLETE", "grade": "F", "score": 0.0, "incomplete": True}),
                result.signed_hash,
            )
            logger.warning("Validation: INCOMPLETE — empty response (response not generated)")
            return result

        result = ValidationResult()

        # 1. Pattern matching
        result.pattern_score, result.detections = self.pattern_matcher.scan(response_text)

        # 2. Consistency with source material
        result.consistency_score = self.consistency_checker.check(response_text, source_context)

        # 3. Contradiction detection
        result.contradiction_score, conflicts = self.contradiction_detector.detect(
            response_text, source_context
        )
        result.conflicts = conflicts

        # 4. Confidence/hedging analysis
        result.confidence_score = self.confidence_analyser.analyse(response_text)

        # 5. Fact checking
        if source_chunks:
            self.fact_checker.register_facts_from_chunks(source_chunks)
        result.fact_check_score, result.unverified_claims = self.fact_checker.check(response_text)

        # 6. Drift monitoring
        result.drift_score, result.drift_events = self.drift_monitor.check_drift()

        # Calculate overall score (weighted)
        result.overall_score = (
            result.pattern_score * 0.25 +
            result.consistency_score * 0.25 +
            result.contradiction_score * 0.15 +
            result.confidence_score * 0.10 +
            result.fact_check_score * 0.15 +
            result.drift_score * 0.10
        )

        # 7. Final grade
        result.accuracy_grade = self.accuracy_grader.grade(result.overall_score)

        # Determine status
        if result.overall_score >= 0.7:
            result.status = "GREEN"
            result.requires_review = False
        elif result.overall_score >= 0.4:
            result.status = "AMBER"
            result.requires_review = True
        else:
            result.status = "RED"
            result.requires_review = True

        # Record for drift monitoring
        self.drift_monitor.record({
            "pattern_score": result.pattern_score,
            "consistency_score": result.consistency_score,
            "overall_score": result.overall_score,
        })

        # Sign the result
        result_data = {
            "overall_score": result.overall_score,
            "status": result.status,
            "grade": result.accuracy_grade,
            "timestamp": time.time(),
        }
        canonical, sig = self.crypto.sign_json(result_data)
        result.signed_hash = CryptoEngine.hash_data(canonical.encode())
        result.signature = sig

        # Audit log
        self.db.add_audit_entry(
            "response_validated",
            json.dumps({"status": result.status, "grade": result.accuracy_grade,
                         "score": round(result.overall_score, 3)}),
            result.signed_hash,
        )

        logger.info(
            f"Validation: {result.status} (grade={result.accuracy_grade}, "
            f"score={result.overall_score:.3f}, detections={len(result.detections)})"
        )

        return result
