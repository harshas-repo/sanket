"""DRR Portal adapter - the official national disaster incident register.

Verified live shape (source inspection):

    POST http://drrportal.gov.np/incidentreport/index_ajax
         parameters={"source":"","incidenttype_id":"","district":"","from":"YYYY-MM-DD","to":"YYYY-MM-DD"}

returns an HTML *table fragment*, not JSON, and CodeIgniter prepends PHP notices to
the body. HTTPS fails the TLS handshake on this host, so plain HTTP is used.

The register carries no coordinates - only district / local level / place names - so
every incident geocodes to a district reference point and is flagged
`location_precision = "district_centroid"`. The map and detail pages show that
approximation rather than implying survey-grade placement.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from data_ingestion.http_fetch import SourceMalformed, fetch
from data_ingestion.normalizers.observation import (
    NormalizedObservation,
    SourceAdapter,
    clean_int,
)
from shared.enums import DRR_TO_SANKET_INCIDENT_TYPE, IncidentType, ObservationKind, Severity
from shared.nepal_places import resolve_place
from shared.timeutils import parse_iso

logger = logging.getLogger("sanket.drr")

DISTRICT_IDS = {
    1: "Taplejung", 2: "Panchthar", 3: "Tamon", 4: "Jhapa", 5: "Bhojpur", 6: "Dhankuta",
    7: "Terhathum", 8: "Sankhuwasabha", 9: "Solukhumbu", 10: "Okhaldhunga", 11: "Khotang",
    12: "Udayapur", 13: "Saptari", 14: "Siraha", 15: "Dhanusha", 16: "Mahottari",
    17: "Sarlahi", 18: "Rautahat", 19: "Bara", 20: "Parsa", 21: "Morang", 22: "Kathmandu",
    23: "Lalitpur", 24: "Bhaktapur", 25: "Kavrepalanchok", 26: "Ramechhap", 27: "Dolakha",
    28: "Sindhupalchok", 29: "Rasuwa", 30: "Dhading", 31: "Makwanpur", 32: "Chitwan",
    33: "Nawalparasi", 34: "Kaski", 35: "Lamjung", 36: "Tanahun", 37: "Syangja",
    38: "Gorkha", 39: "Manang", 40: "Mustang", 41: "Myagdi", 42: "Baglung", 43: "Rupandehi",
    44: "Kapilvastu", 45: "Arghakhanchi", 46: "Palpa", 47: "Gulmi", 48: "Parbat",
    49: "Mustang2", 50: "Dang", 51: "Banke", 52: "Bardiya", 53: "Surkhet", 54: "Dailekh",
    55: "Jumla", 56: "Kalikot", 57: "Mugu", 58: "Dolpa", 59: "Humla", 60: "Jajarkot",
    61: "Salyan", 62: "Rukum", 63: "Darchula", 64: "Baitadi", 65: "Doti", 66: "Achham",
    67: "Kailali", 68: "Kanchanpur", 69: "Kailahun", 70: "Sindhuli", 71: "Dadeldhura",
    72: "Baitadi2", 73: "Nuwakot", 74: "Saptakoshi", 75: "Chure",
}

# Header text -> internal field. Matched loosely because the portal edits labels.
HEADER_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"s\.?\s*no", re.I), "sno"),
    (re.compile(r"district", re.I), "district"),
    (re.compile(r"local\s*level|vdc|municip", re.I), "local_level"),
    (re.compile(r"incident\s*type|^incident$|type\s*of\s*disaster", re.I), "incident"),
    (re.compile(r"incident\s*date|date", re.I), "date"),
    (re.compile(r"death.*male", re.I), "death_male"),
    (re.compile(r"death.*female", re.I), "death_female"),
    (re.compile(r"(total\s*death|deaths?\s*total|no\.?\s*of\s*death)", re.I), "total_death"),
    (re.compile(r"missing", re.I), "missing"),
    (re.compile(r"affected\s*famil", re.I), "affected_family"),
    (re.compile(r"estimated\s*loss", re.I), "estimated_loss"),
    (re.compile(r"injur", re.I), "injured"),
    (re.compile(r"houses?\s*fully\s*damaged", re.I), "houses_fully"),
    (re.compile(r"houses?\s*partially\s*damaged", re.I), "houses_partially"),
    (re.compile(r"displaced", re.I), "displaced"),
    (re.compile(r"incident\s*place|place", re.I), "place"),
    (re.compile(r"remarks|remark", re.I), "remarks"),
]

FAMILY_SIZE_ASSUMPTION = 4.6  # NPRC/NSO average persons per household, used only to
# convert the register's "affected families" into the person-count our impact model
# expects. Recorded in normalized_data so the derivation is never implicit.


class DrrIncidentAdapter(SourceAdapter):
    code = "drr"

    def __init__(self, spec=None, settings=None, lookback_days: int = 45, max_pages: int = 6):
        super().__init__(spec, settings)
        self.lookback_days = lookback_days
        self.max_pages = max_pages

    def filter_payload(self, now: datetime | None = None) -> dict[str, str]:
        end = now or datetime.utcnow()
        start = end - timedelta(days=self.lookback_days)
        return {
            "source": "",
            "incidenttype_id": "",
            "district": "",
            "from": start.strftime("%Y-%m-%d"),
            "to": end.strftime("%Y-%m-%d"),
        }

    def fetch_observations(self) -> list[NormalizedObservation]:
        payload = self.filter_payload()
        observations: list[NormalizedObservation] = []
        seen_rows: set[str] = set()
        for page in range(1, self.max_pages + 1):
            html = self._fetch_page(payload, page)
            rows = self._parse_rows(html)
            if not rows:
                break
            fresh = 0
            for row in rows:
                key = f"{page}-{row.get('sno')}-{row.get('district')}-{row.get('date')}"
                if key in seen_rows:
                    continue
                seen_rows.add(key)
                obs = self._to_observation(row)
                if obs:
                    observations.append(obs)
                    fresh += 1
            if fresh == 0:
                break
        logger.info("DRR register returned %d incidents", len(observations))
        return observations

    def _fetch_page(self, payload: dict[str, str], page: int) -> str:
        url = f"{self.spec.url}/{page}" if page > 1 else self.spec.url
        result = fetch(
            url,
            method="POST" if page == 1 else "GET",
            data={"parameters": json.dumps(payload)} if page == 1 else None,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "http://drrportal.gov.np/incidentreport",
            },
            # The portal's TLS is broken; the catalog URL is already http://.
            verify_tls=False,
            timeout=90.0,
            # Observed live: the register intermittently answers 500 to the filtered
            # POST even when the same query succeeds seconds later.
            retry_statuses=(500, 502, 503, 504),
            retries=3,
        )
        if not result.ok:
            raise SourceMalformed(url, f"HTTP {result.status_code}", result.text)
        return result.text

    def _parse_rows(self, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if not table:
            raise SourceMalformed(self.spec.url, "no <table> in fragment", html[:300])
        header_cells = [c.get_text(" ", strip=True) for c in table.select("thead th, thead td")]
        if not header_cells:
            first_row = table.find("tr")
            header_cells = [c.get_text(" ", strip=True) for c in first_row.find_all(["th", "td"])] if first_row else []
        mapping = self._map_headers(header_cells)
        if not mapping:
            raise SourceMalformed(self.spec.url, "could not map table headers", html[:300])

        rows: list[dict[str, str]] = []
        for tr in table.select("tbody tr") or table.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            record = {field: (cells[idx] if idx < len(cells) else "") for idx, field in mapping.items()}
            if not record.get("district") and not record.get("incident"):
                continue
            rows.append(record)
        return rows

    def _map_headers(self, headers: list[str]) -> dict[int, str]:
        mapping: dict[int, str] = {}
        claimed: set[str] = set()
        for idx, header in enumerate(headers):
            for pattern, field in HEADER_MAP:
                if field in claimed:
                    continue
                if pattern.search(header):
                    mapping[idx] = field
                    claimed.add(field)
                    break
        return mapping

    def _to_observation(self, row: dict[str, str]) -> NormalizedObservation | None:
        district = _clean_district(row.get("district"))
        incident_label = _text(row.get("incident"))
        if not district and not incident_label:
            return None
        place = _text(row.get("place"))
        local_level = _text(row.get("local_level"))
        event_date = parse_iso(row.get("date") or "")

        incident_type = _incident_type(incident_label)
        # Location resolution order: named place in the register, else local level,
        # else district reference point. Always recorded with its precision.
        match = resolve_place(place) or resolve_place(local_level) or resolve_place(district)
        precision = "named_place" if match and place and _norm(match.name) in _norm(place) else (
            "local_level" if match and local_level and _norm(match.name) in _norm(local_level) else "district_centroid"
        )

        deaths = clean_int(row.get("total_death")) or (
            clean_int(row.get("death_male")) + clean_int(row.get("death_female"))
        )
        injured = clean_int(row.get("injured"))
        missing = clean_int(row.get("missing"))
        families = clean_int(row.get("affected_family"))
        affected = int(round(families * FAMILY_SIZE_ASSUMPTION)) if families else 0
        displaced = clean_int(row.get("displaced"))
        houses = clean_int(row.get("houses_fully")) + clean_int(row.get("houses_partially"))
        remarks = _text(row.get("remarks"))

        title_bits = [incident_label or incident_type.value.replace("_", " ").title()]
        location_label = ", ".join([p for p in (place or local_level, district) if p])
        external_id = "-".join(
            [
                # An undated register line must not take today's date as its identity. It used to,
                # which minted a duplicate of the same row at every midnight (18 of the 60 rows in
                # the feed as measured) and re-touched its incident each day for nothing. `sno`,
                # district and the incident label are enough to keep these distinct.
                event_date.strftime("%Y%m%d") if event_date else "undated",
                str(clean_int(row.get("sno")) or 0),
                _slug(district or "nd"),
                _slug(incident_label or "incident"),
            ]
        )
        severity = _severity_from_impact(deaths, injured, missing, affected)
        return NormalizedObservation(
            source_code=self.code,
            external_id=external_id,
            kind=ObservationKind.OFFICIAL_INCIDENT,
            title=f"{title_bits[0]} - {location_label}" if location_label else title_bits[0],
            summary=_summary(incident_label, location_label, deaths, missing, injured, families, event_date),
            latitude=match.lat if match else None,
            longitude=match.lng if match else None,
            location_name=(place or local_level or (match.name if match else None)),
            district=district,
            province=match.province if match else None,
            local_municipality=local_level or None,
            incident_type=incident_type,
            event_time=event_date,
            severity=severity.value,
            deaths=deaths,
            missing=missing,
            injured=injured,
            affected_people=affected,
            houses_damaged=houses,
            source_url="http://drrportal.gov.np/incidentreport",
            subtype=incident_label or None,
            within_nepal=True if match else False,
            normalized_data={
                "register_row": clean_int(row.get("sno")),
                "affected_families": families,
                "affected_person_conversion_factor": FAMILY_SIZE_ASSUMPTION,
                "displaced_persons": displaced,
                "estimated_loss_text": (row.get("estimated_loss") or "").strip() or None,
                "location_precision": precision,
                "location_confidence": (match.match_confidence if match else "none"),
                "raw_incident_label": incident_label,
                "remarks": remarks or None,
                "register_source": "MoHA Disaster Risk Reduction Portal",
            },
            raw_data=row,
        )


def _severity_from_impact(deaths: int, injured: int, missing: int, affected: int) -> Severity:
    if deaths >= 10 or affected >= 5000:
        return Severity.SEVERE
    if deaths >= 1 or missing >= 5 or injured >= 10:
        return Severity.HIGH
    if injured >= 1 or affected >= 100 or missing >= 1:
        return Severity.MODERATE
    return Severity.LOW


def _incident_type(label: str) -> IncidentType:
    number = re.match(r"^\s*(\d+)\s*$", label or "")
    if number:
        mapped = DRR_TO_SANKET_INCIDENT_TYPE.get(int(number.group(1)))
        if mapped:
            return mapped
    return IncidentType.from_source_label(label)


def _clean_district(value: str | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    text = re.sub(r"\s*district\s*$", "", text, flags=re.I)
    aliases = {"chitawan": "Chitwan", "kathmandu": "Kathmandu", "kapilbastu": "Kapilvastu",
               "kapilvastu": "Kapilvastu", "nepalgunj": "Banke", "lalwanpur": "Lalitpur"}
    return aliases.get(text.lower(), text.title())


# The register fills empty cells with "0" or "-", which read as real place names in
# a title ("Snake Bite - 0, Surkhet") until they are treated as what they are.
PLACEHOLDER_CELLS = {"0", "-", "--", "n/a", "na", "none", "null", "x"}


def _text(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in PLACEHOLDER_CELLS else text


def _summary(label, location, deaths, missing, injured, families, event_date) -> str:
    parts = [f"Official {label.lower() or 'disaster'} record"]
    if location:
        parts.append(f"in {location}")
    if event_date:
        parts.append(f"on {event_date.strftime('%d %b %Y')}")
    impacts = []
    if deaths:
        impacts.append(f"{deaths} death{'s' if deaths != 1 else ''}")
    if missing:
        impacts.append(f"{missing} missing")
    if injured:
        impacts.append(f"{injured} injured")
    if families:
        impacts.append(f"{families} families affected")
    if impacts:
        parts.append("- " + ", ".join(impacts))
    return " ".join(parts).strip() + "."


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())[:16] or "x"


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())
