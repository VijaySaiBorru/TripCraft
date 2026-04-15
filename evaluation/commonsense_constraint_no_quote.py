# /scratch/sg/Vijay/TripCraft/evaluation/commonsense_constraint.py
from utils.func import get_valid_name_city,extract_before_parenthesis,extract_numbers_from_filenames
from tools.flights.apis import Flights
from tools.accommodations.apis import Accommodations
from tools.restaurants.apis import Restaurants
from tools.googleDistanceMatrix.apis import GoogleDistanceMatrix
from tools.attractions.apis import Attractions
from tools.events.apis import Events
import math
import json
import re   
import os
import sys
from tqdm import tqdm
import argparse
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

flight = Flights()
accommodation = Accommodations()
restaurants = Restaurants()
googleDistanceMatrix = GoogleDistanceMatrix()
attractions = Attractions()
events = Events()
pois = pd.read_csv('../TripCraft_database/public_transit_gtfs/all_poi_nearest_stops.csv')

city_state_set = open('../TripCraft_database/background/citySet_with_states_140.txt','r').read().split('\n')
city_state_map = {x:y for x,y in [unit.split('\t') for unit in city_state_set]}


def is_early_departure(unit):
    transport = unit.get("transportation")
    if not transport:
        return False

    match = re.search(r'Departure Time:\s*(\d{1,2}):(\d{2})', transport)
    if not match:
        return False

    hour = int(match.group(1))
    return hour < 3

def load_line_json_data(filename):
    """
    Loads a JSONL file where each non-empty line is a JSON object.
    """
    data = []

    with open(filename, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue  # skip empty lines

            try:
                unit = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON on line {line_num} in {filename}: {e}"
                )

            data.append(unit)

    return data

def count_consecutive_values(lst):
    """
    Counts consecutive identical non-empty values.
    '-' and empty values are treated as breaks but not counted.
    """
    if not lst:
        return []

    result = []
    current_value = None
    count = 0

    for val in lst:
        if not val or val == '-':
            # Break current run
            if current_value is not None:
                result.append((current_value, count))
                current_value = None
                count = 0
            continue

        val = val.strip()

        if val == current_value:
            count += 1
        else:
            if current_value is not None:
                result.append((current_value, count))
            current_value = val
            count = 1

    if current_value is not None:
        result.append((current_value, count))

    return result

def transportation_match(text: str):
    """
    Classifies transportation type from a text description.
    Returns one of: 'Flight', 'Self-driving', 'Taxi', or None.
    """
    if not text or not isinstance(text, str):
        return None

    t = text.lower()

    # Flight must be checked first (highest priority)
    if 'flight' in t:
        return 'Flight'

    # Ground transport
    if 'self-driving' in t or 'self driving' in t:
        return 'Self-driving'

    if 'taxi' in t:
        return 'Taxi'

    return None

def extract_from_to(text: str):
    """
    Extracts origin and destination cities strictly from:
    'from <CITY_A> to <CITY_B>' (with spaces around 'to').
    """
    if not text or not isinstance(text, str):
        return None, None

    pattern = r"\bfrom\s+(.+?)\s+to\s+([^,]+)"
    match = re.search(pattern, text, re.IGNORECASE)

    if not match:
        return None, None

    city_from = match.group(1).strip()
    city_to = match.group(2).strip()

    return city_from, city_to

def is_valid_city_sequence(city_list):
    """
    Validates city visit order for multi-day trips.

    Rules:
    - Each city must appear in one contiguous block.
    - The origin city (first city) is allowed to reappear only as the final city.
    - No other city may reappear after its block ends.
    """

    if len(city_list) < 2:
        return False

    origin = city_list[0]
    visited = set()
    prev_city = None

    for idx, city in enumerate(city_list):
        if city != prev_city:
            # Re-entering a city after leaving it
            if city in visited:
                # Only allow origin at the very end (closed loop)
                if city == origin and idx == len(city_list) - 1:
                    return True
                return False

            visited.add(city)
            prev_city = city

    return True

def is_reasonable_visiting_city(question, tested_data):
    """
    Validates whether the visiting city sequence is reasonable:
    - Starts and ends at origin (closed loop)
    - Cities appear contiguously (no zig-zag)
    - All cities are valid
    - Intermediate cities belong to destination state (for trips > 3 days)
    """
    city_list = []

    for i in range(min(question['days'], len(tested_data))):
        city_value = tested_data[i]['current_city']

        if 'from' in city_value:
            city1, city2 = extract_from_to(city_value)

            city1 = extract_before_parenthesis(city1)
            city2 = extract_before_parenthesis(city2)

            if i == 0 and city1 != question['org']:
                return False, f"The first day's city should be {question['org']}."

            city_list.extend([city1, city2])
        else:
            city_list.append(extract_before_parenthesis(city_value))

    # Must be a closed loop
    if city_list[0] != city_list[-1]:
        return False, "The trip should be a closed circle."

    # City sequence validity (no re-visits after leaving)
    if not is_valid_city_sequence(city_list):
        return False, "The city sequence is invalid."

    # City validity + destination-state constraint
    for idx, city in enumerate(city_list):
        if city not in city_state_map:
            return False, f"{city} is not a valid city."

        if (
            idx not in (0, len(city_list) - 1)
            and question['days'] > 3
            and city_state_map[city] != question['dest']
        ):
            return False, f"{city} is not in {question['dest']}."

    return True, None

