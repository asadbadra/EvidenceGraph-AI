"""Pure parsers: raw feed payloads -> `AdvisoryRecord` instances.

Two sources are supported, both official JSON interfaces:
- CISA KEV catalog feed  (static JSON file, no auth)
- NVD API 2.0            (JSON API, optional free API key)

Design rules:
- Pure functions: no network, no database, no clock. Same input -> same
  output, so tests run offline and results are reproducible.
- A structurally unusable payload raises `ParseError`; individual malformed
  records are skipped and reported with a reason instead of aborting the
  whole run.
- Required fields (valid CVE id, title, description) are enforced; missing
  optional fields become empty values. Nothing is ever invented: no dates,
  no titles, no URLs beyond the deterministic detail-page pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.ingestion.models import AdvisoryRecord, is_valid_cve_id

# Source identity defaults. KEV_SOURCE_NAME must stay byte-identical to the
# name already stored in Phase 0's `sources` row, otherwise the same feed
# would be ingested under two different sources.
KEV_SOURCE_NAME = "CISA Known Exploited Vulnerabilities Catalog"
KEV_FEED_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)
NVD_SOURCE_NAME = "National Vulnerability Database (NIST)"
NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_DETAIL_URL_PREFIX = "https://nvd.nist.gov/vuln/detail/"

CWE_PATTERN = re.compile(r"^CWE-\d+$")
_URL_PATTERN = re.compile(r"https?://[^\s\])>\"']+")


class ParseError(ValueError):
    """The payload itself is unusable (as opposed to a single bad record)."""


@dataclass(frozen=True)
class SkippedRecord:
    """A record that was not converted, with an auditable reason."""

    index: int
    identifier: str | None
    reason: str


@dataclass(frozen=True)
class ParseResult:
    """Outcome of parsing one payload."""

    records: tuple[AdvisoryRecord, ...]
    skipped: tuple[SkippedRecord, ...]
    fetched: int  # number of items the payload contained


def _vulnerability_items(payload: Any, source_label: str) -> list[Any]:
    """Return the top-level record list or raise ParseError."""
    if not isinstance(payload, dict):
        raise ParseError(
            f"{source_label}: payload must be a JSON object, "
            f"got {type(payload).__name__}"
        )
    items = payload.get("vulnerabilities")
    if items is None:
        raise ParseError(f"{source_label}: payload has no 'vulnerabilities' key")
    if not isinstance(items, list):
        raise ParseError(
            f"{source_label}: 'vulnerabilities' must be a list, "
            f"got {type(items).__name__}"
        )
    return items


def _text(value: Any) -> str:
    """Coerce a scalar JSON value to a stripped string ('' for anything odd)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _cwes(values: Any) -> tuple[str, ...]:
    """Keep well-formed CWE identifiers in order; drop anything else."""
    if not isinstance(values, list):
        return ()
    seen: list[str] = []
    for value in values:
        text = _text(value)
        if CWE_PATTERN.match(text) and text not in seen:
            seen.append(text)
    return tuple(seen)


def _extract_urls(text: str) -> tuple[str, ...]:
    """Pull http(s) URLs out of free text (e.g. KEV notes), de-duplicated."""
    urls: list[str] = []
    for match in _URL_PATTERN.findall(text):
        url = match.rstrip(".,;:)")
        if url and url not in urls:
            urls.append(url)
    return tuple(urls)


def _first_sentence(text: str, *, max_chars: int = 200) -> str:
    """Derive a compact title from description text.

    Used only when a source provides no title of its own. Truncation cuts at
    a word boundary and marks the cut with '...' rather than silently losing
    the tail of a long sentence.
    """
    stripped = text.strip()
    match = re.match(r"(.+?[.!?])(\s|$)", stripped)
    sentence = (match.group(1) if match else stripped).strip()
    if len(sentence) <= max_chars:
        return sentence
    clipped = sentence[:max_chars]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(",;:") + "..."


# --------------------------------------------------------------------------
# CISA KEV
# --------------------------------------------------------------------------

def parse_kev(
    payload: Any,
    *,
    source_name: str = KEV_SOURCE_NAME,
    source_url: str = KEV_FEED_URL,
) -> ParseResult:
    """Parse a CISA KEV catalog payload.

    Record source_url defaults to the feed URL: that is where the text
    actually came from. Per-record NVD links found in `notes` are preserved
    in `references`, not promoted to source_url.
    """
    items = _vulnerability_items(payload, "CISA KEV")
    records: list[AdvisoryRecord] = []
    skipped: list[SkippedRecord] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            skipped.append(SkippedRecord(index, None, "record is not a JSON object"))
            continue

        external_id = _text(item.get("cveID"))
        if not external_id:
            skipped.append(
                SkippedRecord(index, None, "missing required field: cveID")
            )
            continue
        if not is_valid_cve_id(external_id):
            skipped.append(
                SkippedRecord(index, external_id, f"invalid CVE identifier: {external_id!r}")
            )
            continue

        title = _text(item.get("vulnerabilityName"))
        if not title:
            skipped.append(
                SkippedRecord(
                    index, external_id, "missing required field: vulnerabilityName"
                )
            )
            continue

        description = _text(item.get("shortDescription"))
        if not description:
            skipped.append(
                SkippedRecord(
                    index, external_id, "missing required field: shortDescription"
                )
            )
            continue

        notes = _text(item.get("notes"))
        metadata: dict[str, Any] = {}
        for raw_key, meta_key in (
            ("dueDate", "due_date"),
            ("knownRansomwareCampaignUse", "known_ransomware_campaign_use"),
            ("forensicTriage", "forensic_triage"),
            ("notes", "notes"),
        ):
            value = _text(item.get(raw_key))
            if value:
                metadata[meta_key] = value

        records.append(
            AdvisoryRecord(
                external_id=external_id,
                title=title,
                description=description,
                source_name=source_name,
                source_url=source_url,
                published_at=_text(item.get("dateAdded")),
                vendor=_text(item.get("vendorProject")),
                product=_text(item.get("product")),
                cwes=_cwes(item.get("cwes")),
                action=_text(item.get("requiredAction")),
                references=_extract_urls(notes),
                metadata=metadata,
            )
        )

    return ParseResult(
        records=tuple(records), skipped=tuple(skipped), fetched=len(items)
    )


