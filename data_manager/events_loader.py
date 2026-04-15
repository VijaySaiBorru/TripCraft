# data_manager/events_loader.py
import pandas as pd
import os

class EventsLoader:
    def __init__(self, base_path="./TripCraft_database"):
        self.path = os.path.join(base_path, "events/events_cleaned.csv")
        self.data = None

    def load(self):
        try:
            df = pd.read_csv(self.path)

            # --- SAFETY NORMALIZATION ---
            # Normalize date column only if present
            if "dateTitle" in df.columns:
                df["dateTitle"] = pd.to_datetime(df["dateTitle"], format="%d-%m-%Y", errors="coerce")


            # If city column missing → create empty
            if "city" not in df.columns:
                df["city"] = ""

            # If streetAddress missing → create empty
            if "streetAddress" not in df.columns:
                df["streetAddress"] = ""

            self.data = df
            self.df=df

            # print(f"[EventsLoader] Loaded: {self.path} ({len(df)} rows)")
            # print("Columns:", list(df.columns))

        except Exception as e:
            print(f"[EventsLoader] Error loading events: {e}")
            self.data = None

    def get_events_between(self, start_date, end_date):
        """Return events between two dates inclusive."""
        if self.data is None:
            return pd.DataFrame()

        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        if "dateTitle" not in self.data.columns:
            return pd.DataFrame()

        mask = (self.data["dateTitle"] >= start) & (self.data["dateTitle"] <= end)
        return self.data[mask]

    def get_events_by_city(self, city):
        """Filter events by city name."""
        if self.data is None:
            return pd.DataFrame()

        city = city.lower()

        if "streetAddress" not in self.data.columns:
            return pd.DataFrame()

        return self.data[self.data["streetAddress"].astype(str).str.lower().str.contains(city)]

    def run(self, city, date_range):
        """
        city: string (e.g., "las vegas")
        date_range: [start_date, end_date]
        """
        if self.data is None:
            return []

        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])

        df = self.data.copy()
        city_norm = city.strip().lower()

        # ----------------------------------------
        # DEBUG (remove later)
        # print("[DEBUG] EventsLoader.run city:", city_norm)
        # ----------------------------------------

        # ----------------------------------------
        # FLEXIBLE CITY MATCHING
        # ----------------------------------------
        mask_city = False
        mask_addr = False

        # Match city column
        if "city" in df.columns:
            mask_city = df["city"].astype(str).str.lower().str.contains(city_norm, na=False)

        # Match streetAddress column (important)
        if "streetAddress" in df.columns:
            mask_addr = df["streetAddress"].astype(str).str.lower().str.contains(city_norm, na=False)

        # Combine both
        df = df[mask_city | mask_addr]

        # ----------------------------------------
        # DATE FILTER
        # ----------------------------------------
        if "dateTitle" in df.columns:
            df = df[(df["dateTitle"] >= start) & (df["dateTitle"] <= end)]

        # Return list of dicts
        return df.to_dict(orient="records")