def is_valid_restaurants(question, tested_data):
    """
    Ensures no restaurant (by name) is repeated across the trip,
    regardless of meal type or formatting.
    """
    seen_restaurants = set()

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]

        for meal in ['breakfast', 'lunch', 'dinner']:
            if unit.get(meal) and unit[meal] != '-':
                restaurant_name = unit[meal].rsplit(",", 1)[0].strip().lower()

                if restaurant_name in seen_restaurants:
                    return False, (
                        f"The restaurant '{restaurant_name}' is repeated "
                        f"(day {i+1}, {meal})."
                    )

                seen_restaurants.add(restaurant_name)

    return True, None
           
def is_valid_attractions(question, tested_data):
    """
    Ensures no attraction (by name) is repeated across the trip.
    Prints debug info ONLY when a duplicate is found.
    """
    seen_attractions = {}

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]
        day = i + 1

        if unit.get('attraction') and unit['attraction'] != '-':
            for attraction in unit['attraction'].split(';'):
                attraction = attraction.strip()
                if not attraction:
                    continue

                attraction_name = attraction.rsplit(",", 1)[0].strip().lower()

                if attraction_name in seen_attractions:
                    first_day = seen_attractions[attraction_name]

                    # 🔴 PRINT ONLY ON ERROR
                    # print("\n❌ [Diverse Attractions FAILED]")
                    # print(f"Attraction     : {attraction_name}")
                    # print(f"First seen day : {first_day}")
                    # print(f"Repeated on day: {day}")
                    # print(f"Raw value      : {attraction}")
                    # print("--------------------------------------------------")

                    return False, (
                        f"The attraction '{attraction_name}' is repeated (day {day})."
                    )

                seen_attractions[attraction_name] = day

    return True, None

def is_valid_event(question, tested_data):
    """
    Ensures no event (by name + date) is repeated across the trip.
    City and formatting differences are ignored.
    """

    seen_events = set()

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]

        if unit.get('event') and unit['event'] != '-':
            for event in unit['event'].split(';'):
                event = event.strip()
                if not event:
                    continue

                # Extract name + city
                name = event.rsplit(",", 1)[0].strip().lower()
                city = event.rsplit(",", 1)[-1].strip()

                # 🔍 lookup event date from sandbox
                res = events.data[
                    (events.data['name'].astype(str).str.strip().str.lower() == name) &
                    (events.data['city'].astype(str).str.strip().str.lower() == city.lower())
                ]

                # If not found → sandbox will catch it
                if len(res) == 0:
                    continue

                # Use dateTitle as date identifier
                event_date = str(res.iloc[0].get('dateTitle', '')).strip().lower()

                event_key = (name, event_date)

                if event_key in seen_events:
                    return False, (
                        f"The event '{name}' on '{event_date}' "
                        f"is repeated (day {i+1})."
                    )

                seen_events.add(event_key)

    return True, None

def is_time_difference_valid(time1, time2, min_difference):
    """
    Checks whether time2 occurs at least `min_difference` minutes AFTER time1.
    """
    from datetime import datetime

    fmt = "%H:%M"
    t1 = datetime.strptime(time1, fmt)
    t2 = datetime.strptime(time2, fmt)

    return (t2 - t1).total_seconds() / 60 >= min_difference

