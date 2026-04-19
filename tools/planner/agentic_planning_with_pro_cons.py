# /scratch/sg/Vijay/TripCraft/tools/planner/agentic_planning.py
"""
Run AgenticPlanner on TravelPlanner dataset.

Saves:
  - trip_json_used.json
  - reference.json
  - combined_reference.json  (what is passed into the scheduler)
  - llm_tripcraft_response.json  (FULL LLM output)
  - tripcraft_response.json      (FULL deterministic output)
  - errors.json                  (if any agents / planner report errors)
  - failed_output.json           (if planner returned status "error")
"""

import os
import json
import argparse
import asyncio
from copy import deepcopy
import pandas as pd
from pathlib import Path
from data_manager.data_manager import DataManager
from agentic_trip_with_pro_cons.reference_builder import ReferenceBuilder
from agentic_trip_with_pro_cons.agenticplanner import AgenticPlanner as AgenticPlanner
from agentic_trip_with_pro_cons_mistral.agenticplanner import AgenticPlanner as AgenticPlannerMistral
from core.llm_backend import init_llm
from extract_query import extract_query


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------
def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(x) for x in obj]
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    elif str(obj) == "nan":
        return None
    else:
        return obj


def safe_parse(x):
    if isinstance(x, (dict, list)):
        return x
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        try:
            return json.loads(s)
        except:
            pass
        try:
            import ast
            return ast.literal_eval(s)
        except:
            return s
    return x

def collect_reference_information(row, days):
    refs = []

    # 3-day case
    if "reference_information" in row and pd.notna(row["reference_information"]):
        refs.append(str(row["reference_information"]))

    # 5-day / 7-day / future cases
    idx = 1
    while True:
        key = f"reference_information_{idx}"
        if key not in row:
            break
        val = row.get(key)
        if pd.notna(val):
            refs.append(str(val))
        idx += 1

    if not refs:
        return ""

    return "\n\n".join(refs)


def build_trip_json_from_dataset_row(row):
    """Normalize HF dataset row into trip_json for AgenticPlanner."""
    # print(row)
    dates = safe_parse(row.get("date") or row.get("dates") or [])
    # print(row)
    if isinstance(dates, str):
        try:
            dates = json.loads(dates.replace("'", '"'))
        except:
            dates = [dates]

    persona = row.get("persona") or ""
    budget = row.get("budget") or 0
    days = int(row.get("days") or len(dates) or 1)
    reference_information = collect_reference_information(row, days)


    try:
        budget = float(budget)
    except:
        budget = 0

    people = row.get("people_number", 1)
    try:
        people = int(people)
    except:
        people = 1
    local_constraint = safe_parse(row.get("local_constraint", {}))
    if not isinstance(local_constraint, dict):
        local_constraint = {}

    trip_json = {
        "org": row.get("org"),
        "dest": row.get("dest"),
        "days": int(row.get("days") or len(dates) or 1),
        "dates": dates,
        "people_number": people,
        "local_constraint": local_constraint,
        "budget": budget,
        "visiting_city_number":int(row.get("visiting_city_number")),
        "query": row.get("query", ""),
        "persona": row.get("persona") or row.get("query", ""),
        "reference_information":reference_information
    }
    return trip_json


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


