import pandas as pd

# Paths (your server paths)
review_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_attraction_reviews.csv"
attraction_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/attraction/cleaned_attractions_final.csv"
output_path = "/scratch/sg/Vijay/TripCraft/pend_attraction.csv"

# Load files
reviews_df = pd.read_csv(review_path, encoding="latin1", engine="python")
attractions_df = pd.read_csv(attraction_path, encoding="latin1", engine="python")

# Clean column names
reviews_df.columns = reviews_df.columns.str.strip()
attractions_df.columns = attractions_df.columns.str.strip()

# Create matching key (name + city + state)
reviews_df["key"] = (
    reviews_df["Name"].str.strip().str.lower() + "|" +
    reviews_df["City"].str.strip().str.lower() + "|" +
    reviews_df["State"].str.strip().str.lower()
)

attractions_df["key"] = (
    attractions_df["name"].str.strip().str.lower() + "|" +
    attractions_df["City"].str.strip().str.lower() + "|" +
    attractions_df["State"].str.strip().str.lower()
)

# Count reviews per attraction
review_counts = reviews_df.groupby("key").size().reset_index(name="reviewcount")

# Merge counts with attractions
merged = attractions_df.merge(review_counts, on="key", how="left")

# Fill missing counts with 0
merged["reviewcount"] = merged["reviewcount"].fillna(0).astype(int)

# Filter 0,1,2 reviews
filtered = merged[merged["reviewcount"].isin([0, 1, 2])].copy()

# Select required columns
final_df = filtered[["name", "City", "State", "id", "webUrl", "reviewcount"]].copy()
final_df.columns = ["name", "city", "state", "id", "url", "reviewcount"]

# Convert id to string (avoid scientific notation)
final_df["id"] = final_df["id"].astype(str)

# Save file
final_df.to_csv(output_path, index=False)

print("Total Attractions:", len(attractions_df))
print("Attractions with 0/1/2 reviews:", len(final_df))
print("Saved to:", output_path)