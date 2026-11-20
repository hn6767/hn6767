#!/usr/bin/env python3
"""
SKYFORGE — Living pixel-art night sky for your GitHub profile.

Two-image compositing: SKELETON (dark structure) + LIGHTMAP (lights on).
Python adds all dynamic elements: twinkling stars, shooting star, moon,
flickering windows, shimmering water, pulsing bridge lights, weather HUD.

The sky is computed, not decorated: sky.py works out which real stars,
planets and Moon sit in the scene's field of view (Battery Spencer looking
south-east) at 10 PM Pacific on the night being rendered.
"""

import math
import os
import sys
import zlib
from PIL import Image, ImageDraw, ImageFont
import numpy as np

import sky

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

# Faintest star drawn, after atmospheric extinction. Looking toward the
# city from the Marin Headlands the naked eye reaches roughly magnitude 4-5.
LIMIT_MAG = float(os.environ.get("SKYFORGE_LIMIT_MAG", "5.0"))
LABEL_MAG = 2.0          # name stars at least this bright (catalogue magnitude)
MOON_RADIUS = 9          # px; the real Moon would be ~2 px across at this scale

PLANET_TINTS = {
    "Mercury": (230, 220, 200), "Venus": (255, 252, 235), "Mars": (255, 165, 115),
    "Jupiter": (255, 238, 210), "Saturn": (240, 218, 165),
}


# ─── Astronomy ───────────────────────────────────────────────────────────────

def sky_mask(skel_arr, light_arr):
    """Per column, the first row (from the top) that is no longer open sky:
    buildings, bridge, hills or lights. Stars are only drawn above it."""
    sk = skel_arr.astype(int).sum(axis=2)
    li = light_arr.astype(int).sum(axis=2)
    nonsky = (sk < 50) | (li > 80)
    top = nonsky.argmax(axis=0)
    top[~nonsky.any(axis=0)] = skel_arr.shape[0]
    return top


def visible_objects(bodies, skyline):
    """Bodies inside the frame and above the skyline, with screen position
    and extinction-dimmed magnitude. Brightest first."""
    out = []
    for b in bodies:
        if b.kind == "moon" or b.alt <= 0:
            continue
        xy = sky.project(b.az, b.alt, OUTPUT_W, OUTPUT_H)
        if xy is None:
            continue
        x, y = int(round(xy[0])), int(round(xy[1]))
        if not (0 <= x < OUTPUT_W) or y >= skyline[x] - 1:
            continue
        m = sky.extincted_mag(b.mag, b.alt)
        if b.kind == "star" and m > LIMIT_MAG:
            continue
        out.append((b, x, y, m))
    return sorted(out, key=lambda o: o[3])


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


def _twinkle(key, frame, amp):
    """Deterministic per-object scintillation; amp 0 = steady."""
    phase = (frame * 0.21 + (zlib.crc32(key.encode()) % 1000) * 0.37) % (2 * math.pi)
    return 1.0 - amp * (0.5 + 0.5 * math.sin(phase))


def _set(px, x, y, c, skyline):
    if 0 <= x < OUTPUT_W and 0 <= y < skyline[x] - 1 and y >= 0:
        px[x, y] = c


def draw_stars(draw, px, objs, frame, skyline):
    """Stars and planets at their real positions. Pixel size and brightness
    follow magnitude after extinction; stars scintillate more near the
    horizon, planets shine steadily."""
    fl = font(8)
    labels = []   # occupied label boxes, to avoid overlaps

    for b, sx, sy, mag in reversed(objs):          # faint first, bright on top
        if b.kind == "planet":
            tint = PLANET_TINTS.get(b.name, (255, 250, 230))
            tw = _twinkle(b.name, frame, 0.06)
        else:
            tint = sky.bv_to_rgb(b.bv)
            amp = min(0.65, 0.20 + 0.03 * sky.airmass(b.alt))
            tw = _twinkle(f"{b.name}{b.az:.3f}", frame, amp)

        if mag >= 2.5:
            # Single pixel, brightness from flux relative to a 2.5 mag star.
            k = max(0.22, min(1.0, 10 ** (-0.4 * (mag - 2.5)))) * tw
            _set(px, sx, sy, tuple(int(c * k) for c in tint), skyline)
            continue

        size = 4 if mag < 0 else 3 if mag < 1.0 else 2 if mag < 1.8 else 1
        core = tuple(min(255, int(255 * tw)) for _ in range(3))
        color = tuple(min(255, int(c * tw)) for c in tint)
        _set(px, sx, sy, core if size > 1 else color, skyline)
        for d in range(1, size):
            alpha = 1.0 - d / size
            c = tuple(int(v * alpha) for v in color)
            for dx, dy in [(d, 0), (-d, 0), (0, d), (0, -d)]:
                _set(px, sx + dx, sy + dy, c, skyline)
        if size >= 3:
            for d in range(1, size - 1):
                a = 0.3 * (1 - d / size)
                c = tuple(int(v * a) for v in color)
                for dx, dy in [(d, d), (-d, -d), (d, -d), (-d, d)]:
                    _set(px, sx + dx, sy + dy, c, skyline)

    # Labels for bright named stars and every planet, brightest first so they
    # win any overlap. Steady (not tied to twinkle).
    for b, sx, sy, mag in objs:
        if not b.name or not (b.kind == "planet" or b.mag < LABEL_MAG):
            continue
        size = 4 if mag < 0 else 3 if mag < 1.0 else 2 if mag < 1.8 else 1
        tx, ty = sx + size + 2, sy - 4
        box = (tx, ty, tx + int(draw.textlength(b.name, font=fl)), ty + 9)
        clear = all(box[3] < skyline[x] - 1 for x in range(max(0, tx), min(OUTPUT_W, box[2] + 1)))
        if box[2] < OUTPUT_W and ty >= 0 and clear and not any(
                box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in labels):
            fill = (125, 110, 85) if b.kind == "planet" else (100, 100, 80)
            draw.text((tx, ty), b.name, fill=fill, font=fl)
            labels.append(box)


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


