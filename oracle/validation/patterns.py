"""Hallucination detection patterns — ported from M40."""

# (id, name, category, severity, regex, description)
HALLUCINATION_PATTERNS = [
    # Fake URLs
    ("URL-001", "nonexistent_tld", "fake_url", "high",
     r"https?://[a-z0-9.-]+\.(internal|example|test|invalid|localhost)\b",
     "URL with non-routable TLD"),
    ("URL-002", "suspicious_arxiv", "fake_url", "high",
     r"arxiv\.org/abs/\d{4}\.\d{6,}",
     "Potentially fabricated arXiv ID"),
    ("URL-003", "fake_doi", "fake_url", "high",
     r"doi\.org/10\.\d{4,}/[a-z]{10,}",
     "Potentially fabricated DOI"),
    ("URL-004", "fake_rfc", "fake_url", "medium",
     r"RFC\s*\d{5,}",
     "Potentially fake RFC number"),

    # Fake Citations
    ("CIT-001", "et_al_fabrication", "fake_citation", "high",
     r"\b[A-Z][a-z]+\s+et\s+al\.\s*\(\d{4}\)",
     "Author et al. citation — verify exists"),
    ("CIT-002", "journal_fabrication", "fake_citation", "high",
     r"(?:Journal|Proceedings)\s+of\s+(?:Advanced|International|Modern)\s+\w+",
     "Potentially fabricated journal name"),
    ("CIT-003", "future_citation", "fake_citation", "critical",
     r"\b[A-Z][a-z]+\s+et\s+al\.\s*\(20[3-9]\d\)",
     "Citation from the future"),

    # Fake Statistics
    ("STAT-001", "precise_percentage", "fake_stat", "medium",
     r"\b\d{2}\.\d{2,}%\b",
     "Overly precise percentage"),
    ("STAT-002", "studies_show", "fake_stat", "high",
     r"\b(?:studies|research)\s+(?:show|indicate|suggest)\s+that\s+\d",
     "Unsourced studies claim"),
    ("STAT-003", "billion_dollar", "fake_stat", "medium",
     r"\$\d+(?:\.\d+)?\s*(?:billion|trillion)\b",
     "Specific dollar figure"),

    # Fake Entities
    ("ENT-001", "fake_org", "fake_entity", "high",
     r"(?:The\s+)?(?:International|Global|World)\s+(?:Institute|Association|Council)\s+(?:of|for)\s+\w+",
     "Potentially fabricated organisation"),
    ("ENT-002", "fake_professor", "fake_entity", "high",
     r"(?:Dr|Professor|Prof)\.\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:of|at)\s+(?:the\s+)?University",
     "Named professor — verify exists"),

    # Fabrication indicators (hardware context)
    ("HW-001", "invented_part_number", "fabrication", "high",
     r"\b[A-Z]{2,4}\d{6,}\w*\b",
     "Very long part number — may be fabricated"),
    ("HW-002", "fake_standard", "fabrication", "high",
     r"\b(?:IEEE|ISO|IEC|MIL-STD)\s+\d{6,}",
     "Potentially fabricated standard number"),
    ("HW-003", "verbatim_quote", "fabrication", "high",
     r'(?:said|stated|wrote),?\s*"[A-Z][^"]{50,}"',
     "Long verbatim quote — likely fabricated"),
    ("HW-004", "specific_date_person", "fabrication", "medium",
     r"(?:In|in)\s+\d{4},\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:invented|discovered|developed)",
     "Historical claim with named person"),
]

SEVERITY_WEIGHTS = {
    "critical": 1.0,
    "high": 0.7,
    "medium": 0.4,
    "low": 0.2,
}

# Contradiction word pairs
CONTRADICTION_PAIRS = [
    ("supports", "lacks"), ("has", "missing"), ("includes", "excludes"),
    ("enabled", "disabled"), ("active", "inactive"), ("present", "absent"),
    ("connected", "disconnected"), ("available", "unavailable"),
    ("compatible", "incompatible"), ("required", "optional"),
    ("always", "never"), ("all", "none"),
]

# Hedging language (indicates model uncertainty — lower hallucination risk)
HEDGING_PHRASES = [
    "it appears", "it seems", "possibly", "potentially", "likely",
    "may be", "might be", "could be", "approximately", "roughly",
    "I'm not certain", "based on available", "cannot confirm",
]

# Overconfidence language (higher hallucination risk)
CERTAINTY_PHRASES = [
    "definitely", "certainly", "absolutely", "without doubt",
    "guaranteed", "proven", "confirmed", "undeniably",
    "it is clear that", "there is no question",
]
