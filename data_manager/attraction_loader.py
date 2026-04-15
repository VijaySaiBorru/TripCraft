# /scratch/sg/Vijay/TravelPlanner/data_manager/attraction_loader.py

import pandas as pd
import os


class AttractionLoader:
    """
    Loads attraction data from TravelPlanner DB and enables
    city-based and optional category-based retrieval.

    visit_duration:
        - Units: HOURS (float)
        - Example: 1.5 = 90 minutes
    """

    def __init__(self, base_path):
        self.path = os.path.join(
            base_path,
            "attraction",
            "cleaned_attractions_final.csv"
        )
        self.data = None
        self.df = None

    def load(self):
        try:
            df = pd.read_csv(self.path)

            # ---------------- normalize column names ----------------
            df.columns = [c.strip() for c in df.columns]

            # ---------------- ensure City column ----------------
            city_col = None
            for col in df.columns:
                if col.lower() == "city":
                    city_col = col
                    break

            if city_col is None:
                raise KeyError("City column missing in attractions.csv")

            df["City"] = df[city_col].astype(str).str.strip()

            # ---------------- ensure name column ----------------
            if "name" not in df.columns:
                raise KeyError("name column missing in attractions.csv")

            df["name"] = df["name"].astype(str).str.strip()

            # ---------------- subcategories ----------------
            if "subcategories" not in df.columns:
                df["subcategories"] = ""
            else:
                df["subcategories"] = df["subcategories"].fillna("").astype(str)

            # ---------------- rating ----------------
            if "rating" not in df.columns:
                df["rating"] = 4.5
            else:
                df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(4.5)

            # ---------------- visit_duration (CRITICAL FIX) ----------------
            if "visit_duration" not in df.columns:
                # fallback: 2 hours if missing
                df["visit_duration"] = 2.0
            else:
                df["visit_duration"] = (
                    pd.to_numeric(df["visit_duration"], errors="coerce")
                    .fillna(2.0)
                    .clip(lower=0.5, upper=8.0)   # sanity clamp: 30 min – 8 hrs
                )

            # ---------------- derived helper column ----------------
            # Duration in minutes (convenient for POI builder)
            df["visit_duration_min"] = (df["visit_duration"] * 60).astype(int)

            # ---------------- save ----------------
            self.data = df
            self.df = df

        except Exception as e:
            print(f"[AttractionLoader] Error loading file: {e}")
            self.data = None
            self.df = None

    # ==========================================================
    # Query helpers
    # ==========================================================

    def get_by_city(self, city: str):
        if self.data is None:
            return pd.DataFrame()
        return self.data[self.data["City"].str.lower() == city.lower()]

    def search_by_category(self, category: str):
        if self.data is None:
            return pd.DataFrame()
        return self.data[
            self.data["subcategories"].str.contains(category, case=False, na=False)
        ]

    def get_top_rated(self, city: str, limit: int = 5):
        df = self.get_by_city(city)
        if df.empty:
            return df
        return df.sort_values(by="rating", ascending=False).head(limit)

    # ==========================================================
    # POI-builder-friendly helper
    # ==========================================================

    def get_attraction_with_duration(self, name: str, city: str):
        """
        Return a single attraction row with visit_duration_min.
        Used directly by POI builder.
        """
        if self.data is None:
            return None

        df = self.data[
            (self.data["City"].str.lower() == city.lower())
            & (self.data["name"].str.contains(name, case=False, na=False))
        ]

        if df.empty:
            return None

        return df.iloc[0]
