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
COLOR_SKY_TOP = (8, 8, 32)
COLOR_SKY_MID = (16, 12, 48)
COLOR_SKY_BOTTOM = (32, 20, 64)
COLOR_HORIZON_GLOW = (80, 40, 100)
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
]

# ─── Constellation lines (pairs of star names to connect) ───────────────────

CONSTELLATION_LINES = [
    # Ursa Major (Big Dipper)
    ("Dubhe", "Merak"), ("Merak", "Phecda"), ("Phecda", "Megrez"),
    ("Megrez", "Mizar"), ("Mizar", "Alkaid"), ("Megrez", "Dubhe"),
    # Orion (partial)
    ("Betelgeuse", "Bellatrix"), ("Betelgeuse", "Alnilam"),
    ("Bellatrix", "Alnilam"), ("Alnilam", "Alnitak"), ("Alnilam", "Rigel"),
    # Summer Triangle
    ("Vega", "Deneb"), ("Vega", "Altair"), ("Deneb", "Altair"),
]

# ─── Cityscape buildings (x, width, height) ────────────────────────────────

BUILDINGS = [
    (0, 30, 55), (25, 20, 45), (42, 38, 70), (76, 24, 48),
    (96, 16, 36), (108, 35, 65), (138, 28, 50), (162, 20, 40),
    (178, 42, 75), (216, 24, 44), (236, 30, 58), (262, 16, 32),
    (274, 38, 68), (308, 24, 48), (328, 20, 55), (344, 35, 44),
    (375, 28, 72), (399, 16, 36), (411, 38, 64), (445, 24, 52),
    (465, 30, 40), (491, 20, 60), (507, 42, 68), (545, 24, 48),
    (565, 16, 36), (577, 38, 55), (611, 28, 44), (635, 20, 52),
]

# Antenna positions (building index, relative x offset)
ANTENNA_BUILDINGS = [2, 8, 12, 16, 22]


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

