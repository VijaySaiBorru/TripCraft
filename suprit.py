import os
import json
import argparse

# Base dataset folder
BASE_PATH = "/scratch/sg/Vijay/TripCraft"


def get_input_output_paths(model_name, day_type):
    """
    Build input & output JSONL paths automatically
    """
    input_file = os.path.join(
        BASE_PATH,
        f"{model_name}_{day_type}day_llm_final.jsonl"
    )

    output_file = os.path.join(
        BASE_PATH,
        f"suprit_{model_name}_{day_type}day_llm_clean.jsonl"
    )

    if not os.path.exists(input_file):
        raise FileNotFoundError(f"❌ Input JSONL not found: {input_file}")

    return input_file, output_file


def clean_plan(plan):
    """Remove point_of_interest_list from each day"""
    if not isinstance(plan, list):
        return plan

    for day in plan:
        if isinstance(day, dict):
            day.pop("point_of_interest_list", None)

    return plan


def process_jsonl(input_path, output_path):
    total = 0
    modified = 0

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:

        for line in fin:
            if not line.strip():
                continue

            data = json.loads(line)

            if "plan" in data:
                before = json.dumps(data["plan"])
                data["plan"] = clean_plan(data["plan"])
                after = json.dumps(data["plan"])

                if before != after:
                    modified += 1

            fout.write(json.dumps(data, ensure_ascii=False) + "\n")
            total += 1

    print("\n========== CLEANING COMPLETE ==========")
    print(f"Total entries processed : {total}")
    print(f"Entries modified        : {modified}")
    print(f"Output saved to         : {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remove point_of_interest_list from TripCraft JSONL plans"
    )

    parser.add_argument("--model_name", type=str, required=True,
                        help="Model name (e.g., qwen2.5, llama3, mistral)")

    parser.add_argument("--day_type", type=int, required=True,
                        choices=[3, 5, 7],
                        help="Trip duration (3, 5, or 7 days)")

    args = parser.parse_args()

    input_path, output_path = get_input_output_paths(
        args.model_name,
        args.day_type
    )

    print(f"Reading : {input_path}")
    print(f"Writing : {output_path}")

    process_jsonl(input_path, output_path)
