import pandas as pd
import torch
import numpy as np
import transformers
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from transformers import AutoModelForCausalLM, pipeline
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm
from transformers import BitsAndBytesConfig
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
# =========================================================
# SETTINGS
# =========================================================

reviews_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_accomodation_review.csv"

persona_string = (
    "Laidback traveler interested in cultural exploration, "
    "prefers luxury stays in mountain locations."
)

batch_size = 16
bayesian_m = 20
global_mean = 0.7
min_review_threshold = 5

# =========================================================
# LOAD DATA
# =========================================================

df = pd.read_csv(reviews_path)
df = df[df["Comment"].notna()]

unique_names = df["Name"].unique()
print("Unique Accommodations:", len(unique_names))

accom_name = unique_names[2005]  # change index if needed upto 2367

df_accom = df[df["Name"] == accom_name]

comments = df_accom["Comment"].astype(str).tolist()

print("Accommodation:", accom_name)
print("Total reviews:", len(comments))
print("\n==============================\n")

print("Sample Reviews (first 20):\n")
for i, c in enumerate(comments[:20], 1):
    print(f"{i}. {c}\n")

# =========================================================
# DEVICE
# =========================================================

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

transformers.logging.set_verbosity_error()

# =========================================================
# SENTIMENT MODEL
# =========================================================

sentiment_model_name = "siebert/sentiment-roberta-large-english"

tokenizer = AutoTokenizer.from_pretrained(sentiment_model_name)
sentiment_model = AutoModelForSequenceClassification.from_pretrained(sentiment_model_name)

sentiment_model.to(device)
sentiment_model.eval()

# =========================================================
# EMBEDDING MODEL
# =========================================================

embed_model = SentenceTransformer("all-mpnet-base-v2")

comfort_query = "comfortable stay, cozy room, good sleep quality, relaxing accommodation"
comfort_embedding = embed_model.encode([comfort_query])

# =========================================================
# SENTIMENT INFERENCE
# =========================================================

sentiment_values = []
negative_probs = []

for i in tqdm(range(0, len(comments), batch_size)):

    batch = comments[i:i+batch_size]

    inputs = tokenizer(
        batch,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=512
    ).to(device)

    with torch.no_grad():
        outputs = sentiment_model(**inputs)
        probs = torch.softmax(outputs.logits, dim=1)

    for prob in probs:
        negative = prob[0].item()
        positive = prob[1].item()

        sentiment_values.append(positive - negative)
        negative_probs.append(negative)

num_reviews = len(sentiment_values)

if num_reviews == 0:
    print("No reviews found.")
    exit()

# =========================================================
# CORE SENTIMENT METRICS
# =========================================================

mean_sentiment = np.mean(sentiment_values)
variance_sentiment = np.var(sentiment_values)

base_quality = (mean_sentiment + 1) / 2
stability = max(0, min(1, 1 - variance_sentiment))

extreme_neg_ratio = np.mean([1 if n > 0.8 else 0 for n in negative_probs])

# =========================================================
# DOMAIN SIGNAL KEYWORDS
# =========================================================

comfort_keywords = [
"comfortable","bed","cozy","space","room","home","sleep","mattress","relax","relaxing","quiet","peaceful","comfy","spacious","warm","soft","blanket","pillow"
]

cleanliness_keywords = [
"clean","spotless","tidy","bathroom","kitchen","neat","fresh","well kept","well-kept","immaculate","sparkling"
]

location_keywords = [
"location","close","area","neighborhood","restaurants","walking","distance","downtown","beach","lake","view","central","nearby","steps"
]

host_keywords = [
"host","responsive","helpful","friendly","communication","welcoming","kind","accommodating","quick","supportive","recommendations"
]

amenities_keywords = [
"wifi","kitchen","parking","coffee","pool","hot tub","washer","dryer","bike","bikes","beach","fireplace","patio","gear","balcony","air conditioning","ac","heater","tv","netflix","workspace","desk","bbq","grill","garden","yard","terrace"
]

noise_keywords = [
"noisy","noise","loud","thin walls","traffic","party","construction","street noise"
]

safety_keywords = [
"unsafe","dangerous","scary","crime","sketchy","security","safe","secure"
]

# =========================================================
# SIGNAL EXTRACTION
# =========================================================
import re

def contains_keyword(text, keywords):
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)

comfort_signal = 0
cleanliness_signal = 0
location_signal = 0
host_signal = 0
amenities_signal = 0
noise_risk = 0
safety_risk = 0

