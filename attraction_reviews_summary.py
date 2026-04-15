import pandas as pd
import torch
import numpy as np
import transformers
import re
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from transformers import AutoModelForCausalLM, pipeline
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm
from transformers import BitsAndBytesConfig
import os
from ftfy import fix_text

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# =========================================================
# SETTINGS
# =========================================================

reviews_path = "/home/suprit/temp/clean_attraction_reviews.csv"
output_path = "/home/suprit/temp/attraction_review_summary.csv"

batch_size = 16
bayesian_m = 20
global_mean = 0.6
min_review_threshold = 5

# =========================================================
# LOAD DATA
# =========================================================

df = pd.read_csv(reviews_path)
df = df[df["Comment"].notna()]

unique_names = df["Name"].unique()

print("Unique Attractions:", len(unique_names))

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

experience_query = "fun amazing enjoyable great experience worth visiting"
nature_query = "beautiful scenery nature hiking trails landscape views"

experience_embedding = embed_model.encode([experience_query])
nature_embedding = embed_model.encode([nature_query])

# =========================================================
# LOAD MISTRAL SUMMARIZER ONCE
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

# =========================================================
# KEYWORDS
# =========================================================

experience_keywords = [
"fun","amazing","enjoyed","worth","great","interesting","awesome","best","beautiful"
]

nature_keywords = [
"trail","hike","view","views","mountain","lake","river","park","scenery","nature","forest","beach"
]

culture_keywords = [
"museum","art","history","memorial","heritage","exhibit","exhibits","historic","gallery"
]

family_keywords = [
"kids","family","zoo","animals","play","rides","playground"
]

facility_keywords = [
"parking","visitor center","gift shop","staff","restroom","bathroom"
]

tour_keywords = [
"tour","guided tour","tour guide","audio tour"
]

shopping_keywords = [
"shopping","store","stores","outlet","mall",
"discount","sale","brand","retail"
]

crowd_keywords = [
"crowded","busy","long line","queue","packed","wait"
]

safety_keywords = [
"unsafe","dangerous","injury","accident","scary"
]

# =========================================================
# HELPER
# =========================================================

def contains_keyword(text, keywords):
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)

# =========================================================
# PROCESS ALL ATTRACTIONS
# =========================================================

results = []

