#!/usr/bin/env python3
"""
SKYFORGE v2 — Living night sky over San Francisco.

Uses a pixel-art base image (generated via Grok/Midjourney/etc.) and composites
dynamic layers on top: real star positions with labels, accurate moon phase,
live weather data, twinkling animation, and a shooting star.

The base image provides the beautiful cityscape; Python adds the living data.
"""

import math
import random
import os
import sys
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

try:
    import ephem
except ImportError:
    ephem = None

try:
    import requests
except ImportError:
    requests = None

# ─── Configuration ───────────────────────────────────────────────────────────

# Output dimensions for GitHub README (must be under 5MB)
OUTPUT_WIDTH = 840
OUTPUT_HEIGHT = 360
NUM_FRAMES = 30
FRAME_DELAY_MS = 150

# Location: San Jose / SF Bay Area
DEFAULT_LAT = 37.3382
DEFAULT_LON = -121.8863
LOCATION_NAME = "Bay Area, CA"

# The sky region in the base image (where we overlay stars/moon)
# This defines the rectangle in the OUTPUT image where sky is visible
# We'll detect this from the image or define it manually
SKY_Y_MAX_FRAC = 0.52  # Sky occupies roughly the top 52% of the image

# Color palette for overlays
NEON_CYAN = (0, 255, 220)
NEON_PINK = (255, 0, 180)
NEON_GREEN = (0, 255, 65)
LABEL_COLOR = (200, 210, 230)
HUD_BG = (5, 5, 20)
TEMP_COLOR = (0, 255, 220)
SHOOTING_STAR_COLOR = (220, 240, 255)

# Star catalog: (name, RA_hours, Dec_degrees, magnitude)
BRIGHT_STARS = [
    ("Sirius", 6.752, -16.72, -1.46),
    ("Arcturus", 14.261, 19.18, -0.05),
    ("Vega", 18.616, 38.78, 0.03),
    ("Capella", 5.278, 46.00, 0.08),
    ("Rigel", 5.242, -8.20, 0.13),
    ("Procyon", 7.655, 5.22, 0.34),
    ("Betelgeuse", 5.919, 7.41, 0.42),
    ("Altair", 19.846, 8.87, 0.76),
    ("Aldebaran", 4.599, 16.51, 0.86),
    ("Spica", 13.420, -11.16, 0.97),
    ("Antares", 16.490, -26.43, 1.04),
    ("Pollux", 7.755, 28.03, 1.14),
    ("Deneb", 20.690, 45.28, 1.25),
    ("Regulus", 10.140, 11.97, 1.35),
    ("Polaris", 2.530, 89.26, 1.98),
    ("Dubhe", 11.062, 61.75, 1.79),
    ("Mizar", 13.399, 54.93, 2.27),
    ("Alioth", 12.900, 55.96, 1.77),
    ("Alkaid", 13.792, 49.31, 1.86),
    ("Castor", 7.577, 31.89, 1.58),
]

STAR_COLORS = {
    "Sirius": (180, 210, 255),
    "Vega": (180, 200, 255),
    "Rigel": (170, 200, 255),
    "Betelgeuse": (255, 180, 120),
    "Aldebaran": (255, 190, 130),
    "Antares": (255, 170, 120),
    "Arcturus": (255, 210, 160),
    "Capella": (255, 240, 200),
    "Pollux": (255, 230, 180),
}
DEFAULT_STAR_COLOR = (255, 255, 240)


# ─── Astronomy ───────────────────────────────────────────────────────────────

def get_lst(lon_deg, utc_dt):
    """Local Sidereal Time in hours."""
    jd = (utc_dt - datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)).total_seconds() / 86400.0 + 2451545.0
    T = (jd - 2451545.0) / 36525.0
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T * T) % 360
    return ((gmst + lon_deg) % 360) / 15.0


