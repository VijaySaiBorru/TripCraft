# /scratch/sg/Vijay/TripCraft/evaluation/eval.py
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))

from commonsense_constraint import evaluation as commonsense_eval
from hard_constraint import evaluation as hard_eval

import json
from tqdm import tqdm
import argparse



def load_line_json_data(filename):
    data = []
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f.read().strip().split('\n'):
            unit = json.loads(line)
            data.append(unit)
    return data


def statistics(constraint_statistic):
    """
    Aggregate constraint results by (level, day, constraint),
    counting only applicable constraints.
    """
    result = {
        level: {day: {} for day in constraint_statistic[level]}
        for level in constraint_statistic
    }

    for level, days in constraint_statistic.items():
        for day, dicts in days.items():
            for dct in dicts:
                if not dct:
                    continue

                for key, value in dct.items():
                    # value is expected to be (bool | None, msg)
                    ok = value[0] if isinstance(value, tuple) else value

                    # NOT applicable
                    if ok is None:
                        continue

                    if key not in result[level][day]:
                        result[level][day][key] = {
                            "true": 0,
                            "false": 0,
                            "total": 0
                        }

                    result[level][day][key]["total"] += 1
                    if ok:
                        result[level][day][key]["true"] += 1
                    else:
                        result[level][day][key]["false"] += 1

    return result

def paper_term_mapping(commonsense_constraint_record, hard_constraint_record):
    mapping_dict = {
        'is_valid_information_in_current_city':'Within Current City',
        'is_valid_information_in_sandbox':'Within Sandbox',
        'is_reasonable_visiting_city':'Reasonable City Route',
        'is_valid_restaurants':'Diverse Restaurants',
        'is_valid_transportation':'Non-conf. Transportation',
        'is_valid_attractions':'Diverse Attractions',
        'is_valid_accommodation':'Minimum Nights Stay',
        'is_not_absent':'Complete Information',
        'valid_cost':'Budget',
        'is_valid_event':'No Reapeated Events',
        'is_valid_meal_gaps':'Sufficient Time between meals',
        'is_valid_poi_sequence':'PoI sequence starts and ends with accommodation',
        'valid_room_rule':'Room Rule',
        'valid_cuisine':'Cuisine',
        'valid_room_type':'Room Type',
        'valid_transportation':'Transportation',
        'valid_event_type':'Event Type',
        'valid_attraction_type':'Attraction Type'
    }

    remap_commonsense_constraint_record = {
        level:{day:{} for day in [3,5,7]} for level in ['easy','medium','hard']
    }
    remap_hard_constraint_record = {
        level:{day:{} for day in [3,5,7]} for level in ['easy','medium','hard']
    }

    for level in commonsense_constraint_record:
        for day in commonsense_constraint_record[level]:
            remap_commonsense_constraint_record[level][day] = {
                mapping_dict.get(key, key): val
                for key, val in commonsense_constraint_record[level][day].items()
            }
            remap_hard_constraint_record[level][day] = {
                mapping_dict.get(key, key): val
                for key, val in hard_constraint_record[level][day].items()
            }

    return remap_commonsense_constraint_record, remap_hard_constraint_record

