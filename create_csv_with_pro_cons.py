# /scratch/sg/Vijay/TripCraft/create_csv_with_pro_cons.py

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

def parse_pipe(text):
    if not text or str(text).strip().lower() in ("", "nan"):
        return []
    return [x.strip() for x in str(text).split("|") if x.strip()]


def get_accommodations_for_city(city, persona=None, max_results=25):

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    CSV_PATH = os.path.abspath(
        os.path.join(
            BASE_DIR,
            "TripCraft_database/accommodation/cleaned_listings_final_v2.csv"
        )
    )

    # ✅ USE THIS FILE (already has pros/cons)
    REVIEW_PATH = os.path.abspath(
        os.path.join(
            BASE_DIR,
            "TripCraft_database/review_pro_cons/accomodation_review_pro_cons.csv"
        )
    )

    review_by_index = {}
    review_by_name = {}

    # ------------------------------
    # LOAD PROS / CONS
    # ------------------------------
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

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:

            if row.get("City", "").strip().lower() != city:
                continue

            # ---- price ----
            try:
                pricing_dict = ast.literal_eval(row.get("pricing", ""))
                price = float(pricing_dict.get("price").replace("$", ""))
            except:
                continue

            # ---- rating ----
            try:
                rating_dict = ast.literal_eval(row.get("rating", ""))
                rating = rating_dict.get("average")
            except:
                rating = None

            # ---- occupancy ----
            try:
                max_occ = int(row.get("max_occupancy"))
            except:
                continue

            # -----------------------------
            # REVIEW LOOKUP (PROS / CONS)
            # -----------------------------
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

            pros = []
            cons = []

            if review:
                pros.extend(parse_pipe(review.get("Pros")))
                cons.extend(parse_pipe(review.get("Cons")))

            pros = list(dict.fromkeys(pros))
            cons = list(dict.fromkeys(cons))

            results.append({
                "name": row.get("name"),
                "price_per_night": price,
                "room_type": row.get("roomType"),
                "house_rules": row.get("house_rules"),
                "minimum_nights": 1,
                "maximum_occupancy": max_occ,
                "review_rate": rating,
                "pros": pros,
                "cons": cons,
                "pros_count": len(pros),
                "cons_count": len(cons)
            })

    results = [
        h for h in results
        if h.get("price_per_night") not in (None, math.inf)
    ]

    results.sort(key=lambda h: h.get("price_per_night", math.inf))

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

def extract_multi_reviews(review_rows, parse_pipe):
    pros = []
    cons = []

    for r in review_rows:
        pros.extend(parse_pipe(r.get("Pros") or r.get("pros")))
        cons.extend(parse_pipe(r.get("Cons") or r.get("cons")))

    # remove duplicates
    pros = list(dict.fromkeys(pros))
    cons = list(dict.fromkeys(cons))

    return pros, cons

