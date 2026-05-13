"""
=============================================================================
RGPA Evaluator - NLI / SEMANTIC ENTAILMENT MODE
=============================================================================
This version:
1. Computes RGPA using NLI entailment
2. Separately tracks Pros/Cons entailment distributions
3. Reports statistical ranges and likelihood distributions
=============================================================================
"""

import os
import json
import argparse
import pandas as pd
import numpy as np
import torch
from transformers import pipeline
from tqdm import tqdm


# ============================================================
# LOAD REVIEW DATABASE
# ============================================================

def load_review_database(db_dir):

    reviews_db = {}

    files = [
        os.path.join(db_dir, "review_pro_cons", "accomodation_review_pro_cons.csv"),
        os.path.join(db_dir, "review_pro_cons", "restaurant_review_pro_cons_clean.csv"),
        os.path.join(db_dir, "review_pro_cons", "attraction_review_pro_cons_fixed.csv")
    ]

    for file_path in files:

        if not os.path.exists(file_path):
            continue

        df = pd.read_csv(file_path)

        for _, row in df.iterrows():

            city = str(
                row.get("City", row.get("city", ""))
            ).strip().lower()

            name = str(
                row.get("name", row.get("Name", ""))
            ).strip().lower()

            pros = str(row.get("pros", row.get("Pros", "")))
            cons = str(row.get("cons", row.get("Cons", "")))

            if pd.isna(pros) or pros.lower() == "nan":
                pros = ""

            if pd.isna(cons) or cons.lower() == "nan":
                cons = ""

            pros_text = pros.replace("|", ". ").strip()
            cons_text = cons.replace("|", ". ").strip()

            reviews_db[(city, name)] = {
                "pros": pros_text,
                "cons": cons_text
            }

    return reviews_db


# ============================================================
# MAIN RGPA EVALUATION
# ============================================================

