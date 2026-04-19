import pandas as pd

path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/review_pro_cons/attraction_review_pro_cons_fixed.csv"

df = pd.read_csv(path)

print("=== BASIC INFO ===")
print("Shape:", df.shape)

print("\n=== COLUMNS ===")
print(df.columns.tolist())

print("\n=== REQUIRED COLUMNS CHECK ===")
required = ["City", "Name", "attraction_index", "pros", "cons"]
for col in required:
    print(f"{col}: {'✅' if col in df.columns else '❌'}")

print("\n=== NULL COUNTS ===")
print(df[["pros", "cons"]].isnull().sum())


# -------------------------------
# Parse
# -------------------------------
def parse_pipe(text):
    if pd.isna(text) or str(text).strip() == "":
        return []
    return [x.strip() for x in str(text).split("|") if x.strip()]

df["pros_list"] = df["pros"].apply(parse_pipe)
df["cons_list"] = df["cons"].apply(parse_pipe)


# -------------------------------
# RANDOM SAMPLES
# -------------------------------
print("\n=== RANDOM SAMPLES ===")
sample = df.sample(5, random_state=42)

for _, row in sample.iterrows():
    print("\n---")
    print("Name:", row["Name"])
    print("Pros:", row["pros_list"])
    print("Cons:", row["cons_list"])


# -------------------------------
# LENGTH STATS
# -------------------------------
print("\n=== LENGTH STATS ===")
print("Pros:", df["pros_list"].apply(len).describe())
print("Cons:", df["cons_list"].apply(len).describe())


# -------------------------------
# ZERO LIST COUNTS
# -------------------------------
print("\n=== ZERO LIST COUNTS ===")
print("No pros:", (df["pros_list"].apply(len) == 0).sum())
print("No cons:", (df["cons_list"].apply(len) == 0).sum())


# -------------------------------
# DUPLICATES
# -------------------------------
print("\n=== DUPLICATE CHECK ===")
print("Duplicate index:", df.duplicated(subset=["attraction_index"]).sum())
print("Duplicate (City, Name):", df.duplicated(subset=["City", "Name"]).sum())