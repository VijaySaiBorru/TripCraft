"""
=============================================================================
CASE STUDY FINDER
=============================================================================

This script:
1. Loads WITH-REVIEW and WITHOUT-REVIEW itineraries
2. Computes RGPA scores
3. Finds strongest improvements due to review integration
4. Prints qualitative comparisons
5. Prints actual Pros/Cons evidence for changed entities

Perfect for thesis qualitative analysis + appendix.

=============================================================================
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
import torch

from transformers import pipeline
from tqdm import tqdm


# ============================================================================
# LOAD REVIEW DATABASE
# ============================================================================

def load_review_database(db_dir):

    reviews_db = {}

    files = [
        os.path.join(
            db_dir,
            "review_pro_cons",
            "accomodation_review_pro_cons.csv"
        ),

        os.path.join(
            db_dir,
            "review_pro_cons",
            "restaurant_review_pro_cons_clean.csv"
        ),

        os.path.join(
            db_dir,
            "review_pro_cons",
            "attraction_review_pro_cons_fixed.csv"
        )
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

            reviews_db[(city, name)] = {
                "pros": pros.replace("|", ". "),
                "cons": cons.replace("|", ". ")
            }

    return reviews_db


# ============================================================================
# EXTRACT ENTITIES
# ============================================================================

def extract_entities(plan):

    entities = []

    for day in plan.get("plan", []):

        # ----------------------------------------------------
        # SINGLE ENTITIES
        # ----------------------------------------------------

        for key in [
            "accommodation",
            "breakfast",
            "lunch",
            "dinner"
        ]:

            val = day.get(key, "")

            if val and val != "-" and "," in val:

                name, city = val.rsplit(",", 1)

                entities.append(
                    (
                        city.strip().lower(),
                        name.strip().lower()
                    )
                )

        # ----------------------------------------------------
        # MULTIPLE ATTRACTIONS
        # ----------------------------------------------------

        attractions = day.get("attraction", "")

        if attractions and attractions != "-":

            for attr in attractions.split(";"):

                attr = attr.strip()

                if "," in attr:

                    name, city = attr.rsplit(",", 1)

                    entities.append(
                        (
                            city.strip().lower(),
                            name.strip().lower()
                        )
                    )

    return entities


# ============================================================================
# COMPUTE RGPA
# ============================================================================

def compute_rgpa(
    travel_plan,
    classifier,
    reviews_db,
    lambda_penalty=0.5
):

    persona = travel_plan.get("JSON", {}).get("persona", "")

    if not persona:
        return 0.0

    scores = []

    entities = extract_entities(travel_plan)

    for city, name in entities:

        city = city.replace(".", "").replace(";", "").strip()
        name = name.replace(".", "").replace(";", "").strip()

        if (city, name) not in reviews_db:
            continue

        review = reviews_db[(city, name)]

        pros = review["pros"]
        cons = review["cons"]

        # ----------------------------------------------------
        # PROS ENTAILMENT
        # ----------------------------------------------------

        if pros:

            res_pros = classifier(
                pros,
                [persona],
                hypothesis_template=
                "These features are highly suitable and perfect for: {}."
            )

            sim_pros = res_pros["scores"][0]

        else:
            sim_pros = 0.0

        # ----------------------------------------------------
        # CONS ENTAILMENT
        # ----------------------------------------------------

        if cons:

            res_cons = classifier(
                cons,
                [persona],
                hypothesis_template=
                "These issues are a dealbreaker and terrible for: {}."
            )

            sim_cons = res_cons["scores"][0]

        else:
            sim_cons = 0.0

        score = sim_pros - (lambda_penalty * sim_cons)

        score = max(0.0, min(1.0, score))

        scores.append(score)

    if not scores:
        return 0.0

    return np.mean(scores)


# ============================================================================
# PRINT REVIEW EVIDENCE
# ============================================================================

def print_entity_reviews(entity_list, reviews_db, title):

    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)

    seen = set()

    for city, name in entity_list:

        if (city, name) in seen:
            continue

        seen.add((city, name))

        if (city, name) not in reviews_db:
            continue

        review = reviews_db[(city, name)]

        pros = review["pros"].strip()
        cons = review["cons"].strip()

        print(f"\nENTITY: {name.title()} ({city.title()})")

        if pros:
            print("\nPROS:")
            print(pros)

        if cons:
            print("\nCONS:")
            print(cons)

        print("\n" + "-" * 100)


# ============================================================================
# PRETTY PRINT CASE STUDY
# ============================================================================

def print_case_study(
    idx,
    with_plan,
    without_plan,
    score_with,
    score_without,
    reviews_db
):

    print("\n" + "=" * 120)

    print(f"CASE STUDY #{idx}")

    print("=" * 120)

    persona = with_plan.get("JSON", {}).get("persona", "")

    print(f"\n👤 PERSONA:\n{persona}")

    # ========================================================
    # WITHOUT REVIEW
    # ========================================================

    print("\n" + "-" * 120)
    print("WITHOUT REVIEW INTEGRATION")
    print("-" * 120)

    print(json.dumps(without_plan["plan"], indent=2))

    print(f"\nRGPA Score: {score_without:.4f}")

    # ========================================================
    # WITH REVIEW
    # ========================================================

    print("\n" + "-" * 120)
    print("WITH REVIEW INTEGRATION")
    print("-" * 120)

    print(json.dumps(with_plan["plan"], indent=2))

    print(f"\nRGPA Score: {score_with:.4f}")

    # ========================================================
    # ENTITY DIFFERENCES
    # ========================================================

    with_entities = set(extract_entities(with_plan))
    without_entities = set(extract_entities(without_plan))

    removed_entities = without_entities - with_entities
    added_entities = with_entities - without_entities

    # ========================================================
    # REMOVED ENTITIES
    # ========================================================

    print_entity_reviews(
        removed_entities,
        reviews_db,
        "REMOVED ENTITIES (WITHOUT REVIEW)"
    )

    # ========================================================
    # ADDED ENTITIES
    # ========================================================

    print_entity_reviews(
        added_entities,
        reviews_db,
        "ADDED ENTITIES (WITH REVIEW)"
    )

    # ========================================================
    # FINAL IMPROVEMENT
    # ========================================================

    print("\n" + "-" * 120)

    improvement = score_with - score_without

    print(f"RGPA Improvement: +{improvement:.4f}")

    print("=" * 120 + "\n")


# ============================================================================
# MAIN
# ============================================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--with_review",
        type=str,
        required=True
    )

    parser.add_argument(
        "--without_review",
        type=str,
        required=True
    )

    parser.add_argument(
        "--db_dir",
        type=str,
        required=True
    )

    parser.add_argument(
        "--top_k",
        type=int,
        default=5
    )

    args = parser.parse_args()

    # ========================================================
    # LOAD MODEL
    # ========================================================

    print("[*] Loading NLI model...")

    device = 0 if torch.cuda.is_available() else -1

    classifier = pipeline(
        "zero-shot-classification",
        model="facebook/bart-large-mnli",
        framework="pt",
        device=device
    )

    # ========================================================
    # LOAD REVIEW DATABASE
    # ========================================================

    print("[*] Loading review database...")

    reviews_db = load_review_database(args.db_dir)

    print(f"[*] Loaded {len(reviews_db)} review entries")

    # ========================================================
    # LOAD FILES
    # ========================================================

    with open(args.with_review, "r", encoding="utf-8") as f:
        with_review_plans = [
            json.loads(x)
            for x in f
        ]

    with open(args.without_review, "r", encoding="utf-8") as f:
        without_review_plans = [
            json.loads(x)
            for x in f
        ]

    total = min(
        len(with_review_plans),
        len(without_review_plans)
    )

    print(f"[*] Comparing {total} paired itineraries...")

    improvements = []

    # ========================================================
    # COMPUTE DELTAS
    # ========================================================

    for i in tqdm(range(total), desc="Processing Plans"):

        with_plan = with_review_plans[i]
        without_plan = without_review_plans[i]

        score_with = compute_rgpa(
            with_plan,
            classifier,
            reviews_db
        )

        score_without = compute_rgpa(
            without_plan,
            classifier,
            reviews_db
        )

        delta = score_with - score_without

        improvements.append((
            delta,
            score_with,
            score_without,
            with_plan,
            without_plan
        ))

    # ========================================================
    # SORT BEST IMPROVEMENTS
    # ========================================================

    improvements.sort(
        key=lambda x: x[0],
        reverse=True
    )

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print("\n" + "#" * 120)
    print("TOP REVIEW-INTEGRATION CASE STUDIES")
    print("#" * 120)

    for idx, item in enumerate(
        improvements[:args.top_k],
        start=1
    ):

        delta, score_with, score_without, \
        with_plan, without_plan = item

        print_case_study(
            idx,
            with_plan,
            without_plan,
            score_with,
            score_without,
            reviews_db
        )


# ============================================================================
# ENTRY
# ============================================================================

if __name__ == "__main__":
    main()