def is_valid_poi_sequence(question, tested_data, plan_id=None):
    """
    Debug-enabled version.
    Prints WHY and WHERE a PoI sequence violation happens.
    """

    import re

    time_pattern = re.compile(r'from\s+(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})')

    def dbg(msg):
        prefix = f"[PoI-FAIL][Plan {plan_id}]" if plan_id is not None else "[PoI-FAIL]"
        print(f"{prefix} {msg}")

    def normalize_time(t):
        if t is None:
            return None
        t = str(t).strip()
        if ":" in t:
            h, m = t.split(":")
            if h.isdigit() and m.isdigit():
                return f"{int(h):02d}:{int(m):02d}"
            return None
        if t.isdigit():
            return f"{int(t):02d}:00"
        return None

    def minutes_since_day_start(t):
        t = normalize_time(t)
        if t is None:
            return None
        h, m = map(int, t.split(":"))
        return h * 60 + m

    prev_accommodation = None
    total_days = question['days']

    for i, unit in enumerate(tested_data[:total_days]):
        day_num = i + 1
        is_final_day = (day_num == total_days)

        poi_list = unit.get("point_of_interest_list")
        if (not poi_list or poi_list == '-'):
            if is_final_day and is_early_departure(unit):
                # dbg(f"Day {day_num}: Early departure on last day → PoI not required")
                return True, None 
            # dbg(f"Day {day_num}: PoI list missing")
            return False, f"PoI list missing on day {day_num}."

        poi_entries = [p.strip() for p in poi_list.split(";") if p.strip()]

        curr_acc = unit.get("accommodation")
        curr_acc_base = None
        if curr_acc and curr_acc != "-":
            curr_acc_base = curr_acc.split(",", 1)[0].strip()

        first_poi = poi_entries[0]
        last_poi = poi_entries[-1]

        # ---------- TRANSITION DAY ----------
        if day_num % 2 == 1 and day_num > 1 and prev_accommodation:

            if is_final_day:
                if prev_accommodation not in first_poi:
                    # dbg(
                    #     f"Day {day_num} FINAL transition violation\n"
                    #     f"  Expected checkout from: {prev_accommodation}\n"
                    #     f"  First PoI: {first_poi}"
                    # )
                    return False, (
                        f"Final day PoI list must start with previous accommodation (checkout)."
                    )

            else:
                if not (
                    prev_accommodation in first_poi and
                    curr_acc_base and curr_acc_base in last_poi
                ):
                    # dbg(
                    #     f"Day {day_num} TRANSITION violation\n"
                    #     f"  Prev acc: {prev_accommodation}\n"
                    #     f"  Curr acc: {curr_acc_base}\n"
                    #     f"  First PoI: {first_poi}\n"
                    #     f"  Last PoI: {last_poi}"
                    # )
                    return False, (
                        f"Day {day_num} PoI list must start with previous accommodation "
                        f"and end with current accommodation."
                    )

        # ---------- NORMAL DAY ----------
        else:
            if curr_acc_base:
                if not (
                    curr_acc_base in first_poi and
                    curr_acc_base in last_poi
                ):
                    # dbg(
                    #     f"Day {day_num} NORMAL day violation\n"
                    #     f"  Accommodation: {curr_acc_base}\n"
                    #     f"  First PoI: {first_poi}\n"
                    #     f"  Last PoI: {last_poi}"
                    # )
                    return False, (
                        f"PoI list for day {day_num} must start and end with accommodation."
                    )
            else:
                if prev_accommodation and prev_accommodation not in first_poi:
                    # dbg(
                    #     f"Day {day_num} NO-accommodation start violation\n"
                    #     f"  Prev acc: {prev_accommodation}\n"
                    #     f"  First PoI: {first_poi}"
                    # )
                    return False, (
                        f"PoI list for day {day_num} must start with previous accommodation."
                    )

        # ---------- Events ----------
        if unit.get("event") and unit["event"] != "-":
            for event in {e.split(",", 1)[0].strip() for e in unit["event"].split(";")}:
                if any(event in poi for poi in poi_entries):
                    # dbg(
                    #     f"Day {day_num} EVENT violation\n"
                    #     f"  Event: {event}\n"
                    #     f"  PoIs: {poi_entries}"
                    # )
                    return False, f"PoI list for day {day_num} should not contain events."

        # ---------- Attractions ----------
        if unit.get("attraction") and unit["attraction"] != "-":
            for attr in {a.split(",", 1)[0].strip() for a in unit["attraction"].split(";")}:
                if not any(attr in poi for poi in poi_entries):
                    # dbg(
                    #     f"Day {day_num} ATTRACTION missing\n"
                    #     f"  Missing: {attr}\n"
                    #     f"  PoIs: {poi_entries}"
                    # )
                    return False, (
                        f"PoI list for day {day_num} does not contain all attractions."
                    )

        # ---------- Meals ----------
        for meal in ["breakfast", "lunch", "dinner"]:
            if unit.get(meal) and unit[meal] != "-":
                meal_base = unit[meal].split(",", 1)[0].strip()
                if not any(meal_base in poi for poi in poi_entries):
                    # dbg(
                    #     f"Day {day_num} MEAL missing\n"
                    #     f"  Meal: {meal}\n"
                    #     f"  Place: {meal_base}\n"
                    #     f"  PoIs: {poi_entries}"
                    # )
                    return False, (
                        f"PoI list for day {day_num} does not contain {meal}."
                    )

        # ---------- Update accommodation ----------
        if curr_acc_base:
            prev_accommodation = curr_acc_base

    return True, None

