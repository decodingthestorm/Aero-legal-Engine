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
from enum import Enum
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
    # Plurals, and the verb/noun collision.
    #
    # `\bpermit\b` and `\blicen[cs]e\b` missed "permits", "licenses" and
    # "licensure" — the forms statutes actually use most ("Licenses
    # issued must be displayed", "Initial and renewal licenses"). The
    # taxonomy's single most central subject was missing its own plural.
    #
    # The lookbehinds guard the other direction. "Operators shall not
    # permit occupancy above eight persons" is the verb *to permit*, and
    # tagging it PERMIT_REGISTRATION is not a cosmetic error: subjects
    # feed express_preemption's scope test, so a spurious subject can
    # make a rule appear inside a reserved scope it has nothing to do
    # with, and void an ordinance on a preemption that never touched it.
    (
        SubjectMatter.PERMIT_REGISTRATION,
        (
            r"(?<!not )(?<!shall )(?<!may )(?<!must )(?<!to )\bpermits?\b"
            r"|\blicen[cs]\w*\b"
            r"|\bregist(?:er|ers|ration|rations)\b"
        ),
    ),
    (SubjectMatter.OCCUPANCY_LIMIT, r"\boccupan(?:cy|ts?)\b|number of (?:guests|occupants)"),
    (SubjectMatter.PARKING, r"\bparking\b|off-street space"),
    (SubjectMatter.NOISE, r"\bnoise\b|quiet hours|\bamplified sound\b"),
    (SubjectMatter.TAXATION, r"\btax(?:es|ation)?\b|transient occupancy"),
    (SubjectMatter.ZONING, r"zoning district|\bzoned\b|residential district"),
    # `\binspect(?:ion|ed|s)?\b` could not match "inspections" — the
    # alternation ends before the plural s and \b then fails. Statutes
    # overwhelmingly use the plural: "for the purpose of conducting
    # inspections", "the frequency of inspections". "reinspection" missed
    # for the same reason.
    (
        SubjectMatter.SAFETY_INSPECTION,
        r"\b(?:re)?inspect\w*\b|fire (?:safety|code)|smoke alarm",
    ),
    (SubjectMatter.ADVERTISING_DISCLOSURE, r"\badvertis|\blisting\b|\bposted? in\b"),
    (
        SubjectMatter.SANITATION,
        (
            r"\bsewage\b|\bwastewater\b|\bvermin\b|\bsanitar|\bsanitation\b"
            r"|\bbathroom|\btoilet|\bplumbing\b|\bgarbage\b|\brefuse\b"
            r"|\bfood-?borne\b|\bpotable\b|\bdisinfect|\bfumigat"
            # Linen hygiene lives here rather than in a lodging-specific
            # subject — see SubjectMatter.SANITATION. The docstring said
            # so from the start and the pattern did not: "linen" and
            # "towel" were absent, so Virginia's "the provision, storage,
            # and cleansing of linens and towels" (Va. Code § 35.1-13)
            # found no subject at all while "sheets" would have.
            r"|\bpillowslips?\b|\bsheets?\b|\bbedding\b|\blaundered\b|\bmattress"
            r"|\blinens?\b|\btowels?\b|\bhousekeeping\b"
            # "communicable disease" but not "communicable diseases" —
            # the plural defect again, in the one phrase that carries
            # this subject in Va. Code § 35.1-14.
            r"|\bcontagious\b|\bcommunicable diseases?\b|\bpublic health risk\b"
            # "vermin" was here and "pest" and "vector" were not, so
            # "procedures for vector and pest control" — the standard
            # phrasing in both Virginia sections that use it — matched
            # nothing. Likewise "potable" without "drinking water" or
            # "water supply".
            r"|\bpests?\b|\bvectors?\b|\bpest control\b"
            r"|\bdrinking water\b|\bwater suppl(?:y|ies)\b"
        ),
    ),
    (
        SubjectMatter.FOOD_HANDLING,
        (
            r"\bfood (?:preparation|handling|safety|service|protection|storage"
            r"|allergy|code|temperature)\b"
            r"|\bhandling of food\b|\bpreparation of food\b|\bpreservation of food\b"
            r"|\brefrigerat\w*\b|\bperishable\b|\bfood-?borne\b"
            r"|\bunfit for human consumption\b|\bfit for human consumption\b"
            r"|\bpersonal hygiene\b|\bfood establishment\b|\butensils?\b"
        ),
    ),
    (
        SubjectMatter.RECREATIONAL_WATER,
        # Qualified rather than a bare "pool", which would fire on
        # "pool of applicants" and similar. Every form below is the
        # statutory usage in at least one of the four states that name
        # this as a regulated facility class.
        (
            r"\b(?:swimming|public|wading|bathing|spa)\s+pools?\b"
            r"|\bpools?\s+(?:and|or)\s+spas?\b|\bpublic spas?\b"
            r"|\bsaunas?\b|\bhot tubs?\b|\bwhirlpools?\b"
            r"|\brecreation(?:al)?\s+water\b"
        ),
    ),
    (
        SubjectMatter.FIRE_SAFETY,
        (
            r"\bfire (?:safety|code|extinguisher|escape)\b|\bextinguisher"
            # "Rules establishing fire and life safety requirements" —
            # the conjunction splits "fire" from "safety", so the clause
            # above cannot reach it. The statutory phrase of art is
            # "life safety", and it travels on its own.
            r"|\blife safety\b|\bfire and life safety\b"
            r"|\bsmoke (?:alarm|detector)\b|\bcarbon monoxide\b|\bmeans of egress\b|\bexit sign"
        ),
    ),
    (SubjectMatter.FEES, r"\bfees?\b|\bsurcharge\b|\bpenalt(?:y|ies)\b|\bfine(?:s|d)?\b"),
    (
        SubjectMatter.RULEMAKING,
        # Two blind spots, and the second was the larger defect in this
        # whole taxonomy.
        #
        # First: the active form only. Statutes state the same power in
        # the passive at least as often — "All rules and amendments
        # thereto shall be adopted in conformance with chapter 34.05
        # RCW" — where "rules" and "adopted" are split by the auxiliary.
        #
        # Second: **"rules" but never "regulation"**. The word was
        # learned from Maine and Minnesota and the synonym never was.
        # Virginia writes "regulation" throughout — Va. Code Title 35.1
        # chapter 2 is titled *Regulations* — so essentially every
        # rulemaking provision in the state went unclassified, which is
        # a large part of why Virginia measured a third below Vermont on
        # the same kind of text. A vocabulary gap, not a concept gap:
        # the taxonomy had the right subject and only one of its names.
        (
            r"\badopt(?:s|ed|ing)?\s+(?:such\s+|a\s+|any\s+|final\s+)*"
            r"(?:rules?|regulations?)\b"
            r"|\bby (?:rule|regulation)\b|\brulemaking\b"
            r"|\b(?:rules?|regulations?)\b[^.]{0,40}?\b(?:shall|must|may)\s+be\s+adopted\b"
            r"|\b(?:repeal|amend)(?:s|ed|ing)?\s+(?:any\s+)?(?:rule|regulation)s?\b"
            r"|\bregulations?\s+(?:of|adopted by|promulgated by)\s+the\b"
            r"|\bpromulgat\w*\b"
        ),
    ),
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
            # "suspension" never matched: \bsuspend(?:ed|sion)?\b spells
            # "suspendsion". "revocation" missed for the same reason —
            # the noun forms of the two central enforcement powers.
            r"|\brevok\w*\b|\brevocation\b|\bsuspend\w*\b|\bsuspension\b"
            r"|\benforce\w*\b|\blaw enforcement\b|\bproper destruction\b"
            # No subject owned "violation" or "offense" at all, which
            # left the operative sentence of most penalty sections
            # unclassified: "Each day that the violation remains
            # uncorrected may be counted as a separate offense."
            r"|\bviolations?\b|\boffen[cs]es?\b"
            r"|\benjoin\w*\b|\binjunctive?\b|\bcease and desist\b"
        ),
    ),
    (
        SubjectMatter.ADMINISTRATIVE_PROCEDURE,
        (
            r"\bvariance(?:s)?\b|\bappeal(?:s|ed)?\b|\bhearings?\b"
            r"|\badvisory council\b|\bnotification may be\b|\bupon request by\b"
            # The generic APA cross-reference: "All such proceedings
            # shall be governed by the provisions of chapter 34.05 RCW."
            # Every state has one, and it is the hinge that makes an
            # agency decision reviewable.
            # Virginia calls its APA the Administrative *Process* Act,
            # and states the hearing right as a right "to be heard" or
            # "to show cause" rather than by naming a hearing.
            r"|\bproceedings?\b|\badministrative (?:procedure|process) act\b"
            r"|\bto be heard\b|\bshow cause\b|\bvacated or amended\b"
        ),
    ),
    (
        SubjectMatter.REGULATORY_AUTHORITY,
        (
            r"\bpowers and duties\b|\bhereby granted\b|\bshall have and exercise\b"
            r"|\bdelegat(?:e|es|ed|ion)\b|\bsupplant\b"
            r"|\bauthorized to administer\b|\benabling\b"
            r"|\bjurisdiction (?:of|over)\b"
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
    # Three drafting conventions for the same construct, found one state
    # at a time. Maine and Minnesota write `"Hazard" means ...`;
    # Washington writes `The term "person" shall mean ...`. Each variant
    # missed put a whole definitions section into the coverage
    # denominator as normative text — five of nine abstentions in RCW
    # ch. 70.62 were this single form.
    r"|\bthe term\b[^.]{0,60}?\b(?:shall\s+mean|means)\b"
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
    r"|[\"“][^\"”]{1,80}[\"”]\s+(?:shall\s+mean|means|has the meaning)\b"
    # The short-title clause, which nearly every act carries: "This
    # chapter may be cited as the Example Act." The bare "may" read as a
    # permission, so every statute picked up one spurious abstention from
    # boilerplate that grants nobody anything.
    r"|\bmay be cited as\b"
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
# The lookahead separates the modal "may" from the month "May". Vermont
# closes each section with its amendment history — "(Amended 2007, No.
# 38, § 8a, eff. May 21, 2007; 2017, No. 76, § 5.)" — and case-insensitive
# \bmay\b matched the date, turning citation boilerplate into a
# PERMISSION with no subject. Two of nine abstentions in 18 V.S.A. ch. 85
# were this, inflating the coverage denominator with text that is not
# part of the statute at all.
_PERMISSIVE = re.compile(
    r"\bmay\b(?!\s+\d)|\bis permitted\b|\bare permitted\b|\bis allowed\b", re.IGNORECASE
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


# A provision cut off mid-clause, where the enumerated limbs that carry
# its content were split away into separate sentences:
#
#     "A person, corporation, firm or copartnership may not: A."
#
# Exactly two of twenty-eight abstentions across the held-out regulatory
# set, with no false positives — the whole reason this is a pattern and
# not a length heuristic. Sentence length was tested as a signal for the
# related table-merge defect and rejected: 18% of *correctly classified*
# obligations run past 400 characters, so a length rule would flag
# eleven good extractions to catch one bad one.
_TRUNCATED = re.compile(r":\s*(?:\([a-z0-9]+\)|[A-Z])?\.?\s*$")


class AbstentionReason(str, Enum):
    """Why a provision could not be classified.

    One undifferentiated reason string is not a worklist. Every one of
    the twenty-eight abstentions in the held-out regulatory set carried
    identical text, which told a reader *that* the extractor failed and
    never *how* — and the two failures point in opposite directions:

    * ``NO_SUBJECT_MATCH`` means the taxonomy is short a subject. The
      text was read correctly and there is nowhere to put it.
    * ``TRUNCATED_FRAGMENT`` means the sentence splitter cut a provision
      apart. The taxonomy is fine; adding subjects would not help and
      would dilute every other measurement.

    Acting on the first when it was really the second is how a coverage
    number gets improved without the analysis getting better.
    """

    NO_SUBJECT_MATCH = "no_subject_match"
    TRUNCATED_FRAGMENT = "truncated_fragment"
    MODEL_DECLINED = "model_declined"

    UNGROUNDED = "ungrounded"
    """A backend returned an obligation whose text is not in the source.

    The failure this whole codebase is built against, in its sharpest
    form. A generative backend that invents a provision produces a
    well-formed, confidently-worded obligation for a rule that does not
    exist — indistinguishable in the output from one that does, and
    worse than any inversion, because an inverted provision is at least
    traceable to real text. A fabricated one is not law at all.

    So a returned obligation is checked against the source before it is
    believed, and one that cannot be found there is downgraded to an
    abstention rather than dropped or accepted. Downgraded rather than
    dropped because the caller needs to know the backend is fabricating."""

    MALFORMED = "malformed"
    """The backend's output could not be read as an obligation — a
    missing field, or a subject or modality outside the schema.

    Fails closed into an abstention rather than raising, because one bad
    item in a response should not discard the rest of it, and because a
    model naming a subject this taxonomy does not have is information
    about a gap rather than a crash."""


@dataclass(frozen=True)
class UnclassifiedProvision:
    """Normative language this extractor could not place.

    Surfaced rather than dropped: an ordinance section the extractor
    cannot read is a hole in the analysis, and the analysis has to know
    it has one."""

    text: str
    reason: str
    code: AbstentionReason = AbstentionReason.NO_SUBJECT_MATCH


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

    @property
    def coverage(self) -> float:
        """Share of recognised normative provisions that were classified.

        Read the denominator carefully: it counts provisions this
        extractor recognised as normative, not provisions in the
        document. Text whose deontic force it cannot see at all never
        enters either term, so this is an upper bound on how much of a
        statute was actually understood — never a measure of it.

        1.0 for a document with nothing normative in it, which is the
        honest reading: no provision went unrepresented.
        """
        total = len(self.obligations) + len(self.unclassified)
        return 1.0 if total == 0 else len(self.obligations) / total

    def triage(self) -> dict[AbstentionReason, tuple[UnclassifiedProvision, ...]]:
        """Abstentions grouped by what would actually fix them.

        The output a compliance reader needs before the obligations
        themselves: a list of what was not read, sorted into taxonomy
        gaps and parser defects, which are repaired in different places.
        """
        grouped: dict[AbstentionReason, list[UnclassifiedProvision]] = {}
        for provision in self.unclassified:
            grouped.setdefault(provision.code, []).append(provision)
        return {reason: tuple(items) for reason, items in grouped.items()}

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
                truncated = bool(_TRUNCATED.search(sentence))
                unclassified.append(
                    UnclassifiedProvision(
                        text=sentence,
                        code=(
                            AbstentionReason.TRUNCATED_FRAGMENT
                            if truncated
                            else AbstentionReason.NO_SUBJECT_MATCH
                        ),
                        reason=(
                            "provision cut off mid-clause — its enumerated limbs were split "
                            "into separate sentences, so the subject matter is not in this "
                            "fragment to find"
                            if truncated
                            else "normative language present but no recognised subject matter — "
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
        # `text` is passed so every returned provision is checked against
        # the source before it is believed. See AbstentionReason.UNGROUNDED.
        return _result_from_payload(raw, citation, jurisdiction_tier, jurisdiction_path, text)


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


# Characters a model routinely normalises on its way through, none of
# which change what a provision says.
_QUOTE_FOLD = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                             "–": "-", "—": "-", "§": "§"})


def _normalise_for_grounding(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTE_FOLD)).strip().casefold()


def _is_grounded(fragment: str, source: str) -> bool:
    """Whether ``fragment`` actually appears in ``source``.

    Containment after whitespace, case and punctuation folding — nothing
    fuzzier. A paraphrase is not evidence that meaning was preserved, and
    for a legal tool the safe default when a returned provision cannot be
    located in the text is to disbelieve it. Folding covers only the
    transformations that cannot change what a provision says: curly
    quotes, dash width, section-sign encoding, whitespace, case.
    """
    return _normalise_for_grounding(fragment) in _normalise_for_grounding(source)


def _result_from_payload(
    payload: dict[str, Any],
    citation: str,
    tier: JurisdictionTier,
    path: tuple[str, ...],
    source: str = "",
) -> ExtractionResult:
    """Turn a backend's response into a result, believing none of it by
    default.

    Three ways an item is refused, each becoming an abstention rather
    than an exception or an accepted obligation:

    * its text is not in the source (``UNGROUNDED``) — see that member
    * a field is missing, or a subject or modality is outside the schema
      (``MALFORMED``)
    * the backend itself declined (``MODEL_DECLINED``)

    ``source`` defaults to empty for callers that predate the check;
    grounding is then skipped rather than failing everything, which is
    the only backwards-compatible reading. Any real backend passes it.
    """
    obligations: list[Obligation] = []
    unclassified: list[UnclassifiedProvision] = []

    for item in payload.get("obligations", []):
        try:
            text = item["text"]
            subjects = frozenset(SubjectMatter(s) for s in item["subjects"])
            modality = Modality(item["modality"])
            bearer = Bearer(item.get("bearer", Bearer.REGULATED_PARTY.value))
            if not subjects or not str(text).strip():
                raise ValueError("empty text or subjects")
        except (KeyError, ValueError, TypeError) as exc:
            unclassified.append(
                UnclassifiedProvision(
                    text=str(item.get("text", item))[:500] if isinstance(item, dict) else str(item),
                    code=AbstentionReason.MALFORMED,
                    reason=f"backend returned an item this schema cannot hold: {exc}",
                )
            )
            continue

        if source and not _is_grounded(text, source):
            unclassified.append(
                UnclassifiedProvision(
                    text=text,
                    code=AbstentionReason.UNGROUNDED,
                    reason=(
                        "backend returned a provision that does not appear in the source "
                        "text — not treated as an obligation, because a fabricated "
                        "provision is indistinguishable from a real one once recorded"
                    ),
                )
            )
            continue

        obligations.append(
            Obligation(
                citation=citation,
                jurisdiction_tier=tier,
                jurisdiction_path=path,
                subjects=subjects,
                modality=modality,
                bearer=bearer,
                text=text,
            )
        )

    unclassified.extend(
        UnclassifiedProvision(
            text=t,
            code=AbstentionReason.MODEL_DECLINED,
            reason="model could not classify",
        )
        for t in payload.get("unclassified", [])
    )
    return ExtractionResult(obligations=tuple(obligations), unclassified=tuple(unclassified))


# Codifiers interleave amendment history with the statute, in brackets,
# mid-sentence:
#
#     A. An eating establishment; [PL 2003, c. 452, Pt. K, §20 (NEW); PL
#     2003, c. 452, Pt. X, §2 (AFF).] B. [PL 2017, c. 322, §4 (RP).]
#
# It is not law, and it is dense with the two characters the splitter
# breaks on. Me. Rev. Stat. tit. 22 § 2492 came apart into 52 segments,
# of which roughly thirty were fragments of citations — "PL 2003, c. 452,
# Pt.", "K, §20 (NEW);", "X, §2 (AFF).] B." Removing it first is what
# makes every later rule tractable.
_EDITORIAL_BRACKET = re.compile(r"\[[^\]]{0,300}\]")

# The trailing history block, which is pure metadata and often longer
# than the section it annotates. Every codifier writes it differently and
# none of them bracket it, so each form has to be named:
#
#   Maine       SECTION HISTORY PL 1979, c. 30, §2 (AMD). ...
#   Vermont     (Amended 1959, No. 329 (Adj. Sess.), § 27, eff. March 1,
#               1961; 2007, No. 38, § 8a, eff. May 21, 2007; ...)
#   Virginia    Code 1950, §§ 35-8, 35-9, 35-16; 1970, c. 302; ...
#
# All three are trailing, so each pattern runs to the end of the text.
# Nine noise segments survived in Vermont and six in Virginia while only
# the Maine form was handled.
_SECTION_HISTORY = re.compile(
    r"\bSECTION HISTORY\b.*"
    r"|\((?:Amended|Added)\s+\d{4}.*"
    r"|\bCode\s+19\d\d,\s*§{1,2}.*",
    re.DOTALL | re.IGNORECASE,
)

# Abbreviations whose period is not a sentence boundary. Without this,
# "Pt. K" and "No. 329" each start a new segment, because the splitter
# sees a period followed by a capital and cannot tell the difference.
_ABBREVIATION = re.compile(
    r"\b(?:Pt|Sec|Secs|No|Nos|Art|Ch|Chap|Subd|Subds|Adj|Sess|eff|Rev|Stat|Ann|Supp"
    r"|cl|para|paras|subs|Inc|Co|Corp|Ltd|approx|Dept|Div|Comm|Reg|Regs|Op|Att|Gen)\.",
    re.IGNORECASE,
)

# An enumerated limb's marker — the "A." in "A. An eating establishment".
# A single letter followed by a period is never the end of a sentence,
# because no sentence is one letter long, so this is decidable rather
# than heuristic. Left unprotected it split every limb of every list:
# § 2492's eight-limb licensing provision produced "B.", "C.", "D." and
# "E." as segments in their own right.
_LIST_MARKER = re.compile(r"(?<![A-Za-z])([A-Z])\.(?=\s)")

# Stands in for a protected period while splitting. U+0000 cannot occur
# in statutory text, so restoring it afterwards is lossless.
_PERIOD_GUARD = "\x00"


def _strip_editorial(text: str) -> str:
    """Remove codifier annotations, which are not part of the statute."""
    text = _SECTION_HISTORY.sub(" ", text)
    text = _EDITORIAL_BRACKET.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# A lead-in and the first of its limbs: everything up to a colon, then a
# marker. The colon is what makes this decidable — an enumerated list in
# a statute is introduced by one, and a sentence that merely contains a
# marker does not have one.
#
# The marker allows five characters because statutes enumerate in roman
# numerals. At {1,3} the ninth limb of Va. Code § 35.1-13 was lost: (i)
# through (vii) matched, "(viii)" did not, and the last two limbs were
# swallowed into the seventh.
_LEAD_IN = re.compile(r"^(?P<lead>.*?[^.;:]):\s*(?P<limbs>(?:\([a-z0-9]{1,5}\)|[A-Z]\.)\s+.*)$")

# Where one limb ends and the next begins.
_LIMB_BOUNDARY = re.compile(r"\s+(?=(?:\([a-z0-9]{1,5}\)|[A-Z]\.)\s)")

# The marker itself, stripped once a limb has been isolated.
_LIMB_MARKER = re.compile(r"^(?:\([a-z0-9]{1,5}\)|[A-Z]\.)\s*")

# Connectives left dangling at a limb's tail when the list is read apart.
_LIMB_TAIL = re.compile(r"[;,]?\s*(?:or|and)?\s*$", re.IGNORECASE)


def _distribute_lead_ins(segments: list[str]) -> list[str]:
    """Rejoin an enumerated list into one provision per limb.

    Statutes routinely state a duty once and enumerate what it applies
    to::

        A person ... may not conduct ... the following establishments
        ... without a license issued by the department:
            A. An eating establishment;
            C. A lodging place;
            D. A recreational camp or sporting camp;

    Read literally that is eight provisions, and read as segments it was
    none: the lead-in carried the modality with no subject and abstained,
    while every limb carried a subject with no modality and was dropped
    as non-normative. The duty and the thing it attaches to were in
    different segments, so neither half could be classified.

    Distributing the lead-in over each limb is what the text means — "may
    not operate an eating establishment without a licence" is a provision
    the statute states, just economically.

    Conservative by construction. A colon must be present, a marker must
    follow it, and only immediately-subsequent marked segments are
    consumed; anything else is passed through untouched, so a table or a
    prose colon is left exactly as it was.
    """
    out: list[str] = []
    index = 0
    while index < len(segments):
        match = _LEAD_IN.match(segments[index])
        if match is None:
            out.append(segments[index])
            index += 1
            continue

        lead = match.group("lead").strip()
        remainder = [match.group("limbs")]
        cursor = index + 1
        while cursor < len(segments) and _LIMB_MARKER.match(segments[cursor]):
            remainder.append(segments[cursor])
            cursor += 1

        limbs = [
            stripped
            for chunk in _LIMB_BOUNDARY.split(" ".join(remainder))
            if (stripped := _LIMB_TAIL.sub("", _LIMB_MARKER.sub("", chunk)).strip())
        ]
        # A list whose limbs are all repealed leaves nothing to attach
        # the duty to; emitting the bare lead-in is better than losing it.
        out.extend(f"{lead} {limb}" for limb in limbs) if limbs else out.append(lead)
        index = cursor
    return out


def _sentences(text: str) -> list[str]:
    text = _strip_editorial(text)
    guarded = _ABBREVIATION.sub(lambda m: m.group(0)[:-1] + _PERIOD_GUARD, text)
    guarded = _LIST_MARKER.sub(lambda m: m.group(1) + _PERIOD_GUARD, guarded)
    # The second alternative catches a provision that begins with a
    # lettered marker after text the splitter cannot break on. Minnesota
    # sets its plan-review fees as an unpunctuated table and then starts
    # the next paragraph mid-flow -- "... ten cabins or more $450 (g)
    # Special event food stands are not required to submit plans" -- so
    # the table and the following provision arrived as one segment.
    parts = re.split(
        r"(?<=[.;])\s+(?=[A-Z(])|\s+(?=\([a-z]\)\s+[A-Z])", guarded.strip()
    )
    restored = [p for p in (q.replace(_PERIOD_GUARD, ".").strip() for q in parts) if p]
    return _distribute_lead_ins(restored)


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
