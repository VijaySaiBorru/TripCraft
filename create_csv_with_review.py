# /scratch/sg/Vijay/TripCraft/create_csv.py

import csv
import json
import re
import sys
import os
import ast
import math
from collections import OrderedDict
from datetime import datetime
from ftfy import fix_text
from itertools import product

location_types = [
"beach locations",
"city locations",
"forest and wildlife locations",
"mountain locations"
]

travel_purposes = [
"adventure travel",
"cultural exploration",
"nature exploration",
"relaxation travel"
]

spending_types = [
"economical stays",
"luxury stays"
]

traveler_types = [
"adventure traveler",
"laidback traveler"
]


def build_persona_index():

    personas = []

    for loc, purpose, spend, traveler in product(
        location_types,
        travel_purposes,
        spending_types,
        traveler_types
    ):
        personas.append((traveler, purpose, spend, loc))

    return personas


def persona_json_to_text(persona):

    if isinstance(persona, dict):

        vals = []

        for v in persona.values():

            if isinstance(v, list):
                vals.extend([str(x) for x in v])

            else:
                vals.append(str(v))

        return " ".join(vals).lower()

    return str(persona).lower()


def parse_json_persona(persona):

    p = persona_json_to_text(persona)

    # traveler
    if "laidback" in p:
        traveler = "laidback traveler"
    else:
        traveler = "adventure traveler"

    # purpose
    if "cultural" in p:
        purpose = "cultural exploration"

    elif "nature" in p:
        purpose = "nature exploration"

    elif "relax" in p:
        purpose = "relaxation travel"

    elif "adventure" in p:
        purpose = "adventure travel"

    else:
        purpose = "adventure travel"

    # spending
    if "luxury" in p:
        spend = "luxury stays"

    elif "economical" in p or "budget" in p:
        spend = "economical stays"

    else:
        spend = "economical stays"

    # location
    if "beach" in p:
        location = "beach locations"

    elif "mountain" in p:
        location = "mountain locations"

    elif "forest" in p or "wildlife" in p:
        location = "forest and wildlife locations"

    elif "city" in p:
        location = "city locations"

    else:
        location = "city locations"

    return traveler, purpose, spend, location


def get_persona_index(persona):

    traveler, purpose, spend, location = parse_json_persona(persona)

    personas = build_persona_index()

    target = (traveler, purpose, spend, location)

    for i, p in enumerate(personas):

        if p == target:
            return i + 1

    return 1


# --------------------------------------------------
# Reference collection
# --------------------------------------------------

def collect_reference_information(row: dict) -> list:
    refs = []

    if "reference_information" in row and row["reference_information"]:
        refs.append(row["reference_information"])

    idx = 1
    while True:
        key = f"reference_information_{idx}"
        if key not in row:
            break
        val = row.get(key)
        if val:
            refs.append(val)
        idx += 1

    parsed = []
    for r in refs:
        try:
            parsed.extend(json.loads(r))
        except Exception:
            pass

    return parsed


# --------------------------------------------------
# Transport parsing
# --------------------------------------------------

def parse_transport(desc: str):
    if not desc:
        return None

    m = re.search(
        r"from\s+(.*?)\s+to\s+(.*?)(?:\s+on\s+(\d{4}-\d{2}-\d{2}))?$",
        desc,
        re.IGNORECASE,
    )
    if not m:
        return None

    return {
        "from": m.group(1).strip(),
        "to": m.group(2).strip(),
        "date": m.group(3),
    }


def extract_cities_from_transport(reference_blocks, origin):
    legs = []

    for item in reference_blocks:
        if not isinstance(item, dict):
            continue
        parsed = parse_transport(item.get("Description", ""))
        if parsed:
            legs.append(parsed)

    legs.sort(key=lambda x: x["date"] or "")

    cities = []
    current = origin

    for leg in legs:
        if leg["from"] == current:
            cities.append(leg["to"])
            current = leg["to"]

    return cities


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def enforce_city_count(cities, city_count):
    if len(cities) >= city_count:
        return cities[:city_count]
    return cities + [""] * (city_count - len(cities))


