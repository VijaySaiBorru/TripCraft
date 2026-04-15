import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from itertools import product

# =========================================================
# SETTINGS
# =========================================================

reviews_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_accomodation_review.csv"

# =========================================================
# LOAD DATA
# =========================================================

df = pd.read_csv(reviews_path)
df = df[df["Comment"].notna()]

unique_names = df["Name"].unique()
print("Unique Accommodations:", len(unique_names))

accom_name = unique_names[5]

df_accom = df[df["Name"] == accom_name]

comments = df_accom["Comment"].astype(str).tolist()

print("Accommodation:", accom_name)
print("Total reviews:", len(comments))

# =========================================================
# REVIEW TEXT
# =========================================================

review_corpus = " ".join(comments)

# =========================================================
# EMBEDDING MODEL
# =========================================================

embed_model = SentenceTransformer("all-mpnet-base-v2")

review_embedding = embed_model.encode([review_corpus])

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
"economical stays",
"luxury stays"
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

print("\nTotal Personas:", len(persona_strings))

# =========================================================
# PERSONA ALIGNMENT
# =========================================================

persona_scores = {}

for persona in persona_strings:

    persona_embedding = embed_model.encode([persona])

    similarity = cosine_similarity(
        persona_embedding,
        review_embedding
    )[0][0]

    persona_alignment = max(0, min(1, (similarity + 1) / 2))

    persona_scores[persona] = round(persona_alignment,4)

# =========================================================
# PRINT RESULTS
# =========================================================

print("\n===== PERSONA ALIGNMENT SCORES =====\n")

for p,v in persona_scores.items():
    print(p, ":", v)