# --------------------------------------------------------------------------
# NVD API 2.0
# --------------------------------------------------------------------------

def _pick_description(descriptions: Any) -> tuple[str, str]:
    """Return (text, language), preferring English."""
    if not isinstance(descriptions, list):
        return "", ""
    fallback_lang = ""
    fallback_text = ""
    for entry in descriptions:
        if not isinstance(entry, dict):
            continue
        lang = _text(entry.get("lang")).lower()
        value = _text(entry.get("value"))
        if not value:
            continue
        if lang == "en":
            return value, lang or "en"
        if not fallback_text:
            fallback_text, fallback_lang = value, lang
    return fallback_text, fallback_lang


def _nvd_cwes(weaknesses: Any) -> tuple[str, ...]:
    """Collect CWE ids from all NVD/vendor weakness entries, de-duplicated.

    NVD weakness entries wrap identifiers in {"lang": ..., "value": ...}
    objects (unlike KEV, which uses plain strings), so unwrap them here.
    """
    if not isinstance(weaknesses, list):
        return ()
    collected: list[str] = []
    for entry in weaknesses:
        if not isinstance(entry, dict):
            continue
        descriptions = entry.get("description")
        if not isinstance(descriptions, list):
            continue
        for item in descriptions:
            value = _text(item.get("value") if isinstance(item, dict) else item)
            if CWE_PATTERN.match(value) and value not in collected:
                collected.append(value)
    return tuple(collected)


def _nvd_references(references: Any) -> tuple[str, ...]:
    if not isinstance(references, list):
        return ()
    urls: list[str] = []
    for entry in references:
        if not isinstance(entry, dict):
            continue
        url = _text(entry.get("url"))
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return tuple(urls)


def _nvd_vendor_product(affected: Any) -> tuple[str, str]:
    """Take vendor/product from the first affected entry, if present."""
    if isinstance(affected, list):
        for entry in affected:
            if not isinstance(entry, dict):
                continue
            rows = entry.get("affectedData")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    vendor = _text(row.get("vendor"))
                    product = _text(row.get("product"))
                    if vendor or product:
                        return vendor, product
    return "", ""


def parse_nvd(
    payload: Any,
    *,
    source_name: str = NVD_SOURCE_NAME,
    api_url: str = "",
) -> ParseResult:
    """Parse an NVD API 2.0 response.

    NVD provides no per-record detail URL in the response; records use the
    deterministic pattern https://nvd.nist.gov/vuln/detail/<CVE-id>. The API
    request URL actually used (when supplied by the caller) is kept in
    metadata for auditability. NVD also provides no title field: the title is
    taken from CISA's `cisaVulnerabilityName` when present, otherwise derived
    from the first sentence of the description (recorded via `title_source`).
    """
    items = _vulnerability_items(payload, "NVD")
    records: list[AdvisoryRecord] = []
    skipped: list[SkippedRecord] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            skipped.append(SkippedRecord(index, None, "record is not a JSON object"))
            continue
        cve = item.get("cve")
        if not isinstance(cve, dict):
            skipped.append(SkippedRecord(index, None, "record has no 'cve' object"))
            continue

        external_id = _text(cve.get("id"))
        if not external_id:
            skipped.append(SkippedRecord(index, None, "missing required field: cve.id"))
            continue
        if not is_valid_cve_id(external_id):
            skipped.append(
                SkippedRecord(index, external_id, f"invalid CVE identifier: {external_id!r}")
            )
            continue

        description, description_lang = _pick_description(cve.get("descriptions"))
        if not description:
            skipped.append(
                SkippedRecord(index, external_id, "missing required field: description")
            )
            continue

        cisa_title = _text(cve.get("cisaVulnerabilityName"))
        if cisa_title:
            title, title_source = cisa_title, "cisa_vulnerability_name"
        else:
            title, title_source = _first_sentence(description), "description_first_sentence"

        vendor, product = _nvd_vendor_product(cve.get("affected"))

        metadata: dict[str, Any] = {}
        for raw_key, meta_key in (
            ("vulnStatus", "vuln_status"),
            ("lastModified", "last_modified"),
            ("sourceIdentifier", "source_identifier"),
            ("cisaExploitAdd", "cisa_exploit_add"),
            ("cisaActionDue", "cisa_action_due"),
        ):
            value = _text(cve.get(raw_key))
            if value:
                metadata[meta_key] = value
        metadata["description_lang"] = description_lang or "unknown"
        metadata["title_source"] = title_source
        if api_url:
            metadata["api_url"] = api_url

        records.append(
            AdvisoryRecord(
                external_id=external_id,
                title=title,
                description=description,
                source_name=source_name,
                source_url=f"{NVD_DETAIL_URL_PREFIX}{external_id}",
                published_at=_text(cve.get("published")),
                vendor=vendor,
                product=product,
                cwes=_nvd_cwes(cve.get("weaknesses")),
                action=_text(cve.get("cisaRequiredAction")),
                references=_nvd_references(cve.get("references")),
                metadata=metadata,
            )
        )

    return ParseResult(
        records=tuple(records), skipped=tuple(skipped), fetched=len(items)
    )
