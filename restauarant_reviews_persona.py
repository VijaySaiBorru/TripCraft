import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from itertools import product
from tqdm import tqdm

# =========================================================
# PATHS
# =========================================================

reviews_path = "/home/suprit/temp/clean_restaurant_reviews.csv"
summary_path = "/home/suprit/temp/restaurant_review_summary.csv"

# =========================================================
# LOAD DATA
# =========================================================

reviews_df = pd.read_csv(reviews_path)
summary_df = pd.read_csv(summary_path)

reviews_df = reviews_df[reviews_df["Comment"].notna()]

print("Reviews:", len(reviews_df))
print("Summary rows:", len(summary_df))

# =========================================================
# EMBEDDING MODEL
# =========================================================

embed_model = SentenceTransformer("all-mpnet-base-v2")

# =========================================================
# PERSONA CATEGORIES
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
"economical dining",
"luxury dining"
]

traveler_types = [
"adventure traveler",
"laidback traveler"
]

# =========================================================
# GENERATE 64 PERSONAS
# =========================================================

persona_strings = []

for loc, purpose, spend, traveler in product(
    location_types,
    travel_purposes,
    spending_types,
    traveler_types
):

    persona_strings.append(
        f"{traveler} interested in {purpose}, prefers {spend} in {loc}."
    )

print("Total Personas:", len(persona_strings))

# =========================================================
# PROCESS EACH RESTAURANT
# =========================================================

results = []

for restaurant_index in tqdm(summary_df["restaurant_index"]):

    df_rest = reviews_df[reviews_df["restaurant_index"] == restaurant_index]

    if "Title" in df_rest.columns:
        comments = (
            df_rest["Title"].fillna("").astype(str) + " " +
            df_rest["Comment"].fillna("").astype(str)
        ).tolist()
    else:
        comments = df_rest["Comment"].astype(str).tolist()

    review_text = " ".join(comments)

    review_embedding = embed_model.encode([review_text])

    # get restaurant quality from summary
    row = summary_df[summary_df["restaurant_index"] == restaurant_index].iloc[0]
    final_score = row["restaurant_quality"]

    persona_scores = {}

    for i, persona in enumerate(persona_strings):

        persona_embedding = embed_model.encode([persona])

        similarity = cosine_similarity(
            persona_embedding,
            review_embedding
        )[0][0]

        persona_alignment = max(0, min(1, (similarity + 1) / 2))

        persona_utility = final_score * (0.5 + 0.5 * persona_alignment)

        persona_scores[f"persona_{i+1}_alignment"] = round(persona_alignment,4)
        persona_scores[f"persona_{i+1}_utility"] = round(persona_utility,4)

    persona_scores["restaurant_index"] = restaurant_index

    results.append(persona_scores)

# =========================================================
# CREATE PERSONA DATAFRAME
# =========================================================

persona_df = pd.DataFrame(results)

# =========================================================
# MERGE WITH SUMMARY
# =========================================================

final_df = summary_df.merge(
    persona_df,
    on="restaurant_index",
    how="left"
)

# =========================================================
# SAVE FINAL FILE
# =========================================================

output_path = "/home/suprit/temp/restaurant_review_summary_with_persona.csv"

final_df.to_csv(output_path, index=False)

print("\nSaved:", output_path)