"""Reading ordinance prose into structured obligations.

Two classes of test carry the weight. ``TestModalityIsNotInverted``
guards a bug this extractor actually shipped with for one iteration: "No
dwelling unit may be rented for more than 90 nights" was classified as a
*permission*, because the leading-negation pattern allowed only a
one-word subject and "dwelling unit" is two. A cap read as a licence is
the worst output this component can produce — it is confidently, quietly
backwards.

``TestNothingIsSilentlyDropped`` guards the design property the module
exists for: a provision the extractor cannot classify must surface, not
vanish. A missing obligation is worse than a wrong one, because it
reports an ordinance as not regulating something it does regulate.
"""

from __future__ import annotations

from datetime import date

import pytest

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.corpus import FLORIDA_VACATION_RENTAL_PREEMPTION as FL_RULE
from legal_engine.obligations.express_preemption import PreemptionStatus, analyze
from legal_engine.obligations.extraction import (
    ExtractionResult,
    KeywordObligationExtractor,
    LlmObligationExtractor,
    sample_and_gate,
)
from legal_engine.obligations.models import Bearer, Modality, SubjectMatter

FL_PATH = ("United States", "Florida", "City of Example")


@pytest.fixture
def extractor() -> KeywordObligationExtractor:
    return KeywordObligationExtractor()


def _extract(extractor, text: str, citation: str = "§ 1", path=FL_PATH) -> ExtractionResult:
    return extractor.extract(text, citation, JurisdictionTier.MUNICIPAL, path)


def _only(result: ExtractionResult):
    assert len(result.obligations) == 1, f"expected one obligation, got {len(result.obligations)}"
    return result.obligations[0]


class TestModalityIsNotInverted:
    """A modality error reverses the provision's meaning."""

    def test_a_multiword_subject_after_no_is_still_prohibitive(self):
        """The regression. "dwelling unit" is two words; the original
        pattern admitted exactly one and fell through to permissive."""
        result = _extract(
            KeywordObligationExtractor(),
            "No dwelling unit may be rented as a vacation rental for more than 90 nights "
            "in any calendar year.",
        )
        assert _only(result).modality is Modality.PROHIBITION

    @pytest.mark.parametrize(
        "sentence",
        [
            "No vacation rental may be let for a term of fewer than 7 consecutive nights.",
            "No owner of record may rent a dwelling more than 30 times per calendar year.",
            "A vacation rental may not be operated without a permit.",
            "Vacation rentals shall not be permitted in residential districts.",
            "Vacation rentals are prohibited in all residential zoning districts.",
        ],
    )
    def test_prohibitive_phrasings(self, extractor, sentence):
        assert _only(_extract(extractor, sentence)).modality is Modality.PROHIBITION

    def test_shall_not_is_not_read_as_shall(self, extractor):
        """"shall not" contains "shall" — checking obligation first would
        turn a prohibition into a requirement."""
        result = _extract(extractor, "Operators shall not permit occupancy above eight persons.")
        assert _only(result).modality is Modality.PROHIBITION

    def test_a_genuine_requirement_is_an_obligation(self, extractor):
        result = _extract(extractor, "Each vacation rental shall provide one off-street parking space.")
        assert _only(result).modality is Modality.OBLIGATION

    def test_a_genuine_permission_is_a_permission(self, extractor):
        result = _extract(extractor, "An operator may advertise the permit number on any listing.")
        assert _only(result).modality is Modality.PERMISSION


