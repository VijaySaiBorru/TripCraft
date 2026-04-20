import json
import re
from typing import List, Dict, Any
import os
import csv
import sqlite3

def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(x) for x in obj]
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    else:
        return obj


class TransportAgent:
    def __init__(self, llm):
        self.llm = llm
        self._transport_ref = None

    def _parse_duration_minutes(self, text: str) -> int:
        text = text.lower()

        # CASE 1: duration already in minutes (float or int)
        mins_match = re.search(r'duration:\s*([\d.]+)\s*mins?', text)
        if mins_match:
            return int(float(mins_match.group(1)))

        # CASE 2: hours + minutes
        h = re.search(r'(\d+)\s*(hours?|hrs?)', text)
        m = re.search(r'(\d+)\s*(mins?|minutes?)', text)

        hours = int(h.group(1)) if h else 0
        mins = int(m.group(1)) if m else 0

        return hours * 60 + mins

    def _parse_flights(self, content: str, date: str, from_city: str, to_city: str):
        flights = []
        # print("Content:",content)
        lines = content.split("\n")
        if lines and lines[0].lower().startswith("flight"):
            lines = lines[1:]

        for line in lines:
            # print("Line ",line)
            line = line.strip()
            if not line.startswith("F"):
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            flights.append({
                "flight_number": parts[0],
                "price": int(parts[1]),
                "departure_time": parts[2],
                "arrival_time": parts[3],
                "duration_minutes": self._parse_duration_minutes(line),
                "date": date,
                "from": from_city,
                "to": to_city
            })

        return flights

    def _normalize_transport_ref(self, raw_ref: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize transport reference into:
        {
        "legs": [
            {
            "from": city,
            "to": city,
            "modes": {
                "flight": [...],
                "taxi": {...},
                "self-driving": {...}
            }
            }
        ]
        }
        """

        normalized = {"legs": []}

        for leg in raw_ref.get("legs", []):
            from_city = leg.get("from")
            to_city = leg.get("to")
            modes = leg.get("modes", {})

            if not from_city or not to_city:
                continue

            modes_out = {}

            # --------------------------------------------------
            # ✈️ FLIGHT (OPTIONAL)
            # --------------------------------------------------
            flight_block = modes.get("flight")
            if flight_block and isinstance(flight_block, dict):
                content = flight_block.get("content", "")
                date = flight_block.get("date")

                flight_options = self._parse_flights(
                    content,
                    date,
                    from_city,
                    to_city
                )

                # Only keep flight if actual options parsed
                if flight_options:
                    modes_out["flight"] = flight_options

            # --------------------------------------------------
            # 🚕 TAXI (FIXED)
            # --------------------------------------------------
            taxi_block = modes.get("taxi")
            if taxi_block and isinstance(taxi_block, dict):
                taxi_text = taxi_block.get("content", "")
                if "no valid" not in taxi_text.lower():
                    cost_match = re.search(
                        r'estimated\s*cost:\s*\$?([\d.]+)',
                        taxi_text,
                        re.IGNORECASE
                    )
                    if cost_match:
                        modes_out["taxi"] = {
                            "duration_minutes": self._parse_duration_minutes(taxi_text),
                            "cost": float(cost_match.group(1)),
                            "from": from_city,
                            "to": to_city
                        }

            # --------------------------------------------------
            # 🚗 SELF-DRIVING (FIXED)
            # --------------------------------------------------
            drive_block = modes.get("self-driving")
            if drive_block and isinstance(drive_block, dict):
                drive_text = drive_block.get("content", "")
                if "no valid" not in drive_text.lower():
                    cost_match = re.search(
                        r'estimated\s*cost:\s*\$?([\d.]+)',
                        drive_text,
                        re.IGNORECASE
                    )
                    if cost_match:
                        modes_out["self-driving"] = {
                            "duration_minutes": self._parse_duration_minutes(drive_text),
                            "cost": float(cost_match.group(1)),
                            "from": from_city,
                            "to": to_city
                        }

            # --------------------------------------------------
            # ADD LEG ONLY IF AT LEAST ONE MODE EXISTS
            # --------------------------------------------------
            if modes_out:
                normalized["legs"].append({
                    "from": from_city,
                    "to": to_city,
                    "modes": modes_out
                })

        return normalized
 
    def _round_trip_cost(self, mode: str, transport_ref: Dict[str, Any], people: int) -> float:
        total = 0

        for leg in transport_ref["legs"]:
            m = leg["modes"].get(mode)
            if not m:
                return None   # mode not available for all legs → invalid

            if mode == "flight":
                cheapest = min(m, key=lambda x: x["price"])
                total += cheapest["price"] * people
            else:
                total += m["cost"]

        return total

    # ------------------------------------------------------------
    # JSON EXTRACTOR
    # ------------------------------------------------------------
    def extract_json(self, text):
        if not isinstance(text, str):
            return None

        text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = text.replace("```", "").strip()

        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        return None
        return None

    # ------------------------------------------------------------
    # TRAVEL DAYS BY TRIP LENGTH
    # ------------------------------------------------------------
    def _travel_days(self, days: int) -> List[int]:
        if days == 3:
            return [1, 3]
        if days == 5:
            return [1, 3, 5]
        if days == 7:
            return [1, 3, 5, 7]
        raise ValueError("Unsupported trip length")

    # ------------------------------------------------------------
    # PROMPT BUILDER (FINAL + EXPLAINED)
    # ------------------------------------------------------------
    def build_prompt(
        self,
        transport_ref: Dict[str, Any],
        trip_json: Dict[str, Any],
        persona: Dict[str, Any],
        local_constraints: Dict[str, Any],
        caps: Dict[str, Any],
        people: int,
        allowed_modes: List[str]
    ):

        days = int(trip_json["days"])
        travel_days = self._travel_days(days)
        transport_ref_json = json.dumps(
            make_json_safe(transport_ref),
            indent=2
        ) 
        persona_json = json.dumps(make_json_safe(persona), indent=2)
        local_constraints_json = json.dumps(make_json_safe(local_constraints), indent=2)
        caps_json = json.dumps(make_json_safe(caps), indent=2)
        allowed_modes = ", ".join(allowed_modes)

        prompt = f"""
You are a TRANSPORT PLANNING AGENT.

================================================
ROLE OF THE LLM (IMPORTANT)
================================================

All feasible transport options are ALREADY provided in transport_ref.

Your role is ONLY to:
- Select the most suitable option among the GIVEN ones
- Decide ONE mode_strategy (flight / taxi / self-driving)
- Respect persona preferences
- STRICTLY respect local constraints
- Prefer staying within budget caps when possible
- Assign reasonable timings when rules allow

You MUST NOT:
- Invent new transport options
- Modify transport_ref content
- Change city order or travel days
- Violate hard rules

================================================
TRIP STRUCTURE
================================================

Trip length: {days} days
Travel days: {travel_days}

transport_ref.legs is an ORDERED list.

You MUST output exactly ONE leg per travel day.
NO extra legs. NO missing legs.
Order MUST be preserved.

DAY INDEXING (HARD RULE)
- "day" in the output JSON refers to the trip day index (1-based) within the full itinerary.
- Travel occurs ONLY on odd-numbered trip days (1,3,5,7,...) unless explicitly overridden by the calling system.
- The i-th leg in transport_ref.legs MUST be assigned to the i-th travel day in {travel_days} AND to the corresponding odd-numbered trip day index.
- You MUST NOT renumber days as 1,2,3,... if the itinerary specifies non-consecutive travel days; use the correct odd-numbered trip day indices.

================================================
TRANSPORTATION LOCAL CONSTRAINTS (HARD)
================================================

The field local_constraints["transportation"] is a HARD FILTER on allowed transport modes.

You MUST interpret it as follows:
- If it contains "no flight" (or textual variants), then flights are FORBIDDEN.
- If it contains "no taxi" (or textual variants), then taxis are FORBIDDEN.
- If it contains "no self-driving" (or textual variants), then self-driving is FORBIDDEN.
- If it contains "flight", then flight is REQUIRED as the primary mode_strategy (self-driving MUST NOT be selected).
- If it contains "taxi", then taxi is REQUIRED as the primary mode_strategy (self-driving MUST NOT be selected).
- If it contains "self-driving", then self-driving is REQUIRED as the primary mode_strategy (flight and taxi MUST NOT be selected).
- If it contains "none" or is null, then it imposes NO extra restriction beyond allowed_modes and other HARD rules.

These transportation local constraints MUST be applied BEFORE any cost or mode priority reasoning.

================================================
MODE SELECTION PIPELINE (HARD ORDER)
================================================

You MUST select mode_strategy in this exact order of operations:

Step 1: Initialize the candidate set with all three base modes:
        {"flight", "taxi", "self-driving"}.

Step 2: Intersect this set with the global allowed modes {allowed_modes}.
        Remove any mode not in {allowed_modes}.

Step 3: Apply TRANSPORTATION LOCAL CONSTRAINTS and any other HARD transport constraints:
        - Remove all modes that are forbidden (e.g., "no flight", "no taxi", "no self-driving").
        - If a mode is REQUIRED ("flight", "taxi", or "self-driving" without "no ..."), then:
            * Keep only that required mode in the candidate set.
        - If multiple constraints appear, always choose the most restrictive interpretation:
            * Any mode explicitly forbidden MUST be removed from the candidate set.

Step 4: COST FILTER (HARD with respect to cap):
        - For EACH remaining candidate mode_strategy, compute the TOTAL transport cost across ALL legs.
          (Use the per-person or per-vehicle rules given below.)
        - Remove any candidate whose total cost > budget_caps.
        - If after this step exactly ONE candidate remains, you MUST choose that mode_strategy, even if it is not preferred.

Step 4.5: TRAVEL TIME PREFERENCE (SOFT TIE-BREAKER):
        - For each remaining candidate mode_strategy, compute the TOTAL travel duration across ALL legs
          (sum of duration_minutes for the chosen mode on each leg).
        - If TWO OR MORE candidates remain after Step 4, you SHOULD:
            * Prefer the candidate with the LOWER total travel duration,
              especially when one involves very long overland travel (e.g., > 12 hours per leg or > 20 hours total).
        - This is a SOFT preference:
            * It MUST NOT override any HARD constraint or budget_caps.
            * It only decides between candidates that are already valid and within budget.

Step 5: MODE PRIORITY (CONDITIONAL ORDER, APPLIED ONLY TO CANDIDATES STILL REMAINING):
        - Let the remaining candidate set after Step 4 (and considering Step 4.5 as a soft tie-breaker) be S.
        - You MUST choose mode_strategy from S using the following rules:

          1) If "no flight" is active (flights forbidden by constraints):
             - If "taxi" ∈ S, choose "taxi".
             - ELSE IF "self-driving" ∈ S, choose "self-driving".

          2) ELSE IF "no self-driving" is active (self-driving forbidden):
             - If "flight" ∈ S, choose "flight".
             - ELSE IF "taxi" ∈ S, choose "taxi".

          3) ELSE IF "no taxi" is active (taxis forbidden):
             - If "flight" ∈ S, choose "flight".
             - ELSE IF "self-driving" ∈ S, choose "self-driving".

          4) ELSE (no "no flight", no "no taxi", no "no self-driving" active):
             - If "flight" ∈ S, choose "flight".
             - ELSE IF "taxi" ∈ S, choose "taxi".
             - ELSE IF "self-driving" ∈ S, choose "self-driving".

        - If after Step 4 S contains only one mode, you MUST select that mode regardless of priority.
        - If after Step 4 S is empty (no mode within budget_caps and constraints), you MUST state that no valid mode_strategy exists under the given constraints and budget.

