import json
import re

JSONL_PATH = "/scratch/sg/Vijay/TripCraft/tripcraft_golden_3day.jsonl"

# --------------------------------------------------
# Normalizers
# --------------------------------------------------

def normalize_plan_days_to_day(obj):
    if "plan" not in obj:
        return obj

    for p in obj["plan"]:
        if "days" in p and "day" not in p:
            p["day"] = p["days"]
            del p["days"]

    return obj


def normalize_date_to_dates(obj):
    if "JSON" not in obj:
        return obj

    json_block = obj["JSON"]

    if "date" in json_block and "dates" not in json_block:
        json_block["dates"] = json_block["date"]
        del json_block["date"]

    return obj


def normalize_poi_times(obj):
    """
    Normalize:
    from H:MM to HH:MM
    """

    if "plan" not in obj:
        return obj

    time_pattern = re.compile(
        r'from\s+(\d{1,2}):(\d{2})\s+to\s+(\d{1,2}):(\d{2})'
    )

    def pad(match):
        h1, m1, h2, m2 = match.groups()
        return f"from {int(h1):02d}:{m1} to {int(h2):02d}:{m2}"

    for p in obj["plan"]:
        poi = p.get("point_of_interest_list")
        if not poi or poi == "-":
            continue

        p["point_of_interest_list"] = time_pattern.sub(pad, poi)

    return obj


def normalize_poi_distance(obj):
    """
    CRITICAL FIX:
    - '529.04m away.'  → '529.04m away'
    - normalize extra spaces after 'nearest transit:'
    """

    if "plan" not in obj:
        return obj

    for p in obj["plan"]:
        poi = p.get("point_of_interest_list")
        if not poi or poi == "-":
            continue

        # remove trailing dot ONLY after 'm away.'
        poi = re.sub(r'm away\.', 'm away', poi)

        # normalize spacing after colon
        poi = re.sub(r'nearest transit:\s+', 'nearest transit: ', poi)

        p["point_of_interest_list"] = poi

    return obj


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    fixed_lines = []
    idx_counter = 1

    with open(JSONL_PATH, "r") as f:
        for line in f:
            obj = json.loads(line)

            # overwrite / inject idx
            obj["idx"] = idx_counter
            idx_counter += 1

            # apply all normalizers
            obj = normalize_plan_days_to_day(obj)
            obj = normalize_date_to_dates(obj)
            obj = normalize_poi_times(obj)
            obj = normalize_poi_distance(obj)

            fixed_lines.append(json.dumps(obj, ensure_ascii=False))

    # overwrite file in-place
    with open(JSONL_PATH, "w") as f:
        for line in fixed_lines:
            f.write(line + "\n")

    print("✅ JSONL normalized successfully")
    print("   - day / dates fixed")
    print("   - PoI times padded")
    print("   - 'm away.' → 'm away'")
    print("   - SAFE for evaluator")


if __name__ == "__main__":
    main()
