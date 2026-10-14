"""Normalized, source-agnostic advisory record.

`AdvisoryRecord` is the single intermediate representation between the
source parsers (CISA KEV, NVD) and everything downstream (validation,
persistence, chunking). Parsers are pure transformations: no network, no
database, no clock. That keeps them deterministic and testable offline.

Provenance rules:
- `source_name` / `source_url` say where the record came from.
- `published_at` is the source's own date, stored verbatim; empty string
  means the source did not provide one. Dates are never invented.
- `metadata` preserves source-specific fields that have no normalized slot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# CVE identifiers: "CVE-" + 4-digit year + 4 or more sequence digits.
# (Sequence numbers gained a 5th digit in 2014; 3-digit sequences are invalid.)
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")


def is_valid_cve_id(value: Any) -> bool:
    """Return True iff `value` is a syntactically valid CVE identifier.

    Accepts surrounding whitespace; requires uppercase "CVE" prefix.
    Non-string input is always invalid.
    """
    if not isinstance(value, str):
        return False
    return bool(CVE_PATTERN.match(value.strip()))


@dataclass(frozen=True)
class AdvisoryRecord:
    """One advisory/vulnerability record normalized across sources.

    Parsers guarantee `external_id`, `title`, and `description` are non-empty
    and `external_id` is a valid CVE id (see `validation_errors`). Everything
    else defaults to empty and is never fabricated.
    """

    external_id: str
    title: str
    description: str
    source_name: str
    source_url: str
    # Verbatim source date ("2021-12-10" for KEV, ISO timestamp for NVD).
    published_at: str = ""
    vendor: str = ""
    product: str = ""
    cwes: tuple[str, ...] = ()
    action: str = ""
    references: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validation_errors(self) -> tuple[str, ...]:
        """Return human-readable problems; an empty tuple means the record is
        valid for persistence. Defense in depth: parsers already reject bad
        records, but persistence can call this again before writing."""
        errors: list[str] = []
        if not is_valid_cve_id(self.external_id):
            errors.append(f"invalid CVE identifier: {self.external_id!r}")
        if not self.title.strip():
            errors.append("missing title")
        if not self.description.strip():
            errors.append("missing description")
        if not self.source_name.strip():
            errors.append("missing source name")
        if not self.source_url.strip():
            errors.append("missing source URL")
        return tuple(errors)

    def body_text(self, *, max_references: int = 10) -> str:
        """Render the record as readable advisory text for chunking.

        Only non-empty fields are rendered. Ransomware-use claims keep an
        explicit "per source record; not independently verified here" note so
        downstream answers cannot silently promote them to verified facts.
        """
        lines: list[str] = [
            f"Advisory: {self.title}",
            f"CVE: {self.external_id}",
        ]
        if self.vendor:
            lines.append(f"Vendor: {self.vendor}")
        if self.product:
            lines.append(f"Product: {self.product}")
        if self.description:
            lines.extend(["", self.description])
        if self.action:
            lines.extend(["", f"Required action: {self.action}"])
        if self.cwes:
            lines.append(f"CWEs: {', '.join(self.cwes)}")
        ransomware = str(self.metadata.get("known_ransomware_campaign_use", "") or "")
        if ransomware:
            lines.append(
                f"Known ransomware campaign use: {ransomware} "
                "(per source record; not independently verified here)"
            )
        if self.references:
            shown = list(self.references)[:max_references]
            lines.append("References:")
            lines.extend(f"  - {url}" for url in shown)
            hidden = len(self.references) - len(shown)
            if hidden > 0:
                lines.append(f"  (+{hidden} more references stored in metadata)")
        notes = str(self.metadata.get("notes", "") or "")
        if notes:
            lines.append(f"Notes: {notes}")
        return "\n".join(lines)
