import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from itertools import product
from tqdm import tqdm

# =========================================================
# PATH
# =========================================================

file_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/review_pro_cons/accomodation_review_pro_cons.csv"
output_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/review_pro_cons/accommodation_review_pro_cons_persona_alignment.csv"

df = pd.read_csv(file_path)

# =========================================================
# MODEL
# =========================================================

model = SentenceTransformer("all-mpnet-base-v2")

# =========================================================
# PERSONAS
# =========================================================

location_types = [
    "beach locations",
    "city locations",
    "forest and wildlife locations",
    "mountain locations"
]

travel_purposes = [
    "adventure travel",
    "cultural exploration",
    "nature exploration",
    "relaxation travel"
]

spending_types = [
    "budget stay",
    "luxury stay"
]

traveler_types = [
    "adventure traveler",
    "laidback traveler"
]

persona_strings = [
    f"{traveler} interested in {purpose}, prefers {spend} in {loc}"
    for loc, purpose, spend, traveler in product(
        location_types,
        travel_purposes,
        spending_types,
        traveler_types
    )
]

print("Total personas:", len(persona_strings))

# =========================================================
# PRECOMPUTE PERSONA EMBEDDINGS
# =========================================================

persona_embeddings = model.encode(persona_strings)

# =========================================================
# HELPER FUNCTION
# =========================================================

def parse_text(text):
    if pd.isna(text):
        return []
    return [x.strip().lower() for x in text.split("|") if x.strip()]

# =========================================================
# MAIN PROCESS
# =========================================================

results = []

for idx, row in tqdm(df.iterrows(), total=len(df)):

    pros = parse_text(row.get("Pros", ""))
    cons = parse_text(row.get("Cons", ""))

    # Precompute embeddings for this row
    pros_emb = model.encode(pros) if pros else None
    cons_emb = model.encode(cons) if cons else None

    persona_scores = {}

    for i, persona_emb in enumerate(persona_embeddings):

        # ==============================
        # EDGE CASE: No pros & no cons
        # ==============================
        if not pros and not cons:
            sim_pros = None
            sim_cons = None

        else:
            # ===== Pros alignment =====
            if pros_emb is not None:
                sim_pros = cosine_similarity([persona_emb], pros_emb).max()
                sim_pros = (sim_pros + 1) / 2
            else:
                sim_pros = 0

            # ===== Cons alignment =====
            if cons_emb is not None:
                sim_cons = cosine_similarity([persona_emb], cons_emb).max()
                sim_cons = (sim_cons + 1) / 2
            else:
                sim_cons = 0

        # Store
        persona_scores[f"persona_{i+1}_pros_alignment"] = (
            round(sim_pros, 4) if sim_pros is not None else None
        )
        persona_scores[f"persona_{i+1}_cons_alignment"] = (
            round(sim_cons, 4) if sim_cons is not None else None
        )

    results.append(persona_scores)

# =========================================================
# CREATE DATAFRAME
# =========================================================

persona_df = pd.DataFrame(results)

# =========================================================
# MERGE WITH ORIGINAL DATA
# =========================================================

final_df = pd.concat([df, persona_df], axis=1)

# =========================================================
# SAVE OUTPUT
# =========================================================

final_df.to_csv(output_path, index=False)

print("\nSaved:", output_path)