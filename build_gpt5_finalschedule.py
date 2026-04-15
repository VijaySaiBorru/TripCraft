import pandas as pd
import json
import ast
import csv

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/3day/UHRS_Task_tripcraft_3day_noreview.tsv"

CSV_PATH = "/scratch/sg/Vijay/TripCraft/TripCraft_database/public_transit_gtfs/all_poi_nearest_stops.csv"


# -------------------------------------------------
# SAFE LOADERS (NEW)
# -------------------------------------------------
def safe_json(x):
    try:
        if x is None:
            return None

        if isinstance(x, float) and pd.isna(x):
            return None

        if isinstance(x, (list, dict)):
            return x

        text = str(x).strip()

        if text == "" or text.lower() == "nan":
            return None

        try:
            return json.loads(text)
        except:
            return ast.literal_eval(text)

    except:
        return None


def safe_eval(x):
    try:
        return ast.literal_eval(str(x))
    except:
        return []


# -------------------------------------------------
# TRANSIT RESOLVER
# -------------------------------------------------
def resolve_transit_for_poi(poi_name, city):
    poi = poi_name.strip().lower()
    city_l = city.strip().lower()

    best = None
    best_dist = float("inf")

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if not row.get("PoI") or not row.get("City"):
                continue

            if row["PoI"].strip().lower() != poi:
                continue

            if row["City"].strip().lower() != city_l:
                continue

            try:
                dist_val = float(row.get("nearest_stop_distance"))
            except:
                continue

            if dist_val > 10000:
                continue

            if dist_val < best_dist:
                best = {
                    "stop": row.get("nearest_stop_name"),
                    "distance": dist_val
                }
                best_dist = dist_val

    return best


# -------------------------------------------------
# ADD TRANSIT
# -------------------------------------------------
def enrich_poi_string(poi_text, city):
    if not poi_text:
        return "-"

    entries = poi_text.split(";")
    new_entries = []

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        name = entry.split(",")[0].strip()

        transit = resolve_transit_for_poi(name, city)

        if transit:
            entry = (
                f"{entry}, nearest transit: "
                f"{transit['stop']}, {transit['distance']}m away"
            )

        new_entries.append(entry)

    return "; ".join(new_entries)


# -------------------------------------------------
# LOAD DATA
# -------------------------------------------------
df = pd.read_csv(tsv_path, sep="\t")

final_fixed = []


# -------------------------------------------------
# PROCESS ALL ROWS
# -------------------------------------------------
for idx, row in df.iterrows():
    try:
        schedule = safe_json(row.get("final_schedule")) or []
        dates = safe_eval(row.get("date"))

        events_dict = safe_json(row.get("events_city_1_response")) or {}

        poi_map = {
            1: str(row.get("day1_itinerary_formatted", "")),
            2: str(row.get("day2_itinerary_formatted", "")),
            3: str(row.get("day3_itinerary_formatted", "")),
        }

        # ✅ use dataset city directly
        city = str(row.get("city_1", "")).strip()

        # ---------------- ENRICH ----------------
        for i, day in enumerate(schedule):
            day_num = day.get("day", i + 1)

            # -------- event --------
            date = dates[i] if i < len(dates) else None
            event = events_dict.get(date, "-") if date else "-"

            if event and event != "-":
                day["event"] = f"{event}, {city}"
            else:
                day["event"] = "-"

            # -------- POI + transit --------
            raw_poi = poi_map.get(day_num, "")
            enriched_poi = enrich_poi_string(raw_poi, city)

            day["point_of_interest_list"] = enriched_poi

        final_fixed.append(json.dumps(schedule))

    except Exception as e:
        print(f"❌ Error at row {idx}: {e}")
        final_fixed.append(None)


# -------------------------------------------------
# SAVE COLUMN
# -------------------------------------------------
df["final_schedule_fixed"] = final_fixed
df.to_csv(tsv_path, sep="\t", index=False)

print("✅ Done. Column 'final_schedule_fixed' added.")