Filtered-out modes at any previous step MUST NEVER be reconsidered,
even if they are cheaper or usually higher priority.

================================================
MODE RULES (HARD CONSTRAINTS)
================================================

Choose ONE mode_strategy for the ENTIRE trip:
- self-driving
- flight
- taxi

Mode consistency (STRICT):
- self-driving → ONLY self-driving
- flight → flight OR taxi allowed
- taxi → taxi OR flight allowed
- self-driving MUST NEVER mix with flight or taxi

================================================
GROUP SIZE (IMPORTANT FOR BUDGET)
================================================

Number of travelers: {people}

Cost interpretation guidance:
- Flight prices are PER PERSON.
- Taxi costs are PER VEHICLE (≈ 4 people per taxi).
- Self-driving costs are PER VEHICLE (≈ 5 people per car).

================================================
TIMING RULES (HARD CONSTRAINTS)
================================================

Flights:
- Any timing allowed.

Taxi / Self-driving:
- If duration > 12 hours:
  Day 1:
    departure_time = null
    arrival_time ≈ 19:30
  Last day:
    departure_time = 15:30–16:00
    arrival_time = null
- Otherwise:
  Use reasonable times.

================================================
IMPORTANT (STRICT TRANSPORT CONSTRAINT ENFORCEMENT)
================================================