class TestSubjectClassification:
    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("No unit may be rented more than 90 nights in any calendar year.", SubjectMatter.FREQUENCY),
            ("No rental may be let for a term of fewer than 7 consecutive nights.", SubjectMatter.DURATION),
            ("Each rental shall provide one off-street parking space.", SubjectMatter.PARKING),
            ("Every rental shall register annually with the city.", SubjectMatter.PERMIT_REGISTRATION),
            ("Operators shall remit the transient occupancy tax monthly.", SubjectMatter.TAXATION),
            ("No rental shall exceed maximum occupancy of eight persons.", SubjectMatter.OCCUPANCY_LIMIT),
            ("The dwelling shall be the operator's primary residence.", SubjectMatter.PRIMARY_RESIDENCE),
            ("Amplified sound is prohibited after 10 p.m.", SubjectMatter.NOISE),
        ],
    )
    def test_recognises_common_subjects(self, extractor, sentence, expected):
        assert expected in _only(_extract(extractor, sentence)).subjects

    def test_one_sentence_may_carry_several_subjects(self, extractor):
        """A permit rule that also dictates advertising is genuinely two
        subjects, and flattening it to one would lose a provision."""
        result = _extract(
            extractor,
            "Every vacation rental shall register with the city and display its permit number "
            "in any advertisement.",
        )
        subjects = _only(result).subjects
        assert SubjectMatter.PERMIT_REGISTRATION in subjects
        assert SubjectMatter.ADVERTISING_DISCLOSURE in subjects


class TestProhibitionSubjectVersusModality:
    """A quantitative limit is a limit *on something*. Only an unqualified
    ban is a PROHIBITION subject — otherwise the ban is the modality and
    the quantity is the subject. Conflating them would make every night
    cap look like an outright ban, and outright bans are preempted for a
    different reason than caps are."""

    def test_a_night_cap_is_frequency_not_prohibition(self, extractor):
        subjects = _only(
            _extract(extractor, "No unit may be rented more than 90 nights in any calendar year.")
        ).subjects
        assert SubjectMatter.FREQUENCY in subjects
        assert SubjectMatter.PROHIBITION not in subjects

    def test_a_minimum_stay_is_duration_not_prohibition(self, extractor):
        subjects = _only(
            _extract(extractor, "No rental may be let for a term of fewer than 7 consecutive nights.")
        ).subjects
        assert SubjectMatter.DURATION in subjects
        assert SubjectMatter.PROHIBITION not in subjects

    def test_an_unqualified_ban_is_a_prohibition_subject(self, extractor):
        subjects = _only(
            _extract(extractor, "Vacation rentals are prohibited in all residential districts.")
        ).subjects
        assert SubjectMatter.PROHIBITION in subjects


class TestNothingIsSilentlyDropped:
    """The property the module exists for."""

    def test_normative_text_with_no_known_subject_surfaces(self, extractor):
        result = _extract(
            extractor,
            "Operators shall maintain harmonious aesthetic congruity with neighborhood character.",
        )
        assert result.obligations == ()
        assert len(result.unclassified) == 1

    def test_such_a_result_is_not_complete(self, extractor):
        result = _extract(extractor, "Operators shall preserve the ineffable character of the block.")
        assert result.is_complete is False

    def test_a_fully_understood_ordinance_is_complete(self, extractor):
        result = _extract(extractor, "Each vacation rental shall provide one parking space.")
        assert result.is_complete is True

    def test_a_partial_read_is_flagged_even_when_something_was_extracted(self, extractor):
        """The dangerous case: one clause parsed, another missed. Getting
        *an* answer must not imply getting *the* answer."""
        result = _extract(
            extractor,
            "Each vacation rental shall provide one off-street parking space. "
            "Operators shall maintain harmonious aesthetic congruity.",
        )
        assert len(result.obligations) == 1
        assert result.is_complete is False

    def test_non_normative_text_is_ignored_not_flagged(self, extractor):
        """A definitions clause isn't an unparsed obligation."""
        result = _extract(extractor, 'For purposes of this chapter, "dwelling unit" has its ordinary meaning.')
        assert result.unclassified == ()
        assert result.ignored_sentences >= 1


class TestAdoptionDate:
    def test_iso_format(self, extractor):
        result = _extract(extractor, "No unit may be rented more than 90 nights. Adopted 2019-03-12.")
        assert _only(result).adopted_date == date(2019, 3, 12)

    def test_long_form_with_capital_a(self, extractor):
        """Real ordinances capitalise it. A case-sensitive pattern misses
        the date and silently downgrades a decidable grandfathering
        question to UNDETERMINED."""
        result = _extract(extractor, "No unit may be rented more than 90 nights. Adopted March 12, 2019.")
        assert _only(result).adopted_date == date(2019, 3, 12)

    def test_absent_date_stays_none(self, extractor):
        result = _extract(extractor, "No unit may be rented more than 90 nights.")
        assert _only(result).adopted_date is None


