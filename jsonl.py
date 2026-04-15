import os
import json
import csv
import argparse

# ---------------- CONSTANT BASE PATHS ----------------
CSV_BASE = "/scratch/sg/Vijay/TripCraft"
AGENTIC_ROOT = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic"
# ----------------------------------------------------


def load_levels(csv_path):
    """
    levels[i] corresponds to CSV row (i+1)
    """
    levels = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            levels.append(row["level"].strip())
    return levels


def convert(model_name, day_type):
    csv_path = os.path.join(CSV_BASE, f"tripcraft_{day_type}day.csv")
    agentic_day_dir = os.path.join(
        AGENTIC_ROOT, model_name, f"{day_type}day"
    )

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    if not os.path.isdir(agentic_day_dir):
        raise FileNotFoundError(f"Agentic dir not found: {agentic_day_dir}")

    output_tripcraft = f"{model_name}_{day_type}day_final.jsonl"
    output_llm = f"{model_name}_{day_type}day_llm_final.jsonl"

    levels = load_levels(csv_path)

    expected_indices = set(range(1, len(levels) + 1))

    generated_tc = set()
    generated_llm = set()

    written_tc = 0
    written_llm = 0

    out_tc = open(output_tripcraft, "w", encoding="utf-8")
    out_llm = open(output_llm, "w", encoding="utf-8")

    for inst in sorted(os.listdir(agentic_day_dir), key=lambda x: int(x) if x.isdigit() else 0):
        if not inst.isdigit():
            continue

        inst_idx = int(inst)
        csv_idx = inst_idx - 1

        if csv_idx >= len(levels):
            continue

        inst_dir = os.path.join(agentic_day_dir, inst)
        if not os.path.isdir(inst_dir):
            continue

        query_path = os.path.join(inst_dir, "trip_json_used.json")
        tripcraft_path = os.path.join(inst_dir, "tripcraft_response.json")
        llm_path = os.path.join(inst_dir, "llm_tripcraft_response.json")

        if not os.path.exists(query_path):
            continue

        try:
            with open(query_path, "r", encoding="utf-8") as f:
                query_json = json.load(f)
        except Exception:
            continue

        # inject level
        query_json["level"] = levels[csv_idx]

        base_record = {
            "idx": inst_idx, 
            "model": model_name,
            "day": day_type,
            "JSON": query_json
        }

        # -------- TripCraft response --------
        if os.path.exists(tripcraft_path):
            try:
                with open(tripcraft_path, "r", encoding="utf-8") as f:
                    tc_json = json.load(f)
                tc_plan = tc_json.get("days")

                if isinstance(tc_plan, list) and tc_plan:
                    out_tc.write(json.dumps({
                        **base_record,
                        "plan": tc_plan
                    }, ensure_ascii=False) + "\n")
                    written_tc += 1
                    generated_tc.add(inst_idx)
            except Exception:
                pass

        # -------- LLM response --------
        if os.path.exists(llm_path):
            try:
                with open(llm_path, "r", encoding="utf-8") as f:
                    llm_json = json.load(f)
                llm_plan = llm_json.get("days")

                if isinstance(llm_plan, list) and llm_plan:
                    out_llm.write(json.dumps({
                        **base_record,
                        "plan": llm_plan
                    }, ensure_ascii=False) + "\n")
                    written_llm += 1
                    generated_llm.add(inst_idx)
            except Exception:
                pass

    out_tc.close()
    out_llm.close()

    missing_tc = sorted(expected_indices - generated_tc)
    missing_llm = sorted(expected_indices - generated_llm)

    print(f"\n Manual plans written : {written_tc} → {output_tripcraft}")
    print(f" LLM plans written       : {written_llm} → {output_llm}")

    if missing_tc:
        print(f" Missing Manual plans ({len(missing_tc)}):")
        print(missing_tc)
    else:
        print(" All Manual plans generated!")

    if missing_llm:
        print(f" Missing LLM plans ({len(missing_llm)}):")
        print(missing_llm)
    else:
        print(" All LLM plans generated!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Model name (e.g. qwen2.5)")
    parser.add_argument("--day", required=True, choices=["3", "5", "7"],
                        help="Day type: 3, 5, or 7")

    args = parser.parse_args()

    convert(
        model_name=args.model,
        day_type=args.day
    )
