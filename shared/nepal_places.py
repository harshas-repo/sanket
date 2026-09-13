"""Nepal place gazetteer used for text -> coordinate resolution.

This is a lookup table of the 77 district headquarters plus hazard-relevant
towns/junctions that appear often in community reports. Coordinates are the
published HQ locations; they are used only as a *candidate* location and are
always reported with a `match_confidence` so the product never claims a precise
victim location from a place name alone.

Authoritative reverse geocoding (coordinate -> district/province) comes from the
official DHM district boundary polygons, see backend/app/geo/boundaries.py.
"""

from __future__ import annotations

from dataclasses import dataclass

DISTRICTS: list[tuple[str, str, float, float]] = [
    # (district, province, hq_lat, hq_lng)
    ("Taplejung", "Koshi", 27.302, 87.683),
    ("Panchthar", "Koshi", 27.156, 87.729),
    ("Ilam", "Koshi", 26.909, 87.924),
    ("Jhapa", "Koshi", 26.657, 87.935),
    ("Bhojpur", "Koshi", 27.167, 87.052),
    ("Dhankuta", "Koshi", 26.977, 87.335),
    ("Terhathum", "Koshi", 27.122, 87.287),
    ("Sankhuwasabha", "Koshi", 27.314, 87.206),
    ("Solukhumbu", "Koshi", 27.561, 86.706),
    ("Okhaldhunga", "Koshi", 27.332, 86.381),
    ("Khotang", "Koshi", 27.147, 86.782),
    ("Udayapur", "Koshi", 26.922, 86.981),
    ("Saptari", "Madhesh", 26.573, 86.743),
    ("Sunsari", "Koshi", 26.75, 87.23),
    ("Siraha", "Madhesh", 26.651, 86.209),
    ("Dhanusha", "Madhesh", 26.792, 85.912),
    ("Mahottari", "Madhesh", 26.757, 85.876),
    ("Sarlahi", "Madhesh", 26.653, 85.525),
    ("Rautahat", "Madhesh", 26.698, 85.311),
    ("Bara", "Madhesh", 27.012, 85.109),
    ("Parsa", "Madhesh", 27.144, 84.872),
    ("Morang", "Koshi", 26.712, 87.287),
    ("Kathmandu", "Bagmati", 27.713, 85.324),
    ("Lalitpur", "Bagmati", 27.663, 85.321),
    ("Bhaktapur", "Bagmati", 27.672, 85.429),
    ("Kavrepalanchok", "Bagmati", 27.526, 85.555),
    ("Ramechhap", "Bagmati", 27.379, 86.132),
    ("Dolakha", "Bagmati", 27.435, 86.093),
    ("Sindhupalchok", "Bagmati", 27.853, 85.521),
    ("Rasuwa", "Bagmati", 28.229, 85.416),
    ("Dhading", "Bagmati", 27.872, 84.922),
    ("Makwanpur", "Bagmati", 27.436, 85.047),
    ("Chitwan", "Bagmati", 27.535, 84.36),
    ("Nawalparasi East", "Lumbini", 27.647, 84.127),
    ("Kaski", "Gandaki", 28.22, 83.986),
    ("Lamjung", "Gandaki", 28.362, 84.378),
    ("Tanahun", "Gandaki", 28.152, 84.234),
    ("Syangja", "Gandaki", 28.105, 83.893),
    ("Gorkha", "Gandaki", 28.314, 84.626),
    ("Manang", "Gandaki", 28.55, 84.026),
    ("Mustang", "Gandaki", 29.097, 83.92),
    ("Myagdi", "Gandaki", 28.773, 83.395),
    ("Baglung", "Gandaki", 28.272, 83.591),
    ("Nawalparasi West", "Lumbini", 27.7, 84.13),
    ("Parbat", "Gandaki", 28.27, 83.72),
    ("Rupandehi", "Lumbini", 27.5, 83.45),
    ("Kapilvastu", "Lumbini", 27.55, 83.6),
    ("Arghakhanchi", "Lumbini", 27.92, 83.1),
    ("Palpa", "Lumbini", 28.0, 83.55),
    ("Gulmi", "Lumbini", 28.1, 83.3),
    ("Dang", "Lumbini", 28.0, 82.35),
    ("Banke", "Bheri", 28.1, 81.65),
    ("Bardiya", "Bheri", 28.3, 81.3),
    ("Surkhet", "Karnali", 28.6, 81.6),
    ("Dailekh", "Karnali", 28.85, 81.7),
    ("Jumla", "Karnali", 29.28, 82.18),
    ("Kalikot", "Karnali", 29.2, 81.7),
    ("Mugu", "Karnali", 29.3, 82.7),
    ("Dolpa", "Karnali", 28.9, 82.8),
    ("Humla", "Karnali", 30.0, 81.3),
    ("Jajarkot", "Karnali", 28.65, 82.05),
    ("Salyan", "Karnali", 28.3, 82.15),
    ("Rukum East", "Karnali", 28.85, 82.55),
    ("Rukum West", "Karnali", 29.1, 82.4),
    ("Western Rukum", "Karnali", 28.9, 82.45),
    ("Dailekth", "Karnali", 28.85, 81.7),
    ("Baitadi", "Sudurpashchim", 29.6, 80.55),
    ("Darchula", "Sudurpashchim", 29.85, 80.55),
    ("Doti", "Sudurpashchim", 29.2, 80.85),
    ("Achham", "Sudurpashchim", 28.85, 81.3),
    ("Kailali", "Sudurpashchim", 28.65, 80.6),
    ("Kanchanpur", "Sudurpashchim", 28.75, 80.2),
    ("Bardiya National Park", "Bheri", 28.4, 81.4),
    ("Kailahun", "Sudurpashchim", 28.9, 80.9),
]

