#!/usr/bin/env python3
"""
Rebuild data/stars.csv, the star catalogue Skyforge renders from.

Source: the Big Sky Catalog (Hipparcos + Tycho, MIT licence), magnitude-9
release, plus Starplot's star_designations table for proper names.
This only needs to run if you want a different magnitude cut; the nightly
Action reads the committed CSV and downloads nothing.

    pip install pandas pyarrow && pip install --no-deps starplot
    python tools/build_star_catalog.py [--mag 5.0]
"""
import argparse
import os
import urllib.request

import pandas as pd

# B-V colour index for the bright stars whose Big Sky rows leave it blank
# (published Hipparcos/Johnson values). Only used to tint the pixels.
BV_FILL = {
    32349: 0.00,   # Sirius
    69673: 1.23,   # Arcturus
    71683: 0.71,   # Rigil Kentaurus
    91262: 0.00,   # Vega
    24608: 0.80,   # Capella
    37279: 0.42,   # Procyon
    68702: -0.23,  # Hadar
    71681: 0.90,   # Toliman
    36850: 0.03,   # Castor
    54061: 1.07,   # Dubhe
    41037: 1.20,   # Avior
    31681: 0.00,   # Alhena
    42913: 0.04,   # Alsephina
    25930: -0.22,  # Mintaka
}

BIGSKY_URL = ("https://github.com/steveberardi/starplot-bigsky/releases/download/"
              "v0.1.3/stars.bigksy.0.1.3.mag9.parquet")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mag", type=float, default=5.0, help="faintest magnitude to keep")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "stars.csv"))
    args = ap.parse_args()

    cache = "/tmp/bigsky_mag9.parquet"
    if not os.path.exists(cache):
        urllib.request.urlretrieve(BIGSKY_URL, cache)
    stars = pd.read_parquet(cache)
    stars = stars[(stars.magnitude <= args.mag) & stars.hip.notna()]
    # Multiple components share one HIP number; keep the brightest row.
    stars = stars.sort_values("magnitude").drop_duplicates("hip")

    # Locate starplot's bundled names table without importing the package.
    import importlib.util
    spdir = os.path.dirname(importlib.util.find_spec("starplot").origin)
    names_path = os.path.join(spdir, "data", "library", "star_designations.parquet")
    names = pd.read_parquet(names_path)[["hip", "name"]]
    names = names[names.name.fillna("").str.len() > 0]
    stars = stars.merge(names, on="hip", how="left")

    stars["bv"] = stars.bv.fillna(stars.hip.astype(int).map(BV_FILL))

    out = pd.DataFrame({
        "hip": stars.hip.astype(int),
        "name": stars.name.fillna(""),
        "ra_deg": stars.ra.round(5),
        "dec_deg": stars.dec.round(5),
        "mag": stars.magnitude.round(2),
        "bv": stars.bv.round(2),
        "pm_ra_mas": stars.ra_mas_per_year.round(1),   # mu_alpha * cos(dec)
        "pm_dec_mas": stars.dec_mas_per_year.round(1),
    }).sort_values("mag")
    out.to_csv(args.out, index=False)
    print(f"wrote {len(out)} stars (mag <= {args.mag}) to {args.out}")


if __name__ == "__main__":
    main()