def compute_travel_dates(all_dates, day_type):
    """
    Deterministic mapping that MUST match TransportAgent._travel_days()
    """
    if not all_dates:
        return []

    if day_type == 3:
        return [all_dates[0], all_dates[-1]]

    if day_type == 5:
        return [all_dates[0], all_dates[2], all_dates[-1]]

    if day_type == 7:
        return [all_dates[0], all_dates[2], all_dates[4], all_dates[-1]]

    return []


# --------------------------------------------------
# Accommodation extraction
# --------------------------------------------------

def get_accommodations_for_city(city, persona=None, max_results=25):

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    CSV_PATH = os.path.abspath(
        os.path.join(
            BASE_DIR,
            "TripCraft_database/accommodation/cleaned_listings_final_v2.csv"
        )
    )

    REVIEW_PATH = os.path.abspath(
        os.path.join(
            BASE_DIR,
            "TripCraft_database/review_signal/accomodation_review_summary_with_persona.csv"
        )
    )

    review_by_index = {}
    review_by_name = {}

    if os.path.exists(REVIEW_PATH):

        with open(REVIEW_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    idx = int(float(row["accommodation_index"]))
                    review_by_index[idx] = row
                except:
                    pass

                key = (
                    row["City"].strip().lower(),
                    row["Name"].strip().lower()
                )

                review_by_name[key] = row

    results = []
    city = city.strip().lower()
    persona_idx = get_persona_index(persona) if persona else 1

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:

            if not row.get("City"):
                continue

            if row["City"].strip().lower() != city:
                continue

            try:
                pricing_dict = ast.literal_eval(row.get("pricing", ""))
                price_str = pricing_dict.get("price")
                if not price_str:
                    continue
                price = float(price_str.replace("$", ""))
            except:
                continue

            rating = None
            try:
                rating_dict = ast.literal_eval(row.get("rating", ""))
                rating = rating_dict.get("average")
            except:
                pass

            try:
                max_occ = int(row.get("max_occupancy"))
            except:
                continue

            review = None

            try:
                idx = int(float(row.get("accommodation_index")))
                review = review_by_index.get(idx)
            except:
                pass

            if review is None:

                key = (
                    row.get("City", "").strip().lower(),
                    row.get("name", "").strip().lower()
                )

                review = review_by_name.get(key)

            review_summary = None
            num_reviews = None
            accommodation_quality = None
            comfort_signal = None
            cleanliness_signal = None
            location_signal = None
            host_signal = None
            amenities_signal = None
            noise_risk = None
            safety_risk = None
            alignment = None
            utility = None

            if review:

                review_summary = review.get("Review_Summary")
                num_reviews = float(review.get("num_reviews") or 0)

                accommodation_quality = float(review.get("accommodation_quality") or 0)
                comfort_signal = float(review.get("comfort_signal") or 0)
                cleanliness_signal = float(review.get("cleanliness_signal") or 0)
                location_signal = float(review.get("location_signal") or 0)
                host_signal = float(review.get("host_signal") or 0)
                amenities_signal = float(review.get("amenities_signal") or 0)

                noise_risk = float(review.get("noise_risk") or 0)
                safety_risk = float(review.get("safety_risk") or 0)

                alignment = float(review.get(f"persona_{persona_idx}_alignment") or 0)
                utility = float(review.get(f"persona_{persona_idx}_utility") or 0)

            results.append({
                "name": row.get("name"),
                "price_per_night": price,
                "room_type": row.get("roomType"),
                "house_rules": row.get("house_rules"),
                "minimum_nights": 1,
                "maximum_occupancy": max_occ,
                "review_rate": rating,
                "city": row.get("City"),

                "num_reviews": num_reviews,
                "accommodation_quality": accommodation_quality,
                "comfort_signal": comfort_signal,
                "cleanliness_signal": cleanliness_signal,
                "location_signal": location_signal,
                "host_signal": host_signal,
                "amenities_signal": amenities_signal,
                "noise_risk": noise_risk,
                "safety_risk": safety_risk,
                "persona_alignment": alignment,
                "persona_utility": utility,

                "review_summary": review_summary
            })

    results = [
        h for h in results
        if h.get("price_per_night") not in (None, math.inf)
    ]

    results.sort(
        key=lambda h: (
            h.get("price_per_night", math.inf),
            -(float(h.get("accommodation_quality") or 0))
        )
    )

    return results[:max_results]

def parse_persona_to_json(persona_str):
    if not persona_str or not isinstance(persona_str, str):
        return {}

    persona = {}
    parts = [p.strip() for p in persona_str.split(";") if p.strip()]

    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        persona[key] = value.strip().lower()

    return persona

def parse_duration_to_minutes(duration_str):
    if not duration_str:
        return None

    duration_str = duration_str.lower()

    hours = 0
    minutes = 0

    h = re.search(r"(\d+)\s*hour", duration_str)
    m = re.search(r"(\d+)\s*minute", duration_str)

    if h:
        hours = int(h.group(1))

    if m:
        minutes = int(m.group(1))

    return hours * 60 + minutes

def parse_local_constraint_to_json(local_constraint):
    if not local_constraint:
        return {}

    if isinstance(local_constraint, dict):
        raw = local_constraint
    else:
        try:
            raw = ast.literal_eval(local_constraint)
            if not isinstance(raw, dict):
                return {}
        except Exception:
            return {}

    normalized = {}
    for k, v in raw.items():
        key = k.strip().lower().replace(" ", "_")
        normalized[key] = v

    return normalized

def build_transport_ref(
    origin_city: str,
    city_sequence: list,
    trip_days: int,
    travel_dates: list
):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    DIST_CSV = os.path.abspath(
        os.path.join(
            BASE_DIR,
            "TripCraft_database/distance_matrix/city_distances_times_full.csv"
        )
    )

    FLIGHT_DB = os.path.abspath(
        os.path.join(
            BASE_DIR,
            "db/flights.db"
        )
    )

    # --------------------------------------------------
    # Build legs
    # --------------------------------------------------
    if trip_days == 3:
        legs = [
            (origin_city, city_sequence[0]),
            (city_sequence[0], origin_city),
        ]
    elif trip_days == 5:
        legs = [
            (origin_city, city_sequence[0]),
            (city_sequence[0], city_sequence[1]),
            (city_sequence[1], origin_city),
        ]
    else:  # 7-day
        legs = [
            (origin_city, city_sequence[0]),
            (city_sequence[0], city_sequence[1]),
            (city_sequence[1], city_sequence[2]),
            (city_sequence[2], origin_city),
        ]

    # --------------------------------------------------
    # Load distance matrix
    # --------------------------------------------------
    distance_map = {}
    with open(DIST_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r["distance_km"] or not r["duration_min"]:
                continue
            key = (r["origin"].lower(), r["destination"].lower())
            distance_map[key] = {
                "distance_km": float(r["distance_km"]),
                "duration_minutes": int(float(r["duration_min"]))
            }

    # --------------------------------------------------
    # Build transport_ref
    # --------------------------------------------------
    import sqlite3
    conn = sqlite3.connect(FLIGHT_DB)
    cursor = conn.cursor()

    transport_ref = {"legs": []}

    for (frm, to), date in zip(legs, travel_dates):
        modes = {}

        # ✈️ Flights
        cursor.execute("""
            SELECT "Flight Number", Price, DepTime, ArrTime, ActualElapsedTime
            FROM flights
            WHERE LOWER(OriginCityName) = LOWER(?)
              AND LOWER(DestCityName) = LOWER(?)
              AND FlightDate = ?
            ORDER BY Price ASC
        """, (frm, to, date))

        flights = []
        for f in cursor.fetchall():
            flights.append({
                "flight_number": f[0],
                "price": int(f[1]),
                "departure_time": f[2],
                "arrival_time": f[3],
                "duration_minutes": parse_duration_to_minutes(f[4]),
                "date": date,
                "from": frm,
                "to": to
            })

        if flights:
            modes["flight"] = flights

        # 🚕 Taxi & 🚗 Self-driving
        key = (frm.lower(), to.lower())
        if key in distance_map:
            d = distance_map[key]
            modes["taxi"] = {
                "duration_minutes": d["duration_minutes"],
                "cost": round(d["distance_km"] * 1, 2),
                "from": frm,
                "to": to
            }
            modes["self-driving"] = {
                "duration_minutes": d["duration_minutes"],
                "cost": round(d["distance_km"] * 0.05, 2),
                "from": frm,
                "to": to
            }

        transport_ref["legs"].append({
            "from": frm,
            "to": to,
            "modes": modes
        })

    conn.close()
    return transport_ref

def get_restaurants_for_city(city, persona_json=None, max_results=40):

    BASE = os.path.dirname(os.path.abspath(__file__))

    CSV_PATH = os.path.join(
        BASE,
        "TripCraft_database/restaurants/cleaned_restaurant_details_2024.csv"
    )

    REVIEW_PATH = os.path.join(
        BASE,
        "TripCraft_database/review_signal/restaurant_review_summary_with_persona.csv"
    )

    review_by_index = {}
    review_by_name = {}

    # ----------------------------------
    # LOAD REVIEW SIGNALS
    # ----------------------------------

    if os.path.exists(REVIEW_PATH):

        with open(REVIEW_PATH, newline="", encoding="utf-8") as f:

            reader = csv.DictReader(f)

            for row in reader:

                try:
                    idx = int(float(row["restaurant_index"]))
                    review_by_index[idx] = row
                except:
                    pass

                key = (
                    row["City"].strip().lower(),
                    row["Name"].strip().lower()
                )

                review_by_name.setdefault(key, []).append(row)

    city = city.lower().strip()
    results = []

    persona_idx = get_persona_index(persona_json) if persona_json else 1

    with open(CSV_PATH, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for r in reader:

            # -----------------------
            # City filter
            # -----------------------

            if r.get("City", "").lower().strip() != city:
                continue

            name = r.get("name")

            if not name:
                continue

            # -----------------------
            # Avg cost
            # -----------------------

            try:
                avg_cost = float(r["avg_cost"])
                if avg_cost <= 0:
                    continue
            except:
                continue

            # -----------------------
            # Rating
            # -----------------------

            try:
                rating = float(r["rating"])
            except:
                rating = None

            # -----------------------
            # Cuisines
            # -----------------------

            cuisines = []

            try:
                raw = r.get("cuisines")

                if raw:
                    cuisines = [
                        c.strip().lower()
                        for c in ast.literal_eval(raw)
                        if isinstance(c, str)
                    ]
            except:
                cuisines = []

            # -----------------------
            # REVIEW LOOKUP
            # -----------------------

            review_rows = []

            try:
                idx = int(float(r.get("restaurant_index")))
                rr = review_by_index.get(idx)

                if rr:
                    review_rows = [rr]

            except:
                pass

            if not review_rows:

                key = (
                    r.get("City", "").strip().lower(),
                    name.strip().lower()
                )

                review_rows = review_by_name.get(key, [])

            # -----------------------
            # AGGREGATE REVIEW SIGNALS
            # -----------------------

            restaurant_quality = None
            food_signal = None
            service_signal = None
            ambience_signal = None
            value_signal = None
            menu_variety_signal = None
            wait_risk = None
            hygiene_risk = None
            alignment = None
            utility = None
            review_summary = None

            if review_rows:

                def avg(field):

                    vals = []

                    for rr in review_rows:
                        try:
                            vals.append(float(rr.get(field)))
                        except:
                            pass

                    return sum(vals)/len(vals) if vals else None

                restaurant_quality = avg("restaurant_quality")
                food_signal = avg("food_signal")
                service_signal = avg("service_signal")
                ambience_signal = avg("ambience_signal")
                value_signal = avg("value_signal")
                menu_variety_signal = avg("menu_variety_signal")

                wait_risk = avg("wait_risk")
                hygiene_risk = avg("hygiene_risk")

                alignment = avg(f"persona_{persona_idx}_alignment")
                utility = avg(f"persona_{persona_idx}_utility")

                summaries = [
                    rr.get("Review_Summary")
                    for rr in review_rows
                    if rr.get("Review_Summary")
                ]

                if summaries:
                    review_summary = max(summaries, key=len)

            # -----------------------
            # Final object
            # -----------------------

            results.append({

                "name": name,
                "avg_cost": avg_cost,
                "cuisines": cuisines,
                "aggregate_rating": rating,

                # review signals
                "restaurant_quality": restaurant_quality,
                "food_signal": food_signal,
                "service_signal": service_signal,
                "ambience_signal": ambience_signal,
                "value_signal": value_signal,
                "menu_variety_signal": menu_variety_signal,

                "wait_risk": wait_risk,
                "hygiene_risk": hygiene_risk,

                "persona_alignment": alignment,
                "persona_utility": utility,

                "review_summary": review_summary
            })

    # ----------------------------------
    # SORT (same as agent)
    # ----------------------------------

    results.sort(
        key=lambda r: (
            -(r.get("persona_alignment") or 0),
            -(r.get("persona_utility") or 0),
            -(r.get("restaurant_quality") or 0),
            -(r.get("food_signal") or 0),
            (r.get("wait_risk") or 1),
            (r.get("hygiene_risk") or 1),
            r.get("avg_cost", float("inf"))
        )
    )

    return results[:max_results]


def get_attractions_for_city(city, persona_json=None, max_results=50):

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    CSV_PATH = os.path.join(
        BASE_DIR,
        "TripCraft_database/attraction/cleaned_attractions_final.csv"
    )

    REVIEW_PATH = os.path.join(
        BASE_DIR,
        "TripCraft_database/review_signal/attraction_review_summary_with_persona.csv"
    )

    review_by_index = {}
    review_by_name = {}

    # ----------------------------------
    # LOAD REVIEW SIGNALS
    # ----------------------------------
    if os.path.exists(REVIEW_PATH):

        with open(REVIEW_PATH, newline="", encoding="utf-8") as f:

            reader = csv.DictReader(f)

            for row in reader:

                try:
                    idx = int(float(row["attraction_index"]))
                    review_by_index[idx] = row
                except:
                    pass

                key = (
                    row["City"].strip().lower(),
                    row["Name"].strip().lower()
                )

                review_by_name.setdefault(key, []).append(row)

    city = city.strip().lower()
    persona_idx = get_persona_index(persona_json) if persona_json else 1

    results = []

    with open(CSV_PATH, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            if row.get("City", "").strip().lower() != city:
                continue

            # -------------------
            # Categories
            # -------------------
            categories = []
            try:
                raw = row.get("subcategories") or row.get("subtype")
                if raw:
                    categories = [
                        c.strip().lower()
                        for c in ast.literal_eval(raw)
                        if isinstance(c, str)
                    ]
            except:
                pass

            # -------------------
            # Visit duration
            # -------------------
            try:
                visit_duration = float(row.get("visit_duration"))
            except:
                visit_duration = None

            # -------------------
            # REVIEW LOOKUP
            # -------------------
            review_rows = []

            try:
                idx = int(float(row.get("attraction_index")))
                r = review_by_index.get(idx)
                if r:
                    review_rows = [r]
            except:
                pass

            if not review_rows:

                key = (
                    row.get("City", "").strip().lower(),
                    row.get("name", "").strip().lower()
                )

                review_rows = review_by_name.get(key, [])

            # -------------------
            # REVIEW SIGNALS
            # -------------------
            attraction_quality = None
            experience_signal = None
            nature_signal = None
            culture_signal = None
            family_signal = None
            facility_signal = None
            tour_signal = None
            shopping_signal = None
            crowd_risk = None
            safety_risk = None
            alignment = None
            utility = None
            review_summary = None

            if review_rows:

                def avg(field):
                    vals = []
                    for r in review_rows:
                        try:
                            vals.append(float(r.get(field)))
                        except:
                            pass
                    return sum(vals)/len(vals) if vals else None

                attraction_quality = avg("attraction_quality")
                experience_signal = avg("experience_signal")
                nature_signal = avg("nature_signal")
                culture_signal = avg("culture_signal")
                family_signal = avg("family_signal")
                facility_signal = avg("facility_signal")
                tour_signal = avg("tour_signal")
                shopping_signal = avg("shopping_signal")

                alignment = avg(f"persona_{persona_idx}_alignment")
                utility = avg(f"persona_{persona_idx}_utility")

                crowd_risk = avg("crowd_risk")
                safety_risk = avg("safety_risk")

                summaries = [
                    r.get("Review_Summary")
                    for r in review_rows
                    if r.get("Review_Summary")
                ]

                if summaries:
                    review_summary = max(summaries, key=len)

            results.append({
                "name": row.get("name"),
                "categories": categories,
                "description": row.get("description") or "",
                "visit_duration": visit_duration,

                # review signals
                "attraction_quality": attraction_quality,
                "experience_signal": experience_signal,
                "nature_signal": nature_signal,
                "culture_signal": culture_signal,
                "family_signal": family_signal,
                "facility_signal": facility_signal,
                "tour_signal": tour_signal,
                "shopping_signal": shopping_signal,

                "persona_alignment": alignment,
                "persona_utility": utility,

                "crowd_risk": crowd_risk,
                "safety_risk": safety_risk,

                "review_summary": review_summary
            })

    # same ranking logic as agent
    results.sort(
        key=lambda a: (
            -(a.get("persona_alignment") or 0),
            -(a.get("persona_utility") or 0),
            -(a.get("attraction_quality") or 0),
            -(a.get("experience_signal") or 0),
            (a.get("crowd_risk") or 1),
            (a.get("safety_risk") or 1),
        )
    )

    return results[:max_results]


def get_events_for_city(city, travel_dates, max_results=40):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CSV_PATH = os.path.join(
        BASE_DIR,
        "TripCraft_database/events/events_cleaned.csv"
    )

    city = city.strip().lower()
    results = []
    seen_names = set()

    # convert travel_dates → date objects
    allowed_dates = set(
        datetime.strptime(d, "%Y-%m-%d").date()
        for d in travel_dates
    )

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # ---- CITY FILTER ----
            if row.get("city", "").strip().lower() != city:
                continue

            raw_date = row.get("dateTitle")
            if not raw_date:
                continue

            # ---- DATE PARSING (single or range) ----
            try:
                if "to" in raw_date:
                    s, e = [x.strip() for x in raw_date.split("to")]
                    start = datetime.strptime(s, "%d-%m-%Y").date()
                    end = datetime.strptime(e, "%d-%m-%Y").date()
                else:
                    start = end = datetime.strptime(
                        raw_date.strip(), "%d-%m-%Y"
                    ).date()
            except Exception:
                continue

            # ---- OVERLAP CHECK ----
            if not any(start <= d <= end for d in allowed_dates):
                continue

            name = row.get("name")
            if not name:
                continue

            # ---- PREVENT DUPLICATES PER CITY ----
            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)

            categories = []
            if row.get("segmentName"):
                categories.append(row["segmentName"].lower())

            results.append({
                "name": name,
                # assign FIRST matching date only
                "date": min(
                    d.strftime("%Y-%m-%d")
                    for d in allowed_dates
                    if start <= d <= end
                ),
                "categories": categories,
                "city": row.get("city"),
            })

            if len(results) >= max_results:
                break

    return results

def split_event_dates_by_city(all_dates, city_count):
    usable = all_dates[:-1]  # drop return day

    chunks = []
    for i in range(city_count):
        start = i * 2
        end = start + 2
        chunks.append(usable[start:end])

    return chunks

# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print("Usage: python create_csv.py <3|5|7>")
        sys.exit(1)

    day_type = int(sys.argv[1])
    if day_type not in (3, 5, 7):
        raise ValueError("day_type must be 3, 5, or 7")

    input_csv = f"/scratch/sg/Vijay/TripCraft/tripcraft_{day_type}day.csv"
    output_csv = f"/scratch/sg/Vijay/TripCraft/tripcraft_{day_type}day_review_inputs.tsv"

    city_count = {3: 1, 5: 2, 7: 3}[day_type]

    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    new_rows = []

    for row in rows:
        origin = row.get("org")

        reference_blocks = collect_reference_information(row)
        cities = extract_cities_from_transport(reference_blocks, origin)
        cities = enforce_city_count(cities, city_count)

        all_dates = ast.literal_eval(row.get("date") or row.get("dates"))
        travel_dates = compute_travel_dates(all_dates, day_type)

        new_row = OrderedDict()

        for k, v in row.items():
            if k == "annotation_plan":
                continue
            if k.startswith("reference_information"):
                continue
            new_row[k] = v

        new_row["persona_json"] = json.dumps(
            parse_persona_to_json(row.get("persona")),
            ensure_ascii=False
        )

        new_row["localconstraints_json"] = json.dumps(
            parse_local_constraint_to_json(row.get("local_constraint")),
            ensure_ascii=False
        )

        new_row["city_sequence"] = json.dumps(
            cities, ensure_ascii=False
        )
        event_date_chunks = split_event_dates_by_city(all_dates, city_count)

        

        for i in range(city_count):
            city = cities[i]
            new_row[f"city_{i+1}"] = city
            persona = json.loads(new_row["persona_json"])
            traveler, purpose, spend, location = parse_json_persona(persona)
            persona_idx = get_persona_index(persona)

            # print("\n================ PERSONA DEBUG ================")
            # print("Persona JSON:", persona)
            # print("Parsed traveler:", traveler)
            # print("Parsed purpose:", purpose)
            # print("Parsed spending:", spend)
            # print("Parsed location:", location)
            # print("Persona Index:", persona_idx)
            # print("===============================================\n")

            accoms = get_accommodations_for_city(city,persona) if city else []
            meals = get_restaurants_for_city(city,persona) if city else []
            attractions = get_attractions_for_city(city,persona) if city else []

            new_row[f"accommodation_city_{i+1}"] = json.dumps(
                accoms, ensure_ascii=False
            )
            new_row[f"accommodation_city_{i+1}_response"] = ""
            new_row[f"accommodation_city_{i+1}_upgrade_response"] = ""
            new_row[f"restaurants_city_{i+1}"] = json.dumps(
                meals, ensure_ascii=False
            )
            new_row[f"restaurants_city_{i+1}_response"] = ""
            new_row[f"attractions_city_{i+1}"] = json.dumps(
                attractions, ensure_ascii=False
            )
            new_row[f"attractions_city_{i+1}_response"] = ""
            city_dates = event_date_chunks[i]
            events = get_events_for_city(city, city_dates)

            new_row[f"events_city_{i+1}"] = json.dumps(events, ensure_ascii=False)
            new_row[f"events_city_{i+1}_response"] = ""
        # REQUIRED placeholders for TransportAgent
        transport_ref = build_transport_ref(
            origin_city=origin,
            city_sequence=cities,   
            trip_days=day_type,
            travel_dates=travel_dates
        )
        new_row["transport_cap"] = ""
        new_row["travel_dates"] = json.dumps(
            travel_dates, ensure_ascii=False
        )

        new_row["transport_ref"] = json.dumps(
            transport_ref, ensure_ascii=False
        )
        new_row["allowed_modes"] = ""

        new_row["transport_response"] = ""
        new_row["meals_cap"] = ""
        new_row["upgrade_budget"]=""
        new_row["combined_data"]=""
        new_row["skeleton"]=""
        new_row["generated_plan"]=""

        clean_row = {}

        for k, v in new_row.items():

            if isinstance(v, str):

                v = fix_text(v)

                # 🔧 VERY IMPORTANT
                # remove characters that break TSV structure
                v = v.replace("\n", " ").replace("\r", " ").replace("\t", " ")

                clean_row[k] = v

            else:
                clean_row[k] = v

        new_rows.append(clean_row)
        # print("CITY:", city)
        # print("Restaurant SAMPLE:", json.dumps(meals, indent=2))
        # break

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=new_rows[0].keys(),
            delimiter="\t"
        )
        writer.writeheader()
        writer.writerows(new_rows)

    print(f"✅ Created: {output_csv}")


if __name__ == "__main__":
    main()