def evaluate_itinerary_rgpa(
    travel_plan,
    classifier,
    reviews_db,
    lambda_penalty,
    pros_all_scores,
    cons_all_scores,
    is_debug=False
):

    persona_text = travel_plan.get("JSON", {}).get("persona", "")

    if not persona_text:
        return -1

    entity_scores = []

    if is_debug:
        print("\n" + "=" * 70)
        print("🔍 DEEP DIVE: FIRST ITINERARY")
        print("=" * 70)
        print(f"👤 PERSONA:\n{persona_text}\n")

    # ========================================================
    # ITERATE DAYS
    # ========================================================

    for day in travel_plan.get("plan", []):

        places = []

        # ----------------------------------------------------
        # Accommodation + Meals
        # ----------------------------------------------------

        for key in ["accommodation", "breakfast", "lunch", "dinner"]:

            val = day.get(key, "")

            if val and val != "-" and "," in val:

                name, city = val.rsplit(",", 1)

                places.append((
                    city.strip().lower(),
                    name.strip().lower()
                ))

        # ----------------------------------------------------
        # Attractions
        # ----------------------------------------------------

        attractions_str = day.get("attraction", "")

        if attractions_str and attractions_str != "-":

            for attr in attractions_str.split(";"):

                if "," in attr:

                    name, city = attr.rsplit(",", 1)

                    places.append((
                        city.strip().lower(),
                        name.strip().lower()
                    ))

        # ====================================================
        # ENTITY SCORING
        # ====================================================

        for city, name in places:

            clean_city = city.replace(";", "").replace(".", "").strip()
            clean_name = name.replace(";", "").replace(".", "").strip()

            if (clean_city, clean_name) not in reviews_db:
                continue

            review_data = reviews_db[(clean_city, clean_name)]

            pros_text = review_data["pros"]
            cons_text = review_data["cons"]

            if not pros_text and not cons_text:
                continue

            # =================================================
            # PROS ENTAILMENT
            # =================================================

            if pros_text:

                res_pros = classifier(
                    pros_text,
                    [persona_text],
                    hypothesis_template=(
                        "These features are highly suitable "
                        "and perfect for: {}."
                    )
                )

                sim_pros = res_pros['scores'][0]

            else:
                sim_pros = 0.0

            # =================================================
            # CONS ENTAILMENT
            # =================================================

            if cons_text:

                res_cons = classifier(
                    cons_text,
                    [persona_text],
                    hypothesis_template=(
                        "These issues are a dealbreaker "
                        "and terrible for: {}."
                    )
                )

                sim_cons = res_cons['scores'][0]

            else:
                sim_cons = 0.0

            # =================================================
            # STORE DISTRIBUTIONS
            # =================================================

            pros_all_scores.append(sim_pros)
            cons_all_scores.append(sim_cons)

            # =================================================
            # FINAL RGPA SCORE
            # =================================================

            score = sim_pros - (lambda_penalty * sim_cons)

            bounded_score = max(0.0, min(1.0, score))

            entity_scores.append(bounded_score)

            # =================================================
            # DEBUG
            # =================================================

            if is_debug:

                print(f"📍 ENTITY: {clean_name.title()} ({clean_city.title()})")

                print(f"   [+] Pros Entailment : {sim_pros:.4f}")
                print(f"   [-] Cons Entailment : {sim_cons:.4f}")

                print(
                    f"   🧮 Final Score      : "
                    f"{sim_pros:.4f} - "
                    f"({lambda_penalty} × {sim_cons:.4f}) "
                    f"= {bounded_score:.4f}\n"
                )

    # ========================================================
    # FINAL ITINERARY SCORE
    # ========================================================

    if not entity_scores:

        if is_debug:
            print("❌ No valid entities found.")

        return 0.0

    final_score = np.mean(entity_scores)

    if is_debug:

        print("=" * 70)
        print(f"🏆 FINAL ITINERARY RGPA = {final_score:.4f}")
        print("=" * 70 + "\n")

    return final_score


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--gen_file", type=str, required=True)
    parser.add_argument("--db_dir", type=str, required=True)

    parser.add_argument(
        "--lambda_penalty",
        type=float,
        default=0.5
    )

    args = parser.parse_args()

    # ========================================================
    # LOAD NLI MODEL
    # ========================================================

    print("[*] Loading NLI classifier...")

    device = 0 if torch.cuda.is_available() else -1

    classifier = pipeline(
        "zero-shot-classification",
        model="facebook/bart-large-mnli",
        framework="pt",
        device=device
    )

    print(f"Using device: {'cuda' if device == 0 else 'cpu'}")

    # ========================================================
    # LOAD REVIEW DATABASE
    # ========================================================

    reviews_db = load_review_database(args.db_dir)

    # ========================================================
    # STORAGE
    # ========================================================

    rgpa_scores = []

    pros_all_scores = []
    cons_all_scores = []

    total_evaluated = 0

    # ========================================================
    # EVALUATE
    # ========================================================

    print("\n[*] Evaluating itineraries...")

    with open(args.gen_file, 'r', encoding='utf-8') as f:

        for line in tqdm(f, desc="Processing Plans"):

            try:
                travel_plan = json.loads(line)

            except json.JSONDecodeError:
                continue

            if (
                not travel_plan.get("plan")
                or len(travel_plan["plan"]) == 0
            ):
                continue

            is_debug = (total_evaluated == 0)

            score = evaluate_itinerary_rgpa(
                travel_plan,
                classifier,
                reviews_db,
                args.lambda_penalty,
                pros_all_scores,
                cons_all_scores,
                is_debug
            )

            if score != -1:

                rgpa_scores.append(score)

                total_evaluated += 1

    # ========================================================
    # FINAL RGPA SUMMARY
    # ========================================================

    print("\n========== EXPERIENTIAL EVALUATION SUMMARY ==========")

    print(f"Samples Evaluated : {total_evaluated}")

    if total_evaluated > 0:

        print(
            f"Avg RGPA Score    : "
            f"{np.mean(rgpa_scores):.4f}"
        )

    print("====================================================")

    # ========================================================
    # PROS DISTRIBUTION
    # ========================================================

    pros_arr = np.array(pros_all_scores)

    print("\n========== PROS ENTAILMENT DISTRIBUTION ==========")

    print(f"Count   : {len(pros_arr)}")
    print(f"Mean    : {np.mean(pros_arr):.4f}")
    print(f"Std     : {np.std(pros_arr):.4f}")

    print(f"Min     : {np.min(pros_arr):.4f}")
    print(f"25%     : {np.percentile(pros_arr,25):.4f}")

    print(f"Median  : {np.median(pros_arr):.4f}")

    print(f"75%     : {np.percentile(pros_arr,75):.4f}")
    print(f"Max     : {np.max(pros_arr):.4f}")

    # ========================================================
    # CONS DISTRIBUTION
    # ========================================================

    cons_arr = np.array(cons_all_scores)

    print("\n========== CONS ENTAILMENT DISTRIBUTION ==========")

    print(f"Count   : {len(cons_arr)}")
    print(f"Mean    : {np.mean(cons_arr):.4f}")
    print(f"Std     : {np.std(cons_arr):.4f}")

    print(f"Min     : {np.min(cons_arr):.4f}")
    print(f"25%     : {np.percentile(cons_arr,25):.4f}")

    print(f"Median  : {np.median(cons_arr):.4f}")

    print(f"75%     : {np.percentile(cons_arr,75):.4f}")
    print(f"Max     : {np.max(cons_arr):.4f}")

    print("==================================================")


# ============================================================
# ENTRY
# ============================================================

if __name__ == '__main__':
    main()