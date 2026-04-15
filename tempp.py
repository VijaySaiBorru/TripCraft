import pandas as pd

# Paths
restaurant_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/restaurants/cleaned_restaurant_details_2024.csv"
review_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_restaurant_reviews.csv"
output_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/pending_restaurants.csv"

# Load files
df_rest = pd.read_csv(restaurant_path)
df_review = pd.read_csv(review_path)

# Clean column names
df_rest.columns = df_rest.columns.str.strip()
df_review.columns = df_review.columns.str.strip()

# Standardize keys
df_rest["Name_key"] = df_rest["name"].str.strip().str.lower()
df_rest["City_key"] = df_rest["City"].str.strip().str.lower()
df_rest["State_key"] = df_rest["State"].str.strip().str.lower()

df_review["Name_key"] = df_review["Name"].str.strip().str.lower()
df_review["City_key"] = df_review["City"].str.strip().str.lower()
df_review["State_key"] = df_review["State"].str.strip().str.lower()

# Merge to find restaurants not in reviews
merged = df_rest.merge(
    df_review[["Name_key", "City_key", "State_key"]],
    on=["Name_key", "City_key", "State_key"],
    how="left",
    indicator=True
)

# Keep only restaurants not matched
pending = merged[merged["_merge"] == "left_only"]

# Select required columns
pending_final = pending[["name", "City", "State"]]
pending_final.columns = ["Name", "City", "State"]

# Remove duplicates
pending_final = pending_final.drop_duplicates()

# Save
pending_final.to_csv(output_path, index=False)

print("Pending restaurants saved successfully.")
print("Total pending:", len(pending_final))