"""Road-status adapters: Department of Roads and the DRR daily highway bulletin.

Honest finding from source inspection: Nepal has NO machine-readable road status API.

* dor.gov.np publishes notice tables whose payload is a PDF ("Road Notice").
* The daily highway status bulletin actually lives on the DRR portal as a PDF
  (e.g. http://drrportal.gov.np/uploads/document/2882.pdf), published ~07:00 NPT.

These adapters therefore extract *document and notice metadata only*: title,
publish date, attachment URL. They never synthesise per-road open/closed rows from
a headline, and the source health screen reports them as `machine_readable=False`
so operators know why road layers are thin. A PDF extraction step is the documented
next milestone (`scripts/parse_road_bulletin_pdf.py`).
"""

from __future__ import annotations

import hashlib
import logging
import re

from bs4 import BeautifulSoup

from data_ingestion.http_fetch import SourceMalformed, fetch
from data_ingestion.normalizers.observation import (
    NormalizedObservation,
    SourceAdapter,
    clean_int,
)
from shared.enums import IncidentType, ObservationKind
from shared.nepal_places import resolve_place
from shared.timeutils import parse_iso

logger = logging.getLogger("sanket.road_sources")

PDF_HINT = re.compile(r"\.pdf(\?|$)", re.I)
ROAD_KEYWORDS = ("road", "highway", "hular", "first slide", "landslide", "blocked", "closure", "epoth")


class DorNoticeAdapter(SourceAdapter):
    code = "dor"

    def fetch_observations(self) -> list[NormalizedObservation]:
        result = fetch(self.spec.url, timeout=60.0)
        if not result.ok:
            raise SourceMalformed(self.spec.url, f"HTTP {result.status_code}", result.text)
        soup = BeautifulSoup(result.text, "lxml")
        observations: list[NormalizedObservation] = []
        for anchor in soup.find_all("a"):
            href = anchor.get("href") or ""
            label = anchor.get_text(" ", strip=True)
            if not label or len(label) < 12:
                continue
            looks_like_road_notice = any(k in label.lower() for k in ROAD_KEYWORDS)
            if not (looks_like_road_notice or PDF_HINT.search(href)):
                continue
            observations.append(self._to_observation(label, href, result.url))
        if not observations:
            raise SourceMalformed(self.spec.url, "no road-relevant notices parsed", result.text[:300])
        logger.info("DoR notices parsed: %d", len(observations))
        return observations

    def _to_observation(self, label: str, href: str, page_url: str) -> NormalizedObservation:
        absolute = href if href.startswith("http") else f"https://dor.gov.np/{href.lstrip('/')}"
        match = resolve_place(label)
        # Stable id: built-in hash() is salted per process, which would create a
        # duplicate notice on every ingestion run.
        digest = hashlib.sha1(f"{label}|{absolute}".encode()).hexdigest()[:16]
        external_id = f"dor-{digest}"
        return NormalizedObservation(
            source_code=self.code,
            external_id=external_id,
            kind=ObservationKind.ROAD_STATUS,
            subtype="notice_metadata",
            title=label[:480],
            summary=(
                "Department of Roads notice. The road-status content itself is inside a "
                "PDF, so Sanket records only the notice metadata until PDF extraction is "
                "enabled."
            ),
            latitude=match.lat if match else None,
            longitude=match.lng if match else None,
            location_name=match.name if match else None,
            district=match.district if match else None,
            province=match.province if match else None,
            incident_type=IncidentType.ROAD_BLOCKAGE,
            # No event time. The listing page carries none (verified: this adapter reads only the
            # anchor text and href), and dating the notice by the moment we scraped it rewrote the
            # row on every poll - a fresh `received_at`, a re-stamped incident, a "last change" that
            # was bookkeeping. `event_time` is nullable and every reader of it falls back to
            # `received_at`, which is the honest answer to "when did Sanket learn of this".
            event_time=None,
            source_url=absolute,
            within_nepal=bool(match),
            normalized_data={
                "attachment_url": absolute,
                "is_pdf": bool(PDF_HINT.search(absolute)),
                "structured_road_state_available": False,
                "location_precision": "named_place" if match else "unlocated",
                "timing_basis": "undated_by_source",
            },
            raw_data={"label": label, "href": href, "page": page_url},
        )


class DrrHighwayBulletinAdapter(SourceAdapter):
    code = "drr_highway"

    def fetch_observations(self) -> list[NormalizedObservation]:
        result = fetch(
            self.spec.url, timeout=90.0, verify_tls=False
        )  # drrportal.gov.np TLS handshake fails
        if not result.ok:
            raise SourceMalformed(self.spec.url, f"HTTP {result.status_code}", result.text)
        soup = BeautifulSoup(result.text, "lxml")
        observations: list[NormalizedObservation] = []
        for anchor in soup.find_all("a"):
            href = anchor.get("href") or ""
            label = anchor.get_text(" ", strip=True)
            if "documentdetail" not in href and not PDF_HINT.search(href):
                continue
            if not label or len(label) < 8:
                continue
            obs = self._to_observation(label, href)
            if obs:
                observations.append(obs)
        if not observations:
            raise SourceMalformed(
                self.spec.url, "no bulletin documents found on publication page", result.text[:300]
            )
        return observations

    def _to_observation(self, label: str, href: str) -> NormalizedObservation | None:
        doc_id = clean_int(re.search(r"documentdetail/(\d+)", href).group(1)) if re.search(
            r"documentdetail/(\d+)", href
        ) else None
        if not doc_id:
            match = re.search(r"/uploads/document/(\d+)\.pdf", href)
            doc_id = clean_int(match.group(1)) if match else None
        if not doc_id:
            return None
        pdf_url = f"http://drrportal.gov.np/uploads/document/{doc_id}.pdf"
        published = None
        for candidate in re.findall(r"\d{4}-\d{2}-\d{2}", label):
            published = parse_iso(candidate)
            if published:
                break
        is_highway = any(k in label.lower() for k in ("राजमार्ग", "highway", "road", "sadak"))
        if not is_highway:
            return None
        return NormalizedObservation(
            source_code=self.code,
            external_id=f"highway-{doc_id}",
            kind=ObservationKind.ROAD_STATUS,
            subtype="bulletin_metadata",
            title=label[:480],
            summary=(
                "Daily official highway-status bulletin published by MoHA. Per-road open/"
                "closed state is inside the PDF; until PDF extraction is enabled Sanket "
                "reports this as document availability only."
            ),
            # The date inside the bulletin's own title when it has one, and nothing when it does
            # not - see the note in `DorNoticeAdapter` for why the fetch instant is not a stand-in.
            event_time=published,
            incident_type=IncidentType.ROAD_BLOCKAGE,
            source_url=f"http://drrportal.gov.np/document/documentdetail/{doc_id}",
            within_nepal=True,
            normalized_data={
                "document_id": doc_id,
                "pdf_url": pdf_url,
                "structured_road_state_available": False,
                "location_precision": "national",
                "publish_cadence": "daily ~07:00 NPT",
                "timing_basis": "title_date" if published else "undated_by_source",
            },
            raw_data={"label": label, "href": href},
        )