for poi_name in tqdm(unique_names):

    df_poi = df[df["Name"] == poi_name]

    city = df_poi.iloc[0]["City"]
    state = df_poi.iloc[0]["State"]
    poi_index = df_poi.iloc[0]["attraction_index"]

    if "Title" in df_poi.columns:
        comments = (
            df_poi["Title"].fillna("") + " " +
            df_poi["Comment"].fillna("")
        ).astype(str).tolist()
    else:
        comments = df_poi["Comment"].astype(str).tolist()

    comments = [fix_text(c) for c in comments]

    num_reviews = len(comments)

    if num_reviews == 0:
        continue

    # =====================================================
    # SENTIMENT
    # =====================================================

    sentiment_values = []
    negative_probs = []

    for i in range(0, len(comments), batch_size):

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

            sentiment_values.append(positive-negative)
            negative_probs.append(negative)

    mean_sentiment = np.mean(sentiment_values)
    variance_sentiment = np.var(sentiment_values)

    base_quality = (mean_sentiment+1)/2
    stability = max(0,min(1,1-variance_sentiment))

    extreme_neg_ratio = np.mean([1 if n>0.8 else 0 for n in negative_probs])

    # =====================================================
    # KEYWORD SIGNALS
    # =====================================================

    experience_signal = 0
    nature_signal = 0
    culture_signal = 0
    family_signal = 0
    facility_signal = 0
    tour_signal = 0
    shopping_signal = 0
    crowd_risk = 0
    safety_risk = 0

    for c in comments:

        text = c.lower()

        if contains_keyword(text,experience_keywords):
            experience_signal +=1

        if contains_keyword(text,nature_keywords):
            nature_signal +=1

        if contains_keyword(text,culture_keywords):
            culture_signal +=1

        if contains_keyword(text,family_keywords):
            family_signal +=1

        if contains_keyword(text,facility_keywords):
            facility_signal +=1

        if contains_keyword(text,tour_keywords):
            tour_signal +=1

        if contains_keyword(text,shopping_keywords):
            shopping_signal +=1

        if contains_keyword(text,crowd_keywords):
            crowd_risk +=1

        if contains_keyword(text,safety_keywords):
            safety_risk +=1

    experience_signal /= num_reviews
    nature_signal /= num_reviews
    culture_signal /= num_reviews
    family_signal /= num_reviews
    facility_signal /= num_reviews
    tour_signal /= num_reviews
    shopping_signal /= num_reviews
    crowd_risk /= num_reviews
    safety_risk /= num_reviews

    # =====================================================
    # BAYESIAN SMOOTHING
    # =====================================================

    adjusted_quality = (
        (num_reviews/(num_reviews+bayesian_m))*base_quality +
        (bayesian_m/(num_reviews+bayesian_m))*global_mean
    )

    # =====================================================
    # REVIEW SUMMARY
    # =====================================================

    review_text = " ".join(comments[:30])

    prompt = f"""
You are summarizing visitor reviews for the attraction: {poi_name}.

Summarize the reviews below.

Focus on:
- overall visitor experience
- scenery or natural beauty
- cultural or educational value
- family friendliness
- crowd issues
- safety issues

Keep the summary factual and concise.
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

    # =====================================================
    # SEMANTIC SIGNALS
    # =====================================================

    review_embedding = embed_model.encode([summary])

    nature_similarity = cosine_similarity(review_embedding,nature_embedding)[0][0]
    experience_similarity = cosine_similarity(review_embedding,experience_embedding)[0][0]

    nature_semantic_score = max(0,min(1,(nature_similarity+1)/2))
    experience_semantic_score = max(0,min(1,(experience_similarity+1)/2))

    nature_signal = 0.7*nature_signal + 0.3*nature_semantic_score
    experience_signal = 0.7*experience_signal + 0.3*experience_semantic_score

    # =====================================================
    # FINAL SCORE
    # =====================================================

    domain_bonus = (
        0.26*experience_signal +
        0.20*nature_signal +
        0.16*culture_signal +
        0.12*family_signal +
        0.10*facility_signal +
        0.08*tour_signal +
        0.08*shopping_signal
    )

    risk_penalty = (
        0.7*crowd_risk +
        1.0*safety_risk +
        0.8*extreme_neg_ratio
    )

    core_score = adjusted_quality*stability

    final_score = (
        core_score +
        0.3*domain_bonus -
        0.5*risk_penalty
    )

    if num_reviews < min_review_threshold:
        final_score *=0.85

    final_score = max(0,min(1,final_score))

    
    # =====================================================
    # STORE RESULT
    # =====================================================

    results.append({

        "City": city,
        "State": state,
        "Name": poi_name,
        "attraction_index": poi_index,
        "num_reviews": num_reviews,

        "attraction_quality": round(final_score,4),
        "core_quality": round(core_score,4),
        "stability": round(stability,4),

        "experience_signal": round(experience_signal,4),
        "nature_signal": round(nature_signal,4),
        "culture_signal": round(culture_signal,4),
        "family_signal": round(family_signal,4),
        "facility_signal": round(facility_signal,4),
        "tour_signal": round(tour_signal,4),
        "shopping_signal": round(shopping_signal,4),

        "crowd_risk": round(crowd_risk,4),
        "safety_risk": round(safety_risk,4),
        "extreme_neg_ratio": round(extreme_neg_ratio,4),

        "Review_Summary": summary
    })

# =========================================================
# SAVE CSV
# =========================================================

results_df = pd.DataFrame(results)

results_df.to_csv(output_path, index=False, encoding="utf-8")

print("\nSaved:", output_path)