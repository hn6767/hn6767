"""Tests for the computed sky. Run with:  python -m unittest discover tests"""

import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ephem
import numpy as np
from PIL import Image

import sky

UTC = timezone.utc
W, H = 840, 360


def ephem_dt(d):
    return d.datetime().replace(tzinfo=UTC)


class Catalogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stars = sky.load_stars()

    def test_complete_rows(self):
        self.assertGreater(len(self.stars), 1500)
        for r in self.stars:
            for k in ("ra_deg", "dec_deg", "mag", "bv", "pm_ra_mas", "pm_dec_mas"):
                float(r[k])                                   # raises on blanks
            self.assertTrue(0 <= float(r["ra_deg"]) < 360)
            self.assertTrue(-90 <= float(r["dec_deg"]) <= 90)
            self.assertLessEqual(float(r["mag"]), 5.0)

    def test_known_stars(self):
        by_name = {r["name"]: r for r in self.stars if r["name"]}
        self.assertEqual(self.stars[0]["name"], "Sirius")
        # Spot-check against J2000 values from the Hipparcos catalogue.
        for name, ra, dec in [("Betelgeuse", 88.79, 7.41), ("Vega", 279.23, 38.78),
                              ("Polaris", 37.95, 89.26), ("Fomalhaut", 344.41, -29.62)]:
            self.assertAlmostEqual(float(by_name[name]["ra_deg"]), ra, delta=0.05, msg=name)
            self.assertAlmostEqual(float(by_name[name]["dec_deg"]), dec, delta=0.05, msg=name)
        self.assertGreater(float(by_name["Betelgeuse"]["bv"]), 1.5)      # red
        self.assertLess(float(by_name["Rigel"]["bv"]), 0.1)              # blue-white


class Positions(unittest.TestCase):
    def test_polaris_altitude_is_latitude(self):
        # Polaris sits within ~0.7° of the pole, so its altitude stays close
        # to the observer's latitude all night, every night.
        polaris = [r for r in sky.load_stars() if r["name"] == "Polaris"]
        for h in range(0, 24, 3):
            when = datetime(2026, 11, 20, h, tzinfo=UTC)
            b = sky.compute_sky(when, stars=polaris)[0]
            self.assertAlmostEqual(b.alt, sky.VIEW_LAT, delta=1.0)
            self.assertTrue(b.az < 2 or b.az > 358)

    def test_far_southern_star_never_rises(self):
        rows = [r for r in sky.load_stars() if float(r["dec_deg"]) < -60]
        self.assertTrue(rows)
        for h in range(0, 24, 4):
            for b in sky.compute_sky(datetime(2026, 6, 1, h, tzinfo=UTC), stars=rows):
                if b.kind == "star":
                    self.assertLess(b.alt, 0, b.name)

    def test_naive_and_aware_times_agree(self):
        aware = datetime(2026, 11, 21, 6, tzinfo=UTC)
        local = aware.astimezone(sky.TZ)
        a = sky.compute_sky(aware, stars=[])[-1]
        b = sky.compute_sky(aware.replace(tzinfo=None), stars=[])[-1]
        c = sky.compute_sky(local, stars=[])[-1]
        self.assertAlmostEqual(a.alt, b.alt, places=6)
        self.assertAlmostEqual(a.alt, c.alt, places=6)

    def test_bad_weather_temperature_is_ignored(self):
        when = datetime(2026, 11, 21, 6, tzinfo=UTC)
        self.assertEqual(sky.compute_sky(when, temp_c=None, stars=[])[-1].alt,
                         sky.compute_sky(when, temp_c="n/a", stars=[])[-1].alt)


class MoonPhase(unittest.TestCase):
    def moon_at(self, when):
        return sky.moon_body(sky.observer(when))

    def test_named_phases(self):
        start = ephem.Date("2026/11/01")
        cases = [(ephem.next_new_moon, "NEW", None),
                 (ephem.next_first_quarter_moon, "FIRST QTR", True),
                 (ephem.next_full_moon, "FULL", None),
                 (ephem.next_last_quarter_moon, "LAST QTR", False)]
        for fn, name, waxing in cases:
            m = self.moon_at(ephem_dt(fn(start)))
            self.assertEqual(sky.phase_name(m), name)
            if waxing is not None:
                self.assertEqual(m.waxing, waxing)

    def test_crescent_and_gibbous(self):
        new = ephem_dt(ephem.next_new_moon("2026/11/01"))
        self.assertEqual(sky.phase_name(self.moon_at(new + timedelta(days=4))), "WAXING CRES")
        self.assertEqual(sky.phase_name(self.moon_at(new + timedelta(days=11))), "WAXING GIB")
        self.assertEqual(sky.phase_name(self.moon_at(new + timedelta(days=19))), "WANING GIB")
        self.assertEqual(sky.phase_name(self.moon_at(new + timedelta(days=26))), "WANING CRES")

    def test_bright_limb_points_at_sun(self):
        # Compare the computed limb direction with the on-screen offset from
        # the Moon to the Sun one degree along the great circle between them.
        for days in (3, 7, 10, 20, 24):
            when = datetime(2026, 11, 10, 2, tzinfo=UTC) + timedelta(days=days)
            o = sky.observer(when)
            m, s = ephem.Moon(o), ephem.Sun(o)
            dx, dy = sky._toward_on_screen(math.degrees(m.az), math.degrees(m.alt),
                                           math.degrees(s.az), math.degrees(s.alt))
            self.assertAlmostEqual(math.hypot(dx, dy), 1.0, places=6)
            # Same sign as the plain azimuth/altitude difference when both
            # are close; here just check horizontal sense for a Sun well
            # to one side.
            daz = (math.degrees(s.az) - math.degrees(m.az) + 540) % 360 - 180
            if abs(daz) > 30 and abs(math.degrees(m.alt)) < 60:
                self.assertEqual(dx > 0, daz > 0, f"days={days}")

    def test_screen_basis(self):
        right = sky._toward_on_screen(180, 0, 181, 0)
        up = sky._toward_on_screen(180, 10, 180, 11)
        self.assertAlmostEqual(right[0], 1, places=3)
        self.assertAlmostEqual(up[1], -1, places=3)


