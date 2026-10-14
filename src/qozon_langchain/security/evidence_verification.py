"""Conservative local support checks, not semantic entailment or factual truth.

Release complete source sentences with local citations. Unsupported paraphrases
are withheld. Simple conflicting counts are held or replaced with a canonical
disclosure quoting both passages. Image pixels are not verified by this module.
"""

from dataclasses import dataclass, field
import re
import unicodedata


POLICY_VERSION = "extractive-v2"
CITATION = re.compile(r"\[S([0-9]+)\]")
GROUP = re.compile(r"\[S[0-9]+\](?:\s*\[S[0-9]+\])*")
PAGE = re.compile(r"\bphysical\s+pages?\s+(\d+(?:\s*[-–,]\s*\d+)*)", re.I)
NUMBERS = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(), range(21)))
COUNT = re.compile(
    r"\bthe\s+(?:same\s+)?(?P<subject>[a-z][a-z -]{0,80}?)\s+"
    r"(?P<verb>contains|holds|has|includes)\s+"
    r"(?P<number>\d+|" + "|".join(NUMBERS) + r")\s+(?P<object>[a-z][a-z -]{0,60})[.!?]?$",
    re.I,
)
UNCERTAINTY = {
    "i cannot determine which count is correct",
    "i cannot determine the answer from the supplied evidence",
    "i could not find sufficient evidence in the indexed book to answer this question",
}


class EvidenceVerificationError(Exception):
    """Fixed identifiers only; never include a passage or generated answer."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedAnswer:
    text: str = field(repr=False)
    cited: tuple[int, ...]
    mode: str


def normalized(text):
    # Keep internal punctuation, numbers, negation and word order intact.
    return " ".join(unicodedata.normalize("NFC", text).casefold().split()).strip().rstrip(".")


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def source_sentences(text):
    return {normalized(s) for s in sentences(text)}


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


def claim_sentences(text):
    text = re.sub(r"^[.,;:](?:\s+|$)", "", text.strip()).strip()
    # Only narrowly defined reporting/page wrappers are removable.
    text = re.sub(r"^(?:according to the (?:book|source)|the (?:book|source) states)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"^on physical pages?\s+\d+(?:\s*[-–,]\s*\d+)*\s*,\s*", "", text, flags=re.I)
    # A standalone privacy annotation has no factual value. Keep placeholders
    # inside sentences intact: removing one must not manufacture a source match.
    if re.fullmatch(r"(?:Email:\s*)?\[REDACTED_[A-Z_]+\][.!?]?", text):
        return []
    return [normalized(s) for s in sentences(text) if normalized(s)]


def verify_evidence(answer, evidence):
    """Return a supported extractive answer or raise a safe withholding code.

    Each citation group supports only the preceding claim, never the whole answer.
    Complete sentences must match; a substring/word-overlap is insufficient.
    Bounds keep the local operation predictable and fail closed on larger inputs.
    """
    if not isinstance(answer, str) or len(answer) > 16_000 or not 0 < len(evidence) <= 12:
        raise EvidenceVerificationError("evidence_verification_limit")
    if (any(not isinstance(item.text, str) for item in evidence)
            or sum(len(item.text) for item in evidence) > 100_000 or len(GROUP.findall(answer)) > 64):
        raise EvidenceVerificationError("evidence_verification_limit")
    cited = tuple(sorted({int(n) for n in CITATION.findall(answer)}))
    if not cited or any(n < 1 or n > len(evidence) for n in cited):
        raise EvidenceVerificationError("invalid_source_citation")
    # Reject malformed marker variants rather than quietly overlooking them.
    without_markers = CITATION.sub("", answer)
    if re.search(r"\[\s*[sS]\s*\d", without_markers):
        raise EvidenceVerificationError("invalid_source_citation")
    conflicts = count_conflicts(evidence) + negation_conflicts(evidence)
    if conflicts:
        involved = {n for conflict in conflicts for _, n, _ in conflict}
        check_pages(answer, [evidence[n - 1] for n in cited])
        if (not involved.issubset(cited) or not re.search(r"\bconflict\w*\b", answer, re.I)
                or not re.search(r"\b(?:cannot determine|uncertain|insufficient evidence)\b", answer, re.I)):
            raise EvidenceVerificationError("evidence_conflict")
        # Do not trust other generated prose in a conflict reply. Replace it with
        # deterministic quotations and uncertainty, then let the output gate check it.
        quotes = list(dict.fromkeys((n, s) for conflict in conflicts for _, n, s in conflict))
        text = "The sources contain potentially conflicting passages:\n" + "\n".join(
            f'"{sentence}" [S{n}]' for n, sentence in quotes
        ) + "\nI cannot determine the answer from the supplied evidence."
        return VerifiedAnswer(text, tuple(sorted(involved)), "conflict_disclosure")

    # A pure, fixed uncertainty statement is safe; citations do not make it a
    # factual assertion about the book. Do not exempt mixed claims/refusals.
    if all(claim in UNCERTAINTY for claim in claim_sentences(without_markers)) and claim_sentences(without_markers):
        return VerifiedAnswer("I could not find sufficient evidence in the indexed book to answer this question.", (), "abstention")
    available_by_id = {n: source_sentences(evidence[n - 1].text) for n in cited}
    cursor = 0
    supported = 0
    for group in GROUP.finditer(answer):
        ids = {int(n) for n in CITATION.findall(group[0])}
        segment = answer[cursor:group.start()]
        check_pages(segment, [evidence[n - 1] for n in ids])
        available = set().union(*(available_by_id[n] for n in ids))
        claims = claim_sentences(segment)
        if not claims or any(claim not in available for claim in claims):
            raise EvidenceVerificationError("unsupported_answer")
        if any(not available_by_id[n].intersection(claims) for n in ids):
            raise EvidenceVerificationError("unsupported_answer")
        supported += len(claims)
        cursor = group.end()
    tail = claim_sentences(answer[cursor:])
    if any(claim not in UNCERTAINTY for claim in tail) or not supported:
        raise EvidenceVerificationError("unsupported_answer")
    return VerifiedAnswer(answer, cited, "extractive_support")