def is_valid_meal_gaps(question, tested_data):
    """
    Ensures that consecutive meals on the same day have
    at least a 4-hour time gap between them.
    Prints debug info ONLY on failure (max 10 times).
    """

    import re
    time_pattern = re.compile(r'from\s+(\d{2}:\d{2})\s+to\s+(\d{2}:\d{2})')

    # 🔢 static counter across calls
    if not hasattr(is_valid_meal_gaps, "fail_count"):
        is_valid_meal_gaps.fail_count = 0

    for i, day_plan in enumerate(tested_data[:question['days']]):
        day = i + 1
        meal_times = {}

        poi_list = day_plan.get('point_of_interest_list')
        if not poi_list or poi_list == '-':
            continue

        poi_entries = [p.strip() for p in poi_list.split(";") if p.strip()]

        # ---------- Extract meal times (EXACT name match) ----------
        for meal in ['breakfast', 'lunch', 'dinner']:
            meal_name = day_plan.get(meal)
            if not meal_name or meal_name == '-':
                continue

            meal_base = meal_name.split(",", 1)[0].strip()
            found = False

            for poi in poi_entries:
                poi_name = poi.split(",", 1)[0].strip()  # ✅ exact PoI name

                if poi_name == meal_base:
                    match = time_pattern.search(poi)
                    if not match:
                        if is_valid_meal_gaps.fail_count < 10:
                            # print(
                            #     f"\n❌ [MEAL-GAP-FAIL #{is_valid_meal_gaps.fail_count+1}] "
                            #     f"Day {day} | {meal} time format missing\n"
                            #     f"PoI: {poi}"
                            # )
                            is_valid_meal_gaps.fail_count += 1

                        return False, f"Incorrect PoI time format for {meal} on day {day}."

                    start_time, end_time = match.groups()
                    start_hour = int(start_time[:2]) + int(start_time[3:]) / 60
                    end_hour = int(end_time[:2]) + int(end_time[3:]) / 60

                    meal_times[meal] = (start_hour, end_hour)
                    found = True
                    break

            # Meal listed but not found in PoIs
            if not found:
                if is_valid_meal_gaps.fail_count < 10:
                    # print(
                    #     f"\n❌ [MEAL-GAP-FAIL #{is_valid_meal_gaps.fail_count+1}] "
                    #     f"Day {day} | {meal} missing from PoI list\n"
                    #     f"Meal: {meal_name}\n"
                    #     f"PoIs: {poi_entries}"
                    # )
                    is_valid_meal_gaps.fail_count += 1

                return False, f"{meal.title()} is missing from PoI list on day {day}."

        # ---------- Validate time gaps ----------
        ordered_meals = ['breakfast', 'lunch', 'dinner']
        for j in range(len(ordered_meals) - 1):
            m1, m2 = ordered_meals[j], ordered_meals[j + 1]

            if m1 in meal_times and m2 in meal_times:
                _, end1 = meal_times[m1]
                start2, _ = meal_times[m2]
                gap = start2 - end1

                if gap < 4:
                    if is_valid_meal_gaps.fail_count < 10:
                        # print(
                        #     f"\n❌ [MEAL-GAP-FAIL #{is_valid_meal_gaps.fail_count+1}] "
                        #     f"Day {day} | {m1} → {m2}\n"
                        #     f"{m1} ends at {end1:.2f}, {m2} starts at {start2:.2f}\n"
                        #     f"Gap = {gap:.2f} hours (< 4h)"
                        # )
                        # print("FULL DAY PLAN:")
                        # print(day_plan)
                        is_valid_meal_gaps.fail_count += 1

                    return False, (
                        f"Not sufficient time gap between {m1} and {m2} on day {day}."
                    )

    return True, None

def is_valid_transportation(question, tested_data):
    """
    Ensures:
    1. Transportation exists on odd-numbered (travel) days
    2. Transportation modes used across the trip are not conflicting
    """

    transportation_modes = set()

    for idx, unit in enumerate(tested_data[:question['days']]):
        day_number = idx + 1
        value = unit.get('transportation')

        # Odd days are travel days → transportation required
        if day_number % 2 == 1:
            if not value or value == '-':
                return False, f"No transportation provided on travel day {day_number}."

        if value and value != '-':
            mode = transportation_match(value)
            if mode:
                transportation_modes.add(mode)

    # Conflicting combinations
    if 'Self-driving' in transportation_modes and 'Flight' in transportation_modes:
        return False, "The transportation is conflicting (Self-driving + Flight)."

    if 'Self-driving' in transportation_modes and 'Taxi' in transportation_modes:
        return False, "The transportation is conflicting (Self-driving + Taxi)."

    return True, None