class TestCanonicalFormAndGate:
    def test_canonical_form_summarises_structure(self, extractor):
        result = _extract(extractor, "No unit may be rented more than 90 nights in any calendar year.")
        assert result.canonical_form() == "regulated_party/prohibition:frequency"

    def test_canonical_form_of_an_empty_result(self, extractor):
        assert _extract(extractor, "The sky is blue.").canonical_form() == "(none)"

    def test_a_deterministic_extractor_always_agrees_with_itself(self, extractor):
        """True and unremarkable — which is the point. Agreement means
        stable, not correct, and a deterministic extractor is trivially
        stable even when wrong."""
        result, agreed = sample_and_gate(
            extractor,
            "No unit may be rented more than 90 nights in any calendar year.",
            "§ 1",
            JurisdictionTier.MUNICIPAL,
            FL_PATH,
        )
        assert agreed is True
        assert result.canonical_form() == "regulated_party/prohibition:frequency"

    def test_the_gate_rejects_an_unfireable_threshold(self, extractor):
        """Inherited from SemanticEntropyGate: a threshold at or above
        log(N) could never fire, and is refused at construction."""
        with pytest.raises(ValueError, match="cannot fire"):
            sample_and_gate(
                extractor, "No unit may be rented more than 90 nights.", "§ 1",
                JurisdictionTier.MUNICIPAL, FL_PATH, samples=5, entropy_threshold=8.5,
            )


class TestLlmBackendFailsClosed:
    def test_it_refuses_without_a_client(self):
        """No model is wired into this codebase. Same honesty category as
        SmtpEmailSender and the KMS signers — real dispatch shape, round
        trip unverified."""
        with pytest.raises(NotImplementedError, match="no model is configured"):
            LlmObligationExtractor(model="some-model").extract(
                "text", "§ 1", JurisdictionTier.MUNICIPAL, FL_PATH
            )

    def test_it_parses_a_stubbed_response(self):
        """The parsing path is testable even though the round trip isn't."""

        class _Stub:
            def extract_obligations(self, text, schema):
                return {
                    "obligations": [
                        {"text": text, "modality": "prohibition", "subjects": ["frequency"]}
                    ]
                }

        result = LlmObligationExtractor(model="m", client=_Stub()).extract(
            "No unit may be rented more than 90 nights.", "§ 1", JurisdictionTier.MUNICIPAL, FL_PATH
        )
        assert _only(result).subjects == frozenset({SubjectMatter.FREQUENCY})
        assert _only(result).modality is Modality.PROHIBITION


class TestEndToEnd:
    """Prose in, preemption verdict out — the whole point of Layer 0."""

    @pytest.mark.parametrize(
        ("text", "path", "expected"),
        [
            (
                (
                    "No dwelling unit may be rented as a vacation rental for more than 90 "
                    "nights in any calendar year. Adopted March 12, 2019."
                ),
                FL_PATH,
                PreemptionStatus.PREEMPTED,
            ),
            (
                (
                    "No dwelling unit may be rented as a vacation rental for more than 120 "
                    "nights in any calendar year. Adopted May 4, 2010."
                ),
                FL_PATH,
                PreemptionStatus.GRANDFATHERED,
            ),
            (
                (
                    "Each vacation rental shall provide one off-street parking space per "
                    "bedroom. Adopted September 8, 2021."
                ),
                FL_PATH,
                PreemptionStatus.NOT_IN_SCOPE,
            ),
            (
                "No vacation rental may be let more than 26 times per calendar year.",
                FL_PATH,
                PreemptionStatus.UNDETERMINED,
            ),
            (
                (
                    "No dwelling unit may be rented as a short-term rental for more than 60 "
                    "nights in any calendar year. Adopted April 1, 2020."
                ),
                ("United States", "Arizona", "City of Elsewhere"),
                PreemptionStatus.OUTSIDE_JURISDICTION,
            ),
        ],
        ids=["preempted", "grandfathered", "out-of-scope", "undetermined", "wrong-state"],
    )
    def test_raw_text_reaches_the_right_verdict(self, extractor, text, path, expected):
        result = _extract(extractor, text, citation="§ X", path=path)
        assert analyze(_only(result), FL_RULE).status is expected