def eval_score(set_type: str, file_path: str):

    tested_plans = load_line_json_data(file_path)
    query_data_list = [single_plan["JSON"] for single_plan in tested_plans]

    delivery_cnt = 0

    # micro-level counters
    commonsense_pass = 0
    commonsense_total = 0
    hard_pass = 0
    hard_total = 0

    # macro-level counters
    final_commonsense_cnt = 0
    final_hard_cnt = 0
    final_all_cnt = 0

    # detailed storage (unchanged)
    commonsenseConstraint_statistic = {l:{d:[] for d in [3,5,7]} for l in ['easy','medium','hard']}
    hardConstraint_statistic = {l:{d:[] for d in [3,5,7]} for l in ['easy','medium','hard']}

    for idx in range(len(query_data_list)):
        query_data = query_data_list[idx]
        tested_plan = tested_plans[idx]

        if isinstance(query_data, str):
            query_data = eval(query_data)
        if isinstance(tested_plan, str):
            tested_plan = eval(tested_plan)
        if isinstance(query_data["local_constraint"], str):
            query_data["local_constraint"] = eval(query_data["local_constraint"])

        # ---------- Delivery ----------
        if len(tested_plan["plan"]) <= 2:
            continue
        delivery_cnt += 1

        # ---------- Commonsense ----------
        commonsense_info = commonsense_eval(query_data, tested_plan["plan"])
        commonsenseConstraint_statistic[query_data["level"]][query_data["days"]].append(commonsense_info)

        plan_commonsense_pass = True
        for k, value in commonsense_info.items():
            # value is expected to be (bool | None, msg)
            ok = value[0] if isinstance(value, tuple) else value
            
            # applicability check (skip None)
            if ok is None:
                continue

            commonsense_total += 1
            if ok:
                commonsense_pass += 1
            else:
                plan_commonsense_pass = False

        if plan_commonsense_pass:
            final_commonsense_cnt += 1

        # ---------- Hard constraints gated ----------
        # Gating only on completeness, making sandbox check optional for hard constraints evaluation 
        # (though results might be inaccurate if names don't match)
        if not commonsense_info["is_not_absent"][0]:
            continue

        hard_info = hard_eval(query_data, tested_plan["plan"])
        hardConstraint_statistic[query_data["level"]][query_data["days"]].append(hard_info)

        plan_hard_pass = True

        for k, (ok, _) in hard_info.items():
            # applicability check
            if ok is None:
                continue

            hard_total += 1
            if ok:
                hard_pass += 1
            else:
                plan_hard_pass = False

        # no applicable hard constraints → vacuously true
        if hard_total == 0 or plan_hard_pass:
            final_hard_cnt += 1

        if plan_commonsense_pass and plan_hard_pass:
            final_all_cnt += 1

    # ---------- Metrics ----------
    result = {}

    dataset_size = {
        "3d": 344,
        "5d": 324,
        "7d": 332
    }[set_type]

    result["Delivery Rate"] = delivery_cnt / dataset_size
    result["Commonsense Constraint Micro Pass Rate"] = commonsense_pass / commonsense_total
    result["Commonsense Constraint Macro Pass Rate"] = final_commonsense_cnt / dataset_size

    result["Hard Constraint Micro Pass Rate"] = (
        1.0 if hard_total == 0 else hard_pass / hard_total
    )
    result["Hard Constraint Macro Pass Rate"] = final_hard_cnt / dataset_size
    result["Final Pass Rate"] = final_all_cnt / dataset_size

    # ---------- detailed tables (unchanged pipeline) ----------
    commonsense_processed = statistics(commonsenseConstraint_statistic)
    hard_processed = statistics(hardConstraint_statistic)

    remap_commonsense, remap_hard = paper_term_mapping(
        commonsense_processed, hard_processed
    )

    return result, {
        "Commonsense Constraint": remap_commonsense,
        "Hard Constraint": remap_hard
    }

def explain_plan(query_data, tested_plan):
    """
    Explain why a SINGLE plan failed.
    Returns a list of failed constraints with reasons.
    """

    explanations = []

    # ---------- Commonsense constraints ----------
    commonsense_info = commonsense_eval(query_data, tested_plan["plan"])

    for cname, (ok, msg) in commonsense_info.items():
        if ok is False:
            explanations.append({
                "constraint": cname,
                "reason": msg
            })

    # ---------- Hard constraints (only if gated) ----------
    if (
        commonsense_info["is_not_absent"][0] and
        commonsense_info["is_valid_information_in_sandbox"][0]
    ):
        hard_info = hard_eval(query_data, tested_plan["plan"])

        for cname, (ok, msg) in hard_info.items():
            if ok is False:
                explanations.append({
                    "constraint": cname,
                    "reason": msg
                })

    return explanations

