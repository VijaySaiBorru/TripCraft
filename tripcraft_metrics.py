import json
import pandas as pd
import re


tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/original/UHRS_Task_plangen_7day_tripcraft.tsv"
jsonl_path = "/scratch/sg/Vijay/TripCraft/tripcraft_golden_7day.jsonl"
output_path = "/scratch/sg/Vijay/TripCraft/original_tripcraft_7day.jsonl"

# load TSV
df = pd.read_csv(tsv_path, sep="\t")

generated_plans = df["generated_travel_plan"].apply(json.loads)


def ensure_string(val):

    if val is None:
        return "-"

    if isinstance(val, list):

        items = []
        for v in val:

            if isinstance(v, dict):
                items.append(" ".join(str(x) for x in v.values()))
            else:
                items.append(str(v))

        return "; ".join(items)

    return str(val)


def convert_generated_plan(plan_dict):

    converted = []

    for day_key, content in plan_dict.items():

        match = re.search(r'\d+', str(day_key))
        if not match:
            continue

        day_num = int(match.group())

        converted.append({
            "day": day_num,
            "current_city": ensure_string(content.get("Current City", "-")),
            "transportation": ensure_string(content.get("Transportation", "-")),
            "breakfast": ensure_string(content.get("Breakfast", "-")),
            "attraction": ensure_string(content.get("Attraction", "-")),
            "lunch": ensure_string(content.get("Lunch", "-")),
            "dinner": ensure_string(content.get("Dinner", "-")),
            "accommodation": ensure_string(content.get("Accommodation", "-")),
            "event": ensure_string(content.get("Event", "-")),
            "point_of_interest_list": ensure_string(content.get("Point of Interest List", "-"))
        })

    converted.sort(key=lambda x: x["day"])

    return converted


with open(jsonl_path, "r") as f_in, open(output_path, "w") as f_out:

    for line in f_in:

        obj = json.loads(line)

        idx = obj["idx"] - 1
        gen_plan = generated_plans.iloc[idx]

        obj["plan"] = convert_generated_plan(gen_plan)

        f_out.write(json.dumps(obj) + "\n")


print("Finished. File saved at:", output_path)