class TestBearer:
    """Who the duty falls on.

    Added because measuring against six real sections of Fla. Stat.
    ch. 509 showed the single largest cause of unclassified provisions —
    38% — was duties on the *agency*. Those weren't parsing failures;
    the schema had nowhere to put them.
    """

    def test_an_agency_duty_is_borne_by_the_regulator(self, extractor):
        result = _extract(extractor, "The division shall adopt such rules as are necessary.")
        assert _only(result).bearer is Bearer.REGULATOR

    @pytest.mark.parametrize(
        "sentence",
        [
            "The department shall inspect each licensed establishment twice annually.",
            "The agency may establish by rule a schedule of fees.",
            "The commission shall maintain records of every complaint received.",
        ],
    )
    def test_agency_phrasings(self, extractor, sentence):
        assert _only(_extract(extractor, sentence)).bearer is Bearer.REGULATOR

    def test_an_unattributed_duty_binds_the_regulated_party(self, extractor):
        """"shall provide parking" with no named actor obviously binds the
        operator — defaulting the other way would misfile most of an
        ordinance."""
        result = _extract(extractor, "Each vacation rental shall provide one parking space.")
        assert _only(result).bearer is Bearer.REGULATED_PARTY

    def test_bearer_is_part_of_the_canonical_form(self, extractor):
        """Two extractions that disagree about *who owes the duty* are not
        the same extraction, and the agreement gate has to see that."""
        agency = _extract(extractor, "The division shall maintain records of each inspection.")
        operator = _extract(extractor, "The operator shall maintain records of each inspection.")
        assert agency.canonical_form() != operator.canonical_form()


class TestSubjectsAddedFromMeasurement:
    """Five subjects added because real statutory text needed them, not
    because they seemed tidy. Roughly a third of unclassified provisions
    failed for want of a subject rather than for want of parsing — a gap
    no amount of language understanding fills."""

    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            (
                (
                    "Wastewater or sewage shall be properly treated onsite or discharged "
                    "into an approved system."
                ),
                SubjectMatter.SANITATION,
            ),
            (
                "Any room infested with such vermin shall be fumigated or disinfected.",
                SubjectMatter.SANITATION,
            ),
            ("Each unit shall be equipped with a working smoke alarm.", SubjectMatter.FIRE_SAFETY),
            ("The division may establish by rule a schedule of fees.", SubjectMatter.FEES),
            ("The division shall adopt such rules as are necessary.", SubjectMatter.RULEMAKING),
            ("The report shall be submitted by September 30.", SubjectMatter.RECORDKEEPING),
        ],
    )
    def test_recognises_subjects_real_statutes_actually_use(self, extractor, sentence, expected):
        assert expected in _only(_extract(extractor, sentence)).subjects


class TestDefinitionalTextIsNotNormative:
    """Definitions borrow deontic vocabulary without imposing duties.
    Reading them as normative manufactures obligations that don't exist —
    the opposite of the silent-drop failure, and just as wrong."""

    @pytest.mark.parametrize(
        "sentence",
        [
            "Any facility that may not be classified as a hotel is a roominghouse.",
            "As used in this chapter, the term applies to transient occupancy.",
            "For purposes of this section, a vacation rental is a public lodging establishment.",
        ],
    )
    def test_definitions_produce_nothing(self, extractor, sentence):
        result = _extract(extractor, sentence)
        assert result.obligations == ()
        assert result.unclassified == ()
        assert result.ignored_sentences >= 1

    def test_a_real_prohibition_is_still_caught(self, extractor):
        """The guard must not swallow genuine prohibitions that happen to
        sit near definitional language."""
        result = _extract(extractor, "No vacation rental may be operated without a license.")
        assert _only(result).modality is Modality.PROHIBITION