# Junctions / towns that recur in hazard reporting because they sit onPrithviman
# or Karnali corridor routes.
TOWNS: list[tuple[str, str, float, float]] = [
    ("Kathmandu", "Kathmandu", 27.7172, 85.324),
    ("Lalitpur", "Lalitpur", 27.658, 85.3195),
    ("Bhaktapur", "Bhaktapur", 27.672, 85.4298),
    ("Pokhara", "Kaski", 28.2096, 83.9856),
    ("Bharatpur", "Chitwan", 27.6916, 84.4515),
    ("Narayanghat", "Chitwan", 27.5947, 84.448),
    ("Mugling", "Chitwan", 27.5708, 84.4247),
    ("Kurintal", "Chitwan", 27.7333, 84.45),
    ("Hetauda", "Makwanpur", 27.4287, 85.0168),
    ("Kamalani", "Kavrepalanchok", 27.6333, 85.4),
    ("Dhulikhel", "Kavrepalanchok", 27.6333, 85.5333),
    ("Barhabise", "Sindhupalchok", 28.0333, 85.4667),
    ("Kodari", "Dhading", 27.8667, 85.8667),
    ("Trishuli", "Dhading", 28.0167, 85.3),
    ("Dhunibesi", "Dhading", 27.9333, 85.1333),
    ("Gaurishankar", "Dolakha", 27.8, 86.2),
    ("Bhimeshwar", "Dolakha", 27.6333, 86.0667),
    ("Charikot", "Dolakha", 27.6833, 86.0667),
    ("Namche Bazaar", "Solukhumbu", 27.8059, 86.7065),
    ("Lukla", "Solukhumbu", 27.6875, 86.7314),
    ("Everest Region", "Solukhumbu", 27.9881, 86.925),
    ("Butwal", "Rupandehi", 27.6967, 83.4556),
    ("Siddharthanagar", "Rupandehi", 27.6967, 83.4556),
    ("Sunwal", "Rupandehi", 27.55, 83.4),
    ("Damak", "Jhapa", 26.87, 87.9),
    ("Biratnagar", "Morang", 26.642, 87.275),
    ("Dharan", "Sunsari", 26.812, 87.28),
    ("Itahari", "Sunsari", 26.658, 87.27),
    ("Janakpur", "Dhanusha", 26.7275, 85.928),
    ("Birgunj", "Parsa", 27.0104, 84.877),
    ("Kalaiya", "Saptari", 26.55, 86.73),
    ("Siraha", "Siraha", 26.651, 86.21),
    ("Baglung", "Baglung", 28.2719, 83.592),
    ("Gorusinghe", "Baglung", 28.3, 83.6333),
    ("Beni", "Myagdi", 28.3849, 83.4231),
    ("Tansen", "Palpa", 27.9467, 83.6167),
    ("Tribeni", "Kailali", 28.7667, 81.15),
    ("Nepalgunj", "Banke", 28.084, 81.6185),
    ("Chisapani", "Bardiya", 28.6, 81.4),
    ("Ghorahi", "Dang", 28.009, 82.26),
    ("Tulsipur", "Dang", 28.13, 82.3),
    ("Jumli", "Jumla", 29.275, 82.1833),
    ("Sinja", "Humla", 29.9833, 81.5167),
    ("Simikot", "Humla", 29.9847, 81.8192),
    ("Martadi", "Darchula", 29.9167, 80.4833),
    ("Mahendranagar", "Kanchanpur", 28.9, 80.15),
    ("Dhangadhi", "Kailali", 28.7066, 80.5675),
    ("Amakhola", "Sindhupalchok", 27.8, 85.7333),
    ("Bhotekoshi", "Sindhupalchok", 27.95, 85.6667),
    ("Melamchi", "Sindhupalchok", 28.0667, 85.4167),
    ("Gajalkhani", "Kavrepalanchok", 27.55, 85.5),
    ("Bandipur", "Tanahun", 28.2167, 84.35),
    ("Damauli", "Tanahun", 28.25, 84.2),
    ("Besisahar", "Lamjung", 28.2517, 84.3983),
    ("Besiseshar", "Lamjung", 28.2517, 84.3983),
    ("Chame", "Manang", 28.6333, 84.0667),
    ("Lomanthang", "Mustang", 29.1833, 83.95),
    ("Jomsom", "Mustang", 28.9714, 83.7653),
    ("Bagar", "Mustang", 29.0333, 83.9333),
    ("Lethe", "Rasuwa", 28.2, 85.3167),
    ("Langtang", "Rasuwa", 28.25, 85.5),
    ("Idam", "Rasuwa", 28.1667, 85.4),
    ("Dumre", "Dhading", 28.0, 85.1333),
    ("Thaklek", "Ramechhap", 27.3333, 86.2),
    ("Manthali", "Ramechhap", 27.2667, 86.0333),
    ("Okhaldhunga", "Okhaldhunga", 27.15, 86.3833),
    ("Phidim", "Panchthar", 27.15, 87.7333),
    ("Ilam", "Ilam", 26.909, 87.924),
    ("Bhojpur", "Bhojpur", 27.1667, 87.05),
    ("Dhankuta", "Dhankuta", 26.977, 87.335),
    ("Sanischare", "Morang", 26.7833, 87.4167),
    ("Gelephu", "Saptari", 26.9, 86.9),
    ("Bhadrapur", "Jhapa", 26.547, 87.924),
    ("Khadbari", "Jhapa", 26.75, 87.85),
    ("Chainpur", "Bhojpur", 27.15, 86.95),
    ("Salleri", "Taplejung", 27.3, 87.6),
    ("Phalelu", "Taplejung", 27.2, 87.7),
    ("Takalu", "Khotang", 27.1, 86.85),
    ("Diktel", "Khotang", 27.4333, 86.7),
    ("Katari", "Udayapur", 27.0, 86.94),
    ("Khandbari", "Sankhuwasabha", 27.37, 87.21),
    ("Num", "Sankhuwasabha", 27.4, 87.25),
]


