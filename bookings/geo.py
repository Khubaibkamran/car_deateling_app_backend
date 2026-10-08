from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000
# Used to turn a distance into an arrival estimate (30 km/h in the city).
CITY_SPEED_MPS = 8.33


def distance_meters(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance between two points."""
    lat1, lng1, lat2, lng2 = (radians(float(v)) for v in (lat1, lng1, lat2, lng2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def eta_minutes(meters: float) -> int:
    """Whole minutes to travel `meters` at city speed, never less than 1."""
    return max(1, round(meters / CITY_SPEED_MPS / 60))
