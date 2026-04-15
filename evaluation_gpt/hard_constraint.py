# /scratch/sg/Vijay/TripCraft/evaluation/hard_constraint.py
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
import numpy as np
import os
import sys
from tqdm import tqdm
import argparse

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))
os.chdir(os.path.dirname(os.path.abspath(__file__)))


flight = Flights()
accommodation = Accommodations()
restaurants = Restaurants()
googleDistanceMatrix = GoogleDistanceMatrix()
attractions = Attractions()
events = Events()


def load_line_json_data(filename):
    data = []
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data.append(json.loads(line))
    return data

def convert_bool_values(item):
    if isinstance(item, dict):
        # If the item is a dictionary, recurse on each value
        return {key: convert_bool_values(value) for key, value in item.items()}
    elif isinstance(item, list):
        # If the item is a list, recurse on each item in the list
        return [convert_bool_values(value) for value in item]
    elif isinstance(item, tuple):
        # If the item is a tuple, recurse on each item in the tuple and repackage as a tuple
        return tuple(convert_bool_values(value) for value in item)
    elif isinstance(item, np.bool_):  # Here we check for numpy's bool_ type
        # If the item is a numpy bool_, convert it to a standard Python bool
        return bool(item)
    else:
        # If the item is any other type, return it unchanged
        return item

def extract_from_to(text: str):
    """
    Extracts source and destination cities from strings of the form:
    'from A to B'

    Returns (None, None) if the pattern is not explicitly present.
    """
    if not text or 'from ' not in text.lower() or ' to ' not in text.lower():
        return None, None

    pattern = r"\bfrom\s+([^,]+?)\s+\bto\s+([^,]+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)

    if not match:
        return None, None

    src = match.group(1).strip()
    dst = match.group(2).strip()
    return src, dst

def get_total_cost(question, tested_data):
    total_cost = 0
    people = question['people_number']

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]

        # ---------------- Transportation ----------------
        value = unit.get('transportation')
        if value and value != '-':
            org_city, dest_city = extract_from_to(value)
            if org_city is None or dest_city is None:
                org_city, dest_city = extract_from_to(unit.get('current_city', ''))

            if org_city and dest_city:
                value_l = value.lower()

                if 'flight' in value_l:
                    try:
                        flight_no = value.split('Flight Number:')[1].split(',')[0].strip()
                        res = flight.data[flight.data['Flight Number'] == flight_no]
                        if len(res) > 0:
                            total_cost += res.iloc[0]['Price'] * people
                    except:
                        pass

                elif 'self-driving' in value_l:
                    cost = googleDistanceMatrix.run_for_evaluation(org_city, dest_city, 'self-driving')['cost']
                    if cost:
                        total_cost += cost * math.ceil(people / 5)

                elif 'taxi' in value_l:
                    cost = googleDistanceMatrix.run_for_evaluation(org_city, dest_city, 'taxi')['cost']
                    if cost:
                        total_cost += cost * math.ceil(people / 4)

        # ---------------- Meals (count exactly if present) ----------------
        for meal in ['breakfast', 'lunch', 'dinner']:
            place = unit.get(meal)
            if place and place != '-':
                name, city = get_valid_name_city(place)
                res = restaurants.data[
                    (restaurants.data['name'].astype(str).str.contains(re.escape(name), case=False)) &
                    (restaurants.data['City'] == city)
                ]
                if len(res) > 0:
                    total_cost += res.iloc[0]['avg_cost'] * people

        # ---------------- Accommodation (PLAN-ONLY COUNT) ----------------
        acc = unit.get('accommodation')
        if acc and acc != '-':
            name, city = get_valid_name_city(acc)
            res = accommodation.data[
                (accommodation.data['name'].astype(str).str.contains(re.escape(name), case=False)) &
                (accommodation.data['City'] == city)
            ]

            if len(res) > 0:
                row = res.iloc[0]
                pricing = row.get('pricing', {})

                if isinstance(pricing, str):
                    try:
                        pricing = json.loads(pricing)
                    except:
                        pricing = {}

                price_str = pricing.get('price', '').replace('$', '').strip()
                if price_str:
                    price = float(price_str)
                    max_occ = row.get('max_occupancy', 1)
                    rooms = math.ceil(people / max_occ)

                    # ✅ EXACTLY ONE COUNT PER DAY (as per plan)
                    total_cost += price * rooms

    return total_cost