@dataclass(frozen=True)
class PlaceMatch:
    name: str
    district: str
    province: str | None
    lat: float
    lng: float
    match_confidence: str  # 'high' | 'medium'


_DISTRICT_INDEX: dict[str, tuple[str, float, float]] = {}
_TOWN_INDEX: dict[str, tuple[str, str, float, float]] = {}


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().replace("\u2019", "'").split())


for _d, _p, _lat, _lng in DISTRICTS:
    _DISTRICT_INDEX[_norm(_d)] = (_d, _lat, _lng)
    _DISTRICT_INDEX[_norm(_d + " district")] = (_d, _lat, _lng)

for _t, _d, _lat, _lng in TOWNS:
    _TOWN_INDEX[_norm(_t)] = (_t, _d, _lat, _lng)


def resolve_place(text: str | None) -> PlaceMatch | None:
    """Resolve a free-text location mention to coordinates.

    Town names win over district names because 'Pokhara' implies a far tighter
    location than 'Kaski'. Returns None when nothing matches - callers must then
    ask the user rather than guess.
    """
    if not text:
        return None
    lowered = _norm(text)
    for key, (town, district, lat, lng) in _TOWN_INDEX.items():
        if key in lowered and len(key) > 3:
            province = _province_for(district)
            return PlaceMatch(town, district, province, lat, lng, "medium")
    for key, (district, lat, lng) in _DISTRICT_INDEX.items():
        if key in lowered and len(key) > 3:
            province = _province_for(district)
            return PlaceMatch(district, district, province, lat, lng, "low")
    return None


def _province_for(district: str) -> str | None:
    for d, p, _lat, _lng in DISTRICTS:
        if d == district:
            return p
    return None


def all_districts() -> list[tuple[str, str, float, float]]:
    return list(DISTRICTS)


def all_towns() -> list[tuple[str, str, float, float]]:
    return list(TOWNS)
