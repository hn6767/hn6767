"""
Astronomy for Skyforge: where every star, planet and the Moon really sits
in the sky over the scene, for a given night.

Positions come from PyEphem (libastro), which applies precession, nutation,
aberration and atmospheric refraction. Stars come from data/stars.csv, a
Hipparcos-based catalogue (see tools/build_star_catalog.py), with proper
motion carried forward to the render date.

The scene is the classic view from Battery Spencer in the Marin Headlands,
looking south-east across the Golden Gate Bridge to the SF skyline. Its
compass direction is fitted to the landmarks in the art; see PRESETS below
for the two ways of framing the sky above it.
"""

import csv
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import ephem

HERE = os.path.dirname(os.path.abspath(__file__))
STAR_CATALOG = os.path.join(HERE, "data", "stars.csv")

# ─── Viewpoint and camera ──────────────────────────────────────────────────
# Battery Spencer, Marin Headlands. Bearings from here (WGS84, great-circle):
#   Transamerica Pyramid ~119°, Golden Gate north tower ~142°, south tower ~164°.
VIEW_LAT = float(os.environ.get("SKYFORGE_VIEW_LAT", "37.8297"))
VIEW_LON = float(os.environ.get("SKYFORGE_VIEW_LON", "-122.4836"))
VIEW_ELEV_M = float(os.environ.get("SKYFORGE_VIEW_ELEV_M", "80"))

# Two ways to frame the sky (SKYFORGE_VIEW):
#
#   lens      What a real 90° wide camera at Battery Spencer pointed at the
#             bridge sees. Matches the art's landmarks (Transamerica at
#             x≈190, south tower at x≈650 of 840) and keeps true shapes, but
#             only the lowest ~18° of sky fits above the skyline, so the Moon
#             and most bright stars are usually above the frame.
#
#   panorama  The same viewpoint, widened to a 180° sweep from ENE through
#             S to WSW (centre still south-east of the bridge), with the sky
#             band reaching 70° up. Every object keeps its true compass
#             bearing and altitude; the scale is just stretched, like a
#             fisheye photo. The Moon is in frame on most nights it is up.
PRESETS = {
    #            centre az, width °, top altitude ° (None = same scale as width)
    "lens":     (142.0, 90.0, None),
    "panorama": (150.0, 180.0, 70.0),
}
VIEW_MODE = os.environ.get("SKYFORGE_VIEW", "panorama")
if VIEW_MODE not in PRESETS:
    raise SystemExit(f"SKYFORGE_VIEW must be one of {', '.join(PRESETS)}, not {VIEW_MODE!r}")
_az, _w, _top = PRESETS[VIEW_MODE]
VIEW_AZ_DEG = float(os.environ.get("SKYFORGE_VIEW_AZ", _az))       # centre of frame
HFOV_DEG = float(os.environ.get("SKYFORGE_HFOV", _w))              # left edge to right edge
TOP_ALT_DEG = os.environ.get("SKYFORGE_TOP_ALT", _top)             # altitude at top edge
TOP_ALT_DEG = float(TOP_ALT_DEG) if TOP_ALT_DEG not in (None, "") else None
# Altitude 0° (the true horizon) as a fraction of image height, read off the
# art where open water meets the far shore.
HORIZON_FRAC = float(os.environ.get("SKYFORGE_HORIZON_FRAC", "0.478"))

TZ = ZoneInfo(os.environ.get("SKYFORGE_TZ", "America/Los_Angeles"))
LOCAL_TIME = os.environ.get("SKYFORGE_LOCAL_TIME", "22:00")       # which moment of the night

PLANETS = [ephem.Mercury, ephem.Venus, ephem.Mars, ephem.Jupiter, ephem.Saturn]

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


@dataclass
class Body:
    name: str
    kind: str          # "star" | "planet" | "moon"
    alt: float         # degrees, refracted
    az: float          # degrees, from north through east
    mag: float         # apparent magnitude before atmospheric extinction
    bv: float = 0.6    # colour index (stars); planets get a fixed tint


@dataclass
class Moon(Body):
    illum: float = 0.0       # illuminated fraction 0..1
    waxing: bool = True
    limb_dx: float = 1.0     # unit vector, in screen pixels, toward the Sun
    limb_dy: float = 0.0


# ─── Time ────────────────────────────────────────────────────────────────────

def render_time(now_utc=None):
    """The moment to draw: LOCAL_TIME on the current night, in UTC.

    The nightly Action fires at 06:00 UTC (10 PM PST / 11 PM PDT), which is
    still the evening's local date. A manual run during the day draws the
    coming night; a run between midnight and 6 AM draws the night still in
    progress. SKYFORGE_DATETIME (ISO, local time) overrides everything.
    """
    override = os.environ.get("SKYFORGE_DATETIME")
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(timezone.utc)

    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(TZ)
    night = now_local.date() if now_local.hour >= 6 else now_local.date() - timedelta(days=1)
    hh, mm = (int(v) for v in LOCAL_TIME.split(":"))
    local = datetime(night.year, night.month, night.day, hh, mm, tzinfo=TZ)
    if hh < 12:          # e.g. "01:30" means after midnight of that night
        local += timedelta(days=1)
    return local.astimezone(timezone.utc)


def observer(when_utc, temp_c=None):
    o = ephem.Observer()
    o.lat, o.lon = str(VIEW_LAT), str(VIEW_LON)
    o.elevation = VIEW_ELEV_M
    if when_utc.tzinfo is not None:
        when_utc = when_utc.astimezone(timezone.utc).replace(tzinfo=None)
    o.date = ephem.Date(when_utc)
    if isinstance(temp_c, (int, float)):
        o.temp = temp_c          # refraction uses air temperature
    return o


