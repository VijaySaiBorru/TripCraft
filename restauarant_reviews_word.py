import pandas as pd
import re
from collections import Counter, defaultdict
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation

# =========================================================
# LOAD DATA
# =========================================================

reviews_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_restaurant_reviews.csv"
df = pd.read_csv(reviews_path)

df = df[df["Comment"].notna()]

print("Total reviews:", len(df))
print("Unique Restaurants:", df["Name"].nunique())
print("\n==============================\n")

# =========================================================
# CLEAN FUNCTION
# =========================================================

def clean_text(text):
    text = str(text).lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

df["clean_comment"] = df["Comment"].apply(clean_text)

# =========================================================
# STOP WORDS
# =========================================================

stop_words = set(ENGLISH_STOP_WORDS)

extra_stopwords = {
    "restaurant","place","food","dish","meal","menu",
    "really","just","also","like","one","get","got",
    "would","came","went","time","order","ordered"
}

stop_words = stop_words.union(extra_stopwords)

# =========================================================
# RESTAURANT BALANCED WORD FREQUENCY
# =========================================================

restaurant_groups = df.groupby("Name")

word_scores = defaultdict(float)

for restaurant, group in restaurant_groups:

    comments = group["clean_comment"].tolist()
    titles = group["Title"].astype(str).apply(clean_text).tolist() if "Title" in group else []

    combined_text = " ".join(titles + comments)

    tokens = [
        w for w in combined_text.split()
        if w not in stop_words and len(w) > 2
    ]

    if len(tokens) == 0:
        continue

    counts = Counter(tokens)

    total_words = sum(counts.values())

    for word, count in counts.items():
        word_scores[word] += count / total_words

# =========================================================
# SORT WORD RESULTS
# =========================================================

sorted_words = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)

print("TOP 50 BALANCED RESTAURANT WORDS\n")

for word, score in sorted_words[:50]:
    print(f"{word}: {round(score,4)}")

pd.DataFrame(sorted_words[:200], columns=["word","score"]).to_csv(
    "restaurant_word_frequency.csv", index=False
)

print("\nSaved: restaurant_word_frequency.csv")
print("\n==============================\n")

# =========================================================
# PHRASE DISCOVERY (BIGRAM + TRIGRAM)
# =========================================================

vectorizer = CountVectorizer(
    stop_words="english",
    ngram_range=(2,3),
    min_df=30
)

X = vectorizer.fit_transform(df["clean_comment"])

phrase_counts = X.sum(axis=0).A1
phrases = vectorizer.get_feature_names_out()

phrase_freq = list(zip(phrases, phrase_counts))
phrase_freq.sort(key=lambda x: x[1], reverse=True)

print("TOP 40 RESTAURANT PHRASES\n")

for phrase,count in phrase_freq[:40]:
    print(phrase,":",count)

pd.DataFrame(phrase_freq[:200], columns=["phrase","count"]).to_csv(
    "restaurant_phrases.csv", index=False
)

print("\nSaved: restaurant_phrases.csv")
print("\n==============================\n")

# =========================================================
# TOPIC DISCOVERY (LDA)
# =========================================================

vectorizer = CountVectorizer(
    stop_words="english",
    max_df=0.8,
    min_df=40
)

X = vectorizer.fit_transform(df["clean_comment"])

lda = LatentDirichletAllocation(
    n_components=6,
    random_state=42
)

lda.fit(X)

words = vectorizer.get_feature_names_out()

print("DISCOVERED RESTAURANT REVIEW TOPICS\n")

topics = []

for topic_idx, topic in enumerate(lda.components_):

    top_words = [words[i] for i in topic.argsort()[:-12:-1]]

    print("\nTopic", topic_idx)
    print(", ".join(top_words))

    topics.append({
        "topic": topic_idx,
        "words": ", ".join(top_words)
    })

pd.DataFrame(topics).to_csv("restaurant_topics.csv", index=False)

print("\nSaved: restaurant_topics.csv")