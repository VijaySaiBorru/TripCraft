import pandas as pd
import json

tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/7day/UHRS_Task_v7_tripcraft_7d_noreview_inputs.tsv"

df = pd.read_csv(tsv_path, sep="\t")

fixed_schedules = []

for idx, row in df.iterrows():
    try:
        schedule = json.loads(row["final_schedule_fixed"])

        for day in schedule:
            poi_text = day.get("point_of_interest_list", "").lower()

            def exists_in_poi(name):
                if not name or name == "-":
                    return False
                base = name.split(",")[0].strip().lower()
                return base in poi_text

            # ---------------- FIX MEALS ----------------
            for meal in ["breakfast", "lunch", "dinner"]:
                if not exists_in_poi(day.get(meal)):
                    day[meal] = "-"

            # ---------------- FIX ATTRACTIONS ----------------
            attr = day.get("attraction", "")
            if attr and attr != "-":
                valid_attrs = []

                for a in attr.split(";"):
                    a = a.strip()
                    if not a:
                        continue

                    name = a.split(",")[0].strip()

                    if exists_in_poi(name):
                        valid_attrs.append(a)

                day["attraction"] = "; ".join(valid_attrs) if valid_attrs else "-"

        fixed_schedules.append(json.dumps(schedule))

    except Exception as e:
        print(f"❌ Error at row {idx}: {e}")
        fixed_schedules.append(None)

# Save
df["final_schedule_cleaned"] = fixed_schedules
df.to_csv(tsv_path, sep="\t", index=False)

print("✅ Meals + Attractions cleaned successfully")