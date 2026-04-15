import pandas as pd
import re
from collections import Counter
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation

# =========================================================
# LOAD DATA
# =========================================================

reviews_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_accomodation_review.csv"
df = pd.read_csv(reviews_path)

df = df[df["Comment"].notna()]

print("Total reviews:", len(df))
print("Unique accommodations:", df["Name"].nunique())
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

# remove common review filler words
extra_stopwords = {
    "stay","place","great","nice","really","just","time","good",
    "like","little","also","one","would","us","stayed","staying"
}

stop_words = stop_words.union(extra_stopwords)

# =========================================================
# WORD FREQUENCY
# =========================================================

tokens = []

for comment in df["clean_comment"]:
    words = [
        w for w in comment.split()
        if w not in stop_words and len(w) > 2
    ]
    tokens.extend(words)

word_counts = Counter(tokens)

print("TOP 40 SIGNAL WORDS\n")

for w,c in word_counts.most_common(40):
    print(w,":",c)

# save words
pd.DataFrame(word_counts.most_common(200), columns=["word","count"]).to_csv(
    "accom_word_frequency.csv", index=False
)

print("\nSaved: accom_word_frequency.csv")

print("\n==============================\n")

# =========================================================
# PHRASE DISCOVERY (BIGRAM + TRIGRAM)
# =========================================================

vectorizer = CountVectorizer(
    stop_words="english",
    ngram_range=(2,3),
    min_df=20
)

X = vectorizer.fit_transform(df["clean_comment"])

phrase_counts = X.sum(axis=0).A1
phrases = vectorizer.get_feature_names_out()

phrase_freq = list(zip(phrases, phrase_counts))
phrase_freq.sort(key=lambda x: x[1], reverse=True)

print("TOP 40 PHRASES\n")

for phrase,count in phrase_freq[:40]:
    print(phrase,":",count)

pd.DataFrame(phrase_freq[:200], columns=["phrase","count"]).to_csv(
    "accom_phrases.csv", index=False
)

print("\nSaved: accom_phrases.csv")

print("\n==============================\n")

# =========================================================
# AUTOMATIC TOPIC DISCOVERY
# =========================================================

vectorizer = CountVectorizer(
    stop_words="english",
    max_df=0.8,
    min_df=30
)

X = vectorizer.fit_transform(df["clean_comment"])

lda = LatentDirichletAllocation(
    n_components=6,
    random_state=42
)

lda.fit(X)

words = vectorizer.get_feature_names_out()

print("DISCOVERED REVIEW TOPICS\n")

topics = []

for topic_idx, topic in enumerate(lda.components_):

    top_words = [words[i] for i in topic.argsort()[:-12:-1]]

    print("\nTopic", topic_idx)
    print(", ".join(top_words))

    topics.append({
        "topic": topic_idx,
        "words": ", ".join(top_words)
    })

pd.DataFrame(topics).to_csv("accom_topics.csv", index=False)

print("\nSaved: accom_topics.csv")