class Projection(unittest.TestCase):
    def test_centre_and_horizon(self):
        x, y = sky.project(sky.VIEW_AZ_DEG, 0, W, H)
        self.assertAlmostEqual(x, W / 2)
        self.assertAlmostEqual(y, H * sky.HORIZON_FRAC)

    def test_edges_and_wraparound(self):
        half = sky.HFOV_DEG / 2
        self.assertIsNotNone(sky.project(sky.VIEW_AZ_DEG - half + 0.1, 5, W, H))
        self.assertIsNotNone(sky.project(sky.VIEW_AZ_DEG + half - 0.1, 5, W, H))
        self.assertIsNone(sky.project(sky.VIEW_AZ_DEG + 180, 5, W, H))
        self.assertIsNone(sky.project(sky.VIEW_AZ_DEG, 95, W, H))
        # 360° wrap: az and az+360 land on the same pixel
        a = sky.project(sky.VIEW_AZ_DEG + 10, 5, W, H)
        b = sky.project(sky.VIEW_AZ_DEG + 370, 5, W, H)
        self.assertEqual(a, b)

    def test_landmarks_line_up_in_lens_view(self):
        # In the lens preset, Transamerica (bearing ~119°) and the south tower
        # (~164°) should land near x=190 and x=650 of the 840 px art.
        with mock.patch.multiple(sky, VIEW_AZ_DEG=142.0, HFOV_DEG=90.0, TOP_ALT_DEG=None):
            self.assertAlmostEqual(sky.project(119, 1, W, H)[0], 190, delta=25)
            self.assertAlmostEqual(sky.project(164, 1, W, H)[0], 650, delta=25)

    def test_left_is_east(self):
        self.assertLess(sky.project(100, 10, W, H)[0], sky.project(200, 10, W, H)[0])


class RenderTime(unittest.TestCase):
    def local(self, now_utc):
        return sky.render_time(now_utc).astimezone(sky.TZ)

    def test_nightly_cron(self):
        # The Action runs at 06:00 UTC: 10 PM PST in winter, 11 PM PDT in summer.
        self.assertEqual(self.local(datetime(2026, 11, 21, 6, tzinfo=UTC)),
                         datetime(2026, 11, 20, 22, tzinfo=sky.TZ))
        self.assertEqual(self.local(datetime(2027, 6, 16, 6, tzinfo=UTC)),
                         datetime(2027, 6, 15, 22, tzinfo=sky.TZ))

    def test_dst_changeover_nights(self):
        for night in (datetime(2027, 3, 13), datetime(2027, 3, 14),
                      datetime(2026, 10, 31), datetime(2026, 11, 1)):
            run = (night + timedelta(days=1)).replace(hour=6, tzinfo=UTC)
            got = self.local(run)
            self.assertEqual((got.date(), got.hour, got.minute), (night.date(), 22, 0))

    def test_leap_day(self):
        got = self.local(datetime(2028, 3, 1, 6, tzinfo=UTC))
        self.assertEqual((got.month, got.day, got.hour), (2, 29, 22))

    def test_manual_runs(self):
        # 7 AM run draws the coming night; 2:44 AM run draws the night in progress.
        self.assertEqual(self.local(datetime(2026, 11, 19, 15, 7, tzinfo=UTC)).date(),
                         datetime(2026, 11, 19).date())
        self.assertEqual(self.local(datetime(2026, 11, 20, 10, 44, tzinfo=UTC)).date(),
                         datetime(2026, 11, 19).date())

    def test_override(self):
        with mock.patch.dict(os.environ, {"SKYFORGE_DATETIME": "2026-12-24T21:30"}):
            self.assertEqual(sky.render_time(), datetime(2026, 12, 25, 5, 30, tzinfo=UTC))