Any transportation-related constraint mentioned in:
- persona
- local_constraints
- query intent

MUST be treated as a HARD RULE.

This includes (but is NOT limited to):

TRANSPORT CONSTRAINT RULES (STRICT):
- If local_constraints specify "no flight", flight MUST NOT be selected.
- If local_constraints specify "flight", self-driving MUST NOT be selected.
- If local_constraints specify "no self-driving", self-driving MUST NOT be selected.
- If local_constraints specify "no taxi", taxi MUST NOT be selected.
- If local_constraints specify "none", choose the most restrictive valid option.
- Textual variants (e.g. "no self driving", "no self-driving", "no self_driving")
  MUST be interpreted consistently as the SAME restriction.

These constraints OVERRIDE:
- budget preferences
- comfort preferences
- persona soft guidance
- MODE PRIORITY.

If a constraint conflicts with cost or convenience,
the constraint ALWAYS wins.

================================================
USER CONTEXT (GUIDANCE ONLY)
================================================

persona:
{persona_json}

local_constraints (HARD FILTERS):
{local_constraints_json}

budget_caps (SOFT LIMITS):
{caps_json}

Timing Preference (Soft)
- Day 1: Prefer morning arrival to maximize usable time on the first day.
- Last Day: Prefer late-afternoon departure to allow sufficient buffer and activities.
- Inter-city Days: No timing preference; any reasonable timings are acceptable.
- These are soft preferences only and must be ignored if they conflict with hard rules or local constraints.

