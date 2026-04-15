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
import re

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# =========================================================
# SETTINGS
# =========================================================

reviews_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_restaurant_reviews.csv"

persona_string = (
    "Laidback traveler interested in cultural exploration, "
    "prefers luxury dining experiences."
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

print("Unique Restaurants:", len(unique_names))

restaurant_name = unique_names[1000]

df_rest = df[df["Name"] == restaurant_name]

if "Title" in df_rest.columns:
    comments = (
        df_rest["Title"].astype(str) + " " +
        df_rest["Comment"].astype(str)
    ).tolist()
else:
    comments = df_rest["Comment"].astype(str).tolist()

comments = [c for c in comments if len(c.split()) > 3]

print("Restaurant:", restaurant_name)
print("Total reviews:", len(comments))
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

food_query = "delicious food, fresh ingredients, tasty dishes, high quality meal"
food_embedding = embed_model.encode([food_query])

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
stability = 1 / (1 + variance_sentiment)

extreme_neg_ratio = np.mean([1 if n > 0.8 else 0 for n in negative_probs])

# =========================================================
# KEYWORD SIGNALS
# =========================================================

food_keywords = [
"delicious","tasty","fresh","flavor","amazing","pizza","pasta","burger",
"steak","chicken","seafood","dessert","salad","sushi","ramen"
]

service_keywords = [
"service","staff","friendly","server","waiter","attentive",
"manager","host","helpful"
]

ambience_keywords = [
"atmosphere","ambience","decor","cozy","romantic","music",
"lighting","vibe","bar","view","ocean","beach","sunset",
"window","outdoor","patio","seaside","waterfront","terrace"
]

value_keywords = [
"value","worth","portion","price","reasonable","cheap",
"affordable","expensive","overpriced","pricey","fair",
"reasonable price","good value","worth it"
]

menu_keywords = [
"menu","options","variety","selection","choices","wine list"
]

wait_keywords = [
"wait","waiting","slow","delay","long time","queue",
"waited","waiting time","slow service","long wait"
]

hygiene_keywords = [
"dirty","unclean","smell","rotten","hair","undercooked","cold food","sick","food poisoning","raw","spoiled"
]

def contains_keyword(text, keywords):
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)

food_signal = 0
service_signal = 0
ambience_signal = 0
value_signal = 0
menu_variety_signal = 0
wait_risk = 0
hygiene_risk = 0

for c in comments:

    text = c.lower()

    if contains_keyword(text, food_keywords):
        food_signal += 1

    if contains_keyword(text, service_keywords):
        service_signal += 1

    if contains_keyword(text, ambience_keywords):
        ambience_signal += 1

    if contains_keyword(text, value_keywords):
        value_signal += 1

    if contains_keyword(text, menu_keywords):
        menu_variety_signal += 1

    if contains_keyword(text, wait_keywords):
        wait_risk += 1

    if contains_keyword(text, hygiene_keywords):
        hygiene_risk += 1

food_signal /= num_reviews
service_signal /= num_reviews
ambience_signal /= num_reviews
value_signal /= num_reviews
menu_variety_signal /= num_reviews
wait_risk /= num_reviews
hygiene_risk /= num_reviews

# =========================================================
# BAYESIAN SMOOTHING
# =========================================================

adjusted_quality = (
    (num_reviews / (num_reviews + bayesian_m)) * base_quality +
    (bayesian_m / (num_reviews + bayesian_m)) * global_mean
)

# =========================================================
# MISTRAL SUMMARY
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
Summarize these restaurant reviews.

Focus on:
- food quality
- service
- ambience
- price/value
- hygiene issues
- waiting time

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
# SEMANTIC FOOD SIGNAL
# =========================================================

review_embedding = embed_model.encode([summary])

food_similarity = cosine_similarity(review_embedding, food_embedding)[0][0]

food_semantic_score = max(0, min(1, (food_similarity + 1) / 2))

food_signal = 0.7 * food_signal + 0.3 * food_semantic_score

# =========================================================
# FINAL RESTAURANT SCORE
# =========================================================

domain_bonus = (
    0.40 * food_signal +
    0.20 * service_signal +
    0.15 * ambience_signal +
    0.15 * value_signal +
    0.10 * menu_variety_signal
)

risk_penalty = (
    0.9 * hygiene_risk +
    0.6 * wait_risk +
    0.8 * extreme_neg_ratio
)

core_score = adjusted_quality * stability

final_restaurant_score = (
    core_score +
    0.4 * domain_bonus -
    0.3 * risk_penalty
)

if num_reviews < min_review_threshold:
    final_restaurant_score *= 0.85

final_restaurant_score = max(0, min(1, final_restaurant_score))

# =========================================================
# PERSONA ALIGNMENT
# =========================================================

persona_embedding = embed_model.encode([persona_string])

similarity = cosine_similarity(persona_embedding, review_embedding)[0][0]

persona_alignment = max(0, min(1, (similarity + 1) / 2))

persona_utility = final_restaurant_score * (0.5 + 0.5 * persona_alignment)

# =========================================================
# OUTPUT
# =========================================================

print("\n===== FINAL RESTAURANT REVIEW SIGNAL =====\n")

print({
    "restaurant_quality": round(final_restaurant_score,4),
    "core_quality": round(core_score,4),
    "stability": round(stability,4),

    "food_signal": round(food_signal,4),
    "food_semantic_score": round(food_semantic_score,4),
    "service_signal": round(service_signal,4),
    "ambience_signal": round(ambience_signal,4),
    "value_signal": round(value_signal,4),
    "menu_variety_signal": round(menu_variety_signal,4),

    "wait_risk": round(wait_risk,4),
    "hygiene_risk": round(hygiene_risk,4),
    "extreme_neg_ratio": round(extreme_neg_ratio,4),

    "persona_alignment": round(persona_alignment,4),
    "persona_utility": round(persona_utility,4),

    "num_reviews": num_reviews
})

print("\n===== REVIEW SUMMARY =====\n")
print(summary)