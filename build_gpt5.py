import pandas as pd
import json
import sys
import ast

sys.path.append("/scratch/sg/Vijay/TripCraft")

from agentic_trip.final_schedule_builder_dur import FinalScheduleBuilder

tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/3day/UHRS_Task_tripcraft_3day_noreview.tsv"

# Load full file
df = pd.read_csv(tsv_path, sep="\t")

algorithmic_schedules = []

for idx, row in df.iterrows():
    try:
        # -------------------------------------------------
        # 1️⃣ Load combined_plan
        # -------------------------------------------------
        combined_plan = json.loads(row["combined_plan"])

        # Fix dates
        combined_plan["dates"] = ast.literal_eval(row["date"])

        # Persona STRING (builder expects string)
        persona = row["persona"]
        combined_plan["persona"] = persona

        # -------------------------------------------------
        # 2️⃣ Load structured pools
        # -------------------------------------------------
        restaurants_pool = json.loads(row["restaurants_city_1"])
        attractions_pool = json.loads(row["attractions_city_1"])

        events_pool = json.loads(row["events_city_1"]) if pd.notna(row["events_city_1"]) else []

        # -------------------------------------------------
        # 3️⃣ Load ranked responses (names only)
        # -------------------------------------------------
        restaurants_ranked_names = json.loads(row["restaurants_city_1_response"])
        attractions_ranked_names = json.loads(row["attractions_city_1_response"])

        events_ranked_dict = (
            json.loads(row["events_city_1_response"])
            if pd.notna(row["events_city_1_response"])
            else {}
        )

        accommodation_full = json.loads(row["accommodation_city_1_response"])["hotel"]

        # -------------------------------------------------
        # 4️⃣ Reconstruct ranked structured objects
        # -------------------------------------------------
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

        events_ranked = []

        for date, name in events_ranked_dict.items():
            if name is not None and str(name).strip() != "":
                events_ranked.append({
                    "name": name,
                    "date": date,
                    "city": row["city_1"]
                })

        # -------------------------------------------------
        # 5️⃣ Build builder-compatible structure
        # -------------------------------------------------
        fixed_city = {
            "city": row["city_1"],
            "days": len(combined_plan["dates"]),
            "accommodation": accommodation_full,
            "restaurants_ranked": restaurants_ranked,
            "attractions_ranked": attractions_ranked,
            "events_ranked": events_ranked,
            "raw_transit_rows": []
        }

        combined_plan["cities"] = [fixed_city]

        # -------------------------------------------------
        # 6️⃣ Call Final Builder
        # -------------------------------------------------
        builder = FinalScheduleBuilder(persona=persona)
        final_output = builder.build_plan_from_combined(combined_plan)

        # ✅ Save ONLY the itinerary plan (no budget fields)
        algorithmic_schedules.append(json.dumps(final_output["days"]))

    except Exception as e:
        print(f"❌ Error at row {idx}: {e}")
        algorithmic_schedules.append(None)

# -------------------------------------------------
# 7️⃣ Add new column
# -------------------------------------------------
df["algorithmic_final_schedule"] = algorithmic_schedules

# -------------------------------------------------
# 8️⃣ Save back to same file
# -------------------------------------------------
df.to_csv(tsv_path, sep="\t", index=False)

print("✅ Done. 'algorithmic_final_schedule' column added successfully.")