def is_valid_room_rule(question, tested_data):
    """
    Checks whether accommodation house rules satisfy the user's constraint.
    If a house rule is specified, ALL accommodations must allow it.
    Prints debug info when a violation is found.
    """

    rule = question['local_constraint'].get('house rule')
    if rule is None:
        return None, None

    rule = rule.lower()

    # Mapping from user rule → forbidden phrases
    forbidden_map = {
        'smoking': ['no smoking', 'smoking not allowed', 'smoking prohibited'],
        'parties': ['no parties', 'parties not allowed', 'no events'],
        'children under 10': ['no children', 'no kids', 'children not allowed'],
        'visitors': ['no visitors', 'visitors not allowed'],
        'pets': ['no pets', 'pets not allowed']
    }

    forbidden_phrases = forbidden_map.get(rule, [])

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]
        day = i + 1

        acc = unit.get('accommodation')
        if not acc or acc == '-':
            continue

        name, city = get_valid_name_city(acc)
        res = accommodation.data[
            (accommodation.data['name']
                .astype(str)
                .str.contains(re.escape(name), case=False)) &
            (accommodation.data['City'] == city)
        ]

        if len(res) == 0:
            continue

        for _, row in res.iterrows():
            house_rules = str(row.get('house_rules', '')).lower()

            for phrase in forbidden_phrases:
                if phrase in house_rules:
                    # print("\n❌ [ROOM-RULE-FAIL]")
                    # print(f"Day           : {day}")
                    # print(f"Required rule : {rule}")
                    # print(f"Forbidden text: '{phrase}'")
                    # print(f"Accommodation : {acc}")
                    # print(f"House rules   : {house_rules}")
                    # print("Full day plan :")
                    # print(unit)

                    return False, f"The house rule should be {rule}."

    return True, None

def is_valid_cuisine(question, tested_data):
    """
    Checks whether required cuisines are satisfied.
    A cuisine is satisfied if at least one restaurant
    in the plan serves that cuisine.
    """

    import re
    import ast

    required = question['local_constraint'].get('cuisine')
    if required is None:
        return None, None

    if isinstance(required, str):
        required = [required]

    required = [r.strip().lower() for r in required]
    satisfied = set()

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]

        for meal in ['breakfast', 'lunch', 'dinner']:
            place = unit.get(meal)
            if not place or place == '-':
                continue

            name, city = get_valid_name_city(place)

            # Skip origin city meals
            if city == question['org']:
                continue

            res = restaurants.data[
                (restaurants.data['name']
                    .astype(str)
                    .str.contains(re.escape(name), case=False)) &
                (restaurants.data['City'] == city)
            ]

            if len(res) == 0:
                continue

            for _, row in res.iterrows():
                cuisines = row.get('cuisines', [])

                # Parse stringified list correctly
                if isinstance(cuisines, str):
                    try:
                        cuisines = ast.literal_eval(cuisines)
                    except Exception:
                        cuisines = []

                cuisines = [
                    c.strip().lower()
                    for c in cuisines
                    if isinstance(c, str)
                ]

                for r in required:
                    if r in cuisines:
                        satisfied.add(r)

    if len(satisfied) == len(required):
        return True, None

    for r in required:
        if r not in satisfied:
            return False, f"The cuisine {r} is not satisfied."

    return True, None
 
