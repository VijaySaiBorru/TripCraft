# /scratch/sg/Vijay/TravelPlanner/database/background/citySet_with_states.txt
# /scratch/sg/Vijay/TravelPlanner/data_manager/background_loader.py
# background_loader.py
import os
from collections import defaultdict

class BackgroundLoader:
    """
    Loads city–state mapping from TravelPlanner’s background metadata.
    Provides two utilities:
      • get_state(city)
      • get_cities_in_state(state)
    """

    def __init__(self, base_path):
        # TravelPlanner official database path
        self.path = os.path.join(
            base_path,
            "background",
            "citySet_with_states_140.txt"
        )

        self.cities = []
        self.city_to_state = {}
        self.state_to_cities = defaultdict(list)

    def load(self):
        """Load mapping from city to state."""
        try:
            with open(self.path, "r") as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                parts = line.split()

                if len(parts) < 2:
                    print(f"[BackgroundLoader] Skipping invalid line: {line}")
                    continue

                # City may contain spaces → state is always last token
                city_raw = " ".join(parts[:-1]).strip()
                state_raw = parts[-1].strip()

                # Normalized versions
                city = city_raw.lower()
                state = state_raw.lower()

                # Store normalized info
                self.cities.append(city)
                self.city_to_state[city] = state
                self.state_to_cities[state].append(city)

        except Exception as e:
            print(f"[BackgroundLoader] Error: {e}")

    def get_state(self, city: str):
        """Return state for a city, or None."""
        return self.city_to_state.get(city.lower().strip())

    def get_cities_in_state(self, state: str):
        """Return list of cities belonging to a state."""
        return self.state_to_cities.get(state.lower().strip(), [])
