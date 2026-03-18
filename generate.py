#!/usr/bin/env python3
"""
SKYFORGE — Living pixel-art night sky for your GitHub profile.

Two-image compositing: SKELETON (dark structure) + LIGHTMAP (lights on).
Python adds all dynamic elements: twinkling stars, shooting star, moon,
flickering windows, shimmering water, pulsing bridge lights, weather HUD.
"""

import math
import os
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import numpy as np

try:
    import ephem
except ImportError:
    ephem = None
try:
    import requests
except ImportError:
    requests = None

# ─── Config ──────────────────────────────────────────────────────────────────

OUTPUT_W = 840
OUTPUT_H = 360
NUM_FRAMES = 30
FRAME_DELAY_MS = 130

LAT = float(os.environ.get("SKYFORGE_LAT", "37.7749"))
LON = float(os.environ.get("SKYFORGE_LON", "-122.4194"))
LOCATION = os.environ.get("SKYFORGE_LOCATION", "SF, CA")

# Region boundaries (fractions of image height)
SKY_BOTTOM = 0.35       # Sky ends here
CITY_TOP = 0.28          # City lights start
CITY_BOTTOM = 0.58       # City lights end
WATER_TOP = 0.55         # Water starts
WATER_BOTTOM = 0.90      # Water ends

# Colors
NEON_CYAN = (0, 255, 220)
NEON_PINK = (255, 0, 180)
NEON_GREEN = (0, 255, 65)

# Star catalog: (name, RA_hours, Dec_degrees, magnitude)
STARS = [
    ("Sirius", 6.75, -16.7, -1.46), ("Arcturus", 14.26, 19.2, -0.05),
    ("Vega", 18.62, 38.8, 0.03), ("Capella", 5.28, 46.0, 0.08),
    ("Rigel", 5.24, -8.2, 0.13), ("Procyon", 7.66, 5.2, 0.34),
    ("Betelgeuse", 5.92, 7.4, 0.42), ("Altair", 19.85, 8.9, 0.76),
    ("Aldebaran", 4.60, 16.5, 0.86), ("Spica", 13.42, -11.2, 0.97),
    ("Antares", 16.49, -26.4, 1.04), ("Pollux", 7.76, 28.0, 1.14),
    ("Deneb", 20.69, 45.3, 1.25), ("Regulus", 10.14, 12.0, 1.35),
    ("Polaris", 2.53, 89.3, 1.98), ("Castor", 7.58, 31.9, 1.58),
]

STAR_TINTS = {
    "Sirius": (180, 210, 255), "Vega": (180, 200, 255), "Rigel": (170, 200, 255),
    "Betelgeuse": (255, 180, 120), "Aldebaran": (255, 190, 130), "Antares": (255, 170, 120),
    "Arcturus": (255, 210, 160), "Capella": (255, 240, 200),
}


# ─── Astronomy ───────────────────────────────────────────────────────────────

def lst(lon, dt):
    jd = (dt - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400 + 2451545
    T = (jd - 2451545) / 36525
    return (((280.46062 + 360.98565 * (jd - 2451545) + 0.000388 * T * T) % 360 + lon) % 360) / 15

def altaz(ra, dec, lat, local_st):
    ha = math.radians((local_st - ra) * 15)
    d, la = math.radians(dec), math.radians(lat)
    sa = math.sin(d) * math.sin(la) + math.cos(d) * math.cos(la) * math.cos(ha)
    alt = math.degrees(math.asin(max(-1, min(1, sa))))
    ca = (math.sin(d) - sa * math.sin(la)) / (math.cos(math.asin(sa)) * math.cos(la) + 1e-10)
    az = math.degrees(math.acos(max(-1, min(1, ca))))
    if math.sin(ha) > 0: az = 360 - az
    return alt, az

def visible_stars(lat, lon, dt):
    s = lst(lon, dt)
    return [(n, az / 360, 1 - alt / 90, m) for n, ra, dec, m in STARS
            for alt, az in [altaz(ra, dec, lat, s)] if alt > 8]

def moon_info(lat, lon, dt):
    if ephem:
        o = ephem.Observer(); o.lat, o.lon = str(lat), str(lon)
        o.date = dt.strftime('%Y/%m/%d %H:%M:%S')
        m = ephem.Moon(o)
        return m.phase / 100, float(m.alt) * 180 / math.pi, float(m.az) * 180 / math.pi
    ref = datetime(2024, 1, 11, 11, 57, tzinfo=timezone.utc)
    c = ((dt - ref).total_seconds() / 86400 % 29.53) / 29.53
    return 0.5 * (1 - math.cos(2 * math.pi * c)), 40, 200

def weather(lat, lon):
    if not requests: return {"temp_c": 15, "cond": "clear", "hum": 50, "wind": 10}
    try:
        d = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code&timezone=auto",
            timeout=10).json().get("current", {})
        wmo = d.get("weather_code", 0)
        c = "clear" if wmo <= 1 else "cloudy" if wmo <= 3 else "fog" if wmo <= 48 else "rain" if wmo <= 67 else "storm"
        return {"temp_c": d.get("temperature_2m", 15), "cond": c,
                "hum": d.get("relative_humidity_2m", 50), "wind": d.get("wind_speed_10m", 10)}
    except: return {"temp_c": 15, "cond": "clear", "hum": 50, "wind": 10}