def is_valid_attraction_type(question, tested_data):
    """
    Checks whether required attraction types are satisfied.
    A required attraction type is satisfied if at least one
    non-origin-city attraction in the plan belongs to that type.

    Debug prints ONLY on failure (max 10 times).
    """

    import re
    import ast

    required = question['local_constraint'].get('attraction')
    if required is None:
        return None, None

    if isinstance(required, str):
        required = [required]

    required = [r.strip().lower() for r in required]
    satisfied = set()

    # 🔢 static failure counter
    if not hasattr(is_valid_attraction_type, "fail_count"):
        is_valid_attraction_type.fail_count = 0

    # ---------- MAIN LOGIC ----------
    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]

        if not unit.get('attraction') or unit['attraction'] == '-':
            continue

        for attraction in unit['attraction'].split(';'):
            attraction = attraction.strip()
            if not attraction:
                continue

            name, city = get_valid_name_city(attraction)

            # ❌ Skip origin city attractions
            if city == question['org']:
                continue

            res = attractions.data[
                (attractions.data['name']
                    .astype(str)
                    .str.contains(re.escape(name), case=False)) &
                (attractions.data['City'] == city)
            ]

            if len(res) == 0:
                continue

            for _, row in res.iterrows():
                subcats = row.get('subcategories', [])

                # ✅ FIX: parse stringified list properly
                if isinstance(subcats, str):
                    try:
                        subcats = ast.literal_eval(subcats)
                    except Exception:
                        subcats = []

                subcats = [s.strip().lower() for s in subcats if isinstance(s, str)]

                for r in required:
                    if r in subcats:
                        satisfied.add(r)

    # ---------- FAILURE DEBUG ----------
    if len(satisfied) != len(required):
        if is_valid_attraction_type.fail_count < 10:
            # print("\n❌ [ATTRACTION-TYPE-FAIL]")
            # print("Required types :", required)
            # print("Satisfied types:", sorted(satisfied))
            # print("Origin city    :", question['org'])
            # print("--------------- Attractions seen ---------------")

            for i in range(min(question['days'], len(tested_data))):
                unit = tested_data[i]
                day = i + 1

                if not unit.get('attraction') or unit['attraction'] == '-':
                    continue

                for attraction in unit['attraction'].split(';'):
                    attraction = attraction.strip()
                    if not attraction:
                        continue

                    name, city = get_valid_name_city(attraction)

                    if city == question['org']:
                        # print(f"[Day {day}] {name} ({city}) → SKIPPED (origin city)")
                        continue

                    res = attractions.data[
                        (attractions.data['name']
                            .astype(str)
                            .str.contains(re.escape(name), case=False)) &
                        (attractions.data['City'] == city)
                    ]

                    if len(res) == 0:
                        # print(f"[Day {day}] {name} ({city}) → NOT FOUND IN DB")
                        continue

                    for _, row in res.iterrows():
                        subcats = row.get('subcategories', [])
                        if isinstance(subcats, str):
                            try:
                                subcats = ast.literal_eval(subcats)
                            except Exception:
                                subcats = []

                        # print(
                        #     f"[Day {day}] {name} ({city}) → "
                        #     f"DB subcategories: {subcats}"
                        # )

            # print("-----------------------------------------------")
            is_valid_attraction_type.fail_count += 1

        for r in required:
            if r not in satisfied:
                return False, f"The attraction type {r} is not satisfied."

    return True, None
     
def is_valid_event_type(question, tested_data):
    """
    Checks whether required event types are satisfied.
    A required event type is satisfied if at least one event
    in the plan matches that segment type.
    """
    required = question['local_constraint'].get('event')
    if required is None:
        return None, None

    if isinstance(required, str):
        required = [required]

    required = [r.lower() for r in required]
    satisfied = set()

    # cache events per city to avoid repeated API calls
    event_cache = {}

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]

        if not unit.get('event') or unit['event'] == '-':
            continue

        for event in unit['event'].split(';'):
            name = event.rsplit(',', 1)[0].strip()
            city = event.rsplit(',', 1)[-1].strip()
            dates = question['dates']

            if city not in event_cache:
                event_cache[city] = events.run(city, dates)

            event_data = event_cache[city]
            if event_data is None or len(event_data) == 0:
                continue

            matches = event_data[
                event_data['name'].astype(str).str.contains(re.escape(name), case=False)
            ]

            for _, row in matches.iterrows():
                segment = str(row.get('segmentName', '')).lower()
                if segment in required:
                    satisfied.add(segment)

    if len(satisfied) == len(required):
        return True, None

    for r in required:
        if r not in satisfied:
            return False, f"The event type {r} is not satisfied."

    return True, None

def is_valid_transportation(question, tested_data):
    """
    Checks whether transportation satisfies the user's local transportation constraint.
    Prints debug info ONLY on failure (max 10 times).
    Returns (None, None) if the constraint is not applicable.
    """

    constraint = question['local_constraint'].get('transportation')
    if constraint is None:
        return None, None

    constraint = constraint.lower()

    # 🔢 static failure counter
    if not hasattr(is_valid_transportation, "fail_count"):
        is_valid_transportation.fail_count = 0

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]
        day = i + 1

        value = unit.get('transportation')
        if not value or value == '-':
            continue

        value_l = value.lower()

        # ---------- FAILURE: no flight ----------
        if constraint == 'no flight' and 'flight' in value_l:
            if is_valid_transportation.fail_count < 10:
                # print("\n❌ [TRANSPORTATION-FAIL]")
                # print(f"Day            : {day}")
                # print(f"Constraint     : {constraint}")
                # print(f"Transportation : {value}")
                # print("Reason         : Flight is not allowed")
                # print("Full day plan  :")
                # print(unit)
                is_valid_transportation.fail_count += 1

            return False, "The transportation should not be flight."

        # ---------- FAILURE: no self-driving (taxi counts) ----------
        if constraint == 'no self-driving' and (
            'self-driving' in value_l or 'taxi' in value_l
        ):
            if is_valid_transportation.fail_count < 10:
                # print("\n❌ [TRANSPORTATION-FAIL]")
                # print(f"Day            : {day}")
                # print(f"Constraint     : {constraint}")
                # print(f"Transportation : {value}")
                # print("Reason         : Self-driving / Taxi is not allowed")
                # print("Full day plan  :")
                # print(unit)
                is_valid_transportation.fail_count += 1

            return False, "The transportation should not be self-driving or taxi."

    return True, None