Guidelines:
- Persona influences comfort vs cost WITHIN the chosen mode_strategy only (e.g., which specific flight among flights).
- Persona does NOT change which mode_strategy is chosen and does NOT override any transportation constraint in local_constraints.
- DO NOT take budget from persona.
- Local constraints MUST be respected.
- Budget caps should be respected when possible, but never override HARD constraints.
- When multiple candidates are valid and within budget, you SHOULD avoid very long overland journeys (e.g., > 20 hours total self-driving) by preferring modes with shorter total travel time, as long as this does not violate any HARD constraint.
- HARD RULES and the MODE SELECTION PIPELINE ALWAYS override persona and other preferences.

================================================
COST CHECK (MANDATORY)
================================================

You must:
1. Compute TOTAL transport cost across ALL legs for each candidate mode_strategy in the pipeline.
2. Ensure that the chosen mode_strategy has total cost ≤ transport_cap (budget_caps).
3. If the originally preferred mode_strategy violates budget_caps, you MUST:
   - Remove it from the candidate set and
   - Choose another VALID mode_strategy from the remaining candidates using the MODE SELECTION PIPELINE.

================================================
ALLOWED MODES (HARD CONSTRAINT)
================================================

You MUST choose exactly ONE of the following modes:
{allowed_modes}

Choosing any other mode is INVALID.

CRITICAL:
- The "details" field MUST be copied EXACTLY from transport_ref
- DO NOT remove or omit any keys (including "from", "to")
- DO NOT summarize
- Copy the full object verbatim from transport_ref for the chosen mode on each leg.

================================================
OUTPUT FORMAT (STRICT JSON ONLY)
================================================
{{
  "mode_strategy": "flight | taxi | self-driving",
  "legs": [
    {{
      "day": <int>,
      "from": "<city>",
      "to": "<city>",
      "mode": "flight | taxi | self-driving",
      "details": <EXACT object from transport_ref>,
      "departure_time": "HH:MM | null",
      "arrival_time": "HH:MM | null"
    }}
  ]
}}

================================================
transport_ref:
{transport_ref_json}

