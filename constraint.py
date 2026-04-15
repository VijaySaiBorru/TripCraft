import pandas as pd
import json
import ast
from collections import defaultdict

CSV_PATHS = [
    "/scratch/sg/Vijay/TripCraft/tripcraft_3day.csv",
    "/scratch/sg/Vijay/TripCraft/tripcraft_5day.csv",
    "/scratch/sg/Vijay/TripCraft/tripcraft_7day.csv",
]

ATTRACTION_DB = "/scratch/sg/Vijay/TripCraft/TripCraft_database/attraction/cleaned_attractions_final.csv"

def parse_persona(val):
    """
    Parses persona strings like:
    'Traveler Type: Adventure Seeker; Purpose of Travel: Cultural Exploration; ...'
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return {}

    if not isinstance(val, str):
        return {}

    result = {}
    parts = [p.strip() for p in val.split(";") if p.strip()]

    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        result[key.strip()] = value.strip()

    return result


def safe_parse(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return {}

    if isinstance(val, dict):
        return val

    if isinstance(val, str):
        s = val.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            try:
                return ast.literal_eval(s)
            except Exception:
                return {}

    return {}


def main():
    local_constraint_values = defaultdict(set)
    persona_values = defaultdict(set)

    # ======================================================
    # PART 1: CSV-level aggregation (local_constraint + persona)
    # ======================================================
    for csv_path in CSV_PATHS:
        df = pd.read_csv(csv_path)

        for _, row in df.iterrows():

            # ---------- local_constraint ----------
            lc = safe_parse(row.get("local_constraint"))
            for key, value in lc.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    for v in value:
                        local_constraint_values[key].add(str(v))
                else:
                    local_constraint_values[key].add(str(value))

            # ---------- persona ----------
            persona = parse_persona(row.get("persona"))

            for key, value in persona.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    for v in value:
                        persona_values[key].add(str(v))
                else:
                    persona_values[key].add(str(value))

    # ======================================================
    # PART 2: Attraction duration analysis (DB-level)
    # ======================================================
    att_df = pd.read_csv(ATTRACTION_DB)

    # sanity: drop missing
    att_df = att_df.dropna(subset=["visit_duration"])

    # assume visit_duration is in HOURS → convert to minutes
    durations_min = att_df["visit_duration"] * 60

    buckets = {
        "<=30 min": (0, 30),
        "31–60 min": (31, 60),
        "61–90 min": (61, 90),
        "91–120 min": (91, 120),
        "121–180 min": (121, 180),
        ">180 min": (181, 10000),
    }

    duration_dist = {}
    for label, (lo, hi) in buckets.items():
        duration_dist[label] = ((durations_min >= lo) & (durations_min <= hi)).sum()

    # ======================================================
    # OUTPUT
    # ======================================================
    print("\n" + "=" * 100)
    print("AGGREGATED LOCAL_CONSTRAINT VALUES (3day + 5day + 7day)")
    print("=" * 100)
    for key in sorted(local_constraint_values):
        print(f"\n{key}:")
        for v in sorted(local_constraint_values[key]):
            print(f"  - {v}")

    print("\n" + "=" * 100)
    print("AGGREGATED PERSONA VALUES (3day + 5day + 7day)")
    print("=" * 100)
    for key in sorted(persona_values):
        print(f"\n{key}:")
        for v in sorted(persona_values[key]):
            print(f"  - {v}")

    print("\n" + "=" * 100)
    print("ATTRACTION VISIT_DURATION DISTRIBUTION (minutes)")
    print("=" * 100)
    for k, v in duration_dist.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
