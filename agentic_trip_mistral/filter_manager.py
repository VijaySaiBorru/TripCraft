# agentic_trip/filter_manager.py

import pandas as pd

class FilterManager:
    def __init__(self, dm):
        self.dm = dm

    # ---------------------------------------------------------
    # ACCOMMODATIONS
    # ---------------------------------------------------------
    def filter_accommodations(self, city):
        df = self.dm.get_accommodations(city)
        if df is None or df.empty:
            return []
        return df.head(20).to_dict(orient="records")

    # ---------------------------------------------------------
    # ATTRACTIONS
    # ---------------------------------------------------------
    def filter_attractions(self, city):
        df = self.dm.attractions.get_by_city(city)
        if df is None or df.empty:
            return []
        return df.head(20).to_dict(orient="records")

    # ---------------------------------------------------------
    # RESTAURANTS
    # ---------------------------------------------------------
    def filter_restaurants(self, city):
        df = self.dm.restaurants.get_by_city(city)
        if df is None or df.empty:
            return []
        return df.head(25).to_dict(orient="records")

    # ---------------------------------------------------------
    # FLIGHTS (SMART SELECTION)
    # ---------------------------------------------------------
    def filter_flights(self, origin, dest, date, top_n=10):

        def parse_minutes(t):
            """Convert HH:MM → minutes."""
            if pd.isna(t):
                return None
            t = str(t).strip()

            if ":" in t:
                try:
                    h, m = map(int, t.split(":"))
                    return h * 60 + m
                except:
                    return None

            try:
                t = int(t)
                return (t // 100) * 60 + (t % 100)
            except:
                return None

        def normalize(df):
            """Normalize departure time column."""
            if df is None or df.empty:
                return df

            time_col = None
            for c in ["DepTime", "departure_time", "dep"]:
                if c in df.columns:
                    time_col = c
                    break

            if time_col is None:
                return df

            df["__dep_minutes"] = df[time_col].apply(parse_minutes)
            df = df.dropna(subset=["__dep_minutes"])
            return df

        def select(df, mode):
            df = normalize(df)
            if df is None or df.empty:
                return []

            morning_min, morning_max = 360, 720      # 6AM - 12PM
            afternoon_min, afternoon_max = 720, 1020 # 12PM - 5PM
            evening_min = 1020                       # 5PM+

            dep = df["__dep_minutes"]

            if mode == "onward":
                morning = df[(dep >= morning_min) & (dep <= morning_max)]
                if not morning.empty:
                    return morning.sort_values("Price").head(top_n).to_dict(orient="records")

                afternoon = df[(dep >= afternoon_min) & (dep <= afternoon_max)]
                if not afternoon.empty:
                    return afternoon.sort_values("Price").head(top_n).to_dict(orient="records")

                earliest = df.sort_values("__dep_minutes").head(top_n)
                return earliest.sort_values("Price").to_dict(orient="records")

            # RETURN FLIGHT SELECTION
            evening = df[dep >= evening_min]
            if not evening.empty:
                return evening.sort_values("Price").head(top_n).to_dict(orient="records")

            afternoon = df[(dep >= afternoon_min) & (dep <= afternoon_max)]
            if not afternoon.empty:
                return afternoon.sort_values("Price").head(top_n).to_dict(orient="records")

            latest = df.sort_values("__dep_minutes", ascending=False).head(top_n)
            return latest.sort_values("Price").to_dict(orient="records")

        # ---------------------------------------------------------
        # GET RAW FLIGHTS FROM DATA MANAGER
        # ---------------------------------------------------------
        onward_raw = self.dm.get_flights(origin, dest, date, prefer="cheapest")
        return_raw = self.dm.get_flights(dest, origin, date, prefer="cheapest")

        onward = select(onward_raw, "onward")
        ret = select(return_raw, "return")

        return {"onward": onward, "return": ret}