def is_valid_information_in_current_city(question, tested_data):
    """
    Ensures that all entities (transportation, meals, attractions, accommodation)
    belong to the city or cities specified in current_city.
    Prints debug info ONLY when validation fails.
    """

    for i, unit in enumerate(tested_data[:question['days']]):
        day = i + 1
        current_city = unit.get('current_city', '')

        # -------- Determine valid cities --------
        valid_cities = []

        city1, city2 = extract_from_to(current_city)
        if city1 and city2:
            valid_cities = [
                extract_before_parenthesis(city1),
                extract_before_parenthesis(city2),
            ]
        else:
            city = extract_before_parenthesis(current_city)
            if city:
                valid_cities = [city]

        valid_cities = [c.lower() for c in valid_cities if c]

        # -------- Transportation --------
        transportation = unit.get('transportation')
        if transportation and transportation != '-':
            transport_lower = transportation.lower()

            if not any(x in transport_lower for x in ['taxi', 'self-driving']):
                if not any(city in transport_lower for city in valid_cities):
                    # print("\n❌ [Within Current City FAILED]")
                    # print(f"Day            : {day}")
                    # print(f"Section        : Transportation")
                    # print(f"Current City   : {current_city}")
                    # print(f"Valid Cities   : {valid_cities}")
                    # print(f"Transportation : {transportation}")
                    # print("\n🔎 FULL DAY INPUT:")
                    # print(unit)
                    # print("--------------------------------------------------")

                    return False, (
                        f"[Day {day}] Transportation city mismatch: {transportation}"
                    )

        # -------- Meals --------
        for meal in ['breakfast', 'lunch', 'dinner']:
            value = unit.get(meal)
            if value and value != '-':
                name, city = get_valid_name_city(value)
                if city.lower() not in valid_cities:
                    # print("\n❌ [Within Current City FAILED]")
                    # print(f"Day          : {day}")
                    # print(f"Section      : {meal.title()}")
                    # print(f"Current City : {current_city}")
                    # print(f"Valid Cities : {valid_cities}")
                    # print(f"{meal.title()}     : {value}")
                    # print(f"Parsed City  : {city}")
                    # print("\n🔎 FULL DAY INPUT:")
                    # print(unit)
                    # print("--------------------------------------------------")

                    return False, (
                        f"[Day {day}] {meal.title()} city mismatch: {value}"
                    )

        # -------- Attractions (FIXED) --------
        if unit.get('attraction') and unit['attraction'] != '-':
            for attraction in unit['attraction'].split(';'):
                attraction = attraction.strip()

                # ✅ FIX: skip empty tokens caused by trailing ';'
                if not attraction:
                    continue

                name, city = get_valid_name_city(attraction)
                if city.lower() not in valid_cities:
                    # print("\n❌ [Within Current City FAILED]")
                    # print(f"Day          : {day}")
                    # print(f"Section      : Attraction")
                    # print(f"Current City : {current_city}")
                    # print(f"Valid Cities : {valid_cities}")
                    # print(f"Attraction   : {attraction}")
                    # print(f"Parsed City  : {city}")
                    # print("\n🔎 FULL DAY INPUT:")
                    # print(unit)
                    # print("--------------------------------------------------")

                    return False, (
                        f"[Day {day}] Attraction city mismatch: {attraction}"
                    )

        # -------- Accommodation --------
        if unit.get('accommodation') and unit['accommodation'] != '-':
            name, city = get_valid_name_city(unit['accommodation'])
            if city.lower() != valid_cities[-1]:
                # print("\n❌ [Within Current City FAILED]")
                # print(f"Day              : {day}")
                # print(f"Section          : Accommodation")
                # print(f"Current City     : {current_city}")
                # print(f"Valid Cities     : {valid_cities}")
                # print(f"Accommodation    : {unit['accommodation']}")
                # print(f"Parsed City      : {city}")
                # print(f"Expected City    : {valid_cities[-1]}")
                # print("\n🔎 FULL DAY INPUT:")
                # print(unit)
                # print("--------------------------------------------------")

                return False, (
                    f"[Day {day}] Accommodation city mismatch: {unit['accommodation']} | "
                    f"Allowed city: {valid_cities[-1]}"
                )

    return True, None
     
