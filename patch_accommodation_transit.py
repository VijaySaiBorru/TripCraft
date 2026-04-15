import os
import json
import csv
import argparse

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
BASE_OUTPUT = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic"
CSV_PATH = "/scratch/sg/Vijay/TripCraft/TripCraft_database/public_transit_gtfs/all_poi_nearest_stops.csv"


# ------------------------------------------------------------
# Transit Resolver
# ------------------------------------------------------------
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

            row_poi = row["PoI"].strip().lower()
            row_city = row["City"].strip().lower()

            if row_poi != poi:
                continue

            if row_city != city_l:
                continue

            try:
                dist_val = float(row.get("nearest_stop_distance"))
            except Exception:
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


# ------------------------------------------------------------
# Resolve Correct City
# ------------------------------------------------------------
def resolve_city_for_day(day, idx, n_days):

    current_city = day["current_city"]

    if "from " in current_city:
        route = current_city.replace("from ", "")
        origin, dest = route.split(" to ")
        origin = origin.strip()
        dest = dest.strip()

        if idx == 0:
            return dest
        elif idx == n_days - 1:
            return origin
        else:
            return dest
    else:
        return current_city.strip()


# ------------------------------------------------------------
# Patch POI String (Stay + Visit)
# ------------------------------------------------------------
def patch_poi_string(poi_string, city):

    entries = poi_string.split(";")
    new_entries = []

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        if (
            ("stay from" in entry or "visit from" in entry)
            and "nearest transit" not in entry
        ):
            name = entry.split(",")[0].strip()
            transit = resolve_transit_for_poi(name, city)

            if transit:
                entry = (
                    f"{entry}, nearest transit: "
                    f"{transit['stop']}, "
                    f"{transit['distance']}m away"
                )

        new_entries.append(entry)

    if not new_entries:
        return ""

    return "; ".join(new_entries) + ";"


# ------------------------------------------------------------
# Patch Single File
# ------------------------------------------------------------
def patch_single_file(input_path, output_path):

    if not os.path.exists(input_path):
        return

    print("Processing:", input_path)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    days = data.get("days", [])
    n_days = len(days)

    for idx, day in enumerate(days):
        city = resolve_city_for_day(day, idx, n_days)
        poi_list = day.get("point_of_interest_list", "")
        if poi_list:
            day["point_of_interest_list"] = patch_poi_string(poi_list, city)

    # Handle top-level POI dict (LLM case)
    if isinstance(data.get("point_of_interest_list"), dict):
        top_dict = data["point_of_interest_list"]
        for key, poi_string in top_dict.items():
            day_index = int(key) - 1
            if 0 <= day_index < n_days:
                city = resolve_city_for_day(days[day_index], day_index, n_days)
                top_dict[key] = patch_poi_string(poi_string, city)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("Created:", output_path)


# ------------------------------------------------------------
# Patch All Query Folders
# ------------------------------------------------------------
def patch_all_queries(model_name, days_number):

    day_type = f"{days_number}day"

    base_path = os.path.join(BASE_OUTPUT, model_name, day_type)

    if not os.path.exists(base_path):
        print("Path not found:", base_path)
        return

    print("\n=======================================")
    print("PATCHING ALL QUERIES")
    print("Model:", model_name)
    print("Days:", day_type)
    print("Base Path:", base_path)
    print("=======================================\n")

    for folder in os.listdir(base_path):

        folder_path = os.path.join(base_path, folder)

        if not os.path.isdir(folder_path):
            continue

        print("\n--- Query Folder:", folder, "---")

        input_file_1 = os.path.join(folder_path, "tripcraft_response.json")
        output_file_1 = os.path.join(folder_path, "tripcraft_response_stay.json")

        input_file_2 = os.path.join(folder_path, "llm_tripcraft_response.json")
        output_file_2 = os.path.join(folder_path, "llm_tripcraft_response_stay.json")

        if os.path.exists(input_file_1):
            patch_single_file(input_file_1, output_file_1)

        if os.path.exists(input_file_2):
            patch_single_file(input_file_2, output_file_2)

    print("\n✅ ALL DONE")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--days", type=int, required=True, choices=[3,5,7])

    args = parser.parse_args()

    patch_all_queries(
        model_name=args.model,
        days_number=args.days
    )
