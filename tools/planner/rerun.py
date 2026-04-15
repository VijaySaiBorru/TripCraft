# /scratch/sg/Vijay/TripCraft/tools/planner/rerun.py

"""
Re-run FINAL schedule generation starting from combined_reference.json

- Does NOT rebuild agentic pipeline
- Iterates deterministically from index 1 → dataset size
- Skips indices where combined_reference.json does not exist
- Applies internal count / stop filtering
- Writes rerun outputs to disk
"""

import os
import json
import argparse
from pathlib import Path

from core.llm_backend import init_llm
from agentic_trip.agents.finalscheduleagent import FinalScheduleAgent
from agentic_trip.final_schedule_builder_dur import FinalScheduleBuilder


# --------------------------------------------------
# CONSTANTS
# --------------------------------------------------
BASE_DIR = Path("/scratch/sg/Vijay/TripCraft/output_agentic/agentic")
RETRIES = 3

DATASET_SIZE = {
    "3day": 344,
    "5day": 324,
    "7day": 332,
}


# --------------------------------------------------
# UTILS
# --------------------------------------------------
def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(x) for x in obj]
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    elif str(obj) == "nan":
        return None
    return obj


# --------------------------------------------------
# MAIN
# --------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--day", required=True, help="3 / 5 / 7")
    parser.add_argument("--api_key", required=True)
    parser.add_argument("--start_idx", type=int, default=1)
    parser.add_argument("--end_idx", type=int, default=None)
    args = parser.parse_args()

    # --------------------------------------------------
    # ENV
    # --------------------------------------------------
    os.environ["OPENAI_API_KEY"] = args.api_key
    os.environ["GEMINI_API_KEY"] = args.api_key
    os.environ["GOOGLE_API_KEY"] = args.api_key

    day_folder = f"{args.day}day"

    if day_folder not in DATASET_SIZE:
        raise ValueError(f"Invalid day type: {day_folder}")

    total = DATASET_SIZE[day_folder]

    start = args.start_idx
    end = args.end_idx or total

    # --------------------------------------------------
    # COUNT / STOP LOGIC
    # --------------------------------------------------
    day_type_check = int(args.day)

    if day_type_check == 5:
        count = -1
    elif day_type_check == 7:
        count = -1
    else:
        count = 29

    stop = 370

    base_path = BASE_DIR / args.model / day_folder

    print(
        f"[INFO] Rerun FINAL stage | model={args.model} | day={day_folder} | "
        f"indices={start}..{end} | count={count} | stop={stop}"
    )

    # --------------------------------------------------
    # INIT LLM (ONCE)
    # --------------------------------------------------
    llm = init_llm(args.model, args.api_key)

    # --------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------
    for run_id in range(start, min(end, total) + 1):

        if run_id <= count:
            continue
        if run_id > stop:
            continue

        run_dir = base_path / str(run_id)
        combined_path = run_dir / "combined_reference.json"

        if not combined_path.exists():
            continue

        print(f"\n[RUN] trip={run_id}")

        try:
            combined = json.loads(combined_path.read_text())
        except Exception as e:
            print(f"[ERR] Failed to load combined_reference.json: {e}")
            continue

        trip_json_path = run_dir / "trip_json_used.json"
        query = ""
        persona = ""

        if trip_json_path.exists():
            try:
                trip_json = json.loads(trip_json_path.read_text())
                query = trip_json.get("query", "")
                persona = trip_json.get("persona", "")
            except Exception:
                pass

        try:
            # -------------------------------
            # FINAL AGENT (RETRY-AWARE)
            # -------------------------------
            final_agent = FinalScheduleAgent(llm=llm)

            llm_raw = None

            for attempt in range(1, RETRIES + 1):
                print(f"[LLM] Attempt {attempt} for trip {run_id}")

                try:
                    res = final_agent.generate_final_schedule_from_structured_input(
                        combined,
                        query,
                        retry_attempt=attempt,
                    )
                except Exception as e:
                    print(f"[WARN] Exception on retry {attempt}: {e}")
                    continue

                # 🔑 THIS IS THE CRITICAL FIX
                if isinstance(res, dict) and res.get("error"):
                    print(f"[WARN] Validation failure on retry {attempt}: {res.get('error')}")
                    llm_raw = res
                    continue

                # ✅ success
                llm_raw = res
                break


            # -------------------------------
            # MANUAL BUILDER (ONCE)
            # -------------------------------
            scheduler = FinalScheduleBuilder(persona=persona)
            manual_plan = scheduler.build_plan_from_combined(combined)

            # -------------------------------
            # SAVE OUTPUTS
            # -------------------------------
            if llm_raw is not None:
                with open(run_dir / "llm_tripcraft_response_rerun.json", "w") as f:
                    json.dump(make_json_safe(llm_raw), f, indent=2)

            if manual_plan is not None:
                with open(run_dir / "tripcraft_response_rerun.json", "w") as f:
                    json.dump(make_json_safe(manual_plan), f, indent=2)

            print("[OK] Rerun completed")

        except Exception as e:
            print(f"[ERR] Failed rerun for trip {run_id}: {e}")
            with open(run_dir / "errors_rerun.json", "w") as f:
                json.dump({"error": str(e)}, f, indent=2)

    print("\n[ALL DONE] FINAL reruns finished")


if __name__ == "__main__":
    main()