def is_valid_room_type(question, tested_data):
    """
    Checks whether the accommodation room type satisfies the user's local constraint.
    Prints debug info ONLY on failure (max 10 times).
    Returns (None, None) if the constraint is not applicable.
    """

    required_type = question['local_constraint'].get('room type')
    if required_type is None:
        return None, None

    required_type = required_type.lower()

    # 🔢 static failure counter
    if not hasattr(is_valid_room_type, "fail_count"):
        is_valid_room_type.fail_count = 0

    for i in range(min(question['days'], len(tested_data))):
        unit = tested_data[i]
        day = i + 1

        acc = unit.get('accommodation')
        if not acc or acc == '-':
            continue

        name, city = get_valid_name_city(acc)
        res = accommodation.data[
            (accommodation.data['name']
                .astype(str)
                .str.contains(re.escape(name), case=False)) &
            (accommodation.data['City'] == city)
        ]

        if len(res) == 0:
            # Let sandbox constraint handle invalid accommodation
            continue

        room_type = res.iloc[0]['roomType']

        # ---------- FAILURE CASES ----------
        violated = False
        reason = ""

        if required_type == 'not shared room' and room_type == 'shared_room':
            violated = True
            reason = "Shared room found but shared rooms are not allowed."

        elif required_type == 'shared room' and room_type != 'shared_room':
            violated = True
            reason = f"Room type is '{room_type}', expected 'shared_room'."

        elif required_type == 'private room' and room_type != 'private_room':
            violated = True
            reason = f"Room type is '{room_type}', expected 'private_room'."

        elif required_type == 'entire room' and room_type != 'entire_room':
            violated = True
            reason = f"Room type is '{room_type}', expected 'entire_room'."

        if violated:
            if is_valid_room_type.fail_count < 10:
                # print("\n❌ [ROOM-TYPE-FAIL]")
                # print(f"Day            : {day}")
                # print(f"Required type  : {required_type}")
                # print(f"Accommodation  : {acc}")
                # print(f"DB room type   : {room_type}")
                # print(f"Reason         : {reason}")
                # print("Full day plan  :")
                # print(unit)
                is_valid_room_type.fail_count += 1

            return False, f"The room type should be {required_type}."

    return True, None

def evaluation(query_data, tested_data):
    """
    Evaluate all hard constraints.
    Each constraint returns (bool | None, message | None).
    None means the constraint is not applicable and should not be counted.
    """
    return {
        'valid_cuisine': is_valid_cuisine(query_data, tested_data),
        'valid_room_rule': is_valid_room_rule(query_data, tested_data),
        'valid_transportation': is_valid_transportation(query_data, tested_data),
        'valid_room_type': is_valid_room_type(query_data, tested_data),
        'valid_attraction_type': is_valid_attraction_type(query_data, tested_data),
        'valid_event_type': is_valid_event_type(query_data, tested_data),
        'valid_cost': (
            get_total_cost(query_data, tested_data) <= query_data['budget'],
            None
        )
    }

def boolean_evaluation(query_data, tested_data):
    """
    Returns True if no hard constraint is violated.
    Returns False immediately on the first hard constraint violation.
    Constraints returning (None, None) are treated as not applicable.
    """
    checks = [
        is_valid_cuisine,
        is_valid_room_rule,
        is_valid_transportation,
        is_valid_room_type,
        # lambda q, t: (get_total_cost(q, t) <= q['budget'], None)
    ]

    for check in checks:
        result, _ = check(query_data, tested_data)
        if result is False:
            return False

    return True
