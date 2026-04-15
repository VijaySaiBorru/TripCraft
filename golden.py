import json
import os
import re


def clean_poi_string(poi_string):
    if not isinstance(poi_string, str):
        return poi_string

    # ---------------------------------
    # 1. Fix single-digit hour → HH:MM
    # ---------------------------------
    def fix_time(match):
        hour = int(match.group(1))
        minute = match.group(2)
        return f"{hour:02d}:{minute}"

    poi_string = re.sub(r"\b(\d{1}):(\d{2})\b", fix_time, poi_string)

    # ---------------------------------
    # 2. Fix space before 'm'
    #    "6142.35 m away" → "6142.35m away"
    # ---------------------------------
    poi_string = re.sub(r"(\d+\.?\d*)\s+m away", r"\1m away", poi_string)

    # ---------------------------------
    # 3. Convert "meters away" → "m away"
    # ---------------------------------
    poi_string = re.sub(r"(\d+\.?\d*)\s*meters away", r"\1m away", poi_string)

    # ---------------------------------
    # 4. Fix missing 'away'
    #    "76.21m;" → "76.21m away;"
    # ---------------------------------
    poi_string = re.sub(r"(\d+\.?\d*)m(?=\s*;)", r"\1m away", poi_string)

    # ---------------------------------
    # 5. Fix ANY dots before semicolon
    #    Handles:
    #    m away.;
    #    m away .;
    #    m away. .;
    #    m away...;
    # ---------------------------------
    poi_string = re.sub(r"m away\s*\.+\s*;", "m away;", poi_string)

    # ---------------------------------
    # 6. Remove trailing dot at very end
    # ---------------------------------
    poi_string = poi_string.rstrip().rstrip(".")

    return poi_string


def fix_jsonl_inplace(file_path):

    print(f"\n🔄 Fixing file: {file_path}")

    updated_lines = []

    with open(file_path, "r", encoding="utf-8") as infile:
        for line in infile:
            data = json.loads(line)

            for day in data.get("plan", []):
                if "point_of_interest_list" in day:
                    day["point_of_interest_list"] = clean_poi_string(
                        day["point_of_interest_list"]
                    )

            updated_lines.append(json.dumps(data, ensure_ascii=False))

    with open(file_path, "w", encoding="utf-8") as outfile:
        for line in updated_lines:
            outfile.write(line + "\n")

    print(f"✅ Updated in-place: {file_path}")


if __name__ == "__main__":

    base_path = "/scratch/sg/Vijay/TripCraft"

    fix_jsonl_inplace(os.path.join(base_path, "tripcraft_golden_5day.jsonl"))
    fix_jsonl_inplace(os.path.join(base_path, "tripcraft_golden_7day.jsonl"))

    print("\n🎉 PoI formatting fully sanitized successfully!")
