"""Page-reference checks and narrow conflict patterns on retrieved source text.

No extractive answer matcher, semantic answer judge or evaluation framework.
Image pixels and factual truth are not verified by these helpers.
"""

import re
import unicodedata


PAGE = re.compile(r"\bphysical\s+pages?\s+(\d+(?:\s*[-–,]\s*\d+)*)", re.I)
NUMBERS = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(), range(21)))
COUNT = re.compile(
    r"\bthe\s+(?:same\s+)?(?P<subject>[a-z][a-z -]{0,80}?)\s+"
    r"(?P<verb>contains|holds|has|includes)\s+"
    r"(?P<number>\d+|" + "|".join(NUMBERS) + r")\s+(?P<object>[a-z][a-z -]{0,60})[.!?]?$",
    re.I,
)


class EvidenceVerificationError(Exception):
    """Fixed identifiers only; never include a passage or generated answer."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def normalized(text):
    # Keep internal punctuation, numbers, negation and word order intact.
    return " ".join(unicodedata.normalize("NFC", text).casefold().split()).strip().rstrip(".")


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def count_conflicts(evidence):
    """Detect same explicit subject/predicate/object with different simple counts.

    This covers a bounded English pattern, not arbitrary contradictions. Temporal
    and other qualifiers can be ambiguous, so a hit requires disclosure/review.
    """
    facts = {}
    for n, item in enumerate(evidence, 1):
        for sentence in sentences(item.text):
            match = COUNT.search(sentence)
            if not match or re.search(r"\b(?:not|never|no)\b", sentence, re.I):
                continue
            key = tuple(normalized(match[k]) for k in ("subject", "verb", "object"))
            raw = match["number"].casefold()
            value = int(raw) if raw.isdigit() else NUMBERS[raw]
            facts.setdefault(key, []).append((value, n, sentence))
    return [facts[key] for key in facts if len({v for v, _, _ in facts[key]}) > 1]


def negation_conflicts(evidence):
    """Also hold exact sentence pairs differing only by explicit 'not'."""
    facts = {}
    for n, item in enumerate(evidence, 1):
        for sentence in sentences(item.text):
            value = normalized(sentence)
            if not re.search(r"\b(?:is|are|was|were|does|do|did|can|will)\b", value):
                continue
            key = re.sub(r"\bnot\s+", "", value)
            facts.setdefault(key, []).append((bool(re.search(r"\bnot\b", value)), n, sentence))
    return [facts[key] for key in facts if len({v for v, _, _ in facts[key]}) > 1]


def check_pages(text, items):
    canonical = {p for item in items for p in item.page_numbers}
    for match in PAGE.finditer(text):
        pages = set()
        for part in match[1].split(","):
            bounds = re.split(r"[-–]", part)
            first = int(bounds[0])
            last = int(bounds[-1])
            if first > last or last - first > 1000:
                raise EvidenceVerificationError("invalid_source_page")
            pages.update(range(first, last + 1))
        if not pages.issubset(canonical):
            raise EvidenceVerificationError("invalid_source_page")
