#!/usr/bin/env python3
"""
Skyforge — Pixel-art night sky generator for GitHub profile READMEs.

Calculates real star positions for San Jose (~37.3°N, 121.9°W),
renders the current moon phase, pulls live weather data from Open-Meteo,
and composites everything into an animated pixel-art GIF with twinkling
stars, a cityscape silhouette, animated building windows, shooting stars,
and a weather HUD.
"""

import io
import json
import math
import random
import struct
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ─── Configuration ───────────────────────────────────────────────────────────

# Location: San Jose, CA
LATITUDE = 37.3382
LONGITUDE = -121.8863
TIMEZONE_OFFSET = -7  # PDT (adjust to -8 for PST)
CITY_NAME = "San Jose, CA"

# Image dimensions
WIDTH = 640
HEIGHT = 320
FRAME_COUNT = 24
FRAME_DELAY_MS = 120  # ~8 fps

# Pixel art scale factor (each "pixel" is this many real pixels)
PIXEL_SCALE = 2

# Color palette (retro/neon)
COLOR_SKY_TOP = (10, 10, 40)       # Deep navy
COLOR_SKY_MID1 = (25, 20, 70)      # Dark indigo
COLOR_SKY_MID2 = (60, 40, 110)     # Purple
COLOR_SKY_MID3 = (100, 50, 130)    # Lavender-purple
COLOR_HORIZON_GLOW = (160, 60, 120) # Pink-magenta glow
COLOR_STAR = (255, 255, 240)
COLOR_STAR_DIM = (180, 180, 200)
COLOR_MOON = (255, 250, 220)
COLOR_MOON_SHADOW = (40, 35, 60)
COLOR_BUILDING = (12, 10, 28)
COLOR_WINDOW_ON = (255, 220, 100)
COLOR_WINDOW_OFF = (20, 18, 40)
COLOR_NEON_PINK = (255, 50, 150)
COLOR_NEON_CYAN = (0, 255, 220)
COLOR_NEON_PURPLE = (180, 80, 255)
COLOR_CLOUD = (60, 55, 80)
COLOR_CLOUD_EDGE = (80, 75, 110)
COLOR_HUD_BG = (16, 14, 36)
COLOR_HUD_TEXT = (200, 200, 220)
COLOR_SHOOTING_STAR = (255, 255, 200)
COLOR_ANTENNA_RED = (255, 40, 40)
COLOR_ANTENNA_OFF = (60, 20, 20)

# ─── Tiny Font (3x5 pixel font for HUD) ────────────────────────────────────

FONT_3X5 = {
    'A': ["010", "101", "111", "101", "101"],
    'B': ["110", "101", "110", "101", "110"],
    'C': ["011", "100", "100", "100", "011"],
    'D': ["110", "101", "101", "101", "110"],
    'E': ["111", "100", "110", "100", "111"],
    'F': ["111", "100", "110", "100", "100"],
    'G': ["011", "100", "101", "101", "011"],
    'H': ["101", "101", "111", "101", "101"],
    'I': ["111", "010", "010", "010", "111"],
    'J': ["001", "001", "001", "101", "010"],
    'K': ["101", "110", "100", "110", "101"],
    'L': ["100", "100", "100", "100", "111"],
    'M': ["101", "111", "111", "101", "101"],
    'N': ["101", "111", "111", "111", "101"],
    'O': ["010", "101", "101", "101", "010"],
    'P': ["110", "101", "110", "100", "100"],
    'Q': ["010", "101", "101", "110", "011"],
    'R': ["110", "101", "110", "101", "101"],
    'S': ["011", "100", "010", "001", "110"],
    'T': ["111", "010", "010", "010", "010"],
    'U': ["101", "101", "101", "101", "010"],
    'V': ["101", "101", "101", "010", "010"],
    'W': ["101", "101", "111", "111", "101"],
    'X': ["101", "101", "010", "101", "101"],
    'Y': ["101", "101", "010", "010", "010"],
    'Z': ["111", "001", "010", "100", "111"],
    '0': ["010", "101", "101", "101", "010"],
    '1': ["010", "110", "010", "010", "111"],
    '2': ["110", "001", "010", "100", "111"],
    '3': ["110", "001", "010", "001", "110"],
    '4': ["101", "101", "111", "001", "001"],
    '5': ["111", "100", "110", "001", "110"],
    '6': ["011", "100", "110", "101", "010"],
    '7': ["111", "001", "010", "010", "010"],
    '8': ["010", "101", "010", "101", "010"],
    '9': ["010", "101", "011", "001", "110"],
    ' ': ["000", "000", "000", "000", "000"],
    '.': ["000", "000", "000", "000", "010"],
    ',': ["000", "000", "000", "010", "100"],
    ':': ["000", "010", "000", "010", "000"],
    '-': ["000", "000", "111", "000", "000"],
    '/': ["001", "001", "010", "100", "100"],
    '%': ["101", "001", "010", "100", "101"],
    '°': ["010", "101", "010", "000", "000"],
    '~': ["000", "000", "010", "000", "000"],
    '(': ["010", "100", "100", "100", "010"],
    ')': ["010", "001", "001", "001", "010"],
    '*': ["000", "101", "010", "101", "000"],
}

# ─── Bright star catalog (name, RA hours, Dec degrees, magnitude) ───────────

BRIGHT_STARS = [
    ("Sirius", 6.752, -16.72, -1.46),
    ("Canopus", 6.399, -52.70, -0.74),
    ("Arcturus", 14.261, 19.18, -0.05),
    ("Vega", 18.616, 38.78, 0.03),
    ("Capella", 5.278, 46.00, 0.08),
    ("Rigel", 5.242, -8.20, 0.13),
    ("Procyon", 7.655, 5.22, 0.34),
    ("Betelgeuse", 5.920, 7.41, 0.42),
    ("Altair", 19.846, 8.87, 0.76),
    ("Aldebaran", 4.599, 16.51, 0.86),
    ("Antares", 16.490, -26.43, 0.96),
    ("Spica", 13.420, -11.16, 0.97),
    ("Pollux", 7.755, 28.03, 1.14),
    ("Fomalhaut", 22.961, -29.62, 1.16),
    ("Deneb", 20.690, 45.28, 1.25),
    ("Regulus", 10.140, 11.97, 1.35),
    ("Castor", 7.577, 31.89, 1.58),
    ("Bellatrix", 5.419, 6.35, 1.64),
    ("Alnilam", 5.603, -1.20, 1.69),
    ("Polaris", 2.530, 89.26, 1.98),
    ("Alnitak", 5.679, -1.94, 1.77),
    ("Dubhe", 11.062, 61.75, 1.79),
    ("Mirfak", 3.405, 49.86, 1.80),
    ("Alkaid", 13.792, 49.31, 1.86),
    ("Mizar", 13.399, 54.93, 2.04),
    ("Merak", 11.031, 56.38, 2.37),
    ("Phecda", 11.897, 53.69, 2.44),
    ("Megrez", 12.257, 57.03, 3.31),
    # Additional stars for better March sky coverage
    ("Denebola", 11.818, 14.57, 2.14),  # Leo's tail — completes Leo
    ("Alphard", 9.460, -8.66, 1.98),    # Hydra — "The Solitary One"
    ("Alhena", 6.629, 16.40, 1.93),     # Gemini's foot
]

