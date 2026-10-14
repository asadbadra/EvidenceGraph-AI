"""Tests for the Phase 1 parsers (pure functions, offline, no keys).

Fixture provenance:
- KEV cases reuse `data/sample/advisories.json`, which contains five CISA KEV
  records copied verbatim from the public feed (committed in Phase 0).
- NVD cases use `data/sample/nvd_sample.json`, a trimmed copy of a real
  NVD API 2.0 response (committed in this phase).
Malformed/missing-field cases are synthetic inputs that exercise error
handling only; they are never presented as real advisories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ingestion.models import AdvisoryRecord, is_valid_cve_id
from app.ingestion.parsers import (
    KEV_FEED_URL,
    KEV_SOURCE_NAME,
    NVD_API_URL,
    NVD_SOURCE_NAME,
    ParseError,
    parse_kev,
    parse_nvd,
)

ROOT = Path(__file__).resolve().parent.parent
KEV_FIXTURE = ROOT / "data" / "sample" / "advisories.json"
NVD_FIXTURE = ROOT / "data" / "sample" / "nvd_sample.json"


# --------------------------------------------------------------------------
# CVE identifier validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("CVE-2021-44228", True),
        ("CVE-2014-0160", True),
        ("CVE-2019-0001", True),
        ("CVE-2019-123456", True),  # sequence numbers may exceed 4 digits
        ("  CVE-2021-44228  ", True),  # surrounding whitespace tolerated
        ("cve-2021-44228", False),  # lowercase prefix rejected
        ("CVE-21-44228", False),  # 2-digit year
        ("CVE-2021-442", False),  # 3-digit sequence
        ("CVE-2021-", False),
        ("CVE-2021-44228; DROP TABLE", False),
        ("", False),
        (None, False),
        (202144228, False),
    ],
)
def test_is_valid_cve_id(value, expected):
    assert is_valid_cve_id(value) is expected


# --------------------------------------------------------------------------
# CISA KEV parsing
# --------------------------------------------------------------------------

def test_kev_parses_all_records_from_real_fixture():
    payload = json.loads(KEV_FIXTURE.read_text(encoding="utf-8"))
    result = parse_kev(payload)

    assert result.fetched == 5
    assert len(result.records) == 5
    assert result.skipped == ()
    assert {r.external_id for r in result.records} == {
        "CVE-2021-44228",
        "CVE-2014-0160",
        "CVE-2023-34362",
        "CVE-2018-13379",
        "CVE-2021-34473",
    }


def test_kev_preserves_provenance_and_fields():
    payload = json.loads(KEV_FIXTURE.read_text(encoding="utf-8"))
    result = parse_kev(payload)
    record = next(r for r in result.records if r.external_id == "CVE-2021-44228")

    assert record.source_name == KEV_SOURCE_NAME
    assert record.source_url == KEV_FEED_URL
    assert record.title == "Apache Log4j2 Remote Code Execution Vulnerability"
    assert "JNDI features do not protect" in record.description
    assert record.published_at == "2021-12-10"  # KEV dateAdded, verbatim
    assert record.vendor == "Apache"
    assert record.product == "Log4j2"
    assert record.cwes == ("CWE-20", "CWE-400", "CWE-502")
    assert "Apply updates" in record.action
    assert record.metadata["known_ransomware_campaign_use"] == "Known"
    assert record.metadata["due_date"] == "2021-12-24"
    # NVD link from the notes field survives as a reference, not source_url.
    assert "https://nvd.nist.gov/vuln/detail/CVE-2021-44228" in record.references
    assert record.validation_errors() == ()


def test_kev_optional_fields_absent_yield_empty_values():
    payload = {
        "vulnerabilities": [
            {
                "cveID": "CVE-2020-0001",
                "vulnerabilityName": "Synthetic Test Record",
                "shortDescription": "Synthetic description for missing-field tests.",
            }
        ]
    }
    result = parse_kev(payload)

    assert len(result.records) == 1
    record = result.records[0]
    assert record.published_at == ""  # no dateAdded -> empty, NOT today's date
    assert record.vendor == "" and record.product == ""
    assert record.cwes == () and record.references == () and record.action == ""
    assert record.metadata == {}
    assert record.validation_errors() == ()


@pytest.mark.parametrize(
    "bad_record,expected_reason",
    [
        ({"vulnerabilityName": "T", "shortDescription": "D"}, "missing required field: cveID"),
        (
            {"cveID": "CVE-21-44228", "vulnerabilityName": "T", "shortDescription": "D"},
            "invalid CVE identifier",
        ),
        (
            {"cveID": "CVE-2021-0001", "shortDescription": "D"},
            "missing required field: vulnerabilityName",
        ),
        (
            {"cveID": "CVE-2021-0001", "vulnerabilityName": "T"},
            "missing required field: shortDescription",
        ),
        ("not-an-object", "record is not a JSON object"),
    ],
)
def test_kev_malformed_records_are_skipped_with_reason(bad_record, expected_reason):
    result = parse_kev({"vulnerabilities": [bad_record]})

    assert result.records == ()
    assert len(result.skipped) == 1
    assert result.skipped[0].index == 0
    assert expected_reason in result.skipped[0].reason
    assert result.fetched == 1


def test_kev_valid_and_invalid_records_mixed_report_both():
    payload = {
        "vulnerabilities": [
            {"cveID": "CVE-2020-0001", "vulnerabilityName": "OK", "shortDescription": "D"},
            {"cveID": "NOT-A-CVE", "vulnerabilityName": "Bad id", "shortDescription": "D"},
            {"cveID": "CVE-2020-0002", "vulnerabilityName": "OK2", "shortDescription": "D2"},
        ]
    }
    result = parse_kev(payload)

    assert [r.external_id for r in result.records] == ["CVE-2020-0001", "CVE-2020-0002"]
    assert len(result.skipped) == 1
    assert result.skipped[0].index == 1
    assert result.skipped[0].identifier == "NOT-A-CVE"


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ("just a string", "must be a JSON object"),
        ({"nope": []}, "no 'vulnerabilities' key"),
        ({"vulnerabilities": {"a": 1}}, "must be a list"),
    ],
)
def test_kev_structurally_bad_payload_raises_parse_error(payload, fragment):
    with pytest.raises(ParseError) as excinfo:
        parse_kev(payload)
    assert fragment in str(excinfo.value)


def test_kev_empty_payload_is_empty_success():
    result = parse_kev({"vulnerabilities": []})
    assert result.records == () and result.skipped == () and result.fetched == 0


# --------------------------------------------------------------------------
# NVD API 2.0 parsing
# --------------------------------------------------------------------------

def test_nvd_parses_real_response_fixture():
    payload = json.loads(NVD_FIXTURE.read_text(encoding="utf-8"))
    result = parse_nvd(payload, api_url=f"{NVD_API_URL}?cveId=CVE-2021-44228")

    assert result.fetched == 1
    assert len(result.records) == 1
    assert result.skipped == ()
    record = result.records[0]

    assert record.external_id == "CVE-2021-44228"
    assert record.source_name == NVD_SOURCE_NAME
    assert record.source_url == "https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
    assert record.title == "Apache Log4j2 Remote Code Execution Vulnerability"
    assert record.metadata["title_source"] == "cisa_vulnerability_name"
    # English description preferred over the Spanish one present in the feed.
    assert record.metadata["description_lang"] == "en"
    assert "JNDI features used in configuration" in record.description
    assert record.published_at == "2021-12-10T10:15:09.143"  # verbatim
    assert record.vendor == "Apache Software Foundation"
    assert record.product == "Apache Log4j2"
    # CWEs from all weakness entries, de-duplicated, order preserved.
    assert record.cwes == ("CWE-20", "CWE-400", "CWE-502", "CWE-917")
    assert "apply updates" in record.action.lower()
    assert any(u.startswith("http") for u in record.references)
    assert record.metadata["vuln_status"] == "Analyzed"
    assert record.metadata["api_url"].endswith("cveId=CVE-2021-44228")
    assert record.validation_errors() == ()


def test_nvd_title_derived_from_description_when_no_cisa_title():
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2019-0001",
                    "published": "2019-01-02T03:04:05.678",
                    "descriptions": [
                        {"lang": "en", "value": "First sentence here. Second sentence."},
                        {"lang": "es", "value": "Primera frase."},
                    ],
                }
            }
        ]
    }
    result = parse_nvd(payload)
    record = result.records[0]

    assert record.title == "First sentence here."
    assert record.metadata["title_source"] == "description_first_sentence"
    assert record.description == "First sentence here. Second sentence."
    # Absent optional NVD fields -> empty, never invented.
    assert record.vendor == "" and record.product == ""
    assert record.cwes == () and record.references == () and record.action == ""
    assert record.published_at == "2019-01-02T03:04:05.678"
    assert "vuln_status" not in record.metadata
    assert record.validation_errors() == ()


def test_nvd_falls_back_to_non_english_description():
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2019-0002",
                    "descriptions": [
                        {"lang": "es", "value": "Descripcion en espanol."},
                    ],
                }
            }
        ]
    }
    result = parse_nvd(payload)
    record = result.records[0]
    assert record.description == "Descripcion en espanol."
    assert record.metadata["description_lang"] == "es"


def test_nvd_long_first_sentence_title_is_truncated_at_word_boundary():
    long_sentence = " ".join(f"word{i}" for i in range(80)) + ". Next."
    payload = {
        "vulnerabilities": [
            {"cve": {"id": "CVE-2019-0003", "descriptions": [{"lang": "en", "value": long_sentence}]}}
        ]
    }
    record = parse_nvd(payload).records[0]
    assert record.title.endswith("...")
    assert len(record.title) <= 204
    assert not record.title.endswith(" ...")  # no space before ellipsis


@pytest.mark.parametrize(
    "bad_item,expected_reason",
    [
        ("not-an-object", "record is not a JSON object"),
        ({"noCve": True}, "record has no 'cve' object"),
        ({"cve": {"descriptions": [{"lang": "en", "value": "D"}]}}, "missing required field: cve.id"),
        (
            {"cve": {"id": "CVE-19-9999", "descriptions": [{"lang": "en", "value": "D"}]}},
            "invalid CVE identifier",
        ),
        (
            {"cve": {"id": "CVE-2019-0004", "descriptions": []}},
            "missing required field: description",
        ),
    ],
)
def test_nvd_malformed_records_are_skipped_with_reason(bad_item, expected_reason):
    result = parse_nvd({"vulnerabilities": [bad_item]})

    assert result.records == ()
    assert len(result.skipped) == 1
    assert expected_reason in result.skipped[0].reason


@pytest.mark.parametrize(
    "payload,fragment",
    [
        (42, "must be a JSON object"),
        ({}, "no 'vulnerabilities' key"),
        ({"vulnerabilities": "nope"}, "must be a list"),
    ],
)
def test_nvd_structurally_bad_payload_raises_parse_error(payload, fragment):
    with pytest.raises(ParseError) as excinfo:
        parse_nvd(payload)
    assert fragment in str(excinfo.value)


def test_nvd_malformed_optional_shapes_do_not_crash():
    """Odd-shaped but present optional fields must degrade, not raise."""
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2019-0005",
                    "descriptions": "oops-not-a-list",
                    "weaknesses": "oops",
                    "references": [{"no_url": 1}, "oops"],
                    "affected": [{"affectedData": "oops"}],
                    "vulnStatus": 42,
                }
            }
        ]
    }
    result = parse_nvd(payload)
    # description missing entirely -> record skipped, but nothing crashed.
    assert result.records == ()
    assert len(result.skipped) == 1

    payload["vulnerabilities"][0]["cve"]["descriptions"] = [
        {"lang": "en", "value": "Valid description."}
    ]
    record = parse_nvd(payload).records[0]
    assert record.cwes == ()
    assert record.references == ()
    assert record.vendor == "" and record.product == ""
    assert record.metadata["vuln_status"] == "42"  # scalar coerced to text


# --------------------------------------------------------------------------
# AdvisoryRecord behaviour
# --------------------------------------------------------------------------

def _valid_record(**overrides) -> AdvisoryRecord:
    base = dict(
        external_id="CVE-2021-0001",
        title="Title",
        description="Description.",
        source_name="Source",
        source_url="https://example.invalid/feed",
    )
    base.update(overrides)
    return AdvisoryRecord(**base)


def test_validation_errors_catches_each_required_field():
    assert _valid_record().validation_errors() == ()
    assert "invalid CVE" in _valid_record(external_id="nope").validation_errors()[0]
    assert "missing title" in _valid_record(title="  ").validation_errors()
    assert "missing description" in _valid_record(description="").validation_errors()
    assert "missing source name" in _valid_record(source_name="").validation_errors()
    assert "missing source URL" in _valid_record(source_url="").validation_errors()


def test_body_text_renders_only_present_fields():
    record = _valid_record(
        vendor="Acme",
        product="Widget",
        action="Apply patch.",
        cwes=("CWE-79",),
        references=("https://example.invalid/a",),
        metadata={"known_ransomware_campaign_use": "Known", "notes": "see link"},
    )
    body = record.body_text()

    assert body.startswith("Advisory: Title\nCVE: CVE-2021-0001")
    assert "Vendor: Acme" in body and "Product: Widget" in body
    assert "Required action: Apply patch." in body
    assert "CWEs: CWE-79" in body
    assert "not independently verified here" in body
    assert "https://example.invalid/a" in body
    assert "Notes: see link" in body


def test_body_text_omits_absent_fields():
    body = _valid_record().body_text()
    assert "Vendor:" not in body
    assert "Product:" not in body
    assert "Required action:" not in body
    assert "References:" not in body
    assert "not independently verified" not in body


def test_body_text_caps_reference_list():
    urls = tuple(f"https://example.invalid/{i}" for i in range(15))
    body = _valid_record(references=urls).body_text()
    assert body.count("  - https://") == 10
    assert "+5 more references stored in metadata" in body
    # The full list stays available for persistence/metadata.
    assert len(_valid_record(references=urls).references) == 15


def test_parsers_are_pure_across_calls():
    """Same input twice -> identical output (no clock, no globals, no I/O)."""
    payload = json.loads(KEV_FIXTURE.read_text(encoding="utf-8"))
    first = parse_kev(payload)
    second = parse_kev(payload)
    assert first == second
