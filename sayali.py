import json

input_file = "sayali_3day.jsonl"      # your generated file
output_file = "sayali_3day_fixed.jsonl"

with open(input_file, "r") as infile, open(output_file, "w") as outfile:
    for line in infile:
        data = json.loads(line.strip())

        # Fix plan entries
        if "plan" in data:
            for day_plan in data["plan"]:
                if "days" in day_plan:
                    day_plan["day"] = day_plan.pop("days")

        # Write corrected line
        outfile.write(json.dumps(data) + "\n")

print("✅ Fixed file saved as:", output_file)