# -----------------------------------------------------------
# MAIN
# -----------------------------------------------------------
def main():
    print("[MAIN] Starting AgenticPlanner run...")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", required=True)
    parser.add_argument("--api_key")
    parser.add_argument("--day_type", default="3")
    parser.add_argument("--output_dir", default="output")
    parser.add_argument("--basepath", default="")
    parser.add_argument("--start_idx", type=int, default=0)
    parser.add_argument("--end_idx", type=int, default=None)
    args = parser.parse_args()

    # Set API keys
    os.environ["OPENAI_API_KEY"] = args.api_key
    os.environ["GEMINI_API_KEY"] = args.api_key
    os.environ["GOOGLE_API_KEY"] = args.api_key

    # Load data manager
    dm = DataManager(base_path=args.basepath)
    print("[MAIN] Loading DM resources...")
    dm.load_all()

    # Load dataset
    # ds = load_dataset("osunlp/TravelPlanner", args.set_type)[args.set_type]
    # n = len(ds)
    # print(f"[MAIN] Dataset size: {n}")
    csv_path = Path(__file__).resolve().parents[2] / f"tripcraft_{args.day_type}day.csv"
    # csv_path = f"/scratch/sg/Vijay/TripCraft/tripcraft_{args.day_type}day.csv"
    df = pd.read_csv(csv_path)
    n = len(df)
    print(f"[MAIN] TripCraft CSV size: {n}")


    # Init LLM backend
    print(f"[MAIN] Initializing LLM: {args.model_name}")
    llm = init_llm(args.model_name, args.api_key)
    # print(f"[MAIN] Model initialized: {'mistral' in args.model_name.lower()}")

    planner = AgenticPlannerMistral(dm=dm, llm=llm) if "mistral" in args.model_name.lower() else AgenticPlanner(dm=dm, llm=llm)
    ref_builder = ReferenceBuilder(dm)

    start = args.start_idx
    end = args.end_idx or n
    # count = 171
    day_type_check = int(args.day_type)

    if day_type_check == 5:
        count = 0
    elif day_type_check == 7:
        count = 0
    else:
        count = 0
    # count = -1
    stop =1


    for idx in range(start, min(end, n)):
        
        if idx<=count:
            continue
        if idx > stop:
            continue
        # row = ds[idx]
        row = df.iloc[idx].to_dict()
        print(idx,count)
        trip_json = build_trip_json_from_dataset_row(row)
        days = trip_json.get("days")
        # -------------------------------------------------
        # Query-based extraction (TEST SET ONLY)
        # -------------------------------------------------
        if args.day_type == "test":
            extracted = extract_query(trip_json, llm)

            # merge safely (ONLY if extracted)
            if "people_number" in extracted:
                trip_json["people_number"] = extracted["people_number"]

            if "budget" in extracted:
                trip_json["budget"] = extracted["budget"]

            if "local_constraint" in extracted:
                # ensure dict exists
                if not isinstance(trip_json.get("local_constraint"), dict):
                    trip_json["local_constraint"] = {}
                trip_json["local_constraint"].update(extracted["local_constraint"])


        out_dir = os.path.join(
            args.output_dir,
            "agentic",
            args.model_name,
            f"{days}day",
            str(idx + 1)
        )
        ensure_dir(out_dir)

        # Paths
        ref_path = os.path.join(out_dir, "reference.json")
        trip_json_path = os.path.join(out_dir, "trip_json_used.json")
        llm_path = os.path.join(out_dir, "llm_tripcraft_response.json")
        manual_path = os.path.join(out_dir, "tripcraft_response.json")
        non_agentic_path = os.path.join(out_dir, "non_agentic_tripcraft_response.json")
        combined_ref_path = os.path.join(out_dir, "combined_reference.json")
        errors_path = os.path.join(out_dir, "errors.json")
        failed_output_path = os.path.join(out_dir, "failed_output.json")

        print(f"[RUN] Trip {idx+1} | {trip_json['org']} -> {trip_json['dest']} | {days} days")

        try:
            # Build reference JSON
            # -------------------------------------------------
            # Build reference JSON (ONLY if not already present)
            # -------------------------------------------------
            if trip_json.get("reference_information"):
                print("[MAIN] Using reference_information from dataset (skipping DataManager)")
                reference_json = {
                    "reference_information": safe_parse(trip_json["reference_information"])
                }
            else:
                print("[MAIN] Collecting reference via DataManager")
                reference_json = ref_builder.build(trip_json)

            safe_reference = make_json_safe(reference_json)
            # print("Trip Json Used:",trip_json)


            # Save input jsons
            with open(trip_json_path, "w", encoding="utf-8") as f:
                json.dump(trip_json, f, indent=2)

            with open(ref_path, "w", encoding="utf-8") as f:
                json.dump(safe_reference, f, indent=2)

            # Run full pipeline
            result = asyncio.run(planner.run_full_pipeline(trip_json, reference_json))
            # print("Result came from pipeline",result)

            # --- handle status and errors ---
            status = result.get("status", "ok")
            errors = result.get("errors") or []

            # Save errors.json if any
            if errors:
                try:
                    with open(errors_path, "w", encoding="utf-8") as f:
                        json.dump(errors, f, indent=2)
                except Exception:
                    pass

            if status == "error":
                # fatal planner error — save result for debugging and skip regular saves
                print(f"[ERR] Planner returned fatal error for trip {idx+1}")
                try:
                    with open(failed_output_path, "w", encoding="utf-8") as f:
                        json.dump(make_json_safe(result), f, indent=2)
                except Exception:
                    pass
                # continue to next trip instead of saving partial output
                continue

            if status == "fallback":
                print(f"[WARN] Planner used fallback deterministic plan for trip {idx+1}")

            # -----------------------------
            # Save full LLM output (if exists)
            # -----------------------------
            llm_raw = result.get("llm_raw")
            if llm_raw is not None:
                try:
                    if not llm_raw:
                        payload = {
                            "status": "no_output",
                            "reason": "No valid LLM timing / itinerary produced"
                        }
                    else:
                        payload = make_json_safe(llm_raw)

                    with open(llm_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2)
                except Exception:
                    pass


            # -----------------------------
            # Save full deterministic output (manual plan)
            # -----------------------------
            manual_full = result.get("manual_plan")
            if manual_full is not None:
                try:
                    if not manual_full:
                        payload = {
                            "status": "no_output",
                            "reason": "No valid manual itinerary produced"
                        }
                    else:
                        payload = make_json_safe(manual_full)

                    with open(manual_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2)
                except Exception:
                    pass

            
            # non_agentic_full = result.get("non_agentic_plan")
            # if non_agentic_full is not None:
            #     try:
            #         if not non_agentic_full:
            #             payload = {
            #                 "status": "no_output",
            #                 "reason": "No valid non-agentic itinerary produced"
            #             }
            #         else:
            #             payload = make_json_safe(non_agentic_full)

            #         with open(non_agentic_path, "w", encoding="utf-8") as f:
            #             json.dump(payload, f, indent=2)
            #     except Exception:
            #         pass


            # -----------------------------
            # Save combined reference (what was passed to the scheduler)
            # -----------------------------
            combined = result.get("combined_reference")
            if combined:
                try:
                    with open(combined_ref_path, "w", encoding="utf-8") as f:
                        json.dump(make_json_safe(combined), f, indent=2)
                except Exception:
                    pass

            print(f"[DONE] Saved trip {idx+1} → {out_dir}")

        except Exception as e:
            print(f"[ERR] Failed trip {idx+1}: {e}")
            err_path = os.path.join(out_dir, "error.txt")
            ensure_dir(out_dir)
            with open(err_path, "w", encoding="utf-8") as f:
                import traceback
                traceback.print_exc(file=f)

        # break   # remove later

    print("[ALL DONE]")


if __name__ == "__main__":
    main()


# source ~/.bashrc
# tmux new -s gpu_job
# conda activate tripcraftvijay