for c in comments:

    text = c.lower()

    if contains_keyword(text, comfort_keywords):
        comfort_signal += 1

    if contains_keyword(text, cleanliness_keywords):
        cleanliness_signal += 1

    if contains_keyword(text, location_keywords):
        location_signal += 1

    if contains_keyword(text, host_keywords):
        host_signal += 1

    if contains_keyword(text, amenities_keywords):
        amenities_signal += 1

    if contains_keyword(text, noise_keywords):
        noise_risk += 1

    if contains_keyword(text, safety_keywords):
        safety_risk += 1

comfort_signal /= num_reviews
cleanliness_signal /= num_reviews
location_signal /= num_reviews
host_signal /= num_reviews
amenities_signal /= num_reviews
noise_risk /= num_reviews
safety_risk /= num_reviews

# =========================================================
# BAYESIAN SMOOTHING
# =========================================================

adjusted_quality = (
    (num_reviews / (num_reviews + bayesian_m)) * base_quality +
    (bayesian_m / (num_reviews + bayesian_m)) * global_mean
)







# =========================================================
# BETTER SUMMARIZER (MISTRAL 7B)
# =========================================================

print("\nLoading Mistral summarizer...\n")

model_name = "mistralai/Mistral-7B-Instruct-v0.2"

tokenizer_sum = AutoTokenizer.from_pretrained(model_name)

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16
)

model_sum = AutoModelForCausalLM.from_pretrained(
    model_name,
    quantization_config=bnb_config,
    device_map="auto"
)

summarizer = pipeline(
    "text-generation",
    model=model_sum,
    tokenizer=tokenizer_sum
)

review_text = " ".join(comments)

prompt = f"""
You are summarizing Airbnb reviews.

Summarize the following accommodation reviews.

Focus on:
- comfort
- cleanliness
- location
- host behavior
- amenities
- potential issues

Keep summary factual and concise.
Write a short factual summary.
Do not invent information.

Reviews:
{review_text}

Summary:
"""

output = summarizer(
    prompt,
    max_new_tokens=176,
    temperature=0.2,
    do_sample=False
)

generated = output[0]["generated_text"]

if "Summary:" in generated:
    summary = generated.split("Summary:")[-1].strip()
else:
    summary = generated.strip()



# =========================================================
# PERSONA ALIGNMENT
# =========================================================

review_corpus = summary  # limit size

persona_embedding = embed_model.encode([persona_string])
review_embedding = embed_model.encode([review_corpus])

comfort_similarity = cosine_similarity(review_embedding, comfort_embedding)[0][0]

comfort_semantic_score = max(0, min(1, (comfort_similarity + 1) / 2))
comfort_signal = 0.7 * comfort_signal + 0.3 * comfort_semantic_score


# =========================================================
# DOMAIN BONUS + RISK PENALTY
# =========================================================

domain_bonus = (
    0.25 * comfort_signal +
    0.25 * cleanliness_signal +
    0.15 * host_signal +
    0.15 * location_signal +
    0.10 * amenities_signal
)

risk_penalty = (
    0.7 * noise_risk +
    1.0 * safety_risk +
    0.8 * extreme_neg_ratio
)

core_score = adjusted_quality * stability

final_accommodation_score = (
    core_score
    + 0.3 * domain_bonus
    - 0.5 * risk_penalty
)

if num_reviews < min_review_threshold:
    final_accommodation_score *= 0.85

final_accommodation_score = max(0, min(1, final_accommodation_score))

similarity = cosine_similarity(persona_embedding, review_embedding)[0][0]

persona_alignment = max(0, min(1, (similarity + 1) / 2))
persona_utility = final_accommodation_score * (0.5 + 0.5 * persona_alignment)



# =========================================================
# OUTPUT
# =========================================================


print("\n===== FINAL ACCOMMODATION REVIEW SIGNAL =====\n")

print({
    "accommodation_quality": round(final_accommodation_score,4),
    "core_quality": round(core_score,4),
    "stability": round(stability,4),

    "comfort_signal": round(comfort_signal,4),
    "comfort_semantic_score": round(comfort_semantic_score,4),
    "cleanliness_signal": round(cleanliness_signal,4),
    "location_signal": round(location_signal,4),
    "host_signal": round(host_signal,4),
    "amenities_signal": round(amenities_signal,4),

    "noise_risk": round(noise_risk,4),
    "safety_risk": round(safety_risk,4),
    "extreme_neg_ratio": round(extreme_neg_ratio,4),

    "persona_alignment": round(persona_alignment,4),
    "persona_utility": round(persona_utility,4),

    "num_reviews": num_reviews
})

print("\n===== REVIEW SUMMARY =====\n")
print(summary)