"""Reading ordinance prose into ``Obligation`` records — Layer 0.

Same Protocol-plus-always-available-default-plus-lazy-real-backend shape
as ``KeySigner``, ``EmailSender``, and ``EntailmentModel``.
``KeywordObligationExtractor`` is the deterministic default the test
suite runs against; ``LlmObligationExtractor`` is the real backend and is
not exercised here, because there is no model wired into this codebase.

## The failure that actually matters

Not a misclassified provision — a **silently dropped** one. If an
extractor reads a night cap and produces nothing, downstream analysis
concludes the ordinance has no frequency rule and reports the city as
compliant. That is worse than reporting the wrong subject, because a
wrong subject is visible and an absent one is not.

So ``ExtractionResult`` separates three outcomes, and the middle one is
the point:

- provisions that were classified
- provisions recognised as **normative but unclassifiable** — deontic
  language present, no subject matched
- text with no normative force, ignored

``unclassified`` is not a diagnostic to be logged and forgotten. A result
carrying any is *incomplete*, and ``is_complete`` says so, because a
caller that treats a partial extraction as a total one has been misled by
its own tooling.

## On what the abstention gate can and cannot tell you

``sample_and_gate`` runs an extractor repeatedly and measures whether it
agrees with itself, reusing ``uncertainty/semantic_entropy.py``. That
detects an unstable extractor. It cannot detect a *confidently wrong*
one: a deterministic extractor is perfectly self-consistent and may be
perfectly wrong, and will score zero entropy every time. Self-consistency
is not correctness, and reading the gate as a correctness signal would
manufacture exactly the false confidence this module is built to avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.models import Bearer, Modality, Obligation, SubjectMatter

# Ordered so that more specific patterns are tried before broader ones.
_SUBJECT_PATTERNS: tuple[tuple[SubjectMatter, str], ...] = (
    (
        SubjectMatter.FREQUENCY,
        (
            r"more than\s+\w+\s+(?:nights?|times?|days?|occasions?)"
            r"|(?:nights?|times?|rentals?)\s+per\s+(?:calendar\s+)?year"
            r"|in any calendar year"
            r"|\bfrequency\b"
        ),
    ),
    (
        SubjectMatter.DURATION,
        (
            r"fewer than\s+\w+\s+consecutive"
            r"|less than\s+\w+\s+consecutive"
            r"|minimum\s+(?:stay|term|rental period|length)"
            r"|at least\s+\w+\s+consecutive"
            r"|term of fewer than"
            r"|\bduration\b"
        ),
    ),
    (SubjectMatter.PROPERTY_VALUATION, r"property valuation|assessed (?:value|above|at)"),
    (SubjectMatter.PRIMARY_RESIDENCE, r"primary residence|owner-?occupied"),
    (SubjectMatter.PERMIT_REGISTRATION, r"\bpermit\b|\blicen[cs]e\b|\bregist(?:er|ration)\b"),
    (SubjectMatter.OCCUPANCY_LIMIT, r"\boccupan(?:cy|ts?)\b|number of (?:guests|occupants)"),
    (SubjectMatter.PARKING, r"\bparking\b|off-street space"),
    (SubjectMatter.NOISE, r"\bnoise\b|quiet hours|\bamplified sound\b"),
    (SubjectMatter.TAXATION, r"\btax(?:es|ation)?\b|transient occupancy"),
    (SubjectMatter.ZONING, r"zoning district|\bzoned\b|residential district"),
    (SubjectMatter.SAFETY_INSPECTION, r"\binspect(?:ion|ed|s)?\b|fire (?:safety|code)|smoke alarm"),
    (SubjectMatter.ADVERTISING_DISCLOSURE, r"\badvertis|\blisting\b|\bposted? in\b"),
    (
        SubjectMatter.SANITATION,
        (
            r"\bsewage\b|\bwastewater\b|\bvermin\b|\bsanitar|\bsanitation\b"
            r"|\bbathroom|\btoilet|\bplumbing\b|\bgarbage\b|\brefuse\b"
            r"|\bfood-?borne\b|\bpotable\b|\bdisinfect|\bfumigat"
            # Linen hygiene lives here rather than in a lodging-specific
            # subject — see SubjectMatter.SANITATION.
            r"|\bpillowslips?\b|\bsheets?\b|\bbedding\b|\blaundered\b|\bmattress"
            r"|\bcontagious\b|\bcommunicable disease\b|\bpublic health risk\b"
        ),
    ),
    (
        SubjectMatter.FIRE_SAFETY,
        (
            r"\bfire (?:safety|code|extinguisher|escape)\b|\bextinguisher"
            r"|\bsmoke (?:alarm|detector)\b|\bcarbon monoxide\b|\bmeans of egress\b|\bexit sign"
        ),
    ),
    (SubjectMatter.FEES, r"\bfees?\b|\bsurcharge\b|\bpenalt(?:y|ies)\b|\bfine(?:s|d)?\b"),
    (SubjectMatter.RULEMAKING, r"\badopt(?:s|ed)? (?:such )?rules?\b|\bby rule\b|\brulemaking\b"),
    (
        SubjectMatter.RECORDKEEPING,
        (
            r"\brecords?\b|\breports?\b|\bshall be submitted\b|\bmaintain a (?:log|register)\b"
            r"|\bfiled with\b|\battest in writing\b|\bprovide .{0,30}documentation\b"
            r"|\bonline (?:account|system)\b"
        ),
    ),
    (
        SubjectMatter.ENFORCEMENT,
        (
            r"\badministrative sanctions?\b|\bstop the sale\b|\bstop-sale\b"
            r"|\brevoke|\bsuspend(?:ed|sion)?\b|\benforce(?:ment|s|d)?\b"
            r"|\blaw enforcement\b|\bproper destruction\b"
        ),
    ),
    (
        SubjectMatter.ADMINISTRATIVE_PROCEDURE,
        (
            r"\bvariance(?:s)?\b|\bappeal(?:s|ed)?\b|\bhearing\b"
            r"|\badvisory council\b|\bnotification may be\b|\bupon request by\b"
        ),
    ),
    (
        SubjectMatter.HABITABILITY,
        (
            r"\bventilat|\blight(?:ed|ing)\b|\bheated\b|\bcooled\b|\bair changes?\b"
            r"|\bwindow opening\b|\bopening to the outside\b"
        ),
    ),
    (
        SubjectMatter.BUILDING_STANDARDS,
        (
            r"\brailings?\b|\bbalcon(?:y|ies)\b|\bstairways?\b|\bplatforms?\b"
            r"|\bconstruction standards?\b|\bFlorida Building Code\b|\bstories in height\b"
        ),
    ),
)

# "The division shall adopt rules" is a duty on the agency, not the
# operator. Without this the provision has no bearer the schema can hold
# and falls out of the analysis entirely — the single largest cause of
# unclassified provisions when measured against real statutory text.
_REGULATOR = re.compile(
    r"\bthe (?:division|department|agency|secretary|commission|board)\b", re.IGNORECASE
)

# A city or town is not an agency. Held-out measurement against A.R.S.
# § 9-500.39 put five of seven unclassified provisions in this class,
# including the statute's headline sentence.
#
# The polity must be the *subject of the modal*, not merely mentioned.
# "Every rental shall register with the city" is a duty on the operator
# that happens to name the city as recipient; anchoring on the bare word
# would reassign it and quietly empty the operator's obligation list.
_SUBORDINATE_LEGISLATURE = re.compile(
    r"^\s*(?:a|the|any)?\s*"
    r"(?:city|town|county|municipality|local government|political subdivision)"
    r"(?:\s+or\s+town)?"
    r"[^.]{0,60}?\b(?:may|shall|must)\b",
    re.IGNORECASE,
)

# Definitional and descriptive text borrows deontic vocabulary without
# imposing a duty: "any facility that may not be classified as a hotel"
# is a definition, not a prohibition. Checked before modality, because
# reading it as normative manufactures obligations that don't exist.
_DEFINITIONAL = re.compile(
    r"\bmay not be classified\b"
    r"|\bas used in this (?:chapter|section|part|code)\b"
    r"|\bfor (?:the )?purposes of this (?:chapter|section|part|code)\b"
    r"|\bas defined in\b"
    r"|\bthe term [\"“]?\w+[\"”]? means\b"
    # Statutory definition sections almost never write "the term". They
    # write the defined phrase in quotes and follow it with "means":
    #
    #     "Critical control point" means a point or procedure ...
    #     "Hazard" means any biological, chemical, or physical property
    #
    # The clause above missed both — it demands the literal words "the
    # term", and \w+ cannot span a multi-word phrase. Definitions then
    # reached the modality check, where borrowed vocabulary ("may cause
    # an unacceptable consumer health risk") read as normative. Sixteen
    # definitions across Maine and Minnesota were being counted as
    # provisions, inflating the coverage denominator with sentences that
    # impose no duty at all.
    r"|[\"“][^\"”]{1,80}[\"”]\s+(?:means\b|has the meaning\b)"
    r"|\bhas the meaning given\b",
    re.IGNORECASE,
)

# A quantitative limit is a limit *on* something. "may not be rented more
# than 90 nights" is a FREQUENCY rule expressed prohibitively — its
# subject is frequency and its modality is prohibition. Only an
# unqualified ban is a PROHIBITION *subject*.
_OUTRIGHT_BAN = re.compile(
    r"\b(?:are|is)\s+prohibited\b"
    r"|\bshall not be (?:permitted|allowed|operated)\b"
    r"|\bmay not (?:be )?(?:operate|be operated|be established)\b"
    r"|\bprohibited in\b"
    # "A city or town may not prohibit vacation rentals" is *about*
    # prohibition — a rule governing whether bans may exist at all.
    # Missing it left the headline provision of an entire preemption
    # statute unclassified.
    r"|\bmay not prohibit\b"
    r"|\bshall not prohibit\b"
    r"|\bmay not (?:restrict|ban)\b",
    re.IGNORECASE,
)

# The leading-negation clause allows a multi-word subject between "No"
# and the modal. An earlier version used `\bno \w+ may\b`, which admits
# exactly one word — so "No dwelling unit may be rented for more than 90
# nights" fell through to the permissive branch and a cap was read as a
# licence. A modality error inverts the provision, which is strictly
# worse than any subject-matter mistake, so this is deliberately broad.
_PROHIBITIVE = re.compile(
    r"\bmay not\b"
    r"|\bshall not\b"
    r"|\b(?:is|are)\s+prohibited\b"
    r"|\bprohibited\b"
    r"|^\s*no\s+.{0,60}?\b(?:may|shall|can)\b",
    re.IGNORECASE,
)
# A *negated* requirement is an exemption, and must be caught before
# both branches below — otherwise the negation is stepped over and the
# provision comes out meaning its own opposite.
#
# Found by measurement, not by reading. Minnesota writes exemptions as
# "Special event food stands are not required to submit plans", and
# `\brequired to\b` matched the tail of it: the engine recorded an
# OBLIGATION to submit plans against a statute that says the opposite.
# "A permit is not required to operate a mobile food unit" came back as
# a duty to obtain a permit.
#
# This is the worst failure this extractor can produce. An unrecognised
# provision is a hole the caller is told about; an inverted one is a
# confident wrong answer that reads exactly like a right one, and a
# compliance officer acting on it would demand a permit the law
# expressly waives. Same family as the leading-negation bug above, and
# the reason both patterns are deliberately broad.
#
# PERMISSION rather than a fourth modality: an exemption is a licence
# not to comply, which is what Modality.PERMISSION already means. The
# negation wins regardless of which modal carries it — "shall not be
# required" is an exemption on the same footing as "is not required",
# so this precedes _PROHIBITIVE too.
_NEGATED_OBLIGATION = re.compile(
    r"\bnot\s+(?:be\s+)?(?:required|obligated|compelled)\b"
    r"|\bneed not\b"
    r"|\b(?:is|are)\s+exempt(?:ed)?\b"
    r"|\b(?:is|are)\s+not\s+subject\s+to\b",
    re.IGNORECASE,
)

_OBLIGATORY = re.compile(
    r"\bshall\b|\bmust\b|\bis required\b|\bare required\b|\brequired to\b", re.IGNORECASE
)

# Statutes state duties in the indicative as readily as the imperative.
# "The fee is due by July 1" binds exactly as hard as "the fee shall be
# paid by July 1", and recognising only modal verbs drops the whole
# class — silently, into ignored_sentences, where it never reaches the
# coverage denominator and so cannot show up as a gap.
#
# Deliberately narrow. Only forms whose deontic force is unambiguous are
# here; "constitutes a separate offense" and "is presumed to be" state
# legal consequences rather than duties, and are left to abstain rather
# than be forced into a modality they don't carry.
_INDICATIVE_OBLIGATION = re.compile(
    r"\b(?:is|are)\s+due\b"
    r"|\b(?:is|are)\s+payable\b"
    r"|\b(?:is|are)\s+subject\s+to\b"
    r"|\b(?:is|are)\s+liable\s+for\b"
    r"|\b(?:is|are)\s+responsible\s+for\b",
    re.IGNORECASE,
)
_PERMISSIVE = re.compile(
    r"\bmay\b|\bis permitted\b|\bare permitted\b|\bis allowed\b", re.IGNORECASE
)

# re.I matters here: real ordinances write "Adopted March 12, 2019" with
# a capital A. Without it the date is silently missed, which turns a
# decidable grandfathering question into UNDETERMINED — a quiet loss of
# an answer the text actually supplied.
_ADOPTED = re.compile(
    r"adopted\s+(?:on\s+)?(\d{4})-(\d{2})-(\d{2})"
    r"|adopted\s+(?:on\s+)?([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


@dataclass(frozen=True)
class UnclassifiedProvision:
    """Normative language with no subject this extractor recognises.

    Surfaced rather than dropped: an ordinance section the extractor
    cannot read is a hole in the analysis, and the analysis has to know
    it has one."""

    text: str
    reason: str


@dataclass(frozen=True)
class ExtractionResult:
    obligations: tuple[Obligation, ...]
    unclassified: tuple[UnclassifiedProvision, ...] = field(default_factory=tuple)
    ignored_sentences: int = 0

    @property
    def is_complete(self) -> bool:
        """False when any normative provision went unclassified. A
        caller must not treat a partial extraction as a total one."""
        return not self.unclassified

    def canonical_form(self) -> str:
        """A stable string summary, used to compare two extractions of
        the same text for agreement. Deliberately structural — subjects
        and modality only — because that is what downstream doctrine
        reads. Two extractions that differ only in prose are the same
        extraction for every purpose that matters here."""
        parts = sorted(
            f"{o.bearer.value}/{o.modality.value}:"
            f"{'+'.join(sorted(s.value for s in o.subjects))}"
            for o in self.obligations
        )
        return " | ".join(parts) if parts else "(none)"


class ObligationExtractor(Protocol):
    def extract(
        self,
        text: str,
        citation: str,
        jurisdiction_tier: JurisdictionTier,
        jurisdiction_path: tuple[str, ...],
    ) -> ExtractionResult: ...


class KeywordObligationExtractor:
    """Deterministic pattern matching. The always-available default.

    Genuinely useful as a floor for this domain — short-term-rental
    ordinances use a small, repetitive vocabulary — and genuinely limited:
    it reads surface forms, so a provision phrased unusually becomes an
    ``UnclassifiedProvision`` rather than a wrong answer. That is the
    intended direction of failure.
    """

    def extract(
        self,
        text: str,
        citation: str,
        jurisdiction_tier: JurisdictionTier,
        jurisdiction_path: tuple[str, ...],
    ) -> ExtractionResult:
        adopted = _find_adopted_date(text)
        obligations: list[Obligation] = []
        unclassified: list[UnclassifiedProvision] = []
        ignored = 0

        for sentence in _sentences(text):
            if _DEFINITIONAL.search(sentence):
                ignored += 1
                continue
            modality = _classify_modality(sentence)
            if modality is None:
                ignored += 1
                continue

            subjects = _classify_subjects(sentence)
            if not subjects:
                unclassified.append(
                    UnclassifiedProvision(
                        text=sentence,
                        reason=(
                            "normative language present but no recognised subject matter — "
                            "this provision is not represented in the analysis"
                        ),
                    )
                )
                continue

            obligations.append(
                Obligation(
                    citation=citation,
                    jurisdiction_tier=jurisdiction_tier,
                    jurisdiction_path=jurisdiction_path,
                    subjects=frozenset(subjects),
                    modality=modality,
                    bearer=_classify_bearer(sentence),
                    text=sentence,
                    adopted_date=adopted,
                )
            )

        return ExtractionResult(
            obligations=tuple(obligations),
            unclassified=tuple(unclassified),
            ignored_sentences=ignored,
        )


class LlmObligationExtractor:
    """Real backend: an LLM constrained to emit the ``Obligation`` schema.

    Not exercised anywhere — no model is wired into this codebase, and
    there is no API key or local checkpoint to reach. Same honesty
    category as ``SmtpEmailSender`` and the KMS/Vault signers: the
    dispatch shape is real, the round trip is not verified.

    ``client`` is an injected seam so the prompt assembly and response
    parsing are testable against a stub, matching how every other real
    backend here is built.
    """

    def __init__(self, model: str, client: Any = None) -> None:
        self._model = model
        self._client = client

    def extract(
        self,
        text: str,
        citation: str,
        jurisdiction_tier: JurisdictionTier,
        jurisdiction_path: tuple[str, ...],
    ) -> ExtractionResult:
        if self._client is None:
            raise NotImplementedError(
                "LlmObligationExtractor needs an injected client; no model is configured "
                "in this environment. Use KeywordObligationExtractor, or supply a client "
                "implementing .extract_obligations(text, schema)."
            )
        raw = self._client.extract_obligations(text=text, schema=_OBLIGATION_SCHEMA)
        return _result_from_payload(raw, citation, jurisdiction_tier, jurisdiction_path)


def sample_and_gate(
    extractor: ObligationExtractor,
    text: str,
    citation: str,
    jurisdiction_tier: JurisdictionTier,
    jurisdiction_path: tuple[str, ...],
    samples: int = 5,
    entropy_threshold: float = 0.5,
) -> tuple[ExtractionResult, bool]:
    """Runs the extractor repeatedly and reports whether it agreed with
    itself, returning ``(most_common_result, agreed)``.

    Clustering is by exact match on ``canonical_form`` rather than by
    entailment: these are structured records, so two extractions either
    describe the same subjects and modalities or they don't. Entailment
    scoring exists for prose, and applying it here would add fuzziness to
    a comparison that is genuinely exact.

    Reuses ``SemanticEntropyGate`` for the threshold arithmetic, which
    means the same guarantee applies — a threshold at or above log(N)
    cannot fire and is rejected at construction.

    Reading the result correctly matters: ``agreed=True`` means *stable*,
    not *right*. A deterministic extractor always agrees with itself.
    """
    from legal_engine.uncertainty.entailment import LexicalEntailmentModel
    from legal_engine.uncertainty.semantic_entropy import SemanticEntropyGate

    results = [
        extractor.extract(text, citation, jurisdiction_tier, jurisdiction_path)
        for _ in range(samples)
    ]
    gate = SemanticEntropyGate(
        model=LexicalEntailmentModel(),
        n_samples=samples,
        entropy_threshold=entropy_threshold,
        entailment_threshold=1.0,  # exact structural agreement
    )
    verdict = gate.evaluate([r.canonical_form() for r in results])

    largest = max(verdict.clusters, key=len)
    winner = next(r for r in results if r.canonical_form() == largest[0])
    return winner, verdict.triage_pass


_OBLIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "modality": {"type": "string", "enum": [m.value for m in Modality]},
                    "bearer": {"type": "string", "enum": [b.value for b in Bearer]},
                    "subjects": {
                        "type": "array",
                        "items": {"type": "string", "enum": [s.value for s in SubjectMatter]},
                        "minItems": 1,
                    },
                },
                "required": ["text", "modality", "subjects"],
            },
        },
        "unclassified": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["obligations"],
}


def _result_from_payload(
    payload: dict[str, Any],
    citation: str,
    tier: JurisdictionTier,
    path: tuple[str, ...],
) -> ExtractionResult:
    obligations = tuple(
        Obligation(
            citation=citation,
            jurisdiction_tier=tier,
            jurisdiction_path=path,
            subjects=frozenset(SubjectMatter(s) for s in item["subjects"]),
            modality=Modality(item["modality"]),
            bearer=Bearer(item.get("bearer", Bearer.REGULATED_PARTY.value)),
            text=item["text"],
        )
        for item in payload.get("obligations", [])
    )
    unclassified = tuple(
        UnclassifiedProvision(text=t, reason="model could not classify")
        for t in payload.get("unclassified", [])
    )
    return ExtractionResult(obligations=obligations, unclassified=unclassified)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _classify_modality(sentence: str) -> Modality | None:
    # Order is meaning here, not style. Each branch below contains the
    # next one's trigger as a substring, so a later check firing first
    # would invert the provision:
    #
    #   "are not required to submit"  contains  "required to"
    #   "shall not be operated"       contains  "shall"
    #
    # Negation is therefore checked outermost-first.
    if _NEGATED_OBLIGATION.search(sentence):
        return Modality.PERMISSION
    if _PROHIBITIVE.search(sentence):
        return Modality.PROHIBITION
    if _OBLIGATORY.search(sentence):
        return Modality.OBLIGATION
    if _INDICATIVE_OBLIGATION.search(sentence):
        return Modality.OBLIGATION
    if _PERMISSIVE.search(sentence):
        return Modality.PERMISSION
    return None


def _classify_bearer(sentence: str) -> Bearer:
    """Regulator duties are recognised explicitly; everything else is
    assumed to bind the regulated party, which is the reading that makes
    an unattributed "shall provide parking" mean what it obviously
    means."""
    if _SUBORDINATE_LEGISLATURE.search(sentence):
        return Bearer.SUBORDINATE_LEGISLATURE
    if _REGULATOR.search(sentence):
        return Bearer.REGULATOR
    return Bearer.REGULATED_PARTY


def _classify_subjects(sentence: str) -> set[SubjectMatter]:
    found = {
        subject for subject, pattern in _SUBJECT_PATTERNS if re.search(pattern, sentence, re.IGNORECASE)
    }
    # An outright ban only counts as a PROHIBITION *subject* when nothing
    # quantitative is being limited — otherwise the ban is the modality
    # and the quantity is the subject.
    if _OUTRIGHT_BAN.search(sentence) and not (
        found & {SubjectMatter.FREQUENCY, SubjectMatter.DURATION}
    ):
        found.add(SubjectMatter.PROHIBITION)
    return found


def _find_adopted_date(text: str) -> date | None:
    match = _ADOPTED.search(text)
    if not match:
        return None
    if match.group(1):
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    month = _MONTHS.get(match.group(4).capitalize(), 0)
    if not month:
        return None
    return date(int(match.group(6)), month, int(match.group(5)))