def get_restaurants_for_city(city, persona_json=None, max_results=30):

    BASE = os.path.dirname(os.path.abspath(__file__))

    CSV_PATH = os.path.join(
        BASE,
        "TripCraft_database/restaurants/cleaned_restaurant_details_2024.csv"
    )

    REVIEW_PATH = os.path.join(
        BASE,
        "TripCraft_database/review_pro_cons/restaurant_review_pro_cons_clean.csv"
    )

    review_by_index = {}
    review_by_name = {}

    # ✅ FIX: store LIST per index
    if os.path.exists(REVIEW_PATH):
        with open(REVIEW_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    idx = int(float(row["restaurant_index"]))
                    review_by_index.setdefault(idx, []).append(row)
                except:
                    pass

                key = (
                    row["City"].strip().lower(),
                    row["Name"].strip().lower()
                )
                review_by_name.setdefault(key, []).append(row)

    city = city.lower().strip()
    results = []

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:

            if row.get("City", "").lower().strip() != city:
                continue

            name = row.get("name")
            if not name:
                continue

            try:
                avg_cost = float(row["avg_cost"])
                if avg_cost <= 0:
                    continue
            except:
                continue

            try:
                rating = float(row["rating"])
            except:
                rating = None

            cuisines = []
            try:
                raw = row.get("cuisines")
                if raw:
                    cuisines = [
                        c.strip().lower()
                        for c in ast.literal_eval(raw)
                        if isinstance(c, str)
                    ]
            except:
                pass

            # -----------------------------
            # REVIEW LOOKUP
            # -----------------------------
            review_rows = []

            try:
                idx = int(float(row.get("restaurant_index")))
                rr = review_by_index.get(idx)
                if rr:
                    review_rows = rr   # ✅ FIX
            except:
                pass

            if not review_rows:
                key = (
                    row.get("City", "").strip().lower(),
                    name.strip().lower()
                )
                review_rows = review_by_name.get(key, [])

            # ✅ MULTI EXTRACTION
            pros, cons = extract_multi_reviews(review_rows, parse_pipe)

            if not pros:
                pros = ["good food"]
            if not cons:
                cons = ["no major issues"]

            results.append({
                "name": name,
                "avg_cost": avg_cost,
                "cuisines": cuisines,
                "aggregate_rating": rating,
                "pros": pros,
                "cons": cons,
                "pros_count": len(pros),
                "cons_count": len(cons)
            })

    results.sort(
        key=lambda r: (
            -(r.get("pros_count") or 0),
            (r.get("cons_count") or 0) * 3,
            -(r.get("aggregate_rating") or 0),
            r.get("avg_cost", float("inf"))
        )
    )

    return results[:max_results]

def get_attractions_for_city(city, persona_json=None, max_results=40):

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    CSV_PATH = os.path.join(
        BASE_DIR,
        "TripCraft_database/attraction/cleaned_attractions_final.csv"
    )

    REVIEW_PATH = os.path.join(
        BASE_DIR,
        "TripCraft_database/review_pro_cons/attraction_review_pro_cons_fixed.csv"
    )

    review_by_index = {}
    review_by_name = {}

    # ✅ FIX: store LIST
    if os.path.exists(REVIEW_PATH):
        with open(REVIEW_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    idx = int(float(row["attraction_index"]))
                    review_by_index.setdefault(idx, []).append(row)
                except:
                    pass

                key = (
                    row["City"].strip().lower(),
                    row["Name"].strip().lower()
                )
                review_by_name.setdefault(key, []).append(row)

    city = city.strip().lower()
    results = []

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:

            if row.get("City", "").strip().lower() != city:
                continue

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

            try:
                visit_duration = float(row.get("visit_duration"))
            except:
                visit_duration = None

            # -----------------------------
            # REVIEW LOOKUP
            # -----------------------------
            review_rows = []

            try:
                idx = int(float(row.get("attraction_index")))
                rr = review_by_index.get(idx)
                if rr:
                    review_rows = rr   # ✅ FIX
            except:
                pass

            if not review_rows:
                key = (
                    row.get("City", "").strip().lower(),
                    row.get("name", "").strip().lower()
                )
                review_rows = review_by_name.get(key, [])

            # ✅ MULTI EXTRACTION
            pros, cons = extract_multi_reviews(review_rows, parse_pipe)

            if not pros:
                pros = ["nice place"]
            if not cons:
                cons = ["no major issues"]

            results.append({
                "name": row.get("name"),
                "categories": categories,
                "visit_duration": visit_duration,
                "pros": pros,
                "cons": cons,
                "pros_count": len(pros),
                "cons_count": len(cons)
            })

    results.sort(
        key=lambda a: (
            -(a.get("pros_count") or 0),
            (a.get("cons_count") or 0) * 3,
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
    output_csv = f"/scratch/sg/Vijay/TripCraft/tripcraft_{day_type}day_pro_cons_inputs.tsv"

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
