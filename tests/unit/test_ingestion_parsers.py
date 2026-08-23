import pytest

from legal_engine.core.exceptions import ParseError
from legal_engine.core.models import JurisdictionTier, SourceType
from legal_engine.ingestion.parsers.federal import (
    DeltaKind,
    compute_deltas,
    parse_federal_register_xml,
)
from legal_engine.ingestion.parsers.municipal import parse_municipal_html
from legal_engine.ingestion.parsers.treaty import parse_treaty_xml


class TestMunicipalParser:
    def test_parses_ordinance_with_geo_boundary(self):
        html = """
        <html><body>
          <article class="ordinance" data-citation="Sec. 12.04.030" data-title="ADUs">
            <div class="ordinance-text">No person shall construct an ADU without a permit.</div>
            <div class="geo-boundary" data-lat-min="34.0" data-lat-max="34.1"
                 data-lon-min="-118.3" data-lon-max="-118.2"></div>
          </article>
        </body></html>
        """
        [statute] = parse_municipal_html(html, source_url="https://example.gov/code")

        assert statute.citation == "Sec. 12.04.030"
        assert statute.source_type == SourceType.MUNICIPAL_CODE
        assert statute.jurisdiction_tier == JurisdictionTier.MUNICIPAL
        assert "ADU" in statute.text
        assert statute.geo_boundary is not None
        assert statute.geo_boundary.lat_min == 34.0
        assert statute.source_url == "https://example.gov/code"

    def test_ordinance_without_geo_boundary_is_allowed(self):
        html = """
        <article class="ordinance" data-citation="Sec. 1" data-title="Budget">
          <div class="ordinance-text">Budget text.</div>
        </article>
        """
        [statute] = parse_municipal_html(html)
        assert statute.geo_boundary is None

    def test_multiple_ordinances_parsed(self):
        html = """
        <article class="ordinance" data-citation="Sec. 1" data-title="A">
          <div class="ordinance-text">Text A</div>
        </article>
        <article class="ordinance" data-citation="Sec. 2" data-title="B">
          <div class="ordinance-text">Text B</div>
        </article>
        """
        statutes = parse_municipal_html(html)
        assert [s.citation for s in statutes] == ["Sec. 1", "Sec. 2"]

    def test_missing_citation_raises(self):
        html = '<article class="ordinance" data-title="A"><div class="ordinance-text">x</div></article>'
        with pytest.raises(ParseError, match="data-citation"):
            parse_municipal_html(html)

    def test_missing_ordinance_text_raises(self):
        html = '<article class="ordinance" data-citation="Sec. 1" data-title="A"></article>'
        with pytest.raises(ParseError, match="ordinance-text"):
            parse_municipal_html(html)

    def test_malformed_geo_boundary_raises(self):
        html = """
        <article class="ordinance" data-citation="Sec. 1" data-title="A">
          <div class="ordinance-text">Text</div>
          <div class="geo-boundary" data-lat-min="not-a-number" data-lat-max="1"
               data-lon-min="1" data-lon-max="1"></div>
        </article>
        """
        with pytest.raises(ParseError, match="geo-boundary"):
            parse_municipal_html(html)


class TestFederalParser:
    def test_parses_document_with_effective_date(self):
        xml = """
        <FEDREG>
          <DOCUMENT citation="40 CFR 122.21" title="Application for permit"
                    effective-date="2026-01-01">
            <TEXT>Any person who discharges pollutants must apply for a permit.</TEXT>
          </DOCUMENT>
        </FEDREG>
        """
        [statute] = parse_federal_register_xml(xml, source_url="https://federalregister.gov/x")

        assert statute.citation == "40 CFR 122.21"
        assert statute.source_type == SourceType.FEDERAL_CODE
        assert statute.jurisdiction_tier == JurisdictionTier.FEDERAL
        assert statute.effective_date is not None
        assert statute.effective_date.year == 2026

    def test_document_without_effective_date_is_allowed(self):
        xml = '<FEDREG><DOCUMENT citation="X" title="Y"><TEXT>Z</TEXT></DOCUMENT></FEDREG>'
        [statute] = parse_federal_register_xml(xml)
        assert statute.effective_date is None

    def test_malformed_xml_raises(self):
        with pytest.raises(ParseError, match="Malformed"):
            parse_federal_register_xml("<FEDREG><DOCUMENT>")

    def test_missing_text_raises(self):
        xml = '<FEDREG><DOCUMENT citation="X" title="Y"></DOCUMENT></FEDREG>'
        with pytest.raises(ParseError, match="TEXT"):
            parse_federal_register_xml(xml)

    def test_invalid_effective_date_raises(self):
        xml = '<FEDREG><DOCUMENT citation="X" title="Y" effective-date="not-a-date"><TEXT>Z</TEXT></DOCUMENT></FEDREG>'
        with pytest.raises(ParseError, match="effective-date"):
            parse_federal_register_xml(xml)