# ─── Constellation lines (pairs of star names to connect) ───────────────────

CONSTELLATION_LINES = [
    # Ursa Major (Big Dipper)
    ("Dubhe", "Merak"), ("Merak", "Phecda"), ("Phecda", "Megrez"),
    ("Megrez", "Mizar"), ("Mizar", "Alkaid"), ("Megrez", "Dubhe"),
    # Orion (partial)
    ("Betelgeuse", "Bellatrix"), ("Betelgeuse", "Alnilam"),
    ("Bellatrix", "Alnilam"), ("Alnilam", "Alnitak"), ("Alnilam", "Rigel"),
    # Leo (the dominant March constellation)
    ("Regulus", "Denebola"),
    # Gemini
    ("Castor", "Pollux"), ("Pollux", "Alhena"), ("Castor", "Alhena"),
    # Summer Triangle (only draws when stars are above horizon)
    ("Vega", "Deneb"), ("Vega", "Altair"), ("Deneb", "Altair"),
]

# ─── Cityscape buildings ───────────────────────────────────────────────────
# Each building: (x, width, height, layer, roof_type)
#   layer: 0=background (lighter), 1=midground, 2=foreground (darkest)
#   roof_type: "flat", "pointed", "spire", "stepped", "dome"

BUILDINGS = [
    # Background layer (shorter, lighter)
    (0, 35, 40, 0, "flat"),     (30, 25, 50, 0, "stepped"),
    (55, 40, 35, 0, "flat"),    (90, 20, 55, 0, "pointed"),
    (108, 45, 42, 0, "flat"),   (150, 22, 48, 0, "flat"),
    (170, 30, 38, 0, "dome"),   (200, 50, 45, 0, "flat"),
    (248, 25, 52, 0, "pointed"),(270, 40, 36, 0, "flat"),
    (310, 28, 46, 0, "stepped"),(338, 35, 40, 0, "flat"),
    (370, 22, 55, 0, "pointed"),(390, 45, 38, 0, "flat"),
    (432, 30, 50, 0, "dome"),   (460, 25, 42, 0, "flat"),
    (485, 40, 36, 0, "flat"),   (522, 20, 55, 0, "pointed"),
    (540, 35, 44, 0, "stepped"),(575, 45, 38, 0, "flat"),
    (618, 25, 50, 0, "pointed"),

    # Midground layer
    (5, 28, 60, 1, "pointed"),  (32, 35, 70, 1, "spire"),
    (65, 22, 52, 1, "flat"),    (85, 40, 78, 1, "stepped"),
    (122, 18, 55, 1, "flat"),   (138, 32, 85, 1, "spire"),
    (168, 25, 62, 1, "pointed"),(190, 38, 72, 1, "flat"),
    (226, 20, 58, 1, "flat"),   (244, 42, 80, 1, "pointed"),
    (284, 25, 55, 1, "flat"),   (308, 30, 90, 1, "spire"),
    (336, 22, 60, 1, "flat"),   (356, 36, 75, 1, "stepped"),
    (390, 28, 65, 1, "pointed"),(416, 40, 82, 1, "spire"),
    (454, 22, 55, 1, "flat"),   (474, 35, 70, 1, "pointed"),
    (508, 30, 78, 1, "stepped"),(536, 24, 58, 1, "flat"),
    (558, 38, 85, 1, "spire"),  (594, 22, 62, 1, "pointed"),
    (614, 30, 72, 1, "flat"),

    # Foreground layer (tallest, darkest)
    (10, 32, 75, 2, "flat"),    (48, 44, 95, 2, "spire"),
    (98, 26, 65, 2, "pointed"), (130, 50, 105, 2, "stepped"),
    (185, 30, 70, 2, "flat"),   (220, 48, 100, 2, "spire"),
    (275, 28, 68, 2, "pointed"),(310, 42, 92, 2, "flat"),
    (360, 32, 80, 2, "spire"),  (400, 50, 108, 2, "stepped"),
    (458, 26, 72, 2, "flat"),   (490, 44, 98, 2, "spire"),
    (540, 30, 65, 2, "pointed"),(578, 48, 88, 2, "flat"),
    (630, 28, 75, 2, "spire"),
]

# Building layer base colors (background → foreground)
# Blue/indigo tones like the pixel art inspo, not near-black
BUILDING_COLORS = [
    (55, 55, 100),   # Background: hazy light indigo
    (35, 38, 80),    # Midground: medium blue-indigo
    (18, 22, 55),    # Foreground: deep navy-blue
]

# Per-building color tints for variation (added to base layer color)
BUILDING_TINTS = [
    (0, 0, 0),       # neutral
    (10, 4, -6),     # warm brownish
    (-5, 3, 12),     # cool blue
    (6, 6, -2),      # slightly warm
    (-4, -2, 8),     # blue tint
    (8, 0, -4),      # warm muted
    (-2, 5, 10),     # teal hint
    (4, -3, -3),     # earthy
    (-6, 0, 14),     # strong blue
    (12, 6, 0),      # warm amber
]

# Antenna positions (building index, from foreground layer)
ANTENNA_BUILDINGS = [1, 3, 5, 8, 11, 14]


# ─── Astronomical calculations ──────────────────────────────────────────────

