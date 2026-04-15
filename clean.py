import json
import re
from pathlib import Path

ROOT = Path(
    "/scratch/sg/Vijay/TripCraft/output_agentic/agentic/phi4/3day"
)

TARGET_FILE = "llm_tripcraft_response.json"


def clean_poi_string(poi_str: str) -> str:
    if not poi_str or poi_str == "-":
        return poi_str

    parts = poi_str.split(";")
    cleaned = []

    for p in parts:
        p = p.strip()
        if not p:
            continue

        # remove leading "- " OR "1. ", "2. ", etc.
        p = re.sub(r"^\s*(?:-\s*|\d+\.\s*)", "", p)
        cleaned.append(p)

    return "; ".join(cleaned) + ";" if cleaned else ""


def clean_file(json_path: Path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ---- per-day POIs ----
    for day in data.get("days", []):
        if "point_of_interest_list" in day:
            day["point_of_interest_list"] = clean_poi_string(
                day["point_of_interest_list"]
            )

    # ---- top-level POI map ----
    poi_map = data.get("point_of_interest_list", {})
    for k, v in poi_map.items():
        poi_map[k] = clean_poi_string(v)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ cleaned: {json_path}")


def main():
    if not ROOT.exists():
        raise RuntimeError(f"Root path not found: {ROOT}")

    count = 0

    for run_dir in sorted(ROOT.iterdir()):
        if not run_dir.is_dir():
            continue

        json_path = run_dir / TARGET_FILE
        if not json_path.exists():
            continue

        clean_file(json_path)
        count += 1

    print(f"\n🎯 Done. Cleaned {count} run folders.")


if __name__ == "__main__":
    main()