# ─── Element extraction ─────────────────────────────────────────────────────

def extract_lights(skel_arr, light_arr):
    """Extract all dynamic light pixels from the diff between skeleton and lightmap."""
    diff = np.clip(light_arr.astype(np.float32) - skel_arr.astype(np.float32), 0, 999)
    db = diff.sum(axis=2)
    h, w = skel_arr.shape[:2]

    # Separate into regions
    regions = {
        'city': [],    # Building windows + bridge structure lights
        'water': [],   # Reflections in the bay
    }

    city_t, city_b = int(h * CITY_TOP), int(h * CITY_BOTTOM)
    water_t, water_b = int(h * WATER_TOP), int(h * WATER_BOTTOM)

    ys, xs = np.where(db > 20)
    for i in range(len(ys)):
        y, x = int(ys[i]), int(xs[i])
        r, g, b = int(light_arr[y, x, 0]), int(light_arr[y, x, 1]), int(light_arr[y, x, 2])

        if water_t <= y <= water_b:
            regions['water'].append((x, y, r, g, b))
        elif city_t <= y <= city_b:
            regions['city'].append((x, y, r, g, b))
        elif y > city_b:
            # Below water — probably more reflections or foreground lights
            regions['water'].append((x, y, r, g, b))
        else:
            regions['city'].append((x, y, r, g, b))

    return regions


# ─── Drawing ─────────────────────────────────────────────────────────────────

def font(size):
    try: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except: return ImageFont.load_default()

def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_stars(draw, px, vis, frame, sky_h):
    """Draw twinkling stars at real astronomical positions + background stars."""
    fl = font(8)

    # Background ambient stars
    rng = np.random.RandomState(42)
    for i in range(220):
        sx = rng.randint(0, OUTPUT_W)
        sy = rng.randint(4, sky_h - 2)
        base_b = rng.randint(60, 180)
        phase = (frame * 0.2 + i * 0.8) % (2 * math.pi)
        twinkle = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(phase))
        b = int(base_b * twinkle)
        px[sx, sy] = (b, b, int(b * 0.93))
        # A few double-pixel stars
        if i % 7 == 0 and sx + 1 < OUTPUT_W:
            px[sx + 1, sy] = (b // 2, b // 2, int(b * 0.45))

    # Real catalog stars
    for name, xf, yf, mag in vis:
        sx = int(xf * OUTPUT_W) % OUTPUT_W
        sy = int(yf * sky_h * 0.88) + 4
        if sy >= sky_h or sx >= OUTPUT_W:
            continue

        # Star size from magnitude
        size = 5 if mag < 0 else 4 if mag < 0.5 else 3 if mag < 1.0 else 2 if mag < 1.5 else 1

        # Individual twinkle
        phase = (frame * 0.16 + hash(name) * 0.37) % (2 * math.pi)
        tw = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(phase))

        tint = STAR_TINTS.get(name, (255, 255, 240))
        color = tuple(min(255, int(c * tw)) for c in tint)
        bright_core = tuple(min(255, int(255 * tw)) for _ in range(3))

        # Draw cross pattern
        if 0 <= sx < OUTPUT_W and 0 <= sy < sky_h:
            px[sx, sy] = bright_core
        for d in range(1, size):
            alpha = 1.0 - d / size
            c = tuple(int(v * alpha) for v in color)
            for dx, dy in [(d, 0), (-d, 0), (0, d), (0, -d)]:
                nx, ny = sx + dx, sy + dy
                if 0 <= nx < OUTPUT_W and 0 <= ny < sky_h:
                    px[nx, ny] = c
        # Diagonal glow for big stars
        if size >= 4:
            for d in range(1, size - 1):
                a = 0.3 * (1 - d / size)
                c = tuple(int(v * a) for v in color)
                for dx, dy in [(d, d), (-d, -d), (d, -d), (-d, d)]:
                    nx, ny = sx + dx, sy + dy
                    if 0 <= nx < OUTPUT_W and 0 <= ny < sky_h:
                        px[nx, ny] = c

        # Star name label
        if mag < 1.0 and tw > 0.45:
            lc = int(140 * tw)
            draw.text((sx + size + 2, sy - 4), name, fill=(lc, lc, int(lc * 0.8)), font=fl)


