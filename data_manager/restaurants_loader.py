import pandas as pd
import os


class RestaurantsLoader:
    """
    Loader adapted for YOUR actual restaurants CSV.
    Normalizes to:
        name, City, cuisines, avg_cost, rating
    """

    def __init__(self, base_path):
        self.path = os.path.join(
            base_path,
            "restaurants",
            "cleaned_restaurant_details_2024.csv"
        )
        self.data = None
        self.df = None

    # ----------------------------------------------------
    def load(self):
        try:
            df = pd.read_csv(self.path)
            df.columns = [c.strip() for c in df.columns]

            # print("[DEBUG] Restaurants CSV columns:")
            # print(list(df.columns))

            # -----------------------------
            # Name
            # -----------------------------
            if "name" not in df.columns:
                raise KeyError("Missing 'name' column in restaurants CSV")
            df["name"] = df["name"].astype(str).str.strip()

            # -----------------------------
            # City
            # -----------------------------
            if "City" not in df.columns:
                raise KeyError("Missing 'City' column in restaurants CSV")
            df["City"] = df["City"].astype(str).str.lower().str.strip()

            # -----------------------------
            # Cuisines (already list-like or string)
            # -----------------------------
            if "cuisines" in df.columns:
                df["cuisines"] = (
                    df["cuisines"]
                    .astype(str)
                    .str.lower()
                    .str.replace(", ", ",")
                    .str.split(",")
                )
            else:
                df["cuisines"] = [[]] * len(df)

            # -----------------------------
            # Average cost
            # -----------------------------
            if "avg_cost" in df.columns:
                df["avg_cost"] = pd.to_numeric(df["avg_cost"], errors="coerce")
            else:
                df["avg_cost"] = None

            # -----------------------------
            # Rating
            # -----------------------------
            if "rating" in df.columns:
                df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
            else:
                df["rating"] = None

            self.data = df
            self.df = df

        except Exception as e:
            print(f"[RestaurantsLoader] Error: {e}")

    # ----------------------------------------------------
    def get_by_city(self, city):
        if self.data is None:
            return pd.DataFrame()
        return self.data[self.data["City"] == city.lower().strip()]

    def filter_by_cuisine(self, city, cuisine):
        df = self.get_by_city(city)
        cuisine = cuisine.lower().strip()
        return df[df["cuisines"].apply(lambda x: cuisine in x)]

    def top_rated(self, city, limit=5):
        df = self.get_by_city(city)
        return df.sort_values(by="rating", ascending=False).head(limit)

    def within_budget(self, city, max_cost):
        df = self.get_by_city(city)
        return df[df["avg_cost"] <= max_cost]

    def sample_random(self, city):
        df = self.get_by_city(city)
        if len(df) == 0:
            return None
        return df.sample(1).iloc[0].to_dict()

    def cheapest(self, city):
        df = self.get_by_city(city)
        return df.sort_values(by="avg_cost", ascending=True).head(1)