def draw_moon(px, moon, skyline, radius=MOON_RADIUS):
    """Pixel-art Moon at its real position. The lit part is the exact phase:
    a point on the disc is lit when it faces the Sun, with the bright limb
    turned toward where the Sun really is (below the horizon at night)."""
    xy = sky.project(moon.az, moon.alt, OUTPUT_W, OUTPUT_H, margin=radius)
    if moon.alt <= -1 or xy is None:
        return False
    cx, cy = int(round(xy[0])), int(round(xy[1]))
    cos_i = 2 * moon.illum - 1                       # phase angle i: illum = (1 + cos i) / 2
    sin_i = math.sqrt(max(0.0, 1 - cos_i * cos_i))
    ux, uy = moon.limb_dx, moon.limb_dy

    # Halo first so the disc paints over it
    for dy in range(-radius - 5, radius + 6):
        for dx in range(-radius - 5, radius + 6):
            dist = math.hypot(dx, dy)
            if radius < dist <= radius + 5:
                s = (1 - (dist - radius) / 5) * (0.3 + 0.7 * moon.illum)
                x, y = cx + dx, cy + dy
                if 0 <= x < OUTPUT_W and 0 <= y < OUTPUT_H:
                    base = px[x, y]
                    _set(px, x, y, tuple(min(255, int(c + s * g)) for c, g in zip(base, (34, 32, 20))), skyline)

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = math.hypot(dx, dy)
            if dist > radius:
                continue
            u = (dx * ux + dy * uy) / radius
            w = math.sqrt(max(0.0, 1 - (dist / radius) ** 2))
            if u * sin_i + w * cos_i > 0:
                glow = 1 - dist / radius * 0.25
                bv = int(250 * glow)
                _set(px, cx + dx, cy + dy, (bv, int(bv * 0.97), int(bv * 0.87)), skyline)
            else:
                _set(px, cx + dx, cy + dy, (10, 8, 22), skyline)
    return True


def draw_hud(draw, w, h, wx, moon, objs, date_str):
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

    where = f" · {sky.compass(moon.az)} {moon.alt:.0f}°" if moon.alt > 0 else " · BELOW HORIZON"
    draw.text((w//2-80, ty), f"☾ {sky.phase_name(moon)} {moon.illum:.0%}{where}", fill=NEON_PINK, font=f)
    named = [b.name for b, _, _, _ in objs if b.kind == "planet"]
    named += [b.name for b, _, _, _ in objs if b.kind == "star" and b.name][:5 - len(named)]
    if named: draw.text((w//2-80, ty+12), " · ".join(named[:5]), fill=(60, 65, 88), font=fs)

    draw.text((w-180, ty), LOCATION, fill=NEON_GREEN, font=f)
    draw.text((w-180, ty+12), date_str, fill=(80, 80, 100), font=fs)
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

    skyline = sky_mask(np.array(skel), np.array(light))

    when = sky.render_time()
    local = when.astimezone(sky.TZ)
    print(f"  🕙 Sky for {local:%Y-%m-%d %H:%M %Z}, {sky.VIEW_MODE} view centred "
          f"{sky.compass(sky.VIEW_AZ_DEG)} ({sky.VIEW_AZ_DEG:.0f}°, {sky.HFOV_DEG:.0f}° wide)")

    print("  🌡️  Weather...")
    wx = weather(LAT, LON)
    print(f"     → {wx['temp_c']:.1f}°C, {wx['cond']}")

    print("  ⭐ Stars, planets, Moon...")
    bodies = sky.compute_sky(when, temp_c=wx["temp_c"])
    moon = next(b for b in bodies if b.kind == "moon")
    objs = visible_objects(bodies, skyline)
    print(f"     → {sum(b.kind == 'star' for b, *_ in objs)} stars in view, "
          f"planets: {', '.join(b.name for b, *_ in objs if b.kind == 'planet') or 'none'}")
    print(f"     → Moon {sky.phase_name(moon)} {moon.illum:.0%}, "
          f"az {moon.az:.1f}° alt {moon.alt:.1f}°")

    date_str = local.strftime("%Y-%m-%d %H:%M")

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

        # ── Sky: real stars and planets (Python-generated, not from images) ──
        draw_stars(draw, px, objs, fi, skyline)

        # ── Shooting star ──
        draw_shooting_star(px, fi, NUM_FRAMES)

        # ── Moon (only when it is really in this part of the sky) ──
        draw_moon(px, moon, skyline)

        # ── HUD ──
        draw_hud(draw, OUTPUT_W, OUTPUT_H, wx, moon, objs, date_str)

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
