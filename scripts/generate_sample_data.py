"""Generate data/listings.json: deterministic mock MLS listings from two feeds.

The two feeds deliberately format things differently, as real MLS feeds do:
  MLS_A: "Austin", "TX", "78704",      price "525000"
  MLS_B: "austin ", "Texas", "78704-2231", price "$525,000"
Ids overlap between feeds (both have "1001"), so ids are only unique per source.

Usage:  python scripts/generate_sample_data.py [--count 80] [--seed 42] [--today 2026-10-23]
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

CITIES = [
    # city, state code, state name, zips, (lat, lon), median price
    ("Austin", "TX", "Texas", ["78701", "78702", "78704", "78745"], (30.2672, -97.7431), 620_000),
    ("Round Rock", "TX", "Texas", ["78664", "78665", "78681"], (30.5083, -97.6789), 430_000),
    ("Dallas", "TX", "Texas", ["75201", "75204", "75214"], (32.7767, -96.7970), 480_000),
    ("Houston", "TX", "Texas", ["77002", "77006", "77019"], (29.7604, -95.3698), 410_000),
    ("San Antonio", "TX", "Texas", ["78204", "78209", "78212"], (29.4241, -98.4936), 330_000),
    ("Denver", "CO", "Colorado", ["80202", "80205", "80210"], (39.7392, -104.9903), 640_000),
]
STREETS = ["Oak", "Maple", "Cedar", "Pecan", "Elm", "Main", "Lamar", "Congress", "Riverside",
           "Barton Springs", "Mesquite", "Willow", "Bluebonnet", "Lakeview", "Sunset", "Hillcrest"]
SUFFIXES = ["St", "Ave", "Blvd", "Dr", "Ln", "Ct", "Way", "Rd"]
STYLES = ["bungalow", "craftsman", "ranch-style home", "modern townhome", "colonial", "condo",
          "mid-century home", "farmhouse"]
FEATURES = ["a sparkling pool", "an updated kitchen with quartz counters", "hardwood floors throughout",
            "a large fenced backyard", "a two-car garage", "solar panels", "a home office",
            "vaulted ceilings", "a covered patio", "walk-in closets", "a renovated primary bath",
            "an open floor plan", "energy-efficient windows", "a finished basement", "mountain views",
            "a chef's kitchen", "a whirlpool tub", "smart-home features", "a detached guest suite"]
HOOKS = ["Move-in ready", "Fully renovated", "Charming", "Spacious", "Newly built", "Light-filled",
         "Investor special", "Quiet cul-de-sac", "Walkable", "Updated"]


def make_listing(rng: random.Random, source: str, num: int, today: date) -> dict:
    city, code, state_name, zips, (lat, lon), median = rng.choice(CITIES)
    beds = rng.choices([1, 2, 3, 4, 5, 6], weights=[1, 3, 5, 4, 2, 1])[0]
    baths = max(1.0, min(beds + rng.choice([-1, -0.5, 0, 0.5, 1]), 6.0))
    sqft = int(rng.gauss(550 + beds * 450, 180))
    price = round(median * (sqft / 1900) * rng.uniform(0.8, 1.25), -3)
    listed = today - timedelta(days=int(rng.triangular(0, 150, 10)))
    status = rng.choices(["active", "pending", "sold"], weights=[7, 2, 1])[0]
    features = rng.sample(FEATURES, 3)
    description = (f"{rng.choice(HOOKS)} {beds}-bedroom {rng.choice(STYLES)} in {city} with "
                   f"{features[0]}, {features[1]} and {features[2]}.")
    zip_code = rng.choice(zips)
    address = f"{rng.randint(100, 9999)} {rng.choice(STREETS)} {rng.choice(SUFFIXES)}"

    if source == "MLS_A":
        record_city, record_state, record_zip, record_price = city, code, zip_code, str(int(price))
    else:
        record_city = rng.choice([city.lower(), city.upper(), f" {city} ", city])
        record_state = rng.choice([state_name, code.lower(), state_name.upper()])
        record_zip = rng.choice([f"{zip_code}-{rng.randint(1000, 9999)}", zip_code])
        record_price = f"${int(price):,}"
        if rng.random() < 0.3:
            address = address.upper() + rng.choice(["", " #2", " Unit B"])

    return {
        "id": str(1000 + num),
        "source": source,
        "address": address,
        "city": record_city,
        "state": record_state,
        "zip": record_zip,
        "price": record_price,
        "bedrooms": beds,
        "bathrooms": baths,
        "sqft": sqft,
        "latitude": round(lat + rng.uniform(-0.08, 0.08), 6),
        "longitude": round(lon + rng.uniform(-0.08, 0.08), 6),
        "listedDate": listed.isoformat(),
        "status": status,
        "description": description,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 10, 23))
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "listings.json")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    half = args.count // 2
    listings = [make_listing(rng, "MLS_A", i + 1, args.today) for i in range(half)]
    listings += [make_listing(rng, "MLS_B", i + 1, args.today) for i in range(args.count - half)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(listings, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(listings)} listings to {args.out}")


if __name__ == "__main__":
    main()
