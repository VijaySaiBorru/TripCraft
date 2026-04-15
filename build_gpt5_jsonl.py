import pandas as pd
import json

# -------------------------------------------------
# Paths
# -------------------------------------------------
tsv_path = "/scratch/sg/Vijay/TripCraft/output_agentic_final/agentic/gpt5/7day/UHRS_Task_v7_tripcraft_7d_noreview_inputs.tsv"
jsonl_input_path = "/scratch/sg/Vijay/TripCraft/tripcraft_golden_7day.jsonl"
jsonl_output_path = "/scratch/sg/Vijay/TripCraft/gpt5_7day_llm_final2.jsonl"

# -------------------------------------------------
# 1️⃣ Load TSV
# -------------------------------------------------
df = pd.read_csv(tsv_path, sep="\t")

# Build 1-based idx mapping
idx_to_schedule = {}

for i, row in df.iterrows():
    one_based_idx = i + 1  # JSONL is 1-based

    if pd.notna(row["final_schedule_cleaned"]):
        idx_to_schedule[one_based_idx] = json.loads(row["final_schedule_cleaned"])
    else:
        idx_to_schedule[one_based_idx] = None

# -------------------------------------------------
# 2️⃣ Read original JSONL and modify
# -------------------------------------------------
with open(jsonl_input_path, "r") as infile, \
     open(jsonl_output_path, "w") as outfile:

    for line in infile:
        data = json.loads(line)

        json_idx = data.get("idx")

        # Replace plan if available
        # ❌ Skip if no generated plan
        if json_idx not in idx_to_schedule or idx_to_schedule[json_idx] is None:
            continue

        # ✅ Only keep valid generated plans
        data["plan"] = idx_to_schedule[json_idx]

        # ✅ Add model_name
        data["model_name"] = "gpt5"

        # Write updated object
        outfile.write(json.dumps(data) + "\n")

print("✅ Created new file: gpt5_3day_final.jsonl with model_name added.")

# Delivery Rate: 100.0%
# Commonsense Constraint Micro Pass Rate: 98.98255813953489%
# Commonsense Constraint Macro Pass Rate: 90.69767441860465%
# Hard Constraint Micro Pass Rate: 88.42530282637954%
# Hard Constraint Macro Pass Rate: 70.93023255813954%
# Final Pass Rate: 70.63953488372093%
# ------------------
# {'Commonsense Constraint': {'easy': {3: {'Reasonable City Route': {'true': 90, 'false': 1, 'total': 91}, 'Diverse Restaurants': {'true': 91, 'false': 0, 'total': 91}, 'Diverse Attractions': {'true': 91, 'false': 0, 'total': 91}, 'Non-conf. Transportation': {'true': 90, 'false': 1, 'total': 91}, 'No Reapeated Events': {'true': 91, 'false': 0, 'total': 91}, 'Sufficient Time between meals': {'true': 91, 'false': 0, 'total': 91}, 'PoI sequence starts and ends with accommodation': {'true': 90, 'false': 1, 'total': 91}, 'Within Sandbox': {'true': 87, 'false': 4, 'total': 91}, 'Within Current City': {'true': 91, 'false': 0, 'total': 91}, 'Complete Information': {'true': 89, 'false': 2, 'total': 91}}}, 'medium': {3: {'Reasonable City Route': {'true': 124, 'false': 0, 'total': 124}, 'Diverse Restaurants': {'true': 124, 'false': 0, 'total': 124}, 'Diverse Attractions': {'true': 124, 'false': 0, 'total': 124}, 'Non-conf. Transportation': {'true': 124, 'false': 0, 'total': 124}, 'No Reapeated Events': {'true': 124, 'false': 0, 'total': 124}, 'Sufficient Time between meals': {'true': 124, 'false': 0, 'total': 124}, 'PoI sequence starts and ends with accommodation': {'true': 123, 'false': 1, 'total': 124}, 'Within Sandbox': {'true': 113, 'false': 11, 'total': 124}, 'Within Current City': {'true': 124, 'false': 0, 'total': 124}, 'Complete Information': {'true': 118, 'false': 6, 'total': 124}}}, 'hard': {3: {'Reasonable City Route': {'true': 129, 'false': 0, 'total': 129}, 'Diverse Restaurants': {'true': 129, 'false': 0, 'total': 129}, 'Diverse Attractions': {'true': 129, 'false': 0, 'total': 129}, 'Non-conf. Transportation': {'true': 129, 'false': 0, 'total': 129}, 'No Reapeated Events': {'true': 129, 'false': 0, 'total': 129}, 'Sufficient Time between meals': {'true': 129, 'false': 0, 'total': 129}, 'PoI sequence starts and ends with accommodation': {'true': 129, 'false': 0, 'total': 129}, 'Within Sandbox': {'true': 121, 'false': 8, 'total': 129}, 'Within Current City': {'true': 129, 'false': 0, 'total': 129}, 'Complete Information': {'true': 129, 'false': 0, 'total': 129}}}}, 'Hard Constraint': {'easy': {3: {'Budget': {'true': 84, 'false': 1, 'total': 85}}}, 'medium': {3: {'Room Rule': {'true': 17, 'false': 5, 'total': 22}, 'Budget': {'true': 105, 'false': 2, 'total': 107}, 'Cuisine': {'true': 13, 'false': 8, 'total': 21}, 'Room Type': {'true': 39, 'false': 0, 'total': 39}, 'Attraction Type': {'true': 18, 'false': 8, 'total': 26}, 'Event Type': {'true': 3, 'false': 1, 'total': 4}, 'Transportation': {'true': 4, 'false': 0, 'total': 4}}}, 'hard': {3: {'Room Rule': {'true': 63, 'false': 17, 'total': 80}, 'Room Type': {'true': 68, 'false': 0, 'total': 68}, 'Attraction Type': {'true': 40, 'false': 16, 'total': 56}, 'Budget': {'true': 113, 'false': 8, 'total': 121}, 'Cuisine': {'true': 40, 'false': 18, 'total': 58}, 'Transportation': {'true': 43, 'false': 0, 'total': 43}, 'Event Type': {'true': 7, 'false': 2, 'total': 9}}}}}
# ------------------
# (tripcraftvijay) sg@nikola-tesla-PowerEdge-R7625:/scratch/sg/Vijay/TripCraft/evaluation$ 

# ========== QUALITATIVE EVALUATION SUMMARY ==========
# Annotated samples        : 344
# Generated samples        : 344
# Samples evaluated        : 344
# --------------------------------------------------
# Avg Meal Temporal Score              : 0.8091
# Avg Attraction Temporal (Normalized) : 0.753824
# Avg Attraction Temporal (Unnormalized): 0.258014
# Avg Spatial Score                    : 0.7623
# Avg Persona Alignment                 : 0.5119
# Avg Ordering Score                    : 0.8324
# ==================================================