def is_valid_information_in_sandbox(question, tested_data):
    """
    Validates that all factual entities exist in the sandbox databases.
    Prints debug info ONLY when validation fails.
    """

    for i, unit in enumerate(tested_data[:question['days']]):
        day = i + 1

        current_city = unit.get('current_city', '')
        org_city, dest_city = extract_from_to(current_city)

        if org_city:
            org_city = extract_before_parenthesis(org_city)
        if dest_city:
            dest_city = extract_before_parenthesis(dest_city)

        # ---------- Transportation ----------
        transportation = unit.get('transportation')
        if transportation and transportation != '-':
            value = transportation.lower()

            if 'flight number' in value:
                try:
                    flight_no = transportation.split('Flight Number:')[1].split(',')[0].strip()
                except Exception:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : Flight format")
                    # print(unit)
                    return False, f"Incorrect flight format in day {day}."

                if not org_city or not dest_city:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : Flight city parse")
                    # print(unit)
                    return False, f"Cannot parse flight cities in day {day}."

                res = flight.data[
                    (flight.data['Flight Number'] == flight_no) &
                    (flight.data['OriginCityName'] == org_city) &
                    (flight.data['DestCityName'] == dest_city)
                ]

                if len(res) < 1:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : Flight DB lookup")
                    # print(unit)
                    return False, f"The flight number in day {day} is invalid in the sandbox."

            elif 'self-driving' in value or 'taxi' in value:
                if not org_city or not dest_city:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : Ground transport city parse")
                    # print(unit)
                    return False, f"Cannot parse transportation cities in day {day}."

                mode = 'self-driving' if 'self-driving' in value else 'taxi'
                cost = googleDistanceMatrix.run_for_evaluation(org_city, dest_city, mode=mode)['cost']
                # print(cost,org_city,dest_city,mode)

                if cost is None:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : Ground transport DB")
                    # print(unit)
                    return False, f"The {mode} in day {day} is invalid in the sandbox."

        # ---------- Restaurants ----------
        for meal in ['breakfast', 'lunch', 'dinner']:
            if meal in unit and unit[meal] and unit[meal] != '-':
                name, city = get_valid_name_city(unit[meal])
                res = restaurants.data[
                    (restaurants.data['name'].astype(str).str.contains(re.escape(name))) &
                    (restaurants.data['City'] == city)
                ]

                if len(res) < 1:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print(f"Section : {meal.title()}")
                    # print(unit)
                    return False, f"The {meal} in day {day} is invalid in the sandbox."

        # ---------- Attractions ----------
        if unit.get('attraction') and unit['attraction'] != '-':
            for attraction in unit['attraction'].split(';'):
                attraction = attraction.strip()
                if not attraction:
                    continue

                name, city = get_valid_name_city(attraction)
                res = attractions.data[
                    (attractions.data['name'].astype(str).str.contains(re.escape(name))) &
                    (attractions.data['City'] == city)
                ]

                if len(res) < 1:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : Attraction")
                    # print(unit)
                    return False, f"The attraction {attraction} in day {day} is invalid in the sandbox."

        # ---------- Events ----------
        if unit.get('event') and unit['event'] != '-':
            for event in unit['event'].split(';'):
                event = event.strip()
                if not event:
                    continue

                name = event.rsplit(',', 1)[0].strip()
                city = event.rsplit(',', 1)[-1].strip().lower()

                # ✅ strict name + city match (normalized)
                res = events.data[
                    (events.data['name'].astype(str).str.strip() == name) &
                    (events.data['city'].astype(str).str.strip().str.lower() == city)
                ]

                if len(res) < 1:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print("Day     :", day)
                    # print("Section : Event")
                    # print("Event name from plan :", name)
                    # print("Event city from plan :", city)

                    # print("\nEvents available in this city:")
                    # print(
                    #     events.data[
                    #         events.data['city'].astype(str).str.strip().str.lower() == city
                    #     ][['name', 'dateTitle', 'streetAddress', 'city']].head(20)
                    # )

                    # print("\nTop name matches across DB:")
                    # print(
                    #     events.data[
                    #         events.data['name']
                    #         .astype(str)
                    #         .str.contains(re.escape(name), case=False, na=False)
                    #     ][['name', 'dateTitle', 'streetAddress', 'city']].head(20)
                    # )

                    # print("=============================================\n")

                    return False, (
                        f"The event '{event}' in day {day} is invalid in the sandbox."
                    )

        # ---------- Accommodation ----------
        if unit.get('accommodation') and unit['accommodation'] != '-':
            name, city = get_valid_name_city(unit['accommodation'])
            # print(name,city)
            res = accommodation.data[
                (accommodation.data['name'].astype(str).str.contains(re.escape(name))) &
                (accommodation.data['City'] == city)
            ]

            if len(res) < 1:
                # print("\n❌ [SANDBOX FAILED]")
                # print(f"Day     : {day}")
                # print("Section : Accommodation")
                # print(unit)
                return False, f"The accommodation in day {day} is invalid in the sandbox."

        # ---------- PoI Nearest Transit (CORRECT CITY LOGIC) ----------
        if unit.get('point_of_interest_list') and unit['point_of_interest_list'] != '-':
            for poi in unit['point_of_interest_list'].split(';'):
                if 'nearest transit:' not in poi:
                    continue

                try:
                    transit_info = poi.split('nearest transit:')[1].strip()
                    poi_name = poi.split('nearest transit:')[0].strip()[:-1].rsplit(',', 1)[0].strip()
                    transit_stop = transit_info.rsplit(',', 1)[0].strip()
                    stop_distance = float(
                        transit_info.rsplit(',', 1)[-1].replace('m away', '').strip()
                    )
                except Exception:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : PoI format")
                    # print(unit)
                    return False, f"Incorrect PoI format in day {day}."

                # ✅ Correct city logic
                allowed_cities = set()

                if org_city and dest_city:
                    if day == 1:
                        allowed_cities.add(dest_city)
                    elif day == question['days']:
                        allowed_cities.add(org_city)
                    else:
                        allowed_cities.add(org_city)
                        allowed_cities.add(dest_city)
                else:
                    city = extract_before_parenthesis(current_city)
                    if city:
                        allowed_cities.add(city)

                if not allowed_cities:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : PoI city resolve")
                    # print(unit)
                    return False, f"Cannot determine city for PoI in day {day}."

                res = pois[
                    (pois['nearest_stop_name'].astype(str).str.contains(re.escape(transit_stop))) &
                    (pois['PoI'] == poi_name) &
                    (pois['City'].isin(allowed_cities)) &
                    (abs(pois['nearest_stop_distance'] - stop_distance) <= 5)
                ]

                if len(res) < 1:
                    # print("\n❌ [SANDBOX FAILED]")
                    # print(f"Day     : {day}")
                    # print("Section : PoI nearest transit")
                    # print(unit)
                    return False, f"The PoI nearest stops in day {day} have hallucinated data."

    return True, None

