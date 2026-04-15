import pandas as pd
import json
import ast
import csv

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/5day/UHRS_Task_v13_vijaysai_selcol_tripcraft_5d_noreview.tsv"

CSV_PATH = "/scratch/sg/Vijay/TripCraft/TripCraft_database/public_transit_gtfs/all_poi_nearest_stops.csv"


# -------------------------------------------------
# SAFE LOADERS
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
# PROCESS
# -------------------------------------------------
for idx, row in df.iterrows():
    try:
        schedule = safe_json(row.get("final_schedule")) or []
        dates = safe_eval(row.get("date"))

        events_city_1 = safe_json(row.get("events_city_1_response")) or {}
        events_city_2 = safe_json(row.get("events_city_2_response")) or {}

        city_1 = str(row.get("city_1", "")).strip()
        city_2 = str(row.get("city_2", "")).strip()

        poi_map = {
            1: str(row.get("day1_itinerary_formatted", "")),
            2: str(row.get("day2_itinerary_formatted", "")),
            3: str(row.get("day3_itinerary_formatted", "")),
            4: str(row.get("day4_itinerary_formatted", "")),
            5: str(row.get("day5_itinerary_formatted", "")),
        }

        # ---------------- PROCESS DAYS ----------------
        for i, day in enumerate(schedule):
            day_num = day.get("day", i + 1)

            # 🔥 CITY SWITCH
            if day_num <= 3:
                city = city_1
                events_dict = events_city_1
            else:
                city = city_2
                events_dict = events_city_2

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
# SAVE
# -------------------------------------------------
df["final_schedule_fixed"] = final_fixed
df.to_csv(tsv_path, sep="\t", index=False)

print("✅ Done. 5-day schedule enriched successfully.")