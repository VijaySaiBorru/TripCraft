import pandas as pd
import json
import sys
import ast

sys.path.append("/scratch/sg/Vijay/TripCraft")

from agentic_trip.final_schedule_builder_dur import FinalScheduleBuilder

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/7day/UHRS_Task_v7_tripcraft_7d_noreview_inputs.tsv"

df = pd.read_csv(tsv_path, sep="\t")

algorithmic_schedules = []

DEBUG_FIRST = False


for idx, row in df.iterrows():
    try:
        # -------------------------------------------------
        # 1️⃣ Load combined_plan
        # -------------------------------------------------
        combined_plan = json.loads(row["combined_plan"])
        combined_plan["dates"] = ast.literal_eval(row["date"])
        persona = row["persona"]
        combined_plan["persona"] = persona

        cities_final = []

        # =================================================
        # 🔥 LOOP FOR 3 CITIES
        # =================================================
        for city_idx in [1, 2, 3]:

            city_key = f"city_{city_idx}"

            if pd.isna(row.get(city_key)):
                continue

            city_name = row[city_key]

            # ---------------- Pools ----------------
            restaurants_pool = json.loads(row[f"restaurants_city_{city_idx}"])
            attractions_pool = json.loads(row[f"attractions_city_{city_idx}"])

            events_pool = (
                json.loads(row[f"events_city_{city_idx}"])
                if pd.notna(row[f"events_city_{city_idx}"])
                else []
            )

            # ---------------- Ranked names ----------------
            restaurants_ranked_names = json.loads(row[f"restaurants_city_{city_idx}_response"])
            attractions_ranked_names = json.loads(row[f"attractions_city_{city_idx}_response"])

            events_ranked_dict = (
                json.loads(row[f"events_city_{city_idx}_response"])
                if pd.notna(row[f"events_city_{city_idx}_response"])
                else {}
            )

            accommodation_full = json.loads(
                row[f"accommodation_city_{city_idx}_response"]
            )

            # ---------------- Lookups ----------------
            restaurant_lookup = {r["name"]: r for r in restaurants_pool}
            attraction_lookup = {a["name"]: a for a in attractions_pool}

            restaurants_ranked = [
                restaurant_lookup[name]
                for name in restaurants_ranked_names
                if name in restaurant_lookup
            ]

            attractions_ranked = [
                attraction_lookup[name]
                for name in attractions_ranked_names
                if name in attraction_lookup
            ]

            # ---------------- Events ----------------
            events_ranked = []
            for date, name in events_ranked_dict.items():
                if name and str(name).strip():
                    events_ranked.append({
                        "name": name,
                        "date": date,
                        "city": city_name
                    })

            # ---------------- Final city object ----------------
            city_obj = {
                "city": city_name,

                # ⚠️ Optional improvement:
                # Instead of full trip length, you can later use city_days_map
                "days": len(combined_plan["dates"]),

                "accommodation": accommodation_full,
                "restaurants_ranked": restaurants_ranked,
                "attractions_ranked": attractions_ranked,
                "events_ranked": events_ranked,
                "raw_transit_rows": []
            }

            cities_final.append(city_obj)

        # -------------------------------------------------
        # 2️⃣ Attach cities
        # -------------------------------------------------
        combined_plan["cities"] = cities_final

        # -------------------------------------------------
        # 3️⃣ Call builder
        # -------------------------------------------------
        builder = FinalScheduleBuilder(persona=persona)
        final_output = builder.build_plan_from_combined(combined_plan)

        if DEBUG_FIRST:
            print("\n========== FINAL OUTPUT ==========\n")
            print(json.dumps(final_output["days"], indent=2))
            break

        algorithmic_schedules.append(json.dumps(final_output["days"]))

    except Exception as e:
        print(f"❌ Error at row {idx}: {e}")
        if not DEBUG_FIRST:
            algorithmic_schedules.append(None)


# -------------------------------------------------
# SAVE
# -------------------------------------------------
if not DEBUG_FIRST:
    df["algorithmic_final_schedule"] = algorithmic_schedules
    df.to_csv(tsv_path, sep="\t", index=False)

    print("✅ Done. 7-day 3-city schedules generated.")