# ─── Catalogue ───────────────────────────────────────────────────────────────

def load_stars(path=STAR_CATALOG):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _deg(rad):
    return math.degrees(float(rad))


def compute_sky(when_utc, temp_c=None, stars=None):
    """All stars (to the catalogue limit), planets and the Moon, as Bodies."""
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=timezone.utc)
    o = observer(when_utc, temp_c)
    years = (when_utc - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).days / 365.25

    bodies = []
    for row in stars if stars is not None else load_stars():
        dec = float(row["dec_deg"]) + float(row["pm_dec_mas"] or 0) * years / 3.6e6
        cosd = max(1e-6, math.cos(math.radians(dec)))
        ra = float(row["ra_deg"]) + float(row["pm_ra_mas"] or 0) * years / 3.6e6 / cosd
        fb = ephem.FixedBody()
        fb._ra, fb._dec, fb._epoch = math.radians(ra % 360), math.radians(dec), ephem.J2000
        fb.compute(o)
        bv = row.get("bv")
        bodies.append(Body(row["name"] or "", "star", _deg(fb.alt), _deg(fb.az),
                           float(row["mag"]), float(bv) if bv not in (None, "") else 0.6))

    for cls in PLANETS:
        p = cls(o)
        bodies.append(Body(p.name, "planet", _deg(p.alt), _deg(p.az), float(p.mag)))

    bodies.append(moon_body(o))
    return bodies


def moon_body(o):
    m, s = ephem.Moon(o), ephem.Sun(o)
    illum = float(m.moon_phase)
    elong = (float(ephem.Ecliptic(m).lon) - float(ephem.Ecliptic(s).lon)) % (2 * math.pi)
    dx, dy = _toward_on_screen(_deg(m.az), _deg(m.alt), _deg(s.az), _deg(s.alt))
    return Moon("Moon", "moon", _deg(m.alt), _deg(m.az), float(m.mag),
                illum=illum, waxing=elong < math.pi, limb_dx=dx, limb_dy=dy)


def _enu(az, alt):
    a, h = math.radians(az), math.radians(alt)
    return (math.sin(a) * math.cos(h), math.cos(a) * math.cos(h), math.sin(h))


def _toward_on_screen(az, alt, taz, talt):
    """Screen direction (x right, y down) from (az, alt) toward (taz, talt),
    i.e. where the Moon's bright limb points for the Sun as target."""
    a, h = math.radians(az), math.radians(alt)
    right = (math.cos(a), -math.sin(a), 0.0)                      # increasing azimuth
    up = (-math.sin(a) * math.sin(h), -math.cos(a) * math.sin(h), math.cos(h))
    t = _enu(taz, talt)
    sx = sum(p * q for p, q in zip(t, right))
    sy = -sum(p * q for p, q in zip(t, up))
    n = math.hypot(sx, sy) or 1.0
    return sx / n, sy / n


# ─── Atmosphere ────────────────────────────────────────────────────────────

def airmass(alt):
    """Kasten & Young (1989) relative air mass."""
    h = max(alt, 0.0)
    return 1.0 / (math.sin(math.radians(h)) + 0.50572 * (h + 6.07995) ** -1.6364)


def extincted_mag(mag, alt, k=0.30):
    """Apparent magnitude after atmospheric extinction (k mag per air mass,
    a typical sea-level value; worse than a mountain site)."""
    return mag + k * (airmass(alt) - 1.0)


# ─── Projection ──────────────────────────────────────────────────────────────

def project(az, alt, width, height, margin=0):
    """(az, alt) in degrees to (x, y) pixels, or None if outside the frame
    (plus `margin` pixels, so a large disc can be partly in view).

    Cylindrical panorama centred on VIEW_AZ_DEG with the horizon at
    HORIZON_FRAC. Horizontally it is linear in azimuth; vertically linear in
    altitude, with the same pixels-per-degree as horizontally (lens) or
    scaled so TOP_ALT_DEG lands on the top edge (panorama).
    """
    xppd, yppd = pixels_per_degree(width, height)
    d = (az - VIEW_AZ_DEG + 540.0) % 360.0 - 180.0
    x = width / 2 + d * xppd
    y = height * HORIZON_FRAC - alt * yppd
    if not (-margin <= x < width + margin and -margin <= y < height + margin):
        return None
    return x, y


def pixels_per_degree(width, height):
    xppd = width / HFOV_DEG
    yppd = xppd if TOP_ALT_DEG is None else height * HORIZON_FRAC / TOP_ALT_DEG
    return xppd, yppd


def compass(az):
    return COMPASS[int((az % 360) / 22.5 + 0.5) % 16]


def phase_name(moon):
    f = moon.illum
    if f < 0.03:
        return "NEW"
    if f > 0.97:
        return "FULL"
    if 0.47 <= f <= 0.53:
        return "FIRST QTR" if moon.waxing else "LAST QTR"
    return ("WAXING " if moon.waxing else "WANING ") + ("CRES" if f < 0.5 else "GIB")


def bv_to_rgb(bv):
    """Rough star colour from B-V index (blue-white O/B through orange M)."""
    bv = max(-0.4, min(2.0, bv))
    stops = [(-0.4, (155, 176, 255)), (0.0, (202, 216, 255)), (0.4, (248, 247, 255)),
             (0.8, (255, 238, 210)), (1.2, (255, 214, 165)), (1.6, (255, 190, 127)),
             (2.0, (255, 170, 100))]
    for (b0, c0), (b1, c1) in zip(stops, stops[1:]):
        if bv <= b1:
            t = (bv - b0) / (b1 - b0)
            return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))
    return stops[-1][1]