class TestComputeDeltas:
    def test_classifies_new_changed_and_unchanged(self):
        xml_v1 = '<FEDREG><DOCUMENT citation="X" title="Y"><TEXT>original text</TEXT></DOCUMENT></FEDREG>'
        [original] = parse_federal_register_xml(xml_v1)

        xml_v2 = """
        <FEDREG>
          <DOCUMENT citation="X" title="Y"><TEXT>original text</TEXT></DOCUMENT>
          <DOCUMENT citation="Z" title="W"><TEXT>changed text</TEXT></DOCUMENT>
          <DOCUMENT citation="NEW" title="N"><TEXT>brand new</TEXT></DOCUMENT>
        </FEDREG>
        """
        known = {"X": original, "Z": original.model_copy(update={"citation": "Z", "text": "old text"})}
        incoming = parse_federal_register_xml(xml_v2)

        deltas = {d.citation: d.kind for d in compute_deltas(incoming, known)}
        assert deltas["X"] == DeltaKind.UNCHANGED
        assert deltas["Z"] == DeltaKind.CHANGED
        assert deltas["NEW"] == DeltaKind.NEW


class TestTreatyParser:
    def test_parses_multilingual_articles_with_choice_of_law_and_territory(self):
        xml = """
        <TREATIES>
          <TREATY name="UN Convention on the Law of the Sea" citation="UNCLOS Art. 76">
            <ARTICLE lang="en">The continental shelf comprises the seabed and subsoil.</ARTICLE>
            <ARTICLE lang="fr">Le plateau continental comprend les fonds marins.</ARTICLE>
            <CHOICE-OF-LAW>International Tribunal for the Law of the Sea</CHOICE-OF-LAW>
            <TERRITORY lat-min="10.0" lat-max="15.0" lon-min="-70.0" lon-max="-60.0" />
          </TREATY>
        </TREATIES>
        """
        articles = parse_treaty_xml(xml, source_url="https://un.org/unclos")

        assert {a.language for a in articles} == {"en", "fr"}
        en_article = next(a for a in articles if a.language == "en")
        assert en_article.choice_of_law == "International Tribunal for the Law of the Sea"
        assert en_article.statute.citation == "UNCLOS Art. 76 [en]"
        assert en_article.statute.jurisdiction_tier == JurisdictionTier.INTERNATIONAL_TREATY
        assert en_article.statute.geo_boundary is not None
        assert en_article.statute.geo_boundary.lat_min == 10.0

    def test_treaty_without_territory_is_allowed(self):
        xml = """
        <TREATIES><TREATY name="X" citation="Y">
          <ARTICLE lang="en">Text</ARTICLE>
        </TREATY></TREATIES>
        """
        [article] = parse_treaty_xml(xml)
        assert article.statute.geo_boundary is None
        assert article.choice_of_law is None

    def test_treaty_with_no_articles_raises(self):
        xml = '<TREATIES><TREATY name="X" citation="Y"></TREATY></TREATIES>'
        with pytest.raises(ParseError, match="no <ARTICLE>"):
            parse_treaty_xml(xml)

    def test_article_missing_lang_raises(self):
        xml = '<TREATIES><TREATY name="X" citation="Y"><ARTICLE>Text</ARTICLE></TREATY></TREATIES>'
        with pytest.raises(ParseError, match="lang attribute"):
            parse_treaty_xml(xml)

    def test_malformed_territory_raises(self):
        xml = """
        <TREATIES><TREATY name="X" citation="Y">
          <ARTICLE lang="en">Text</ARTICLE>
          <TERRITORY lat-min="bad" lat-max="1" lon-min="1" lon-max="1" />
        </TREATY></TREATIES>
        """
        with pytest.raises(ParseError, match="TERRITORY"):
            parse_treaty_xml(xml)
