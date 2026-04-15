# agentic_trip/agents/accommodationagent.py

import json
import re
import os
import math
import csv
import ast
from typing import Any, Dict, List, Optional


class AccommodationAgent:

    def __init__(self, llm):
        self.llm = llm

    # ----------------------------------------------------------
    # Extract JSON safely from LLM output
    # ----------------------------------------------------------
    @staticmethod
    def normalize_accommodations(raw_list: List[str], city: str) -> List[Dict]:
        normalized = []

        for block in raw_list:
            if not isinstance(block, str):
                continue

            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue

                # skip header
                if line.lower().startswith("name"):
                    continue

                # remove emojis / non-ascii
                line = re.sub(r"[^\x00-\x7F]+", " ", line)

                parts = line.split()
                if len(parts) < 7:
                    continue

                try:
                    # ---- RIGHT-SIDE PARSING (CORRECT) ----
                    room_type = parts[-6]

                    price_token = parts[-5]
                    price = math.inf if price_token == "N/A" else float(price_token.replace("$", ""))

                    max_occupancy = int(parts[-4])

                    rating_token = parts[-3]
                    rating = None if rating_token == "N/A" else float(rating_token)

                    house_rules = " ".join(parts[-2:])

                    name = " ".join(parts[:-6]).strip()

                except Exception:
                    continue

                normalized.append({
                    "name": name,
                    "price_per_night": price,
                    "room_type": room_type,
                    "house_rules": house_rules,
                    "minimum_nights": 1,     # ✅ DEFAULT (as you requested)
                    "maximum_occupancy": max_occupancy,
                    "review_rate": rating,
                    "city": city
                })

        return normalized

    def extract_json(self, text: str) -> Dict[str, Any]:
        if not text or not isinstance(text, str):
            return {}

        stack = []
        start = None

        for i, ch in enumerate(text):
            if ch == "{":
                if start is None:
                    start = i
                stack.append("{")
            elif ch == "}":
                if stack:
                    stack.pop()
                    if not stack:  # completed JSON block
                        block = text[start:i + 1]
                        try:
                            return json.loads(block)
                        except Exception:
                            # continue scanning
                            start = None
        return {}

    def get_accommodations_for_city(
            self,
        city: str,
        max_results: int = 20
    ) -> List[Dict]:
        """
        Retrieve and preprocess accommodations for a given city.

        Responsibilities:
        - Read from CSV
        - Filter by city
        - Normalize pricing / rating / coordinates
        - Drop invalid or unusable rows
        - Return top-N cheapest valid accommodations

        NO persona logic.
        NO house-rule interpretation.
        NO selection decisions.
        """
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        CSV_PATH = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/accommodation/cleaned_listings_final_v2.csv"
            )
        )

        results = []

        city = city.strip().lower()

        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                if not row.get("City"):
                    continue

                if row["City"].strip().lower() != city:
                    continue

                # ---- Parse pricing ----
                pricing = row.get("pricing")
                try:
                    pricing_dict = ast.literal_eval(pricing)
                    price_str = pricing_dict.get("price")
                    if not price_str:
                        continue
                    price = float(price_str.replace("$", ""))
                except Exception:
                    continue

                # ---- Parse rating ----
                rating = None
                try:
                    rating_dict = ast.literal_eval(row.get("rating", ""))
                    rating = rating_dict.get("average")
                except Exception:
                    continue

                # ---- Parse coordinates ----
                try:
                    coord_dict = ast.literal_eval(row.get("coordinates", ""))
                    latitude = coord_dict.get("latitude")
                    longitude = coord_dict.get("longitude")
                except Exception:
                    latitude = None
                    longitude = None

                # ---- Max occupancy ----
                try:
                    max_occ = int(row.get("max_occupancy"))
                except Exception:
                    continue

                results.append({
                    "name": row.get("name"),
                    "price_per_night": price,
                    "room_type": row.get("roomType"),
                    "house_rules": row.get("house_rules"),
                    "minimum_nights": 1,            # default
                    "maximum_occupancy": max_occ,
                    "review_rate": rating,
                    # "latitude": latitude,
                    # "longitude": longitude,
                    "city": row.get("City"),
                    # "state": row.get("State"),
                    # "url": row.get("url"),
                    # "id": row.get("id"),
                })

        # ---- Final sanity filtering ----
        results = [
            h for h in results
            if h.get("price_per_night") not in (None, math.inf)
        ]

        # ---- Sort cheapest first ----
        results.sort(key=lambda h: h["price_per_night"])

        return results[:max_results]
   
    # ----------------------------------------------------------
    # Build Prompt
    # ----------------------------------------------------------
    def build_prompt(
        self,
        accommodation_ref,
        persona,
        trip_json,
        local_constraints,
        nights,
        caps: Optional[Dict[str, Any]] = None
    ) -> str:

        caps_text = ""
        if caps:
            caps_text = f"\nBUDGET CAPS: {json.dumps(caps, indent=2)}\n"

        prompt = f"""
You are the ACCOMMODATION SELECTION AGENT.

Your task:
- Select EXACTLY ONE hotel from accommodation_ref.
- You MUST select an EXACT hotel object (no modifying fields, no hallucinated values).
- DO NOT select any hotel requiring more nights than the trip has.
- Choose the CHEAPEST valid option.
- Trip nights = 2

{caps_text}

====================================================
ACCOMMODATION OPTIONS (already filtered):
====================================================
{json.dumps(accommodation_ref, indent=2)}

====================================================
PERSONA:
====================================================
{json.dumps(persona, indent=2)}

- Do NOT take budget from persona.

IMPORTANT (STRICT HOUSE & ROOM RULE ENFORCEMENT):
----------------------------------------------------
Any accommodation selected MUST fully comply with
ALL house-rule AND room-related constraints mentioned in:

- persona
- local_constraints
- query intent

This includes (but is NOT limited to):

HOUSE RULES (STRICT):
- children allowed / children under 10
- pets allowed / no pets
- smoking restrictions
- visitor restrictions
- party restrictions

ROOM TYPE RULES (STRICT):
- If local_constraints specify a room type (e.g. entire home, private room, shared room, not shared room),
  the selected hotel MUST match that room type.
- If a hotel’s room_type conflicts with the room type mentioned in local_constraints,
  that hotel MUST NOT be selected.
- Room type rules are HARD CONSTRAINTS, not preferences.

***If ANY house rule or room type constraint is violated, that accommodation MUST be rejected under ALL circumstances.***
====================================================
LOCAL CONSTRAINTS:
====================================================
{json.dumps(local_constraints, indent=2)}

====================================================
STRICT OUTPUT FORMAT:
====================================================
{{
  "hotel": {{
      ... EXACT hotel object from accommodation_ref ...
  }}
}}

NO explanation.
NO markdown.
ONLY pure JSON.
"""
        
        return prompt
    
    def build_upgrade_prompt(
        self,
        accommodation_ref,
        persona,
        trip_json,
        local_constraints,
        nights,
        caps: Optional[Dict[str, Any]] = None
    ) -> str:

        caps_text = ""
        if caps:
            caps_text = f"\nBUDGET CAPS: {json.dumps(caps, indent=2)}\n"

        prompt = f"""
You are the ACCOMMODATION SELECTION AGENT.

Your task:
- Select EXACTLY ONE hotel from accommodation_ref.
- You MUST select an EXACT hotel object (no modifying fields, no hallucinated values).
- DO NOT select any hotel requiring more nights than the trip has.
- Choose the BEST valid option within the give budget cap.
- Trip nights = {nights}

{caps_text}

====================================================
ACCOMMODATION OPTIONS (already filtered):
====================================================
{json.dumps(accommodation_ref, indent=2)}

====================================================
PERSONA:
====================================================
{json.dumps(persona, indent=2)}

- Do NOT take budget from persona.

IMPORTANT (STRICT HOUSE & ROOM RULE ENFORCEMENT):
----------------------------------------------------
Any accommodation selected MUST fully comply with
ALL house-rule AND room-related constraints mentioned in:

- persona
- local_constraints
- query intent

This includes (but is NOT limited to):

HOUSE RULES (STRICT):
- children allowed / children under 10
- pets allowed / no pets
- smoking restrictions
- visitor restrictions
- party restrictions

ROOM TYPE RULES (STRICT):
- If local_constraints specify a room type (e.g. entire home, private room, shared room, not shared room),
  the selected hotel MUST match that room type.
- If a hotel’s room_type conflicts with the room type mentioned in local_constraints,
  that hotel MUST NOT be selected.
- Room type rules are HARD CONSTRAINTS, not preferences.

***If ANY house rule or room type constraint is violated, that accommodation MUST be rejected under ALL circumstances.***
*** It must check the local constraint :room_type and house rules. ***

====================================================
LOCAL CONSTRAINTS:
====================================================
{json.dumps(local_constraints, indent=2)}

====================================================
STRICT OUTPUT FORMAT:
====================================================
{{
  "hotel": {{
      ... EXACT hotel object from accommodation_ref ...
  }}
}}

NO explanation.
NO markdown.
ONLY pure JSON.
"""
        
        return prompt

    # ----------------------------------------------------------
    # Strict matching logic to verify the LLM output
    # ----------------------------------------------------------
    def match_hotel(self, selected, ref_list):

        sel_name = (selected.get("name") or "").strip().lower()

        for h in ref_list:
            name_ok = (h.get("name") or "").strip().lower() == sel_name

            # price_per_night comparison (float-safe)
            p1 = h.get("price_per_night")
            p2 = selected.get("price_per_night")
            price_ok = False
            try:
                if p1 is None and p2 is None:
                    price_ok = True
                elif p1 is not None and p2 is not None:
                    price_ok = abs(float(p1) - float(p2)) < 1e-2
            except Exception:
                price_ok = False

            # latitude comparison
            lat1 = h.get("latitude")
            lat2 = selected.get("latitude")

            if lat1 is None and lat2 is None:
                lat_ok = True
            else:
                try:
                    lat_ok = abs(float(lat1) - float(lat2)) < 1e-5
                except Exception:
                    lat_ok = False

            if name_ok and (price_ok or lat_ok):
                return True

        return False

    # ----------------------------------------------------------
    # Main selection function (NO FALLBACK)
    # ----------------------------------------------------------
    def choose_accommodation(
        self,
        reference_json,
        persona,
        trip_json,
        local_constraints,
        city,
        caps: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        accommodation_ref = reference_json.get("accommodations", []) if reference_json else []
        # print(accommodation_ref,city)
        check_accom = self.get_accommodations_for_city(city)
        accommodation_ref = check_accom
        if not accommodation_ref:
            raise Exception("AccommodationAgent: No accommodations available")

        # Compute trip nights
        dates = trip_json.get("dates") or trip_json.get("date") or []
        nights = max(0, len(dates) - 1)
        # print("Accomodation before",accommodation_ref)
        # accommodation_ref=self.normalize_accommodations(accommodation_ref,city)
        
        # print("Accomodation from csv",check_accom)
        # print("Accomodation refined",accommodation_ref)
        
        # ----------------------------------------------------------
        # REMOVE hotels with N/A / infinite price (CRITICAL FIX)
        # ----------------------------------------------------------
        accommodation_ref = [
            h for h in accommodation_ref
            if h.get("price_per_night") not in (None, math.inf)
        ]

        if not accommodation_ref:
            raise Exception(
                "AccommodationAgent: No accommodations with valid pricing available"
            )


        # Filter hotels by minimum_nights
        valid_hotels = []
        for h in accommodation_ref:
            try:
                min_nights = int(h.get("minimum_nights") or 0)
            except Exception:
                min_nights = 0

            if min_nights <= 2:
                valid_hotels.append(h)

        if not valid_hotels:
            raise Exception(
                f"AccommodationAgent: No valid hotels match trip nights={nights}"
            )
        
        valid_hotels = sorted(
            valid_hotels,
            key=lambda h: h.get("price_per_night", math.inf)
        )

        # Build LLM prompt
        prompt = self.build_prompt(valid_hotels, persona, trip_json, local_constraints, nights, caps)
        # print("Accomodation agent prompt:",prompt)

        # Call LLM — DO NOT fallback
        try:
            # print("Prompt:",prompt)
            response = self.llm.generate(prompt)
            # print("Response:",response)
        except Exception as e:
            raise Exception(f"AccommodationAgent: LLM call failed: {e}")

        if not response:
            raise Exception("AccommodationAgent: Empty LLM response")

        # Parse JSON
        data = self.extract_json(response)
        if not data or "hotel" not in data:
            raise Exception("AccommodationAgent: Invalid or missing JSON field 'hotel'")

        hotel = data["hotel"]

        # Validate hotel selection EXACTLY
        if not self.match_hotel(hotel, valid_hotels):
            raise Exception("AccommodationAgent: LLM selected an invalid hotel not present in the reference list")
        # print(hotel)
        return {"hotel": hotel}
    

    def choose_accommodation_upgrade(
        self,
        persona,
        trip_json,
        local_constraints,
        city,
        current_hotel_name: str,
        leftover_budget: float,
    ) -> Dict[str, Any]:
        """
        Upgrade accommodation using leftover budget.
        - Source of truth: CSV ONLY
        - Removes current + cheaper hotels
        - Allows only hotels within (current_price + leftover_budget)
        """

        # ----------------------------------------------------------
        # SOURCE OF TRUTH: CSV
        # ----------------------------------------------------------
        accommodation_ref = self.get_accommodations_for_city(city)
        if not accommodation_ref:
            raise Exception("AccommodationAgent: No accommodations available")

        # ----------------------------------------------------------
        # Find current hotel price
        # ----------------------------------------------------------
        current_hotel_name = current_hotel_name.strip().lower()
        current_price = None

        for h in accommodation_ref:
            if (h.get("name") or "").strip().lower() == current_hotel_name:
                current_price = h.get("price_per_night")
                break

        if current_price is None:
            raise Exception("AccommodationAgent: Current accommodation not found")

        max_allowed_price = current_price + max(0.0, leftover_budget/2)

        # ----------------------------------------------------------
        # Remove invalid pricing
        # ----------------------------------------------------------
        accommodation_ref = [
            h for h in accommodation_ref
            if h.get("price_per_night") not in (None, math.inf)
        ]

        # ----------------------------------------------------------
        # FILTER: STRICT UPGRADE ONLY
        # ----------------------------------------------------------
        upgrade_hotels = [
            h for h in accommodation_ref
            if h.get("price_per_night") > current_price
            and h.get("price_per_night") <= max_allowed_price
        ]

        if not upgrade_hotels:
            return {"hotel": None}  # no upgrade possible (expected case)

        # ----------------------------------------------------------
        # Compute trip nights
        # ----------------------------------------------------------
        dates = trip_json.get("dates") or []
        nights = max(0, len(dates) - 1)

        # ----------------------------------------------------------
        # Filter by minimum nights
        # ----------------------------------------------------------
        valid_hotels = []
        for h in upgrade_hotels:
            try:
                min_nights = int(h.get("minimum_nights") or 0)
            except Exception:
                min_nights = 0

            if min_nights <= nights:
                valid_hotels.append(h)

        if not valid_hotels:
            return {"hotel": None}

        # ----------------------------------------------------------
        # Sort cheapest upgrade first (deterministic)
        # ----------------------------------------------------------
        valid_hotels.sort(key=lambda h: h.get("price_per_night", math.inf))

        # ----------------------------------------------------------
        # Build prompt (caps are advisory)
        # ----------------------------------------------------------
        caps = {
            "upgrade_budget": round(leftover_budget/2, 2),
            "max_price_per_night": round(max_allowed_price, 2),
        }

        prompt = self.build_upgrade_prompt(
            valid_hotels,
            persona,
            trip_json,
            local_constraints,
            nights,
            caps,
        )

        # ----------------------------------------------------------
        # Call LLM (NO fallback)
        # ----------------------------------------------------------
        response = self.llm.generate(prompt)
        if not response:
            raise Exception("AccommodationAgent (upgrade): Empty LLM response")

        data = self.extract_json(response)
        if not data or "hotel" not in data:
            raise Exception("AccommodationAgent (upgrade): Invalid JSON")

        hotel = data["hotel"]

        # ----------------------------------------------------------
        # STRICT validation
        # ----------------------------------------------------------
        if not self.match_hotel(hotel, valid_hotels):
            raise Exception(
                "AccommodationAgent (upgrade): LLM selected invalid hotel"
            )

        return {"hotel": hotel}