def star_altaz(ra_h, dec_deg, lat_deg, lst_h):
    """RA/Dec → altitude/azimuth."""
    ha_rad = math.radians((lst_h - ra_h) * 15.0)
    dec_rad = math.radians(dec_deg)
    lat_rad = math.radians(lat_deg)
    sin_alt = math.sin(dec_rad) * math.sin(lat_rad) + math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad)
    alt = math.degrees(math.asin(max(-1, min(1, sin_alt))))
    cos_az = (math.sin(dec_rad) - math.sin(math.radians(alt)) * math.sin(lat_rad)) / (math.cos(math.radians(alt)) * math.cos(lat_rad) + 1e-10)
    az = math.degrees(math.acos(max(-1, min(1, cos_az))))
    if math.sin(ha_rad) > 0:
        az = 360 - az
    return alt, az


def get_visible_stars(lat, lon, utc_dt):
    """Return visible stars as (name, x_frac, y_frac, magnitude)."""
    lst = get_lst(lon, utc_dt)
    visible = []
    for name, ra, dec, mag in BRIGHT_STARS:
        alt, az = star_altaz(ra, dec, lat, lst)
        if alt > 8:
            y_frac = 1.0 - (alt / 90.0)
            x_frac = az / 360.0
            visible.append((name, x_frac, y_frac, mag))
    return visible


def get_moon_info(lat, lon, utc_dt):
    """Moon phase (0-1), altitude, azimuth."""
    if ephem:
        obs = ephem.Observer()
        obs.lat, obs.lon = str(lat), str(lon)
        obs.date = utc_dt.strftime('%Y/%m/%d %H:%M:%S')
        moon = ephem.Moon(obs)
        return moon.phase / 100.0, float(moon.alt) * 180 / math.pi, float(moon.az) * 180 / math.pi
    ref = datetime(2024, 1, 11, 11, 57, 0, tzinfo=timezone.utc)
    cycle = ((utc_dt - ref).total_seconds() / 86400.0 % 29.53) / 29.53
    return 0.5 * (1 - math.cos(2 * math.pi * cycle)), 45, 200


def get_weather(lat, lon):
    """Fetch from Open-Meteo (free, no key)."""
    if not requests:
        return {"temp_c": 15, "condition": "clear", "humidity": 50, "wind_kmh": 10}
    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
               f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code&timezone=auto")
        data = requests.get(url, timeout=10).json().get("current", {})
        wmo = data.get("weather_code", 0)
        cond = ("clear" if wmo <= 1 else "cloudy" if wmo <= 3 else "fog" if wmo <= 48 else
                "rain" if wmo <= 67 else "snow" if wmo <= 77 else "storm")
        return {"temp_c": data.get("temperature_2m", 15), "condition": cond,
                "humidity": data.get("relative_humidity_2m", 50),
                "wind_kmh": data.get("wind_speed_10m", 10)}
    except Exception:
        return {"temp_c": 15, "condition": "clear", "humidity": 50, "wind_kmh": 10}


# ─── Drawing helpers ─────────────────────────────────────────────────────────

def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_star_cross(draw, x, y, size, color, glow_color=None):
    """Draw a pixel-art star with cross/diamond shape."""
    draw.point((x, y), fill=(255, 255, 255))  # Bright center

    if size >= 3:
        # 4-point cross
        for d in range(1, size):
            alpha = 1.0 - d / size
            c = tuple(int(v * alpha) for v in color)
            draw.point((x + d, y), fill=c)
            draw.point((x - d, y), fill=c)
            draw.point((x, y + d), fill=c)
            draw.point((x, y - d), fill=c)
        # Diagonal glow for biggest stars
        if size >= 4 and glow_color:
            for d in range(1, size - 1):
                alpha = 0.4 * (1.0 - d / size)
                c = tuple(int(v * alpha) for v in glow_color)
                draw.point((x + d, y + d), fill=c)
                draw.point((x - d, y - d), fill=c)
                draw.point((x + d, y - d), fill=c)
                draw.point((x - d, y + d), fill=c)
    elif size == 2:
        draw.rectangle([x, y, x + 1, y + 1], fill=color)
    # size 1 = just the center point