def is_valid_accommodation(question, tested_data):
    """
    Validates whether consecutive stays at the same accommodation
    respect the minimum nights rule defined in the database.
    """

    accommodations = []

    for i, unit in enumerate(tested_data[:question['days']]):
        if 'accommodation' not in unit:
            return False, "No accommodation information."

        accommodations.append(unit['accommodation'])

    consecutive_stays = count_consecutive_values(accommodations)

    for acc_name, stay_len in consecutive_stays:
        if not acc_name or acc_name in ['-', '']:
            continue

        try:
            name, city = get_valid_name_city(acc_name)
        except Exception:
            continue

        if not name or not city:
            continue

        res = accommodation.data[
            (accommodation.data['name'].astype(str).str.contains(re.escape(name))) &
            (accommodation.data['City'] == city)
        ]

        # Only validate if uniquely identified
        if len(res) == 1:
            min_nights = res.iloc[0].get('minimum nights')
            if min_nights is not None and stay_len < min_nights:
                return (
                    False,
                    f"The accommodation {acc_name} does not obey the minimum nights rule."
                )

    return True, None

def is_valid_visiting_city_number(question, tested_data):
    """
    Checks whether the number of unique visiting cities (excluding origin)
    matches question['visiting_city_number'].
    """

    city_set = set()

    for i, unit in enumerate(tested_data[:question['days']]):
        city_value = unit.get('current_city')
        if not city_value:
            continue

        city_value_lower = city_value.lower()

        if 'from ' in city_value_lower and ' to ' in city_value_lower:
            city1, city2 = extract_from_to(city_value)
            if not city1 or not city2:
                return False, f"Cannot parse city transition on day {i+1}."

            city1 = extract_before_parenthesis(city1)
            city2 = extract_before_parenthesis(city2)

            if i == 0 and city1 != question['org']:
                return False, f"The first day's city should be {question['org']}."

            city_set.add(city1)
            city_set.add(city2)

        else:
            city = extract_before_parenthesis(city_value)
            if city:
                city_set.add(city)

    # Remove origin city
    city_set.discard(question['org'])

    if len(city_set) != question['visiting_city_number']:
        return False, f"The number of visiting cities should be {question['visiting_city_number']}."

    return True, None

def is_valid_days(question, tested_data):
    """
    Checks whether the number of valid plan days exactly matches question['days'].
    """

    valid_days = 0

    for unit in tested_data[:question['days']]:
        if isinstance(unit, dict) and unit.get('current_city'):
            valid_days += 1

    if valid_days != question['days']:
        return False, f"The number of days should be {question['days']}."

    return True, None

