import pandas as pd
import os
import ast


class AccommodationLoader:
    """
    Loads accommodation data and normalizes all column names
    EXACTLY to what TravelPlanner agents expect.
    """

    def __init__(self, base_path):
        self.path = os.path.join(
            base_path,
            "accommodation",
            "cleaned_listings_final_v2.csv"
        )
        self.data = None
        self.df = None

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------
    @staticmethod
    def extract_price_from_pricing(val):
        """
        pricing example:
        {'label': '$179 per night', 'price': '$179', ...}
        """
        if not isinstance(val, str):
            return None
        try:
            obj = ast.literal_eval(val)
            price = obj.get("price")
            if isinstance(price, str):
                return float(price.replace("$", "").strip())
        except Exception:
            return None
        return None

    @staticmethod
    def extract_rating(val):
        """
        rating example:
        {'label': '4.83 out of 5...', 'average': 4.83}
        """
        if not isinstance(val, str):
            return None
        try:
            obj = ast.literal_eval(val)
            avg = obj.get("average")
            if avg is not None:
                return float(avg)
        except Exception:
            return None
        return None

    # --------------------------------------------------
    # Main loader
    # --------------------------------------------------
    def load(self):
        try:
            df = pd.read_csv(self.path)

            # print("[DEBUG] Accommodation CSV columns:")
            # print(list(df.columns))

            # Remove unnamed index columns
            df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

            # Ensure City exists
            if "City" not in df.columns:
                raise KeyError("City column missing in accommodation CSV")

            df["City"] = df["City"].astype(str).str.strip()

            # -------------------------------
            # Normalize pricing → price_per_night
            # -------------------------------
            if "pricing" in df.columns:
                df["price_per_night"] = df["pricing"].apply(
                    self.extract_price_from_pricing
                )
            else:
                df["price_per_night"] = None

            # -------------------------------
            # Normalize rating → float
            # -------------------------------
            if "rating" in df.columns:
                df["rating"] = df["rating"].apply(self.extract_rating)
            else:
                df["rating"] = None

            # -------------------------------
            # Normalize occupancy
            # -------------------------------
            if "max_occupancy" in df.columns:
                df["max_occupancy"] = pd.to_numeric(
                    df["max_occupancy"], errors="coerce"
                )

            # -------------------------------
            # Compatibility with ReferenceBuilder
            # -------------------------------
            df["price"] = df["price_per_night"]

            self.data = df
            self.df = df

        except Exception as e:
            print(f"[AccommodationLoader] Error loading file: {e}")

    # --------------------------------------------------
    # Accessor
    # --------------------------------------------------
    def get_by_city(self, city):
        """Return accommodations in city."""
        if self.data is None:
            return pd.DataFrame()

        return self.data[
            self.data["City"].str.lower() == city.lower().strip()
        ]