def draw_shooting_star(px, frame, total):
    """Animated shooting star that streaks and fades."""
    cycle = frame % total
    # Visible during frames 5-15 out of 30
    if cycle < 5 or cycle > 16:
        return

    t = (cycle - 5) / 11.0  # 0 to 1 over the animation window

    # Trajectory: upper-right to mid-left
    sx, sy = int(OUTPUT_W * 0.78), int(OUTPUT_H * 0.05)
    ex, ey = int(OUTPUT_W * 0.55), int(OUTPUT_H * 0.22)

    # Head position
    hx = sx + (ex - sx) * t
    hy = sy + (ey - sy) * t

    trail_len = 35
    for i in range(trail_len):
        frac = i / trail_len
        tx = int(hx - (ex - sx) * frac * 0.15)
        ty = int(hy - (ey - sy) * frac * 0.15)

        alpha = (1.0 - frac) ** 2
        # Fade in at start, fade out at end of animation
        if t < 0.2:
            alpha *= t / 0.2
        elif t > 0.7:
            alpha *= (1 - t) / 0.3

        b = int(255 * alpha)
        if b < 5:
            continue

        if 0 <= tx < OUTPUT_W and 0 <= ty < OUTPUT_H:
            px[tx, ty] = (b, b, int(b * 0.85))
            # Wider head
            if i < 4:
                for ny in [ty - 1, ty + 1]:
                    if 0 <= ny < OUTPUT_H:
                        px[tx, ny] = (b // 3, b // 3, int(b * 0.3))


def draw_moon_at(draw, phase, cx, cy, radius=12):
    """Pixel-art moon with phase."""
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > radius:
                continue
            # Phase terminator
            if phase < 0.5:
                lit = dx > radius * (1 - phase * 4)
            else:
                lit = dx < -radius * (1 - (1 - phase) * 4)

            px_x, px_y = cx + dx, cy + dy
            if not (0 <= px_x < OUTPUT_W and 0 <= px_y < OUTPUT_H):
                continue

            if lit:
                glow = 1 - dist / radius * 0.25
                bv = int(250 * glow)
                draw.point((px_x, px_y), fill=(bv, int(bv * 0.97), int(bv * 0.87)))
            else:
                draw.point((px_x, px_y), fill=(10, 8, 22))

    # Halo
    for dy in range(-radius - 5, radius + 6):
        for dx in range(-radius - 5, radius + 6):
            dist = math.sqrt(dx * dx + dy * dy)
            if radius < dist <= radius + 5:
                px_x, px_y = cx + dx, cy + dy
                if 0 <= px_x < OUTPUT_W and 0 <= px_y < OUTPUT_H:
                    s = 1 - (dist - radius) / 5
                    draw.point((px_x, px_y), fill=(int(40 * s), int(38 * s), int(25 * s)))


def draw_hud(draw, w, h, wx, m_phase, vis, date_str):
    """Bottom HUD with weather + astronomy data."""
    by = h - 34
    for y in range(by, h):
        draw.line([(0, y), (w, y)], fill=(6, 5, 14))
    # Gradient line
    for x in range(10, w - 10):
        c = lerp(NEON_CYAN, NEON_PINK, x / w)
        draw.point((x, by + 1), fill=tuple(v // 4 for v in c))

    f, fs = font(10), font(9)
    ty = by + 6
    tc = wx["temp_c"]
    draw.text((14, ty), f"{tc:.0f}°C / {tc*9/5+32:.0f}°F", fill=NEON_CYAN, font=f)
    draw.text((14, ty + 12), wx["cond"].upper(), fill=(115, 115, 135), font=fs)

    pn = next(n for th, n in [(0.05,"NEW"),(0.25,"WAXING CRES"),(0.45,"FIRST QTR"),
              (0.55,"FULL"),(0.75,"WANING GIB"),(0.95,"LAST QTR"),(1.01,"WANING CRES")] if m_phase < th)
    draw.text((w//2-50, ty), f"☾ {pn}", fill=NEON_PINK, font=f)
    names = " · ".join(n for n, _, _, _ in vis[:5])
    if names: draw.text((w//2-60, ty+12), names, fill=(60, 65, 88), font=fs)

    draw.text((w-155, ty), LOCATION, fill=NEON_GREEN, font=f)
    draw.text((w-210, ty+12), date_str, fill=(80, 80, 100), font=fs)
    draw.text((w-66, by+22), "SKYFORGE", fill=(25, 25, 38), font=fs)


# ─── Main generation ─────────────────────────────────────────────────────────

def generate():
    skel_path = os.environ.get("SKYFORGE_SKELETON", "skeleton.png")
    light_path = os.environ.get("SKYFORGE_LIGHTMAP", "lightmap.png")
    output = os.environ.get("SKYFORGE_OUTPUT", "skyforge.gif")

    print("🌌 SKYFORGE — Building your living night sky")

    for p, n in [(skel_path, "Skeleton"), (light_path, "Lightmap")]:
        if not os.path.exists(p):
            print(f"  ❌ {n} not found: {p}"); sys.exit(1)

    print("  📐 Loading images...")
    skel = Image.open(skel_path).convert('RGB').resize((OUTPUT_W, OUTPUT_H), Image.LANCZOS)
    light = Image.open(light_path).convert('RGB').resize((OUTPUT_W, OUTPUT_H), Image.LANCZOS)

    print("  🔍 Extracting light elements...")
    regions = extract_lights(np.array(skel), np.array(light))
    print(f"     → City/bridge: {len(regions['city'])} px")
    print(f"     → Water: {len(regions['water'])} px")

    now = datetime.now(timezone.utc)
    print("  🌡️  Weather...")
    wx = weather(LAT, LON)
    print(f"     → {wx['temp_c']:.1f}°C, {wx['cond']}")

    print("  🌙 Moon...")
    m_phase, m_alt, m_az = moon_info(LAT, LON, now)
    print(f"     → {m_phase:.0%}, Alt: {m_alt:.1f}°")

    print("  ⭐ Stars...")
    vis = visible_stars(LAT, LON, now)
    print(f"     → {len(vis)} visible")

    local_now = now.astimezone(ZoneInfo("America/Los_Angeles"))
    date_str = local_now.strftime("%Y-%m-%d %I:%M %p %Z")
    sky_h = int(OUTPUT_H * SKY_BOTTOM)

    print(f"  🎞️  Rendering {NUM_FRAMES} frames...")
    frames = []

    for fi in range(NUM_FRAMES):
        img = skel.copy()
        px = img.load()
        draw = ImageDraw.Draw(img)

        # ── City lights: steady with subtle flicker ──
        for x, y, r, g, b in regions['city']:
            seed = (x * 11 + y * 17) % 100
            if seed < 6:
                # 6% flicker on/off
                phase = (fi * 0.18 + seed * 0.6) % (2 * math.pi)
                if math.sin(phase) > -0.4:
                    v = 0.65 + 0.35 * math.sin(phase)
                    px[x, y] = (min(255, int(r*v)), min(255, int(g*v)), min(255, int(b*v)))
                # else stays dark (skeleton color)
            else:
                # Steady warm glow, very subtle breathing
                v = 0.90 + 0.10 * math.sin(fi * 0.06 + seed * 0.02)
                px[x, y] = (min(255, int(r*v)), min(255, int(g*v)), min(255, int(b*v)))

        # ── Water: wave shimmer ──
        for x, y, r, g, b in regions['water']:
            wave = math.sin(fi * 0.20 + x * 0.03)
            ripple = math.sin(fi * 0.12 + y * 0.06)
            shimmer = 0.35 + 0.65 * (0.5 + 0.3 * wave + 0.2 * ripple)
            px[x, y] = (min(255, int(r*shimmer)), min(255, int(g*shimmer)), min(255, int(b*shimmer)))

        # ── Sky: stars (Python-generated, not from images) ──
        draw_stars(draw, px, vis, fi, sky_h)

        # ── Shooting star ──
        draw_shooting_star(px, fi, NUM_FRAMES)

        # ── Moon ──
        if m_alt > 5:
            mx = int((m_az / 360) * OUTPUT_W) % OUTPUT_W
            my = int((1 - m_alt / 90) * sky_h * 0.75) + 8
            if 0 <= my < sky_h:
                draw_moon_at(draw, m_phase, mx, my)

        # ── HUD ──
        draw_hud(draw, OUTPUT_W, OUTPUT_H, wx, m_phase, vis, date_str)

        frames.append(img)
        if (fi + 1) % 10 == 0:
            print(f"     → {fi+1}/{NUM_FRAMES}")

    print(f"  💾 Saving {output}...")
    opt = [f.quantize(colors=256, method=2, dither=1).convert('RGB') for f in frames]
    opt[0].save(output, save_all=True, append_images=opt[1:],
                duration=FRAME_DELAY_MS, loop=0, optimize=True)
    kb = os.path.getsize(output) / 1024
    print(f"  ✅ {output} — {kb:.0f} KB ({kb/1024:.1f} MB)")
    if kb > 4500:
        print("  ⚠️  Near 5MB GitHub limit")


if __name__ == "__main__":
    generate()