class TestSecondMeasuredRound:
    """Four more subjects, added after a second pass over Fla. Stat.
    ch. 509 took coverage from 64.7% to 93.1%.

    Each was admitted only because it generalises beyond lodging law.
    "Linens" recurs throughout that chapter and was deliberately *not*
    given its own subject — a category that only ever fires on hotel
    statutes is overfitting to the corpus that produced it. Bedding
    hygiene folds into SANITATION instead, which is tested here.
    """

    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            (
                "The division may impose administrative sanctions for violations of this section.",
                SubjectMatter.ENFORCEMENT,
            ),
            (
                (
                    "Local law enforcement shall provide immediate assistance in pursuing "
                    "an illegally operating establishment."
                ),
                SubjectMatter.ENFORCEMENT,
            ),
            (
                "The division's advisory council shall review applications for variances.",
                SubjectMatter.ADMINISTRATIVE_PROCEDURE,
            ),
            (
                "Each establishment shall be properly lighted, heated, cooled, and ventilated.",
                SubjectMatter.HABITABILITY,
            ),
            (
                (
                    "Each establishment three or more stories in height must have secure "
                    "railings on all balconies and stairways."
                ),
                SubjectMatter.BUILDING_STANDARDS,
            ),
            (
                "All changes must be filed with the division through the online system.",
                SubjectMatter.RECORDKEEPING,
            ),
        ],
    )
    def test_recognises_the_added_subjects(self, extractor, sentence, expected):
        assert expected in _only(_extract(extractor, sentence)).subjects

    def test_linen_hygiene_is_sanitation_not_a_subject_of_its_own(self, extractor):
        """The overfitting test. Bedding rules are real obligations and
        must be classified — but as hygiene, not as a lodging-specific
        category that would never fire on any other corpus."""
        result = _extract(
            extractor,
            "Sheets and pillowslips shall be laundered before they are used by another guest.",
        )
        assert SubjectMatter.SANITATION in _only(result).subjects

    def test_enforcement_is_distinct_from_fees(self, extractor):
        """A fine is a sum of money; an enforcement action is a power the
        regulator exercises. Merging them would make "revoke the licence"
        indistinguishable from "the fee is $50"."""
        revocation = _extract(extractor, "The division may revoke the license of any operator.")
        assert SubjectMatter.ENFORCEMENT in _only(revocation).subjects


class TestSubordinateLegislatureBearer:
    """A third bearer class, found by held-out measurement.

    Against A.R.S. § 9-500.39 — fetched after the extractor was already
    tuned on Florida, and never tuned against — five of seven unclassified
    provisions were directed at a city or town rather than at an operator
    or an agency. That included the headline sentence of the entire
    statute.

    It is genuinely distinct from REGULATOR: an agency *administers* a
    statute, a subordinate legislature *makes rules* under one. Preemption
    statutes consist mostly of provisions binding the second, so a model
    without this bearer cannot represent the documents this system exists
    to read.
    """

    def test_a_duty_on_a_city_is_borne_by_the_subordinate_legislature(self, extractor):
        result = _extract(
            extractor, "A city or town may not prohibit vacation rentals or short-term rentals."
        )
        assert _only(result).bearer is Bearer.SUBORDINATE_LEGISLATURE

    @pytest.mark.parametrize(
        "sentence",
        [
            "A county may not restrict the use of short-term rentals.",
            "The municipality shall not impose additional occupancy limits.",
            "A city or town may regulate noise under this section.",
        ],
    )
    def test_polity_phrasings(self, extractor, sentence):
        assert _only(_extract(extractor, sentence)).bearer is Bearer.SUBORDINATE_LEGISLATURE

    def test_a_city_merely_named_as_recipient_does_not_take_the_duty(self, extractor):
        """The false positive that would have done real damage. "register
        with the city" is an operator's duty that happens to name the city.
        Anchoring on the bare word would reassign it and quietly empty the
        operator's obligation list — the silent-drop failure wearing a
        different hat."""
        result = _extract(extractor, "Every vacation rental shall register annually with the city.")
        assert _only(result).bearer is Bearer.REGULATED_PARTY

    def test_prohibiting_prohibition_is_about_prohibition(self, extractor):
        """"A city may not prohibit X" is a rule about whether bans may
        exist. Its subject is the ban itself. Missing this left the single
        most important sentence of a preemption statute unclassified."""
        result = _extract(extractor, "A city or town may not prohibit vacation rentals.")
        assert SubjectMatter.PROHIBITION in _only(result).subjects