"""
        return prompt

    # ------------------------------------------------------------
    # VALIDATION (STRICT)
    # ------------------------------------------------------------
    def validate(self, data: Dict[str, Any], days: int):

        if not isinstance(data, dict):
            return False, "Output is not JSON"

        if "mode_strategy" not in data or "legs" not in data:
            return False, "Missing required keys"

        strategy = data["mode_strategy"]
        legs = data["legs"]

        valid_modes = {"flight", "taxi", "self-driving"}
        if strategy not in valid_modes:
            return False, "Invalid mode_strategy"

        expected_days = self._travel_days(days)
        if len(legs) != len(expected_days):
            return False, "Incorrect number of legs"

        for idx, leg in enumerate(legs):
            ref_leg = self._transport_ref["legs"][idx]

            if leg.get("day") != expected_days[idx]:
                return False, "Incorrect day ordering"

            if leg.get("from") != ref_leg["from"]:
                return False, "Incorrect from-city"
            if leg.get("to") != ref_leg["to"]:
                return False, "Incorrect to-city"

            leg_mode = leg.get("mode")
            if leg_mode not in valid_modes:
                return False, "Invalid leg mode"

            if strategy == "self-driving" and leg_mode != "self-driving":
                return False, "Self-driving cannot mix modes"

            if strategy in {"flight", "taxi"} and leg_mode == "self-driving":
                return False, "Self-driving cannot mix modes"

            details = leg.get("details")
            if not self._is_from_reference(details):
                return False, "Transport details not from reference"

        return True, ""

    # ------------------------------------------------------------
    # EXACT OBJECT MATCH
    # ------------------------------------------------------------
    def _is_from_reference(self, details):
        if not isinstance(details, dict):
            return False

        for leg in self._transport_ref["legs"]:
            for mode, mode_obj in leg["modes"].items():

                # Flights → list match
                if mode == "flight":
                    if details in mode_obj:
                        return True

                # Taxi / self-driving → direct match
                else:
                    if details == mode_obj:
                        return True

        return False

    def build_transport_ref(
        self,
        origin_city: str,
        city_sequence: List[str],
        trip_days: int,
        travel_dates: List[str]
    ) -> Dict[str, Any]:
        """
        Build transport_ref for TransportAgent.

        DEBUG VERSION – prints every important step.
        """

        import os, csv, sqlite3, json, re

        # print("\n================ BUILD TRANSPORT REF ================\n")

        # --------------------------------------------------
        # Validate trip
        # --------------------------------------------------
        # print("[DEBUG] origin_city:", origin_city)
        # print("[DEBUG] city_sequence:", city_sequence)
        # print("[DEBUG] trip_days:", trip_days)
        # print("[DEBUG] travel_dates:", travel_dates)

        if trip_days not in (3, 5, 7):
            raise ValueError("trip_days must be 3, 5, or 7")

        if trip_days == 3:
            legs = [
                (origin_city, city_sequence[0]),
                (city_sequence[0], origin_city),
            ]
        elif trip_days == 5:
            legs = [
                (origin_city, city_sequence[0]),
                (city_sequence[0], city_sequence[1]),
                (city_sequence[1], origin_city),
            ]
        else:  # 7-day
            legs = [
                (origin_city, city_sequence[0]),
                (city_sequence[0], city_sequence[1]),
                (city_sequence[1], city_sequence[2]),
                (city_sequence[2], origin_city),
            ]

        # print("[DEBUG] Computed legs:", legs)

        if len(travel_dates) != len(legs):
            raise ValueError(
                f"travel_dates length ({len(travel_dates)}) "
                f"must match number of legs ({len(legs)})"
            )

        # --------------------------------------------------
        # Paths
        # --------------------------------------------------
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

        DIST_CSV = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/distance_matrix/city_distances_times_full.csv"
            )
        )

        FLIGHT_DB = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../db/flights.db"
            )
        )

        # print("[DEBUG] Distance CSV path:", DIST_CSV)
        # print("[DEBUG] Flights DB path:", FLIGHT_DB)

        # --------------------------------------------------
        # Load distance matrix
        # --------------------------------------------------
        distance_map = {}
        total_dist_rows = 0

        with open(DIST_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                total_dist_rows += 1
                if not r["distance_km"] or not r["duration_min"]:
                    continue

                key = (
                    r["origin"].strip().lower(),
                    r["destination"].strip().lower()
                )
                distance_map[key] = {
                    "distance_km": float(r["distance_km"]),
                    "duration_minutes": int(float(r["duration_min"]))
                }

        # print(f"[DEBUG] Distance rows read: {total_dist_rows}")
        # print(f"[DEBUG] Valid distance entries loaded: {len(distance_map)}")

        # --------------------------------------------------
        # SQLite connection
        # --------------------------------------------------
        # print("[DEBUG] Connecting to flights DB...")
        conn = sqlite3.connect(FLIGHT_DB)
        cursor = conn.cursor()

        # --------------------------------------------------
        # Helpers
        # --------------------------------------------------
        def parse_duration(text):
            """
            Converts:
            '1 hours 50 minutes' → 110
            """
            if isinstance(text, (int, float)):
                return int(text)

            if isinstance(text, str):
                h = re.search(r"(\d+)\s*hours?", text)
                m = re.search(r"(\d+)\s*minutes?", text)

                hours = int(h.group(1)) if h else 0
                minutes = int(m.group(1)) if m else 0

                total = hours * 60 + minutes
                return total if total > 0 else None

            return None

        # --------------------------------------------------
        # Build transport_ref
        # --------------------------------------------------
        transport_ref = {"legs": []}

        for idx, ((frm, to), date) in enumerate(zip(legs, travel_dates), start=1):

            # print("\n--------------------------------------------------")
            # print(f"[DEBUG] LEG {idx}")
            # print(f"[DEBUG] From → To: {frm} → {to}")
            # print(f"[DEBUG] Date: {date}")

            modes = {}

            # -------------------------------
            # ✈️ Flights (direct only)
            # -------------------------------
            # print("[DEBUG] Querying flights...")

            cursor.execute("""
                SELECT
                    "Flight Number",
                    Price,
                    DepTime,
                    ArrTime,
                    ActualElapsedTime
                FROM flights
                WHERE TRIM(LOWER(OriginCityName)) = TRIM(LOWER(?))
                AND TRIM(LOWER(DestCityName)) = TRIM(LOWER(?))
                AND FlightDate = ?
                           ORDER BY
                    Price ASC,
                    CAST(
                        SUBSTR(ActualElapsedTime, 1, INSTR(ActualElapsedTime, ' ') - 1
                    ) AS INTEGER) ASC,
                    DepTime ASC
            """, (frm.strip(), to.strip(), date))

            rows = cursor.fetchall()
            # print(f"[DEBUG] Flight rows found: {len(rows)}")

            flights = []

            for f in rows:
                dur = parse_duration(f[4])
                if dur is None:
                    # print("[WARN] Skipping flight with invalid duration:", f)
                    continue

                flights.append({
                    "flight_number": f[0],
                    "price": int(f[1]),
                    "departure_time": f[2],
                    "arrival_time": f[3],
                    "duration_minutes": dur,
                    "date": date,
                    "from": frm,
                    "to": to
                })

            if flights:
                modes["flight"] = flights
                # print(f"[DEBUG] Flights added: {len(flights)}")
            else:
                pass
                # print("[DEBUG] No valid flights added")

            # -------------------------------
            # 🚕 Taxi & 🚗 Self-driving
            # -------------------------------
            dist_key = (frm.lower(), to.lower())

            if dist_key in distance_map:
                d = distance_map[dist_key]

                modes["taxi"] = {
                    "duration_minutes": d["duration_minutes"],
                    "cost": round(d["distance_km"] * 1, 2),
                    "from": frm,
                    "to": to
                }

                modes["self-driving"] = {
                    "duration_minutes": d["duration_minutes"],
                    "cost": round(d["distance_km"] * 0.05, 2),
                    "from": frm,
                    "to": to
                }

                # print("[DEBUG] Distance-based modes added (taxi, self-driving)")
            else:
                pass
                # print("[WARN] No distance entry found for:", dist_key)

            # -------------------------------
            # Append leg
            # -------------------------------
            if modes:
                transport_ref["legs"].append({
                    "from": frm,
                    "to": to,
                    "modes": modes
                })
                # print("[DEBUG] Leg appended with modes:", list(modes.keys()))
            else:
                pass
                # print("[WARN] Leg skipped — no modes available")

        conn.close()

        # print("\n================ FINAL TRANSPORT REF ================\n")
        # print(json.dumps(transport_ref, indent=2))

        return transport_ref

    # MAIN ENTRY
    # ------------------------------------------------------------
    def choose_transport(
        self,
        transport_ref,
        persona,
        trip_json,
        people,
        city_sequence,
        travel_dates,
        local_constraints=None,
        caps=None,
    ):
        # print("Before transport_ref:",transport_ref)
        # print("City_sequence:",city_sequence,"Travel_dates:",travel_dates)
        transport_ref = self._normalize_transport_ref(transport_ref)
        # print("Refined tranpsort_ref",transport_ref)
        origin = trip_json.get("org")
        dates = trip_json.get("dates") or []
        trip_days = int(trip_json["days"])

        if not origin or not dates:
            raise ValueError("Missing origin or dates for transport planning")

        db_transport_ref = self.build_transport_ref(
            origin_city=origin,
            city_sequence=city_sequence,
            trip_days=trip_days,
            travel_dates=travel_dates
        )
        # print("Built transport_ref from DB:",db_transport_ref)
        transport_ref=db_transport_ref

        self._transport_ref = transport_ref

        days = int(trip_json["days"])
        # print("Debug: ",transport_ref,persona,local_constraints,caps)
        cap = (caps or {}).get("transport_cap")
        # print("Transport_ref:",transport_ref,"Cap:",cap)

        allowed_modes = []
        available_modes = []

        for leg in transport_ref.get("legs", []):
            for mode in leg.get("modes", {}).keys():
                if mode not in available_modes:
                    available_modes.append(mode)


        # print(available_modes)
        if cap is not None:
            if "flight" in available_modes:
                flight_cost = self._round_trip_cost("flight", transport_ref, people)
                # print(flight_cost,cap)
                if flight_cost is not None and flight_cost <= cap:
                    allowed_modes.append("flight")
            # print(allowed_modes)

            if "taxi" in available_modes:
                taxi_cost = self._round_trip_cost("taxi", transport_ref, people)
                if taxi_cost is not None and taxi_cost <= cap:
                    allowed_modes.append("taxi")

            if "self-driving" in available_modes:
                drive_cost = self._round_trip_cost("self-driving", transport_ref, people)
                if drive_cost is not None and drive_cost <= cap:
                    allowed_modes.append("self-driving")

            if not allowed_modes:
                # Soft fallback: choose the cheapest available mode
                print("⚠️ No mode fits budget, selecting cheapest available mode")

                cheapest_mode = None
                cheapest_cost = float("inf")

                for mode in available_modes:
                    cost = self._round_trip_cost(mode, transport_ref, people)
                    if cost is not None and cost < cheapest_cost:
                        cheapest_cost = cost
                        cheapest_mode = mode

                if cheapest_mode is None:
                    raise Exception("No valid transport modes available at all")

                allowed_modes = [cheapest_mode]

        else:
            allowed_modes = list(available_modes)


        # print("Allowed",allowed_modes)
        # --------------------------------------------------
        # PRUNE transport_ref to ONLY allowed modes
        # --------------------------------------------------
        for leg in transport_ref["legs"]:
            leg["modes"] = {
                mode: mode_obj
                for mode, mode_obj in leg["modes"].items()
                if mode in allowed_modes
            }

        # Safety check (should never trigger, but defensive)
        for leg in transport_ref["legs"]:
            if not leg["modes"]:
                raise Exception("No allowed transport modes left for a leg")

        
        prompt = self.build_prompt(
            transport_ref,
            trip_json,
            persona,
            local_constraints,
            caps,
            people,
            allowed_modes
        )

        # print("The PRompt:",prompt)

        response = self.llm.generate(prompt)
        # print("the response:",response)
        data = self.extract_json(response)
        if not data:
            raise Exception("TransportAgent: Invalid JSON")

        MAX_RETRIES = 3
        attempt = 0

        ok, msg = self.validate(data, days)

        while not ok and attempt < MAX_RETRIES:
            attempt += 1
            # print(f"[TransportAgent] Retry {attempt}/{MAX_RETRIES} due to: {msg}")

            retry_prompt = (
                prompt
                + "\n\nERROR:\n"
                + msg
                + f"\nYou MUST output {len(self._travel_days(days))} legs, "
                f"one for each travel day {self._travel_days(days)}.\n"
                + "Fix ALL issues and output STRICT JSON only.\n"
            )

            response = self.llm.generate(retry_prompt)
            # print("The Retry Response:",response)
            data = self.extract_json(response)

            if not data:
                msg = "Invalid JSON"
                continue

            ok, msg = self.validate(data, days)

        if not ok:
            raise Exception(f"TransportAgent failed after {MAX_RETRIES} retries: {msg}")

        return data
