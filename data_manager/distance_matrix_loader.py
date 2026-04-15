import pandas as pd
import os
import difflib


class DistanceMatrixLoader:
    """
    Loader adapted for YOUR actual distance CSV format:
        origin, destination, distance_km, duration_min

    Exposes:
        driving_km, driving_min
    """

    def __init__(self, base_path):
        self.path = os.path.join(
            base_path,
            "distance_matrix",
            "city_distances_times_full.csv"
        )
        self.data = None

    # ----------------------------------------------------
    def load(self):
        try:
            df = pd.read_csv(self.path)
            df.columns = [c.strip().lower() for c in df.columns]

            # print("[DEBUG] DistanceMatrixLoader CSV columns:")
            # print(list(df.columns))

            # Required columns (ACTUAL)
            for col in ["origin", "destination", "distance_km", "duration_min"]:
                if col not in df.columns:
                    raise KeyError(f"Missing column '{col}' in distance.csv")

            # Normalize city names
            df["Origin"] = df["origin"].astype(str).str.strip().str.lower()
            df["Destination"] = df["destination"].astype(str).str.strip().str.lower()

            # Direct mapping (already numeric)
            df["driving_km"] = pd.to_numeric(df["distance_km"], errors="coerce")
            df["driving_min"] = pd.to_numeric(df["duration_min"], errors="coerce")

            # Taxi cost not available in this dataset
            df["taxi_cost"] = None

            self.data = df

        except Exception as e:
            print(f"[DistanceMatrixLoader] Load FAILED: {e}")
            self.data = None

    # ----------------------------------------------------
    # EXACT LOOKUP
    # ----------------------------------------------------
    def get_distance(self, origin, destination, mode="self-driving"):
        if self.data is None:
            return None

        o = origin.lower().strip()
        d = destination.lower().strip()

        df = self.data[
            (self.data["Origin"] == o) &
            (self.data["Destination"] == d)
        ]

        if df.empty:
            return None

        row = df.iloc[0]

        if mode == "self-driving":
            return {
                "distance_km": row["driving_km"],
                "duration_min": row["driving_min"]
            }

        elif mode == "taxi":
            return {"cost": row["taxi_cost"]}

        return None

    # ----------------------------------------------------
    # FUZZY MATCH
    # ----------------------------------------------------
    def get_distance_fuzzy(self, origin, destination, mode="self-driving", threshold=0.75):
        if self.data is None:
            return None

        o = origin.lower().strip()
        d = destination.lower().strip()

        all_o = self.data["Origin"].unique().tolist()
        all_d = self.data["Destination"].unique().tolist()

        best_o = difflib.get_close_matches(o, all_o, n=1, cutoff=threshold)
        best_d = difflib.get_close_matches(d, all_d, n=1, cutoff=threshold)

        if not best_o or not best_d:
            return None

        return self.get_distance(best_o[0], best_d[0], mode=mode)