def draw_sky_gradient(canvas):
    """Draw the night sky gradient background."""
    city_y = canvas.height - 95  # Leave room for cityscape + HUD

    for y in range(city_y):
        t = y / city_y
        if t < 0.5:
            # Top half: dark to mid
            s = t / 0.5
            r = int(COLOR_SKY_TOP[0] * (1 - s) + COLOR_SKY_MID[0] * s)
            g = int(COLOR_SKY_TOP[1] * (1 - s) + COLOR_SKY_MID[1] * s)
            b = int(COLOR_SKY_TOP[2] * (1 - s) + COLOR_SKY_MID[2] * s)
        else:
            # Bottom half: mid to horizon glow
            s = (t - 0.5) / 0.5
            r = int(COLOR_SKY_MID[0] * (1 - s) + COLOR_HORIZON_GLOW[0] * s)
            g = int(COLOR_SKY_MID[1] * (1 - s) + COLOR_HORIZON_GLOW[1] * s)
            b = int(COLOR_SKY_MID[2] * (1 - s) + COLOR_HORIZON_GLOW[2] * s)

        # Quantize to pixel art steps
        step = PIXEL_SCALE * 2
        yq = (y // step) * step
        if yq != y:
            prev = canvas.get_pixel(0, yq)
            r, g, b = prev

        for x in range(canvas.width):
            canvas.set_pixel(x, y, (r, g, b))


def compute_visible_stars(dt):
    """Calculate which stars are visible and their screen positions."""
    sky_height = HEIGHT - 95
    visible = []

    for name, ra, dec, mag in BRIGHT_STARS:
        alt, az = star_alt_az(ra, dec, dt, LATITUDE, LONGITUDE)
        if alt < 5:  # Below horizon
            continue

        # Map azimuth to x (0-360 -> 0-WIDTH, with North at center)
        x = int(((az + 180) % 360) / 360.0 * WIDTH)
        # Map altitude to y (90° at top, 0° at horizon)
        y = int((1 - alt / 90.0) * sky_height)

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
    sky_height = HEIGHT - 95

    for _ in range(200):
        sx = bg_rng.randint(0, WIDTH - 1)
        sy = bg_rng.randint(0, sky_height - 20)
        # Twinkle
        brightness = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(
            frame_idx * 0.3 + sx * 0.1 + sy * 0.17))
        if bg_rng.random() < 0.1:
            brightness *= 0.3  # Occasional flicker

        color = (
            int(COLOR_STAR_DIM[0] * brightness),
            int(COLOR_STAR_DIM[1] * brightness),
            int(COLOR_STAR_DIM[2] * brightness),
        )
        canvas.set_pixel(sx, sy, color)

    # Named bright stars
    for star in visible_stars:
        # Twinkle effect
        phase = frame_idx * 0.2 + hash(star["name"]) * 0.1
        twinkle = 0.7 + 0.3 * math.sin(phase)

        color = (
            int(COLOR_STAR[0] * twinkle),
            int(COLOR_STAR[1] * twinkle),
            int(COLOR_STAR[2] * twinkle),
        )

        size = star["size"]
        x, y = star["x"], star["y"]

        if size >= 3:
            # Large star: cross pattern
            canvas.set_pixel(x, y, color)
            for d in range(1, size):
                alpha = 1.0 - d / size
                canvas.blend_pixel(x + d, y, color, alpha * twinkle)
                canvas.blend_pixel(x - d, y, color, alpha * twinkle)
                canvas.blend_pixel(x, y + d, color, alpha * twinkle)
                canvas.blend_pixel(x, y - d, color, alpha * twinkle)
        elif size >= 2:
            canvas.set_pixel(x, y, color)
            canvas.blend_pixel(x + 1, y, color, 0.5 * twinkle)
            canvas.blend_pixel(x - 1, y, color, 0.5 * twinkle)
            canvas.blend_pixel(x, y + 1, color, 0.5 * twinkle)
            canvas.blend_pixel(x, y - 1, color, 0.5 * twinkle)
        else:
            canvas.set_pixel(x, y, color)


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
    """Draw the moon with its current phase."""
    alt, az = moon_position(dt, LATITUDE, LONGITUDE)

    if alt < 0:
        return  # Moon below horizon

    sky_height = HEIGHT - 95
    mx = int(((az + 180) % 360) / 360.0 * WIDTH)
    my = int((1 - alt / 90.0) * sky_height)

    # Clamp to visible area
    mx = max(20, min(WIDTH - 20, mx))
    my = max(20, min(sky_height - 20, my))

    radius = 12
    phase, illumination = moon_phase(dt)

    # Draw moon glow
    for dy in range(-radius - 6, radius + 7):
        for dx in range(-radius - 6, radius + 7):
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < radius + 6:
                glow = max(0, 1 - dist / (radius + 6))
                canvas.blend_pixel(mx + dx, my + dy, COLOR_MOON, glow * 0.15)

    # Draw moon body
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                # Determine if this pixel is in shadow based on phase
                # phase 0 = new (all shadow), 0.25 = first quarter, 0.5 = full, etc.
                if phase < 0.5:
                    # Waxing: shadow on the left
                    terminator = (2 * phase - 0.5) * 2 * radius
                    if dx < terminator:
                        canvas.set_pixel(mx + dx, my + dy, COLOR_MOON_SHADOW)
                    else:
                        canvas.set_pixel(mx + dx, my + dy, COLOR_MOON)
                else:
                    # Waning: shadow on the right
                    terminator = (1.5 - 2 * phase) * 2 * radius
                    if dx > terminator:
                        canvas.set_pixel(mx + dx, my + dy, COLOR_MOON_SHADOW)
                    else:
                        canvas.set_pixel(mx + dx, my + dy, COLOR_MOON)


def draw_cityscape(canvas, frame_idx, rng):
    """Draw the cityscape silhouette with animated windows."""
    base_y = HEIGHT - 65  # Bottom area reserved for HUD

    for bx, bw, bh in BUILDINGS:
        # Building body
        canvas.fill_rect(bx, base_y - bh, bw, bh, COLOR_BUILDING)

        # Windows (grid pattern)
        win_w = 3
        win_h = 4
        win_gap_x = 6
        win_gap_y = 7

        for wy in range(base_y - bh + 4, base_y - 4, win_gap_y):
            for wx in range(bx + 3, bx + bw - win_w - 1, win_gap_x):
                # Each window has a consistent random on/off state that can change
                win_seed = hash((wx, wy)) % 100
                # Some windows flicker
                is_on = win_seed < 40
                if win_seed < 5:
                    is_on = (frame_idx // 6) % 2 == 0  # Flickering window
                elif win_seed < 8:
                    is_on = (frame_idx // 12) % 2 == 0  # Slow flicker

                if is_on:
                    # Random warm tint
                    tint = hash((wx, wy, 99)) % 40
                    color = (
                        min(255, COLOR_WINDOW_ON[0] - tint),
                        min(255, COLOR_WINDOW_ON[1] - tint // 2),
                        COLOR_WINDOW_ON[2],
                    )
                    canvas.fill_rect(wx, wy, win_w, win_h, color)
                else:
                    canvas.fill_rect(wx, wy, win_w, win_h, COLOR_WINDOW_OFF)

    # Antenna lights on tall buildings
    for bidx in ANTENNA_BUILDINGS:
        if bidx < len(BUILDINGS):
            bx, bw, bh = BUILDINGS[bidx]
            ax = bx + bw // 2
            ay = base_y - bh - 5

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