def explain(idx, file_path="/scratch/sg/Vijay/TripCraft/gpt5_3day.jsonl"):
    """
    Single-line helper:
    explain(1) → explains the plan whose JSON field "idx" == 1
    phi4_5day_llm.jsonl
    """

    plans = load_line_json_data(file_path)

    # 🔍 find plan by internal idx
    matched = None
    for plan in plans:
        if plan.get("idx") == idx:
            matched = plan
            break

    if matched is None:
        print(f"❌ No plan present with idx = {idx}")
        return

    query = matched["JSON"]

    reasons = explain_plan(query, matched)

    if not reasons:
        print(f"✅ Plan with idx = {idx} has NO violations")
        return

    print(f"\n🔎 PLAN idx = {idx} FAILURES:")
    for r in reasons:
        print(f"❌ {r['constraint']} → {r['reason']}")

# def explain_batch(start_idx, end_idx, file_path="/scratch/sg/Vijay/TripCraft/tripcraft_golden_3day.jsonl"):
#     for idx in range(start_idx, end_idx + 1):
#         print("\n" + "=" * 60)
#         explain(idx, file_path)

def explain_batch(start_idx, end_idx, file_path="/scratch/sg/Vijay/TripCraft/gpt5_3day_v25_llm.jsonl"):
    plans = load_line_json_data(file_path)
    plan_map = {p.get("idx"): p for p in plans}

    for idx in range(start_idx, end_idx + 1):
        matched = plan_map.get(idx)
        if not matched:
            continue

        reasons = explain_plan(matched["JSON"], matched)

        if not reasons:
            continue  # ✅ skip valid plans

        print("\n" + "=" * 60)
        print(f"🔎 PLAN idx = {idx} FAILURES:")
        for r in reasons:
            print(f"❌ {r['constraint']} → {r['reason']}")

# def explain_batch(start_idx, end_idx,
#                   file_path="/scratch/sg/Vijay/TripCraft/gpt5_3day_v25_llm.jsonl"):

#     import pandas as pd
#     import json

#     TSV_PATH = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/3day/UHRS_Task_v25_tripcraft_3day.tsv"

#     # Load TSV
#     df = pd.read_csv(TSV_PATH, sep="\t")

#     # Load JSONL
#     plans = load_line_json_data(file_path)
#     plan_map = {p.get("idx"): p for p in plans}

#     for idx in range(start_idx, end_idx + 1):

#         row_index = idx - 1  # 1-based → 0-based

#         if row_index >= len(df):
#             continue

#         matched = plan_map.get(idx)

#         if not matched:
#             df.at[row_index, "remarks"] = "no violation"
#             continue

#         reasons = explain_plan(matched["JSON"], matched)

#         if not reasons:
#             df.at[row_index, "remarks"] = "no violation"
#         else:
#             combined = " | ".join(
#                 f"{r['constraint']} → {r['reason']}"
#                 for r in reasons
#             )
#             df.at[row_index, "remarks"] = combined

#     # Save back
#     df.to_csv(TSV_PATH, sep="\t", index=False)

#     print(f"✅ Updated remarks for rows {start_idx} to {end_idx}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--set_type", type=str, default="validation")
    parser.add_argument("--evaluation_file_path", type=str, default="./")
    args = parser.parse_args()

    scores, detailed_scores = eval_score(
        args.set_type,
        file_path=args.evaluation_file_path
    )

    # ---------- Print overall scores ----------
    for key in scores:
        print(f"{key}: {scores[key]*100}%")

    print("------------------")

    # ---------- FILTER detailed scores by set_type ----------
    target_day = int(args.set_type[0])  # "3d" -> 3, "5d" -> 5, "7d" -> 7

    filtered_details = {}

    for constraint_type, level_dict in detailed_scores.items():
        filtered_details[constraint_type] = {}
        for level, day_dict in level_dict.items():
            # keep only the relevant day bucket
            if target_day in day_dict and day_dict[target_day]:
                filtered_details[constraint_type][level] = {
                    target_day: day_dict[target_day]
                }
            else:
                filtered_details[constraint_type][level] = {}

    print(filtered_details)
    print("------------------")

