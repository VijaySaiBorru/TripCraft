# /Vijay/TravelPlanner/data_manager/data_manager.py
import os
from typing import List, Optional

from data_manager.accommodation_loader import AccommodationLoader
from data_manager.attraction_loader import AttractionLoader
from data_manager.restaurants_loader import RestaurantsLoader
from data_manager.distance_matrix_loader import DistanceMatrixLoader
from data_manager.background_loader import BackgroundLoader
from data_manager.events_loader import EventsLoader
from data_manager.flights_loader_sql import FlightsLoaderSQL


class DataManager:
    """
    Clean, corrected DataManager for TravelPlanner.
    """

    def __init__(self, base_path: str = "./database"):
        # Normalize base path
        self.base_path = os.path.abspath(base_path)

        # ---------------------------------------------------------
        # Loaders for local DB datasets
        # ---------------------------------------------------------
        self.accommodation = AccommodationLoader(self.base_path)
        self.attractions = AttractionLoader(self.base_path)
        self.restaurants = RestaurantsLoader(self.base_path)
        self.distance = DistanceMatrixLoader(self.base_path)
        self.background = BackgroundLoader(self.base_path)
        self.events = EventsLoader(self.base_path)

        # ---------------------------------------------------------
        # Flights DB MUST BE inside TravelPlanner/database/flights.db
        # ---------------------------------------------------------
        db_path = os.path.abspath(
            os.path.join(self.base_path, "..", "db", "flights.db")
        )

        print(f"[DEBUG] Flights DB path → {db_path}")

        # Correct flights loader base_path
        self.flights = FlightsLoaderSQL(
            base_path=self.base_path,
            db_path=db_path
        )

    # ---------------------------------------------------------
    # LOAD ALL
    # ---------------------------------------------------------
    def load_all(self):
        self.accommodation.load()
        self.attractions.load()
        self.restaurants.load()
        self.distance.load()
        self.background.load()
        self.flights.load()
        self.events.load()

    # ---------------------------------------------------------
    # ACCOMMODATION
    # ---------------------------------------------------------
    def get_accommodations(self, city: str):
        return self.accommodation.get_by_city(city)

    # ---------------------------------------------------------
    # ATTRACTIONS
    # ---------------------------------------------------------
    def get_attractions(self, city: str, categories: Optional[List[str]] = None, top_k: int = 50):
        df = self.attractions.get_by_city(city)

        if categories:
            mask = False
            for c in categories:
                mask = mask | df["subcategories"].astype(str).str.contains(c, case=False, na=False)
            return df[mask].sort_values(by="rating", ascending=False).head(top_k)

        return self.attractions.get_top_rated(city, limit=top_k)

    # ---------------------------------------------------------
    # RESTAURANTS
    # ---------------------------------------------------------
    def get_restaurants(self, city: str, cuisine: Optional[str] = None, budget: Optional[float] = None, top_k: int = 30):
        df = self.restaurants.get_by_city(city)

        if cuisine:
            df = df[df["cuisines"].str.contains(cuisine, case=False, na=False)]

        if budget is not None and "avg_cost" in df.columns:
            df = df[df["avg_cost"] <= budget]

        if "rating" in df.columns:
            return df.sort_values(by="rating", ascending=False).head(top_k)

        return df.head(top_k)

    # ---------------------------------------------------------
    # DISTANCE
    # ---------------------------------------------------------
    def get_distance(self, origin: str, destination: str):
        origin = origin.strip().lower()
        destination = destination.strip().lower()

        r = self.distance.get_distance(origin, destination)
        if r:
            return r

        r = self.distance.get_distance_fuzzy(origin, destination)
        if r:
            return r

        return {"distance_km": None, "duration_min": None}

    # ---------------------------------------------------------
    # FLIGHTS DIRECT
    # ---------------------------------------------------------
    def get_flights(self, origin: str, dest: str, date: str, prefer="cheapest"):
        df = self.flights.get_flights(origin, dest, date)

        if df is None or df.empty:
            return df

        if prefer == "cheapest" and "Price" in df.columns:
            return df.sort_values(by="Price").head(5)

        if prefer == "earliest" and "DepTime" in df.columns:
            return df.sort_values(by="DepTime").head(5)

        return df

    # ---------------------------------------------------------
    # CONNECTING FLIGHTS
    # ---------------------------------------------------------
    def find_connecting_flights(self, origin: str, dest: str, date: str):
        return self.flights.get_connecting_flights(origin, dest, date)