class Atmosphere(unittest.TestCase):
    def test_airmass(self):
        self.assertAlmostEqual(sky.airmass(90), 1.0, places=2)
        self.assertAlmostEqual(sky.airmass(30), 2.0, delta=0.02)
        self.assertGreater(sky.airmass(0), 30)
        self.assertLess(sky.extincted_mag(1.0, 80), sky.extincted_mag(1.0, 10))

    def test_colours(self):
        blue, red = sky.bv_to_rgb(-0.3), sky.bv_to_rgb(1.8)
        self.assertGreater(blue[2], blue[0])
        self.assertGreater(red[0], red[2])
        self.assertEqual(len(sky.bv_to_rgb(5)), 3)


class YearOfNights(unittest.TestCase):
    def test_every_night_of_a_year(self):
        """Every 10 PM of a full year computes and lands sensible objects."""
        import generate
        skel = np.array(Image.open(os.path.join(sky.HERE, "skeleton.png")).convert("RGB")
                        .resize((W, H), Image.LANCZOS))
        light = np.array(Image.open(os.path.join(sky.HERE, "lightmap.png")).convert("RGB")
                         .resize((W, H), Image.LANCZOS))
        skyline = generate.sky_mask(skel, light)
        stars = sky.load_stars()
        moon_nights = 0
        for d in range(366):
            night = datetime(2027, 1, 1, 22, tzinfo=sky.TZ) + timedelta(days=d)
            bodies = sky.compute_sky(night.astimezone(UTC), stars=stars)
            objs = generate.visible_objects(bodies, skyline)
            self.assertGreater(sum(b.kind == "star" for b, *_ in objs), 100, night)
            for b, x, y, m in objs:
                self.assertTrue(0 <= x < W and 0 <= y < skyline[x], (night, b.name))
            moon = bodies[-1]
            if moon.alt > 0 and sky.project(moon.az, moon.alt, W, H):
                moon_nights += 1
        # The Moon is up at 10 PM on roughly half the nights, and the
        # panorama catches most of those.
        self.assertGreater(moon_nights, 120)


class Labels(unittest.TestCase):
    def test_labels_never_overlap_or_cover_the_moon(self):
        """Over a year of nights, star/planet names stay inside the frame,
        above the skyline, apart from each other and off the Moon."""
        import generate
        from PIL import ImageDraw
        skel = np.array(Image.open(os.path.join(sky.HERE, "skeleton.png")).convert("RGB")
                        .resize((W, H), Image.LANCZOS))
        light = np.array(Image.open(os.path.join(sky.HERE, "lightmap.png")).convert("RGB")
                         .resize((W, H), Image.LANCZOS))
        skyline = generate.sky_mask(skel, light)
        stars = sky.load_stars()
        fl = generate.font(8)
        labelled = 0
        for d in range(0, 366, 3):
            night = datetime(2027, 1, 1, 22, tzinfo=sky.TZ) + timedelta(days=d)
            bodies = sky.compute_sky(night.astimezone(UTC), stars=stars)
            objs = generate.visible_objects(bodies, skyline)
            mbox = generate.moon_box(bodies[-1])
            img = Image.new("RGB", (W, H))
            draw = ImageDraw.Draw(img)
            boxes = []
            real_text = draw.text

            def record(xy, text, **kw):
                x, y = xy
                boxes.append((x, y, x + int(draw.textlength(text, font=fl)), y + 9))
                real_text(xy, text, **kw)

            draw.text = record
            generate.draw_stars(draw, img.load(), objs, 0, skyline,
                                keep_clear=[mbox] if mbox else ())
            labelled += len(boxes)
            others = boxes + ([mbox] if mbox else [])
            for i, a in enumerate(boxes):
                self.assertTrue(0 <= a[0] and a[2] < W and a[1] >= 0, (night, a))
                self.assertTrue(all(a[3] < skyline[x] for x in range(a[0], a[2] + 1)), night)
                for j, b in enumerate(others):
                    if i != j:
                        overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                        self.assertFalse(overlap, (night, a, b))
        self.assertGreater(labelled, 500)


class EndToEnd(unittest.TestCase):
    def test_render_gif(self):
        import generate
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sky.gif")
            env = {"SKYFORGE_OUTPUT": out, "SKYFORGE_DATETIME": "2026-11-20T22:00",
                   "SKYFORGE_SKELETON": os.path.join(sky.HERE, "skeleton.png"),
                   "SKYFORGE_LIGHTMAP": os.path.join(sky.HERE, "lightmap.png")}
            # No network: weather must fall back instead of failing the run.
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(generate.requests, "get", side_effect=OSError("offline")):
                generate.generate()
            with Image.open(out) as im:
                self.assertEqual(im.size, (W, H))
                self.assertEqual(im.n_frames, generate.NUM_FRAMES)
                frame = np.array(im.convert("RGB")).astype(int)
            self.assertLess(os.path.getsize(out), 4.5 * 1024 * 1024)
            # The Moon disc is drawn where the ephemeris puts it.
            moon = sky.compute_sky(datetime(2026, 11, 21, 6, tzinfo=UTC), stars=[])[-1]
            mx, my = (int(round(v)) for v in sky.project(moon.az, moon.alt, W, H))
            self.assertGreater(frame[my, mx].sum(), 500)


if __name__ == "__main__":
    unittest.main()
