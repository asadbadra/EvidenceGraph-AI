"""Load sample advisory records from a committed JSON fixture into SQLite.

The fixture format mirrors the CISA KEV JSON feed so a real feed can be
dropped in later without code changes:

{
  "source": {"name": "...", "url": "..."},
  "retrieved_at": "ISO-8601",
  "vulnerabilities": [ { ...KEV fields... }, ... ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import Chunk, Document, Source
from app.ingestion.chunking import chunk_text

REQUIRED_FIELDS = ("cveID", "vendorProject", "product", "vulnerabilityName", "shortDescription")


@dataclass(frozen=True)
class LoadReport:
    """Summary of what a load operation wrote to the database."""

    documents: int
    chunks: int
    source_id: int


def _build_body(record: dict) -> str:
    """Flatten a KEV record into readable advisory text."""
    lines: list[str] = []
    lines.append(f"Advisory: {record.get('vulnerabilityName', '').strip()}")
    lines.append(f"CVE: {record.get('cveID', '')}")
    lines.append(f"Vendor: {record.get('vendorProject', '')}")
    lines.append(f"Product: {record.get('product', '')}")
    description = record.get("shortDescription", "").strip()
    if description:
        lines.append("")
        lines.append(description)
    action = record.get("requiredAction", "").strip()
    if action:
        lines.append("")
        lines.append(f"Required action: {action}")
    cwes = record.get("cwes") or []
    if cwes:
        lines.append(f" CWEs: {', '.join(cwes)}")
    ransomware = record.get("knownRansomwareCampaignUse", "").strip()
    if ransomware:
        lines.append(
            f" Known ransomware campaign use: {ransomware} "
            "(per source record; not independently verified here)"
        )
    notes = record.get("notes", "").strip()
    if notes:
        lines.append(f"Notes: {notes}")
    return "\n".join(lines)


def load_advisories(
    session: Session,
    fixture_path: str | Path,
    *,
    chunk_max_chars: int = 900,
    chunk_overlap_chars: int = 150,
    replace: bool = True,
) -> LoadReport:
    """Ingest advisory records from `fixture_path` into the database.

    Records missing required fields are skipped (counted in the report's
    document total as loaded only when valid).
    """
    path = Path(fixture_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_meta = payload.get("source", {})
    source_name = source_meta.get("name", "unknown source")
    source_url = source_meta.get("url", "")

    source = session.scalar(select(Source).where(Source.name == source_name))
    if source is None:
        source = Source(name=source_name, url=source_url)
        session.add(source)
        session.flush()
    elif replace:
        # Idempotent reload: drop previous documents for this source.
        doc_ids = list(
            session.scalars(
                select(Document.id).where(Document.source_id == source.id)
            )
        )
        if doc_ids:
            session.execute(delete(Chunk).where(Chunk.document_id.in_(doc_ids)))
            session.execute(delete(Document).where(Document.id.in_(doc_ids)))

    records = payload.get("vulnerabilities", [])
    doc_count = 0
    chunk_count = 0
    for record in records:
        if any(not str(record.get(field, "")).strip() for field in REQUIRED_FIELDS):
            continue
        published = str(record.get("dateAdded", "")) or datetime.now(
            timezone.utc
        ).date().isoformat()
        document = Document(
            source_id=source.id,
            external_id=record["cveID"],
            title=record["vulnerabilityName"].strip(),
            published_at=published,
            source_url=f"https://nvd.nist.gov/vuln/detail/{record['cveID']}",
            metadata_json=json.dumps(
                {
                    "vendor": record.get("vendorProject", ""),
                    "product": record.get("product", ""),
                    "cwes": record.get("cwes", []),
                    "known_ransomware_campaign_use": record.get(
                        "knownRansomwareCampaignUse", ""
                    ),
                    "fixture": str(path),
                },
                ensure_ascii=False,
            ),
        )
        session.add(document)
        session.flush()
        body = _build_body(record)
        for position, text in enumerate(
            chunk_text(body, max_chars=chunk_max_chars, overlap_chars=chunk_overlap_chars)
        ):
            session.add(
                Chunk(
                    document_id=document.id,
                    position=position,
                    text=text,
                    source_url=document.source_url,
                )
            )
            chunk_count += 1
        doc_count += 1

    session.commit()
    return LoadReport(documents=doc_count, chunks=chunk_count, source_id=source.id)