def julian_date(dt):
    """Calculate Julian Date from a datetime object."""
    y = dt.year
    m = dt.month
    d = dt.day + dt.hour / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0
    if m <= 2:
        y -= 1
        m += 12
    A = int(y / 100)
    B = 2 - A + int(A / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


def local_sidereal_time(dt, longitude):
    """Calculate Local Sidereal Time in degrees."""
    jd = julian_date(dt)
    T = (jd - 2451545.0) / 36525.0
    # Greenwich Mean Sidereal Time in degrees
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + \
           0.000387933 * T * T - T * T * T / 38710000.0
    gmst = gmst % 360.0
    lst = (gmst + longitude) % 360.0
    return lst


def star_alt_az(ra_hours, dec_deg, dt, lat, lon):
    """Convert RA/Dec to altitude/azimuth for given location and time."""
    lst = local_sidereal_time(dt, lon)
    ra_deg = ra_hours * 15.0
    ha = (lst - ra_deg) % 360.0

    ha_rad = math.radians(ha)
    dec_rad = math.radians(dec_deg)
    lat_rad = math.radians(lat)

    # Altitude
    sin_alt = (math.sin(dec_rad) * math.sin(lat_rad) +
               math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.degrees(math.asin(sin_alt))

    # Azimuth
    cos_az = (math.sin(dec_rad) - math.sin(alt * math.pi / 180) * math.sin(lat_rad)) / \
             (math.cos(alt * math.pi / 180) * math.cos(lat_rad) + 1e-10)
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    if math.sin(ha_rad) > 0:
        az = 360.0 - az

    return alt, az


def moon_phase(dt):
    """Calculate moon phase (0=new, 0.5=full, 1=new again) and illumination."""
    # Reference new moon: 2000-01-06 18:14 UTC
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    days = (dt - ref).total_seconds() / 86400.0
    synodic = 29.530588853
    phase = (days % synodic) / synodic
    # Illumination percentage
    illumination = (1 - math.cos(2 * math.pi * phase)) / 2.0
    return phase, illumination


def moon_position(dt, lat, lon):
    """Approximate moon position (very rough, good enough for visualization)."""
    jd = julian_date(dt)
    T = (jd - 2451545.0) / 36525.0

    # Simplified lunar position
    L0 = 218.3165 + 481267.8813 * T  # Mean longitude
    M = 134.9634 + 477198.8676 * T   # Mean anomaly
    F = 93.2720 + 483202.0175 * T    # Argument of latitude

    L0 = L0 % 360
    M_rad = math.radians(M % 360)
    F_rad = math.radians(F % 360)

    # Longitude correction
    lon_moon = L0 + 6.289 * math.sin(M_rad)
    lat_moon = 5.128 * math.sin(F_rad)

    # Convert ecliptic to equatorial (rough)
    obliquity = 23.439 - 0.0000004 * (jd - 2451545.0)
    obl_rad = math.radians(obliquity)
    lon_rad = math.radians(lon_moon)
    lat_rad = math.radians(lat_moon)

    ra = math.degrees(math.atan2(
        math.sin(lon_rad) * math.cos(obl_rad) - math.tan(lat_rad) * math.sin(obl_rad),
        math.cos(lon_rad)
    )) / 15.0  # Convert to hours
    ra = ra % 24

    dec = math.degrees(math.asin(
        math.sin(lat_rad) * math.cos(obl_rad) +
        math.cos(lat_rad) * math.sin(obl_rad) * math.sin(lon_rad)
    ))

    alt, az = star_alt_az(ra, dec, dt, lat, lon)
    return alt, az


# ─── Weather fetching ───────────────────────────────────────────────────────

def fetch_weather(lat, lon):
    """Fetch current weather from Open-Meteo (free, no API key)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,cloud_cover,"
        f"weather_code,wind_speed_10m"
        f"&temperature_unit=celsius&wind_speed_unit=kmh"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Skyforge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        current = data.get("current", {})
        return {
            "temperature": current.get("temperature_2m", 15),
            "humidity": current.get("relative_humidity_2m", 50),
            "cloud_cover": current.get("cloud_cover", 0),
            "weather_code": current.get("weather_code", 0),
            "wind_speed": current.get("wind_speed_10m", 0),
        }
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return {
            "temperature": 15,
            "humidity": 50,
            "cloud_cover": 0,
            "weather_code": 0,
            "wind_speed": 0,
        }


def weather_description(code):
    """Convert WMO weather code to short description."""
    descriptions = {
        0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
        45: "Foggy", 48: "Rime Fog", 51: "Light Drizzle", 53: "Drizzle",
        55: "Heavy Drizzle", 61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
        71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 80: "Rain Showers",
        81: "Heavy Showers", 82: "Violent Showers", 95: "Thunderstorm",
    }
    return descriptions.get(code, "Clear")


# ─── Raw image buffer (RGB) ─────────────────────────────────────────────────

class PixelCanvas:
    """Simple RGB pixel buffer with drawing primitives."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.pixels = [[(0, 0, 0)] * width for _ in range(height)]

    def set_pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y][x] = color

    def get_pixel(self, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.pixels[y][x]
        return (0, 0, 0)

    def fill_rect(self, x, y, w, h, color):
        for dy in range(h):
            for dx in range(w):
                self.set_pixel(x + dx, y + dy, color)

    def blend_pixel(self, x, y, color, alpha):
        """Blend color onto existing pixel with alpha (0.0 - 1.0)."""
        if 0 <= x < self.width and 0 <= y < self.height:
            bg = self.pixels[y][x]
            r = int(bg[0] * (1 - alpha) + color[0] * alpha)
            g = int(bg[1] * (1 - alpha) + color[1] * alpha)
            b = int(bg[2] * (1 - alpha) + color[2] * alpha)
            self.pixels[y][x] = (min(255, r), min(255, g), min(255, b))

    def draw_circle(self, cx, cy, radius, color):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    self.set_pixel(cx + dx, cy + dy, color)

    def draw_text(self, x, y, text, color, scale=1):
        """Draw text using the 3x5 pixel font."""
        cursor_x = x
        for ch in text.upper():
            glyph = FONT_3X5.get(ch)
            if glyph is None:
                cursor_x += 4 * scale
                continue
            for row_idx, row in enumerate(glyph):
                for col_idx, bit in enumerate(row):
                    if bit == '1':
                        for sy in range(scale):
                            for sx in range(scale):
                                self.set_pixel(
                                    cursor_x + col_idx * scale + sx,
                                    y + row_idx * scale + sy,
                                    color,
                                )
            cursor_x += (len(glyph[0]) + 1) * scale

    def draw_line(self, x0, y0, x1, y1, color, alpha=1.0):
        """Bresenham's line algorithm."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            if alpha < 1.0:
                self.blend_pixel(x0, y0, color, alpha)
            else:
                self.set_pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy


# ─── GIF encoder (minimal, no external dependencies) ────────────────────────

def build_color_table(frames):
    """Build a global color table from all frames (up to 256 colors via median cut)."""
    # Collect all unique colors across frames
    color_set = set()
    for frame in frames:
        for row in frame.pixels:
            for pixel in row:
                color_set.add(pixel)

    colors = list(color_set)

    if len(colors) <= 256:
        # Pad to power of 2
        table_size = 2
        while table_size < len(colors):
            table_size *= 2
        while len(colors) < table_size:
            colors.append((0, 0, 0))
        return colors

    # Median cut quantization to 256 colors
    return _median_cut(colors, 256)


def _median_cut(colors, max_colors):
    """Simple median cut color quantization."""
    buckets = [colors]

    while len(buckets) < max_colors:
        # Find the bucket with the widest range
        best_idx = 0
        best_range = -1
        for i, bucket in enumerate(buckets):
            if len(bucket) < 2:
                continue
            for ch in range(3):
                vals = [c[ch] for c in bucket]
                r = max(vals) - min(vals)
                if r > best_range:
                    best_range = r
                    best_idx = i
                    best_ch = ch

        if best_range <= 0:
            break

        bucket = buckets.pop(best_idx)
        bucket.sort(key=lambda c: c[best_ch])
        mid = len(bucket) // 2
        buckets.append(bucket[:mid])
        buckets.append(bucket[mid:])

    # Average each bucket to get palette colors
    palette = []
    for bucket in buckets:
        if not bucket:
            palette.append((0, 0, 0))
            continue
        r = sum(c[0] for c in bucket) // len(bucket)
        g = sum(c[1] for c in bucket) // len(bucket)
        b = sum(c[2] for c in bucket) // len(bucket)
        palette.append((r, g, b))

    while len(palette) < 256:
        palette.append((0, 0, 0))

    return palette[:256]


def color_index(color, palette):
    """Find closest color in palette."""
    best = 0
    best_dist = float('inf')
    for i, pc in enumerate(palette):
        dist = (color[0] - pc[0]) ** 2 + (color[1] - pc[1]) ** 2 + (color[2] - pc[2]) ** 2
        if dist == 0:
            return i
        if dist < best_dist:
            best_dist = dist
            best = i
    return best


def _build_palette_lookup(palette):
    """Build a dict for O(1) exact color lookups."""
    return {c: i for i, c in enumerate(palette)}


def _fast_color_index(color, lookup, palette):
    """Fast color index: exact match first, then nearest neighbor with caching."""
    idx = lookup.get(color)
    if idx is not None:
        return idx
    idx = color_index(color, palette)
    lookup[color] = idx  # Cache for future lookups
    return idx


def lzw_compress(indices, min_code_size):
    """LZW compression for GIF."""
    clear_code = 1 << min_code_size
    eoi_code = clear_code + 1

    code_table = {}
    for i in range(clear_code):
        code_table[(i,)] = i

    next_code = eoi_code + 1
    code_size = min_code_size + 1
    max_code = (1 << code_size)

    result_bits = []
    bit_buffer = 0
    bit_count = 0

    def emit(code, size):
        nonlocal bit_buffer, bit_count
        bit_buffer |= code << bit_count
        bit_count += size
        while bit_count >= 8:
            result_bits.append(bit_buffer & 0xFF)
            bit_buffer >>= 8
            bit_count -= 8

    emit(clear_code, code_size)

    if not indices:
        emit(eoi_code, code_size)
        if bit_count > 0:
            result_bits.append(bit_buffer & 0xFF)
        return bytes(result_bits)

    buffer = (indices[0],)

    for i in range(1, len(indices)):
        symbol = indices[i]
        test = buffer + (symbol,)
        if test in code_table:
            buffer = test
        else:
            emit(code_table[buffer], code_size)
            if next_code < 4096:
                code_table[test] = next_code
                next_code += 1
                if next_code > max_code and code_size < 12:
                    code_size += 1
                    max_code = 1 << code_size
            else:
                emit(clear_code, code_size)
                code_table = {}
                for j in range(clear_code):
                    code_table[(j,)] = j
                next_code = eoi_code + 1
                code_size = min_code_size + 1
                max_code = 1 << code_size
            buffer = (symbol,)

    emit(code_table[buffer], code_size)
    emit(eoi_code, code_size)

    if bit_count > 0:
        result_bits.append(bit_buffer & 0xFF)

    return bytes(result_bits)


def encode_gif(frames, palette, delay_ms=80, loop=0):
    """Encode frames into an animated GIF."""
    width = frames[0].width
    height = frames[0].height

    # Determine color table size
    table_size_bits = 1
    while (1 << table_size_bits) < len(palette):
        table_size_bits += 1
    table_size = 1 << table_size_bits

    out = io.BytesIO()

    # Header
    out.write(b"GIF89a")

    # Logical screen descriptor
    out.write(struct.pack("<HH", width, height))
    packed = 0x80 | ((table_size_bits - 1) << 4) | (table_size_bits - 1)
    out.write(struct.pack("BBB", packed, 0, 0))

    # Global color table
    for i in range(table_size):
        if i < len(palette):
            out.write(struct.pack("BBB", *palette[i]))
        else:
            out.write(b"\x00\x00\x00")

    # Netscape extension (looping)
    out.write(b"\x21\xFF\x0BNETSCAPE2.0\x03\x01")
    out.write(struct.pack("<H", loop))
    out.write(b"\x00")

    # Build palette lookup once
    lookup = _build_palette_lookup(palette)
    min_code_size = max(2, table_size_bits)

    for frame in frames:
        # Graphic control extension
        out.write(b"\x21\xF9\x04")
        out.write(struct.pack("B", 0x00))  # no transparency
        out.write(struct.pack("<H", delay_ms // 10))
        out.write(b"\x00\x00")

        # Image descriptor
        out.write(b"\x2C")
        out.write(struct.pack("<HHHH", 0, 0, width, height))
        out.write(b"\x00")  # no local color table

        # Build index data
        indices = []
        for row in frame.pixels:
            for pixel in row:
                indices.append(_fast_color_index(pixel, lookup, palette))

        # LZW compress
        compressed = lzw_compress(indices, min_code_size)

        out.write(struct.pack("B", min_code_size))

        # Sub-blocks
        pos = 0
        while pos < len(compressed):
            chunk = compressed[pos:pos + 255]
            out.write(struct.pack("B", len(chunk)))
            out.write(chunk)
            pos += 255
        out.write(b"\x00")

    # Trailer
    out.write(b"\x3B")

    return out.getvalue()


# ─── Scene rendering ────────────────────────────────────────────────────────

def _lerp_color(c1, c2, t):
    """Linearly interpolate between two RGB colors."""
    return (
        int(c1[0] * (1 - t) + c2[0] * t),
        int(c1[1] * (1 - t) + c2[1] * t),
        int(c1[2] * (1 - t) + c2[2] * t),
    )


def draw_sky_gradient(canvas):
    """Draw the night sky gradient background with multi-stop gradient."""
    city_y = canvas.height - 95  # Leave room for cityscape + HUD

    # Gradient stops: (position 0-1, color)
    stops = [
        (0.0, COLOR_SKY_TOP),
        (0.3, COLOR_SKY_MID1),
        (0.55, COLOR_SKY_MID2),
        (0.75, COLOR_SKY_MID3),
        (1.0, COLOR_HORIZON_GLOW),
    ]

    for y in range(city_y):
        t = y / city_y

        # Find the two stops we're between
        for i in range(len(stops) - 1):
            if t <= stops[i + 1][0]:
                local_t = (t - stops[i][0]) / (stops[i + 1][0] - stops[i][0])
                r, g, b = _lerp_color(stops[i][1], stops[i + 1][1], local_t)
                break
        else:
            r, g, b = stops[-1][1]

        # Quantize to pixel art steps
        step = PIXEL_SCALE * 2
        yq = (y // step) * step
        if yq != y:
            prev = canvas.get_pixel(0, yq)
            r, g, b = prev

        for x in range(canvas.width):
            canvas.set_pixel(x, y, (r, g, b))


# Maximum y coordinate for stars — must be above the tallest building
# tallest building = 108px, base_y = HEIGHT - 65, so top = HEIGHT - 173
# Add margin so stars aren't right at the building edge
STAR_CEILING_Y = HEIGHT - 185  # ~135px from top


def compute_visible_stars(dt):
    """Calculate which stars are visible and their screen positions."""
    visible = []

    for name, ra, dec, mag in BRIGHT_STARS:
        alt, az = star_alt_az(ra, dec, dt, LATITUDE, LONGITUDE)
        if alt < 5:  # Below horizon
            continue

        # Map azimuth to x (0-360 -> 0-WIDTH, with North at center)
        x = int(((az + 180) % 360) / 360.0 * WIDTH)
        # Map altitude to y (90° at top, 0° at horizon)
        # Use STAR_CEILING_Y so stars stay above the skyline
        y = int((1 - alt / 90.0) * STAR_CEILING_Y)

        # Star size based on magnitude
        size = max(1, int(3 - mag))

        visible.append({
            "name": name, "x": x, "y": y, "size": size,
            "mag": mag, "alt": alt, "az": az,
        })

    return visible


def draw_stars(canvas, visible_stars, frame_idx, rng):
    """Draw twinkling stars."""
    # Background dim stars (random but consistent per seed)
    bg_rng = random.Random(42)

    for _ in range(200):
        sx = bg_rng.randint(0, WIDTH - 1)
        sy = bg_rng.randint(0, STAR_CEILING_Y - 10)
        # Twinkle — varied speeds make field feel alive
        speed = 0.25 + (sx * 7 + sy * 3) % 11 * 0.04  # 0.25–0.69
        brightness = 0.2 + 0.8 * (0.5 + 0.5 * math.sin(
            frame_idx * speed + sx * 0.1 + sy * 0.17))
        if bg_rng.random() < 0.12:
            brightness *= 0.2  # Occasional deep flicker

        color = (
            int(COLOR_STAR_DIM[0] * brightness),
            int(COLOR_STAR_DIM[1] * brightness),
            int(COLOR_STAR_DIM[2] * brightness),
        )
        canvas.set_pixel(sx, sy, color)

    # Named bright stars — cross/diamond sparkle shapes
    for star in visible_stars:
        size = star["size"]
        x, y = star["x"], star["y"]
        name_hash = hash(star["name"])

        # Twinkle effect — bigger stars get more dramatic variation
        # Each star has its own phase offset and speed so they don't sync
        speed = 0.35 + 0.15 * (name_hash % 7) / 6  # 0.35–0.50 per frame
        phase = frame_idx * speed + name_hash * 0.1

        # Layer multiple sine waves for organic, less predictable twinkling
        wave1 = math.sin(phase)
        wave2 = math.sin(phase * 1.7 + 2.0)  # faster secondary wave
        wave3 = math.sin(phase * 0.4 + 5.0)  # slow drift

        if size >= 3:
            # Big named stars: dramatic twinkle (range 0.3–1.0)
            twinkle = 0.55 + 0.25 * wave1 + 0.12 * wave2 + 0.08 * wave3
            # Occasional bright flash for the biggest stars
            flash = math.sin(phase * 0.6 + name_hash)
            if flash > 0.92:
                twinkle = min(1.0, twinkle + 0.3)
        elif size >= 2:
            # Medium stars: moderate twinkle (range 0.4–1.0)
            twinkle = 0.65 + 0.20 * wave1 + 0.10 * wave2 + 0.05 * wave3
        else:
            # Small stars: subtle twinkle
            twinkle = 0.7 + 0.20 * wave1 + 0.10 * wave2

        twinkle = max(0.15, min(1.0, twinkle))

        color = (
            int(COLOR_STAR[0] * twinkle),
            int(COLOR_STAR[1] * twinkle),
            int(COLOR_STAR[2] * twinkle),
        )

        # Center pixel always bright
        canvas.set_pixel(x, y, color)

        if size >= 3:
            # Large star: 4-pointed cross sparkle with pulsing arm length
            base_arm = size + 1
            arm_len = max(2, int(base_arm * (0.6 + 0.4 * twinkle)))
            for d in range(1, arm_len + 1):
                alpha = (1.0 - d / (arm_len + 1)) * twinkle
                canvas.blend_pixel(x + d, y, color, alpha)
                canvas.blend_pixel(x - d, y, color, alpha)
                canvas.blend_pixel(x, y + d, color, alpha)
                canvas.blend_pixel(x, y - d, color, alpha)
            # Diagonal accents that pulse with twinkle
            diag_alpha = 0.35 * twinkle
            canvas.blend_pixel(x + 1, y + 1, color, diag_alpha)
            canvas.blend_pixel(x - 1, y - 1, color, diag_alpha)
            canvas.blend_pixel(x + 1, y - 1, color, diag_alpha)
            canvas.blend_pixel(x - 1, y + 1, color, diag_alpha)
            # Extra glow halo for brightest moments
            if twinkle > 0.85:
                glow_alpha = (twinkle - 0.85) * 2.0  # 0.0–0.30
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        canvas.blend_pixel(x + dx, y + dy, color, glow_alpha)
        elif size >= 2:
            # Medium star: small cross with pulsing
            arm_reach = 2 if twinkle > 0.6 else 1
            for d in range(1, arm_reach + 1):
                alpha = (1.0 - d / 3) * twinkle
                canvas.blend_pixel(x + d, y, color, alpha)
                canvas.blend_pixel(x - d, y, color, alpha)
                canvas.blend_pixel(x, y + d, color, alpha)
                canvas.blend_pixel(x, y - d, color, alpha)


def draw_constellation_lines(canvas, visible_stars):
    """Draw faint lines connecting constellation stars."""
    star_positions = {s["name"]: (s["x"], s["y"]) for s in visible_stars}

    for name1, name2 in CONSTELLATION_LINES:
        if name1 in star_positions and name2 in star_positions:
            x1, y1 = star_positions[name1]
            x2, y2 = star_positions[name2]
            canvas.draw_line(x1, y1, x2, y2, (40, 50, 80), alpha=0.3)


def draw_star_labels(canvas, visible_stars):
    """Label the brightest visible stars."""
    labeled = sorted(visible_stars, key=lambda s: s["mag"])[:8]
    for star in labeled:
        x = star["x"] + star["size"] + 3
        y = star["y"] - 2
        # Ensure label stays on screen
        name = star["name"]
        text_width = len(name) * 4
        if x + text_width > WIDTH - 5:
            x = star["x"] - text_width - 3
        if y < 2:
            y = 2
        canvas.draw_text(x, y, name, (100, 110, 140))


def draw_moon(canvas, dt, frame_idx):
    """Draw a prominent moon — always visible for aesthetics."""
    alt, az = moon_position(dt, LATITUDE, LONGITUDE)

    # If the moon is below horizon, place it at a nice decorative position
    if alt < 0:
        mx = WIDTH // 2 + 40
        my = 45
    else:
        mx = int(((az + 180) % 360) / 360.0 * WIDTH)
        my = int((1 - alt / 90.0) * STAR_CEILING_Y)
        mx = max(30, min(WIDTH - 30, mx))
        my = max(30, min(STAR_CEILING_Y - 30, my))

    radius = 22  # Larger, more prominent moon
    phase_val, illumination = moon_phase(dt)

    # Outer glow (large, soft)
    glow_color = (180, 200, 255)  # Blue-white glow
    for dy in range(-radius - 20, radius + 21):
        for dx in range(-radius - 20, radius + 21):
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < radius + 20:
                glow = max(0, 1 - dist / (radius + 20))
                canvas.blend_pixel(mx + dx, my + dy, glow_color, glow * glow * 0.12)

    # Inner glow (brighter ring)
    for dy in range(-radius - 8, radius + 9):
        for dx in range(-radius - 8, radius + 9):
            dist = math.sqrt(dx * dx + dy * dy)
            if radius < dist < radius + 8:
                glow = max(0, 1 - (dist - radius) / 8)
                canvas.blend_pixel(mx + dx, my + dy, COLOR_MOON, glow * 0.25)

    # Moon body with surface detail
    moon_detail_rng = random.Random(12345)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist_sq = dx * dx + dy * dy
            if dist_sq <= radius * radius:
                # Phase shadow (Northern Hemisphere view)
                # Waxing: shadow on left, receding rightward as phase grows
                # Waning: shadow on right, growing leftward as phase grows
                if phase_val < 0.5:
                    # Waxing: at phase 0 everything shadow, at 0.5 nothing shadow
                    terminator = radius * (1 - 4 * phase_val)
                    in_shadow = dx < terminator
                else:
                    # Waning: at phase 0.5 nothing shadow, at 1.0 everything shadow
                    terminator = radius * (3 - 4 * phase_val)
                    in_shadow = dx > terminator

                if in_shadow:
                    canvas.set_pixel(mx + dx, my + dy, COLOR_MOON_SHADOW)
                else:
                    # Surface detail: subtle darker patches (craters)
                    base = COLOR_MOON
                    detail_seed = ((dx + 50) * 73 + (dy + 50) * 37) % 100
                    if detail_seed < 12:
                        # Darker crater patches
                        base = (220, 225, 200)
                    elif detail_seed < 18:
                        base = (235, 235, 210)
                    canvas.set_pixel(mx + dx, my + dy, base)

                    # Edge shading for spherical look
                    edge_dist = math.sqrt(dist_sq) / radius
                    if edge_dist > 0.85:
                        darken = (edge_dist - 0.85) / 0.15 * 0.3
                        px = canvas.get_pixel(mx + dx, my + dy)
                        canvas.set_pixel(mx + dx, my + dy, (
                            int(px[0] * (1 - darken)),
                            int(px[1] * (1 - darken)),
                            int(px[2] * (1 - darken)),
                        ))


def _draw_building_roof(canvas, bx, bw, top_y, roof_type, color):
    """Draw a shaped roof on a building."""
    if roof_type == "pointed":
        # Triangular peak in the center
        peak_h = min(bw // 2, 12)
        cx = bx + bw // 2
        for dy in range(peak_h):
            span = int(bw / 2 * (1 - dy / peak_h))
            for dx in range(-span, span + 1):
                canvas.set_pixel(cx + dx, top_y - dy, color)
    elif roof_type == "spire":
        # Narrow spire rising from center
        spire_h = min(bw, 18)
        cx = bx + bw // 2
        for dy in range(spire_h):
            t = dy / spire_h
            half_w = max(0, int((1 - t) * bw // 4))
            for dx in range(-half_w, half_w + 1):
                canvas.set_pixel(cx + dx, top_y - dy, color)
    elif roof_type == "stepped":
        # Stepped/tiered top
        step_w = bw // 3
        step_h = 6
        # First step
        canvas.fill_rect(bx + step_w // 2, top_y - step_h,
                         bw - step_w, step_h, color)
        # Second step (narrower)
        canvas.fill_rect(bx + step_w, top_y - step_h * 2,
                         bw - step_w * 2, step_h, color)
    elif roof_type == "dome":
        # Rounded dome
        cx = bx + bw // 2
        dome_r = bw // 3
        for dy in range(dome_r):
            span = int(math.sqrt(max(0, dome_r * dome_r - dy * dy)))
            for dx in range(-span, span + 1):
                canvas.set_pixel(cx + dx, top_y - dy, color)
    # "flat" = no extra roof


def _tinted_color(base, tint_idx):
    """Apply a tint from BUILDING_TINTS to a base color."""
    tint = BUILDING_TINTS[tint_idx % len(BUILDING_TINTS)]
    return (
        max(0, min(255, base[0] + tint[0])),
        max(0, min(255, base[1] + tint[1])),
        max(0, min(255, base[2] + tint[2])),
    )


def draw_cityscape(canvas, frame_idx, rng):
    """Draw the cityscape silhouette with animated windows and varied rooftops."""
    base_y = HEIGHT - 65  # Bottom area reserved for HUD

    # Sort by layer so background draws first, foreground last
    sorted_buildings = sorted(enumerate(BUILDINGS), key=lambda b: b[1][3])

    for bldg_idx, (bx, bw, bh, layer, roof_type) in sorted_buildings:
        base_color = BUILDING_COLORS[layer]
        building_color = _tinted_color(base_color, bldg_idx)
        top_y = base_y - bh

        # Building body
        canvas.fill_rect(bx, top_y, bw, bh, building_color)

        # Left edge highlight (light source from left)
        edge_light = (
            min(255, building_color[0] + 8),
            min(255, building_color[1] + 8),
            min(255, building_color[2] + 12),
        )
        # Right edge shadow
        edge_dark = (
            max(0, building_color[0] - 5),
            max(0, building_color[1] - 5),
            max(0, building_color[2] - 5),
        )
        for y in range(top_y, base_y):
            canvas.set_pixel(bx, y, edge_light)
            canvas.set_pixel(bx + 1, y, edge_light)
            canvas.set_pixel(bx + bw - 1, y, edge_dark)

        # Roof shape
        _draw_building_roof(canvas, bx, bw, top_y, roof_type, building_color)

        # Horizontal ledge lines (top + mid-building band)
        ledge_color = (
            min(255, building_color[0] + 12),
            min(255, building_color[1] + 12),
            min(255, building_color[2] + 15),
        )
        for x in range(bx, bx + bw):
            canvas.set_pixel(x, top_y, ledge_color)
        # Mid-building accent band (for taller buildings)
        if bh > 50 and layer >= 1:
            band_y = top_y + bh // 3
            for x in range(bx, bx + bw):
                canvas.set_pixel(x, band_y, ledge_color)

        # Rooftop detail structures (only on flat/stepped mid+foreground buildings)
        if roof_type in ("flat", "stepped") and layer >= 1 and bw > 20:
            detail_seed = hash((bx, bw, bh)) % 5
            detail_color = (
                min(255, building_color[0] + 4),
                min(255, building_color[1] + 4),
                min(255, building_color[2] + 6),
            )
            roof_top = top_y if roof_type == "flat" else top_y - 12
            if detail_seed == 0:
                # Small rooftop box (AC unit)
                box_w = min(8, bw // 4)
                canvas.fill_rect(bx + 3, roof_top - 5, box_w, 5, detail_color)
            elif detail_seed == 1:
                # Water tank (cylinder approximation)
                tank_w = min(6, bw // 5)
                tank_h = 8
                cx = bx + bw - tank_w - 4
                canvas.fill_rect(cx, roof_top - tank_h, tank_w, tank_h, detail_color)
                # Tank stand legs
                canvas.set_pixel(cx + 1, roof_top, building_color)
                canvas.set_pixel(cx + tank_w - 2, roof_top, building_color)
            elif detail_seed == 2:
                # Small antenna/pole
                pole_x = bx + bw // 3
                for py in range(roof_top - 7, roof_top):
                    canvas.set_pixel(pole_x, py, detail_color)
            elif detail_seed == 3 and bw > 30:
                # Two small rooftop boxes
                box_w = min(6, bw // 5)
                canvas.fill_rect(bx + 3, roof_top - 4, box_w, 4, detail_color)
                canvas.fill_rect(bx + bw - box_w - 3, roof_top - 6, box_w, 6, detail_color)

        # Windows (grid pattern)
        win_w = 2 if layer == 0 else 3
        win_h = 3 if layer == 0 else 4
        win_gap_x = 5 if layer == 0 else 6
        win_gap_y = 6 if layer == 0 else 7
        win_on_pct = 25 if layer == 0 else (40 if layer == 1 else 50)

        for wy in range(top_y + 4, base_y - 4, win_gap_y):
            for wx in range(bx + 3, bx + bw - win_w - 1, win_gap_x):
                win_seed = hash((wx, wy)) % 100
                is_on = win_seed < win_on_pct
                if win_seed < 5:
                    is_on = (frame_idx // 6) % 2 == 0
                elif win_seed < 8:
                    is_on = (frame_idx // 12) % 2 == 0

                if is_on:
                    tint = hash((wx, wy, 99)) % 40
                    # Vary window color: some warm yellow, some warm orange
                    warm_shift = hash((wx, wy, 77)) % 3
                    if warm_shift == 0:
                        color = (
                            min(255, COLOR_WINDOW_ON[0] - tint),
                            min(255, COLOR_WINDOW_ON[1] - tint // 2),
                            COLOR_WINDOW_ON[2],
                        )
                    elif warm_shift == 1:
                        # Warmer orange
                        color = (
                            min(255, 255 - tint),
                            min(255, 180 - tint),
                            60,
                        )
                    else:
                        # Cooler white-ish
                        color = (
                            min(255, 220 - tint),
                            min(255, 210 - tint),
                            min(255, 160 - tint // 2),
                        )
                    # Background windows are dimmer
                    if layer == 0:
                        color = (color[0] * 2 // 3, color[1] * 2 // 3, color[2] * 2 // 3)
                    elif layer == 1:
                        color = (color[0] * 5 // 6, color[1] * 5 // 6, color[2] * 5 // 6)
                    canvas.fill_rect(wx, wy, win_w, win_h, color)
                else:
                    win_off = (
                        building_color[0] + 6,
                        building_color[1] + 6,
                        building_color[2] + 10,
                    )
                    canvas.fill_rect(wx, wy, win_w, win_h, win_off)

    # Antenna lights on tall foreground buildings
    fg_buildings = [b for b in BUILDINGS if b[3] == 2]
    for bidx in ANTENNA_BUILDINGS:
        if bidx < len(fg_buildings):
            bx, bw, bh, _, roof_type = fg_buildings[bidx]
            ax = bx + bw // 2
            # Adjust for roof height
            extra = 8 if roof_type in ("spire", "pointed") else 5
            ay = base_y - bh - extra

            # Antenna pole
            for y in range(ay, ay + 5):
                canvas.set_pixel(ax, y, (40, 35, 60))

            # Blinking red light
            blink = (frame_idx + bidx * 7) % 24
            if blink < 12:
                canvas.set_pixel(ax, ay, COLOR_ANTENNA_RED)
                canvas.blend_pixel(ax - 1, ay, COLOR_ANTENNA_RED, 0.3)
                canvas.blend_pixel(ax + 1, ay, COLOR_ANTENNA_RED, 0.3)
                canvas.blend_pixel(ax, ay - 1, COLOR_ANTENNA_RED, 0.3)
            else:
                canvas.set_pixel(ax, ay, COLOR_ANTENNA_OFF)


def draw_neon_divider(canvas, y):
    """Draw a neon gradient divider line."""
    for x in range(WIDTH):
        t = x / WIDTH
        r = int(COLOR_NEON_PINK[0] * (1 - t) + COLOR_NEON_CYAN[0] * t)
        g = int(COLOR_NEON_PINK[1] * (1 - t) + COLOR_NEON_CYAN[1] * t)
        b = int(COLOR_NEON_PINK[2] * (1 - t) + COLOR_NEON_CYAN[2] * t)
        canvas.set_pixel(x, y, (r, g, b))
        canvas.blend_pixel(x, y - 1, (r, g, b), 0.3)
        canvas.blend_pixel(x, y + 1, (r, g, b), 0.3)


def draw_shooting_star(canvas, frame_idx):
    """Draw an occasional shooting star."""
    # Shooting star appears every ~40 frames, lasts 8 frames
    cycle = 40
    start_frame = (frame_idx // cycle) * cycle + 5
    progress = frame_idx - start_frame

    if 0 <= progress < 8:
        rng = random.Random(start_frame)
        sx = rng.randint(100, WIDTH - 200)
        sy = rng.randint(20, 100)
        angle = rng.uniform(0.3, 0.8)

        length = progress * 8
        tail_length = min(length, 20)

        ex = sx + int(length * math.cos(angle))
        ey = sy + int(length * math.sin(angle))

        tx = ex - int(tail_length * math.cos(angle))
        ty = ey - int(tail_length * math.sin(angle))

        # Head (bright)
        canvas.set_pixel(ex, ey, COLOR_SHOOTING_STAR)
        canvas.blend_pixel(ex + 1, ey, COLOR_SHOOTING_STAR, 0.5)
        canvas.blend_pixel(ex, ey + 1, COLOR_SHOOTING_STAR, 0.3)

        # Tail (fading)
        canvas.draw_line(tx, ty, ex, ey, COLOR_SHOOTING_STAR, alpha=0.6)


def draw_clouds(canvas, cloud_cover, frame_idx):
    """Draw scrolling clouds based on cloud coverage."""
    if cloud_cover < 15:
        return

    sky_height = HEIGHT - 95
    num_clouds = max(1, cloud_cover // 15)
    cloud_rng = random.Random(123)

    for i in range(num_clouds):
        cy = cloud_rng.randint(30, sky_height - 40)
        base_cx = cloud_rng.randint(0, WIDTH)
        cloud_width = cloud_rng.randint(60, 140)
        cloud_height = cloud_rng.randint(10, 20)

        # Scroll based on frame
        speed = 0.5 + cloud_rng.random() * 1.0
        cx = int((base_cx + frame_idx * speed) % (WIDTH + cloud_width)) - cloud_width // 2

        opacity = min(0.7, cloud_cover / 100.0 * 0.8)

        # Draw cloud as overlapping ellipses
        for blob in range(3):
            bx = cx + blob * cloud_width // 4 - cloud_width // 4
            by = cy + (1 if blob == 1 else 3)
            bw = cloud_width // 2
            bh = cloud_height - (2 if blob != 1 else 0)

            for dy in range(-bh, bh + 1):
                for dx in range(-bw, bw + 1):
                    dist = (dx / bw) ** 2 + (dy / bh) ** 2
                    if dist < 1:
                        edge = 1 - dist
                        a = opacity * edge * 0.6
                        px, py = bx + dx, by + dy
                        if dist < 0.7:
                            canvas.blend_pixel(px, py, COLOR_CLOUD_EDGE, a)
                        else:
                            canvas.blend_pixel(px, py, COLOR_CLOUD, a * 0.7)


def draw_hud(canvas, weather, visible_stars, dt, phase_val, illumination):
    """Draw the weather and sky info HUD at the bottom."""
    hud_y = HEIGHT - 60

    # HUD background
    canvas.fill_rect(0, hud_y, WIDTH, 60, COLOR_HUD_BG)

    # Neon divider
    draw_neon_divider(canvas, hud_y)

    # Temperature and weather
    temp = weather["temperature"]
    desc = weather_description(weather["weather_code"])
    humidity = weather["humidity"]
    wind = weather["wind_speed"]
    cloud = weather["cloud_cover"]

    # Phase name
    if phase_val < 0.03 or phase_val > 0.97:
        phase_name = "New Moon"
    elif phase_val < 0.22:
        phase_name = "Waxing Crescent"
    elif phase_val < 0.28:
        phase_name = "First Quarter"
    elif phase_val < 0.47:
        phase_name = "Waxing Gibbous"
    elif phase_val < 0.53:
        phase_name = "Full Moon"
    elif phase_val < 0.72:
        phase_name = "Waning Gibbous"
    elif phase_val < 0.78:
        phase_name = "Last Quarter"
    else:
        phase_name = "Waning Crescent"

    # Left column: Weather
    col1_x = 15
    canvas.draw_text(col1_x, hud_y + 8, f"{temp:.0f}°C  {desc}", COLOR_NEON_CYAN, scale=2)
    canvas.draw_text(col1_x, hud_y + 24, f"Humidity {humidity}%  Wind {wind:.0f} km/h",
                     COLOR_HUD_TEXT, scale=1)
    canvas.draw_text(col1_x, hud_y + 34, f"Cloud Cover {cloud}%",
                     COLOR_HUD_TEXT, scale=1)

    # Middle column: Moon
    col2_x = 260
    canvas.draw_text(col2_x, hud_y + 8, phase_name, COLOR_NEON_PINK, scale=2)
    canvas.draw_text(col2_x, hud_y + 24, f"Illumination {illumination * 100:.0f}%",
                     COLOR_HUD_TEXT, scale=1)

    # Right column: Stars visible
    col3_x = 460
    canvas.draw_text(col3_x, hud_y + 8, f"{len(visible_stars)} Stars Visible",
                     COLOR_NEON_PURPLE, scale=2)

    # Star names (top 5)
    top_stars = sorted(visible_stars, key=lambda s: s["mag"])[:6]
    star_names = ", ".join(s["name"] for s in top_stars)
    # Truncate if too long
    if len(star_names) > 50:
        star_names = star_names[:47] + "..."
    canvas.draw_text(col3_x, hud_y + 24, star_names, COLOR_HUD_TEXT, scale=1)

    # Location and date
    date_str = dt.strftime("%Y-%m-%d %H:%M PDT")
    canvas.draw_text(col1_x, hud_y + 44, f"Skyforge ~ {CITY_NAME} ~ {date_str}",
                     (100, 100, 120), scale=1)

    # Credits
    canvas.draw_text(WIDTH - 140, hud_y + 44, "github.com/hn6767",
                     (80, 80, 100), scale=1)


def generate_frame(frame_idx, visible_stars, weather, dt, phase_val, illumination, rng):
    """Generate a single frame of the animation."""
    canvas = PixelCanvas(WIDTH, HEIGHT)

    # Sky gradient
    draw_sky_gradient(canvas)

    # Constellation lines (behind stars)
    draw_constellation_lines(canvas, visible_stars)

    # Stars (twinkling)
    draw_stars(canvas, visible_stars, frame_idx, rng)

    # Star labels
    if frame_idx == 0:  # Only on reference frame calc, labels are static
        pass  # Labels drawn on all frames below
    draw_star_labels(canvas, visible_stars)

    # Moon
    draw_moon(canvas, dt, frame_idx)

    # Clouds
    draw_clouds(canvas, weather["cloud_cover"], frame_idx)

    # Shooting star
    draw_shooting_star(canvas, frame_idx)

    # Cityscape
    draw_cityscape(canvas, frame_idx, rng)

    # HUD
    draw_hud(canvas, weather, visible_stars, dt, phase_val, illumination)

    return canvas


def main():
    """Generate the skyforge animated GIF."""
    print("Skyforge — Generating night sky for", CITY_NAME)

    # Use ~11 PM local time tonight
    now_utc = datetime.now(timezone.utc)
    local_offset = timedelta(hours=TIMEZONE_OFFSET)
    local_now = now_utc + local_offset

    # Set to 11 PM tonight
    target = local_now.replace(hour=23, minute=0, second=0, microsecond=0)
    target_utc = target - local_offset

    print(f"  Target time: {target.strftime('%Y-%m-%d %H:%M')} local")
    print(f"  UTC: {target_utc.strftime('%Y-%m-%d %H:%M')}")

    # Fetch weather
    print("  Fetching weather data...")
    weather = fetch_weather(LATITUDE, LONGITUDE)
    desc = weather_description(weather["weather_code"])
    print(f"  Weather: {weather['temperature']:.1f}°C, {desc}, "
          f"{weather['cloud_cover']}% clouds")

    # Compute star positions
    print("  Computing star positions...")
    visible_stars = compute_visible_stars(target_utc)
    print(f"  {len(visible_stars)} bright stars visible")
    for s in sorted(visible_stars, key=lambda x: x["mag"])[:5]:
        print(f"    {s['name']} (mag {s['mag']:.1f}, alt {s['alt']:.0f}°)")

    # Moon phase
    phase_val, illumination = moon_phase(target_utc)
    print(f"  Moon phase: {phase_val:.2f}, illumination: {illumination * 100:.0f}%")

    moon_alt, moon_az = moon_position(target_utc, LATITUDE, LONGITUDE)
    print(f"  Moon position: alt {moon_alt:.1f}°, az {moon_az:.1f}°")

    # Generate frames
    print(f"  Generating {FRAME_COUNT} frames...")
    rng = random.Random(int(target.strftime("%Y%m%d")))
    frames = []
    for i in range(FRAME_COUNT):
        if (i + 1) % 12 == 0:
            print(f"    Frame {i + 1}/{FRAME_COUNT}")
        frames.append(generate_frame(
            i, visible_stars, weather, target_utc, phase_val, illumination, rng
        ))

    # Build color palette
    print("  Building color palette...")
    palette = build_color_table(frames)
    print(f"  Palette: {len(palette)} colors")

    # Encode GIF
    print("  Encoding GIF...")
    gif_data = encode_gif(frames, palette, delay_ms=FRAME_DELAY_MS)

    output_path = "skyforge.gif"
    with open(output_path, "wb") as f:
        f.write(gif_data)

    size_kb = len(gif_data) / 1024
    print(f"  Output: {output_path} ({size_kb:.0f} KB)")
    print("Done!")


if __name__ == "__main__":
    main()