def draw_moon_overlay(draw, phase, cx, cy, radius=14):
    """Draw a pixel-art moon with correct phase at given position."""
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= radius:
                # Phase terminator
                if phase < 0.5:
                    illum = phase * 2
                    terminator = radius * (1 - 2 * illum)
                    lit = dx > terminator
                else:
                    illum = (1 - phase) * 2
                    terminator = -radius * (1 - 2 * illum)
                    lit = dx < terminator

                if lit:
                    # Moon surface: slight variation
                    glow_t = dist / radius
                    bright = int(255 * (1.0 - glow_t * 0.3))
                    color = (bright, int(bright * 0.98), int(bright * 0.9))
                else:
                    # Shadow side — very dark, nearly transparent
                    color = (15, 12, 30)

                # Edge anti-alias
                if abs(dist - radius) < 1.2:
                    color = tuple(c // 2 for c in color)

                px, py = cx + dx, cy + dy
                if 0 <= px < OUTPUT_WIDTH and 0 <= py < int(OUTPUT_HEIGHT * SKY_Y_MAX_FRAC):
                    draw.point((px, py), fill=color)

    # Glow halo
    for dy in range(-radius - 5, radius + 6):
        for dx in range(-radius - 5, radius + 6):
            dist = math.sqrt(dx * dx + dy * dy)
            if radius < dist <= radius + 5:
                px, py = cx + dx, cy + dy
                if 0 <= px < OUTPUT_WIDTH and 0 <= py < int(OUTPUT_HEIGHT * SKY_Y_MAX_FRAC):
                    strength = 1.0 - (dist - radius) / 5.0
                    glow = (int(60 * strength), int(55 * strength), int(40 * strength))
                    draw.point((px, py), fill=glow)


def draw_shooting_star(overlay_draw, frame, total_frames):
    """Animated shooting star in certain frame windows."""
    cycle = frame % total_frames
    if 4 <= cycle <= 10:
        t = (cycle - 4) / 6.0
        sx, sy = 580, 25
        ex, ey = 480, 95
        cx = int(sx + (ex - sx) * t)
        cy = int(sy + (ey - sy) * t)

        trail_len = 25
        for i in range(trail_len):
            tt = max(0, t - i * 0.015)
            tx = int(sx + (ex - sx) * tt)
            ty = int(sy + (ey - sy) * tt)
            alpha = (1.0 - i / trail_len) ** 1.5
            brightness = int(255 * alpha)
            if 0 <= tx < OUTPUT_WIDTH and 0 <= ty < OUTPUT_HEIGHT:
                color = (brightness, brightness, int(brightness * 0.85))
                overlay_draw.point((tx, ty), fill=color)
                if i < 3:
                    # Wider head
                    overlay_draw.point((tx, ty + 1), fill=(brightness // 2, brightness // 2, brightness // 3))


def draw_hud_bar(draw, width, height, weather, moon_phase, visible_stars, date_str):
    """Draw the retro HUD at the bottom of the image."""
    bar_h = 38
    bar_y = height - bar_h

    # Semi-transparent dark bar
    for y in range(bar_y, height):
        t = (y - bar_y) / bar_h
        alpha = 0.75 + 0.15 * t
        color = (int(5 * alpha), int(4 * alpha), int(15 * alpha))
        draw.line([(0, y), (width, y)], fill=color)

    # Neon gradient divider
    for x in range(8, width - 8):
        t = x / width
        c = lerp(NEON_CYAN, NEON_PINK, t)
        c = tuple(v // 3 for v in c)
        draw.point((x, bar_y + 1), fill=c)

    font = get_font(10)
    font_sm = get_font(9)
    ty = bar_y + 8

    # Temperature
    tc = weather["temp_c"]
    tf = tc * 9 / 5 + 32
    draw.text((15, ty), f"{tc:.0f}°C / {tf:.0f}°F", fill=TEMP_COLOR, font=font)
    draw.text((15, ty + 14), weather["condition"].upper(), fill=(140, 140, 160), font=font_sm)

    # Moon phase
    phases = [(0.05, "NEW"), (0.25, "WAXING CRES"), (0.45, "FIRST QTR"),
              (0.55, "FULL"), (0.75, "WANING GIB"), (0.95, "LAST QTR"), (1.01, "WANING CRES")]
    phase_name = next(name for threshold, name in phases if moon_phase < threshold)
    mx = width // 2 - 60
    draw.text((mx, ty), f"☾ {phase_name}", fill=NEON_PINK, font=font)

    # Visible stars
    names = [n for n, _, _, _ in visible_stars[:5]]
    if names:
        draw.text((mx - 20, ty + 14), " · ".join(names), fill=(80, 85, 110), font=font_sm)

    # Location & date
    rx = width - 170
    draw.text((rx, ty), LOCATION_NAME, fill=NEON_GREEN, font=font)
    draw.text((rx, ty + 14), date_str, fill=(100, 100, 120), font=font_sm)

    # Branding
    draw.text((width - 68, bar_y + 26), "SKYFORGE", fill=(35, 35, 50), font=font_sm)


def create_sky_mask(base_img):
    """Create a mask of the sky region in the base image.
    Sky pixels are typically very dark (deep blue/black). We detect them
    so we only overlay stars where there's actual sky, not on buildings."""
    w, h = base_img.size
    sky_h = int(h * SKY_Y_MAX_FRAC)
    mask = Image.new('L', (w, h), 0)
    pixels = base_img.load()
    mask_pixels = mask.load()

    for y in range(sky_h):
        for x in range(w):
            r, g, b = pixels[x, y][:3]
            brightness = r + g + b
            # Sky pixels: dark, blue-ish
            if brightness < 120 and b >= r * 0.7:
                # Darker = more likely sky
                confidence = max(0, min(255, int(255 * (1.0 - brightness / 150))))
                mask_pixels[x, y] = confidence

    return mask


# ─── Main generation ─────────────────────────────────────────────────────────

def generate_frames(base_path, lat, lon, utc_dt):
    """Generate all animation frames."""
    print("  📐 Loading and resizing base image...")
    base_full = Image.open(base_path).convert('RGB')
    base = base_full.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.LANCZOS)

    print("  🎭 Creating sky mask...")
    sky_mask = create_sky_mask(base)

    print("  🌡️  Fetching weather...")
    weather = get_weather(lat, lon)
    print(f"     → {weather['temp_c']:.1f}°C, {weather['condition']}")

    print("  🌙 Computing moon...")
    moon_phase, moon_alt, moon_az = get_moon_info(lat, lon, utc_dt)
    print(f"     → Phase: {moon_phase:.0%}, Alt: {moon_alt:.1f}°")

    print("  ⭐ Computing star positions...")
    visible = get_visible_stars(lat, lon, utc_dt)
    print(f"     → {len(visible)} bright stars above horizon")

    local_offset = timedelta(hours=-7)
    date_str = (utc_dt + local_offset).strftime("%Y-%m-%d")

    sky_h = int(OUTPUT_HEIGHT * SKY_Y_MAX_FRAC)
    mask_pixels = sky_mask.load()

    # Precompute star screen positions
    star_positions = []
    for name, xf, yf, mag in visible:
        sx = int(xf * OUTPUT_WIDTH) % OUTPUT_WIDTH
        sy = int(yf * sky_h * 0.85) + 8
        # Check sky mask — only place stars where there's actual sky
        if 0 <= sx < OUTPUT_WIDTH and 0 <= sy < sky_h:
            if mask_pixels[sx, sy] > 40:
                size = 4 if mag < 0 else 3 if mag < 1 else 2 if mag < 1.8 else 1
                color = STAR_COLORS.get(name, DEFAULT_STAR_COLOR)
                star_positions.append((name, sx, sy, size, color, mag))

    # Precompute background twinkle stars
    random.seed(int(date_str.replace("-", "")))
    bg_stars = []
    for _ in range(180):
        bx = random.randint(0, OUTPUT_WIDTH - 1)
        by = random.randint(5, sky_h - 5)
        if mask_pixels[bx, by] > 60:
            bright = random.randint(80, 220)
            sz = 1 if random.random() > 0.1 else 2
            bg_stars.append((bx, by, bright, sz))

    # Moon position
    moon_x, moon_y = None, None
    if moon_alt > 5:
        moon_x = int((moon_az / 360.0) * OUTPUT_WIDTH) % OUTPUT_WIDTH
        moon_y = int((1.0 - moon_alt / 90.0) * sky_h * 0.7) + 15
        # Verify it's in sky region
        if not (0 <= moon_x < OUTPUT_WIDTH and 0 <= moon_y < sky_h):
            moon_x, moon_y = None, None
        elif mask_pixels[min(moon_x, OUTPUT_WIDTH - 1), min(moon_y, sky_h - 1)] < 30:
            moon_x, moon_y = None, None

    print(f"  🎞️  Generating {NUM_FRAMES} frames...")
    frames = []
    font_label = get_font(8)

    for f in range(NUM_FRAMES):
        # Start from base image copy
        frame = base.copy()
        draw = ImageDraw.Draw(frame)

        # ── Background twinkle stars ──
        for i, (bx, by, bright_base, sz) in enumerate(bg_stars):
            phase = (f * 0.18 + i * 0.7) % (2 * math.pi)
            twinkle = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(phase))
            bright = int(bright_base * twinkle)
            c = (bright, bright, int(bright * 0.92))
            if sz == 1:
                draw.point((bx, by), fill=c)
            else:
                draw.rectangle([bx, by, bx + 1, by + 1], fill=c)

        # ── Real catalog stars ──
        for name, sx, sy, size, color, mag in star_positions:
            # Twinkle
            phase = (f * 0.14 + hash(name) * 0.3) % (2 * math.pi)
            twinkle = 0.5 + 0.5 * math.sin(phase)
            animated_size = size if twinkle > 0.3 else max(1, size - 1)

            bright_mult = 0.6 + 0.4 * twinkle
            anim_color = tuple(min(255, int(c * bright_mult)) for c in color)

            draw_star_cross(draw, sx, sy, animated_size, anim_color,
                           glow_color=color if size >= 3 else None)

            # Label for brightest stars
            if mag < 1.0 and twinkle > 0.4:
                label_alpha = int(180 * (0.5 + 0.5 * twinkle))
                label_c = (label_alpha, label_alpha, int(label_alpha * 0.85))
                draw.text((sx + size + 3, sy - 4), name, fill=label_c, font=font_label)

        # ── Moon ──
        if moon_x is not None and moon_y is not None:
            draw_moon_overlay(draw, moon_phase, moon_x, moon_y, radius=12)

        # ── Shooting star ──
        draw_shooting_star(draw, f, NUM_FRAMES)

        # ── HUD bar ──
        draw_hud_bar(draw, OUTPUT_WIDTH, OUTPUT_HEIGHT, weather, moon_phase, visible, date_str)

        frames.append(frame)

        if (f + 1) % 12 == 0:
            print(f"     → Frame {f + 1}/{NUM_FRAMES}")

    return frames


def main():
    print("🌌 SKYFORGE v2 — Living night sky (base image + dynamic layers)")

    base_path = os.environ.get("SKYFORGE_BASE", "base.png")
    lat = float(os.environ.get("SKYFORGE_LAT", DEFAULT_LAT))
    lon = float(os.environ.get("SKYFORGE_LON", DEFAULT_LON))
    output = os.environ.get("SKYFORGE_OUTPUT", "skyforge.gif")

    if not os.path.exists(base_path):
        print(f"  ❌ Base image not found: {base_path}")
        print(f"     Place your pixel-art cityscape as '{base_path}'")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    frames = generate_frames(base_path, lat, lon, now)

    print(f"  💾 Saving {output}...")
    # Quantize to 256 colors for GIF size optimization
    # This is critical — without it the GIF can exceed GitHub's 5MB camo proxy limit
    optimized = []
    for f in frames:
        optimized.append(f.quantize(colors=256, method=2, dither=1).convert('RGB'))

    optimized[0].save(output, save_all=True, append_images=optimized[1:],
                   duration=FRAME_DELAY_MS, loop=0, optimize=True)

    size_kb = os.path.getsize(output) / 1024
    print(f"  ✅ Done! {output} ({size_kb:.0f} KB)")
    if size_kb > 4500:
        print("  ⚠️  Close to GitHub's 5MB limit — consider reducing frames or dimensions")

    return output


if __name__ == "__main__":
    main()