import json
import sys
from pathlib import Path


class SkeletonBuilder:
    """
    Builds deterministic day skeletons.
    Responsibilities:
    - transportation string
    - current_city
    - accommodation availability
    - gate breakfast / lunch / dinner / attraction as "-" or ""
    """

    # -------------------------
    # helpers
    # -------------------------
    @staticmethod
    def hhmm_to_min(t):
        if not t:
            return None
        h, m = map(int, t.split(":"))
        return h * 60 + m

    @staticmethod
    def min_to_hhmm(m):
        h = m // 60
        m = m % 60
        return f"{h:02d}:{m:02d}"

    # -------------------------
    # extract inputs from combined_reference.json
    # -------------------------
    def extract_inputs(self, combined):
            # --------------------------------------------------
            # 1. Basic extraction
            # --------------------------------------------------
            dates = combined.get("dates", [])
            n_days = len(dates)

            cities = combined.get("cities", [])
            transport_legs = combined.get("transportation", {}).get("legs", [])

            # --------------------------------------------------
            # 2. DAY → CITY MAP (NON-TRAVEL DAYS ONLY)
            #     MUST MATCH ORIGINAL LOGIC
            # --------------------------------------------------
            if n_days == 3:
                day_city = [cities[0]["city"]] * 3

            elif n_days == 5:
                day_city = (
                    [cities[0]["city"]] * 3 +
                    [cities[1]["city"]] * 2
                )

            elif n_days == 7:
                day_city = (
                    [cities[0]["city"]] * 3 +
                    [cities[1]["city"]] * 2 +
                    [cities[2]["city"]] * 2
                )

            else:
                raise ValueError(f"Unsupported trip length: {n_days}")

            # --------------------------------------------------
            # 3. Accommodation map (EXACT FORMAT)
            # --------------------------------------------------
            accommodation_by_city = {
                c["city"]: f'{c["accommodation"]["name"]}, {c["city"]}'
                for c in cities
                if c.get("accommodation")
            }

            return n_days, day_city, transport_legs, accommodation_by_city

    # -------------------------
    # core skeleton builder
    # -------------------------
    def build_days_skeleton(
            self,
        n_days,
        dates,
        day_city,              # list of cities per day index
        transport_legs,        # ordered legs with mode + details
        accommodation_by_city  # city -> accommodation string
    ):
        """
        Builds deterministic day skeleton.
        Decides:
        - transportation string + timings
        - accommodation placement
        - where meals / attraction MUST be "-"
        """

        days = []

        # Helper
        def hhmm_to_min(t):
            if not t:
                return None
            h, m = map(int, t.split(":"))
            return h * 60 + m

        def min_to_hhmm(m):
            h = m // 60
            m = m % 60
            return f"{h:02d}:{m:02d}"

        # Travel days map (day_index -> leg)
        travel_days = {}
        for leg in transport_legs:
            travel_days[leg["day"] - 1] = leg

        for i in range(n_days):
            day = {
                "day": i + 1,
                "current_city": "",
                "transportation": "-",
                "breakfast": "",
                "lunch": "",
                "dinner": "",
                "attraction": "",
                "accommodation": "-",
                "event": "-",                     
                "point_of_interest_list": ""
            }

            is_travel = i in travel_days
            is_day1 = i == 0
            is_last = i == n_days - 1

            # ----------------------------
            # NON-TRAVEL DAY
            # ----------------------------
            if not is_travel:
                city = day_city[i]
                day["current_city"] = city
                day["accommodation"] = accommodation_by_city.get(city, "-")
                days.append(day)
                continue

            leg = travel_days[i]
            mode = leg["mode"]
            details = leg["details"]
            duration = details.get("duration_minutes")

            dep = arr = None

            # ----------------------------
            # FLIGHT → FIXED TIMES
            # ----------------------------
            if mode == "flight":
                dep = details["departure_time"]
                arr = details["arrival_time"]

            # ----------------------------
            # TAXI / SELF-DRIVING → DERIVED
            # ----------------------------
            # ----------------------------
            # TAXI / SELF-DRIVING → DERIVED
            # ----------------------------
            else:
                # DAY 1
                if is_day1:
                    if duration <= 12 * 60:
                        dep = "06:00"
                        arr = min_to_hhmm(6 * 60 + duration)
                    else:
                        dep = None
                        arr = "19:30"

                # LAST DAY
                elif is_last:
                    if duration <= 12 * 60:
                        dep = "15:30"
                    else:
                        dep = "15:30"
                    arr = None

                # INTER-CITY DAY (ALWAYS NEED TIMINGS)
                else:
                    if duration <= 12 * 60:
                        dep = "06:00"
                        arr = min_to_hhmm(6 * 60 + duration)
                    else:
                        target_arr = 21 * 60 + 30
                        dep_min = max(2 * 60, target_arr - duration)
                        arr_min = dep_min + duration
                        dep = min_to_hhmm(dep_min)
                        arr = min_to_hhmm(arr_min)


            # Transportation string
            # ----------------------------
            # Transportation string
            # ----------------------------
            if mode == "flight":
                flight_no = details.get("flight_number") or details.get("Flight Number")

                parts = []
                if flight_no:
                    parts.append(f"Flight Number: {flight_no}")

                parts.append(f"from {leg['from']} to {leg['to']}")

                if dep:
                    parts.append(f"Departure Time: {dep}")
                if arr:
                    parts.append(f"Arrival Time: {arr}")

                day["transportation"] = ", ".join(parts)

            else:
                # Non-flight keeps duration
                parts = [
                    f"{mode.title()} from {leg['from']} to {leg['to']}",
                    f"Duration: {duration} mins"
                ]

                if dep:
                    parts.append(f"Departure Time: {dep}")
                if arr:
                    parts.append(f"Arrival Time: {arr}")

                day["transportation"] = ", ".join(parts)



            # ----------------------------
            # DAY 1 (ARRIVAL ONLY)
            # ----------------------------
            if is_day1:
                # 🔴 DAY-1 FLIGHT AFTER MIDNIGHT FIX
                if mode == "flight":
                    arr_min = hhmm_to_min(arr)

                    # Arrival after midnight → next calendar day
                    if arr_min is not None and arr_min < 5 * 60:
                        day["current_city"] = f"from {leg['from']} to {leg['to']}"
                        day["breakfast"] = "-"
                        day["lunch"] = "-"
                        day["dinner"] = "-"
                        day["attraction"] = "-"
                        day["accommodation"] = accommodation_by_city.get(leg["to"], "-")
                        days.append(day)
                        continue

                arr_min = hhmm_to_min(arr)
                day["current_city"] = f"from {leg['from']} to {leg['to']}"


                if arr_min is None or arr_min > 8 * 60 + 10:
                    day["breakfast"] = "-"
                if arr_min is None or arr_min > 13 * 60:
                    day["lunch"] = "-"
                if arr_min is None or arr_min > 16 * 60 + 45:
                    day["attraction"] = "-"
                if arr_min is None or arr_min  > 20 * 60 :
                    day["dinner"] = "-"

                day["accommodation"] = accommodation_by_city.get(leg["to"], "-")
                days.append(day)
                continue

            # ----------------------------
            # LAST DAY (DEPARTURE ONLY)
            # ----------------------------
            if is_last:
                dep_min = hhmm_to_min(dep)
                day["current_city"] = f"from {leg['from']} to {leg['to']}"


                if dep_min is None or dep_min < 9 * 60 + 20:
                    day["breakfast"] = "-"
                if dep_min is None or dep_min < 13 * 60 + 30:
                    day["lunch"] = "-"
                if dep_min is None or dep_min <= 20 * 60 + 45:
                    day["dinner"] = "-"
                if dep_min is None or dep_min <= 13 * 60 + 20:
                    day["attraction"] = "-"

                days.append(day)
                continue

            # ----------------------------
            # INTER-CITY DAY
            # ----------------------------
            dep_min = hhmm_to_min(dep)
            arr_min = hhmm_to_min(arr)
            day["current_city"] = f"from {leg['from']} to {leg['to']}"


            # Long travel → pure transition
            # Breakfast in origin city
            # Breakfast logic (INTER-CITY DAY)
            # Allow breakfast if arrival is early, else check departure
            # ----------------------------
            # INTER-CITY DAY (TIME-BASED)
            # ----------------------------
            # Breakfast
            if not (
                (arr_min is not None and arr_min <= 8 * 60 + 10) or
                (dep_min is not None and dep_min >= 9 * 60 + 20)
            ):
                day["breakfast"] = "-"

            # Lunch
            if not (
                (arr_min is not None and arr_min <= 13 * 60 ) or
                (dep_min is not None and dep_min >= 13 * 60 +30)
            ):
                day["lunch"] = "-"

            # Dinner
            if not (
                (arr_min is not None and arr_min <= 20 * 60) or
                (dep_min is not None and dep_min >= 20 * 60 + 45)
            ):
                day["dinner"] = "-"

            # Attraction (max 1, rare windows)
            if not (
                (arr_min is not None and arr_min <= 16 * 60 + 45) or
                (dep_min is not None and dep_min >= 13 * 60 + 20)
            ):
                day["attraction"] = "-"



            day["accommodation"] = accommodation_by_city.get(leg["to"], "-")
            days.append(day)

        return days



# -------------------------
# CLI runner
# -------------------------
def main():
    if len(sys.argv) != 2:
        print("Usage: python skeleton_builder.py <query_number>")
        sys.exit(1)

    query_no = sys.argv[1]

    base = Path(
        "/scratch/sg/Vijay/TripCraft/output_agentic/agentic/qwen2.5/3day"
    ) / query_no

    combined_path = base / "combined_reference.json"

    if not combined_path.exists():
        raise FileNotFoundError(combined_path)

    with open(combined_path) as f:
        combined = json.load(f)

    builder = SkeletonBuilder()

    n_days, day_city, transport_legs, accommodation_by_city = builder.extract_inputs(
        combined
    )

    days = builder.build_days_skeleton(
        n_days=n_days,
        dates=combined["dates"],
        day_city=day_city,
        transport_legs=transport_legs,
        accommodation_by_city=accommodation_by_city,
    )

    print("\n===== DAY SKELETON =====")
    for d in days:
        print(json.dumps(d, indent=2))


if __name__ == "__main__":
    main()