def is_not_absent(question, tested_data):
    """
    Debug-enabled version.
    Prints EXACT reason + full plan when failure occurs.
    """

    REQUIRED_KEYS = [
        'transportation',
        'breakfast',
        'lunch',
        'dinner',
        'attraction',
        'accommodation',
        'event',
        'point_of_interest_list'
    ]

    needed_info = len(REQUIRED_KEYS) * question['days']
    total_valid_info = 0

    def dbg(msg, day=None, unit=None):
        print("\n❌ [COMPLETE-INFORMATION-FAIL]")
        if day is not None:
            print(f"Day    : {day}")
        print(f"Reason : {msg}")
        if unit is not None:
            print("\n🔎 FULL DAY PLAN:")
            print(unit)
        print("--------------------------------------------------")

    # ---------- Global checks ----------
    ok, msg = is_valid_days(question, tested_data)
    if not ok:
        # dbg(msg)
        return False, msg

    ok, msg = is_valid_visiting_city_number(question, tested_data)
    if not ok:
        # dbg(msg)
        return False, msg

    # ---------- Per-day checks ----------
    for i in range(min(question['days'], len(tested_data))):
        day = i + 1
        unit = tested_data[i]

        # Required keys
        for key in REQUIRED_KEYS:
            if key not in unit:
                # dbg(f"Missing key: {key}", day, unit)
                return False, f"No {key.replace('_', ' ').title()} info."

        # Transit distance sanity
        poi_list = unit.get('point_of_interest_list')
        if poi_list and poi_list != '-':
            for poi in poi_list.split(";"):
                if "nearest transit:" in poi:
                    transit_info = poi.split("nearest transit:")[1].strip()
                    if "," in transit_info:
                        dist = transit_info.rsplit(",", 1)[-1].replace("m away", "").strip()
                        if not dist or dist == '-':
                            # dbg("Missing nearest transit distance", day, unit)
                            return False, "No transit stop distance mentioned."

        # Travel day → transportation required
        if ('from ' in unit['current_city'] or 'to ' in unit['current_city']):
            if unit['transportation'] in ['', '-']:
                # dbg("Travel day without transportation", day, unit)
                return False, f"No transportation in day {day} is not allowed."

        # Non-travel day → attraction required
        if ('from ' not in unit['current_city'] and ' to ' not in unit['current_city']):
            if unit['attraction'] in ['', '-']:
                # dbg("Non-travel day without attraction", day, unit)
                return False, f"No attraction in day {day} is not allowed."

        # Accommodation required except final day
        if day != question['days'] and unit['accommodation'] in ['', '-']:
            # dbg("Missing accommodation on non-final day", day, unit)
            return False, f"No accommodation in day {day} is not allowed."

        # Meals required on non-travel days
        if 'from ' not in unit['current_city']:
            for meal in ['breakfast', 'lunch', 'dinner']:
                if unit[meal] in ['', '-']:
                    # dbg(f"Missing {meal}", day, unit)
                    return False, f"No meal in day {day} is not allowed."

        # PoI list must exist
        if unit['point_of_interest_list'] in ['', '-']:
            # dbg("Empty PoI list", day, unit)
            return False, "Point of Interest list cannot be empty."

        # Count valid info
        for key in REQUIRED_KEYS:
            if unit[key] and unit[key] != '-':
                total_valid_info += 1

    # ---------- Overall completeness ----------
    ratio = total_valid_info / needed_info
    if ratio < 0.5:
        # dbg(f"Only {ratio:.2f} of required information present (< 0.5)")
        return False, "The absent information is more than 50%."

    return True, None

def evaluation(query_data, tested_data):
    return_info = {}
    return_info['is_reasonable_visiting_city'] = is_reasonable_visiting_city(query_data, tested_data)
    return_info['is_valid_restaurants'] = is_valid_restaurants(query_data, tested_data)
    return_info['is_valid_attractions'] = is_valid_attractions(query_data, tested_data)
    # return_info['is_valid_accommodation'] = is_valid_accommodaton(query_data, tested_data)
    return_info['is_valid_transportation'] = is_valid_transportation(query_data, tested_data)
    return_info['is_valid_event'] = is_valid_event(query_data, tested_data) 
    return_info['is_valid_meal_gaps'] = is_valid_meal_gaps(query_data, tested_data)
    return_info['is_valid_poi_sequence'] = is_valid_poi_sequence(query_data, tested_data)
    return_info['is_valid_information_in_sandbox'] = is_valid_information_in_sandbox(query_data, tested_data) 
    return_info['is_valid_information_in_current_city'] = is_valid_information_in_current_city(query_data, tested_data) 
    return_info['is_not_absent'] = is_not_absent(query_data, tested_data)  
    return return_info

def boolean_evaluation(query_data, tested_data):
    return_info = {}
    return_info['is_reasonable_visiting_city'] = is_reasonable_visiting_city(query_data, tested_data)
    return_info['is_valid_restaurants'] = is_valid_restaurants(query_data, tested_data)
    # return_info['is_valid_accommodation'] = is_valid_accommodaton(query_data, tested_data)
    return_info['is_valid_attractions'] = is_valid_attractions(query_data, tested_data)
    return_info['is_valid_transportation'] = is_valid_transportation(query_data, tested_data)
    return_info['is_valid_information_in_current_city'] = is_valid_information_in_current_city(query_data, tested_data)
    return_info['is_valid_information_in_sandbox'] = is_valid_information_in_sandbox(query_data, tested_data)
    return_info['is_not_absent'] = is_not_absent(query_data, tested_data)
    for key in return_info:
        if return_info[key][0] == False:
            print(return_info[key][1])
            return False
    return True

