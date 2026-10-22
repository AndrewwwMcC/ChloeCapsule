"""Where a photo was taken, worked out offline.

`reverse_geocode` carries a list of the world's towns (geonames, population 1000
and up) and answers from it — no API key, no network call, no per-photo cost.
The nearest town wins, except that a city within BIG_CITY_KM takes it instead:
a photo from central Paris should say Paris, not whichever suburb's centre
happens to be a kilometre closer.

The answer is stored on the photo at upload time, so a page never geocodes."""
import logging
from math import asin, cos, radians, sin, sqrt

log = logging.getLogger("uvicorn.error")

BIG_CITY_POP = 150_000
BIG_CITY_KM = 12

_geocoder = None  # the library, or False once we know it isn't installed


def _library():
    global _geocoder
    if _geocoder is None:
        try:
            import reverse_geocode
            _geocoder = reverse_geocode
        except ImportError:
            log.warning("reverse_geocode isn't installed; photos won't get place names.")
            _geocoder = False
    return _geocoder or None


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def place_for(lat: float | None, lon: float | None) -> str | None:
    """A town or city name for these coordinates, or None if we can't tell."""
    if lat is None or lon is None:
        return None
    rg = _library()
    if not rg:
        return None
    try:
        near = rg.get((lat, lon))
        big = rg.get((lat, lon), min_population=BIG_CITY_POP)
    except Exception as exc:  # a bad coordinate shouldn't stop an upload
        log.warning("Couldn't place %s, %s: %s", lat, lon, exc)
        return None
    if big and km_between(lat, lon, big["latitude"], big["longitude"]) <= BIG_CITY_KM:
        return big.get("city") or None
    return (near or {}).get("city") or None
