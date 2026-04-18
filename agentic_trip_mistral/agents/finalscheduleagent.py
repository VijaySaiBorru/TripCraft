# agentic_trip/agents/finalscheduleagent.py
import json
import re
import os
from typing import Any, Dict, List, Optional
from agentic_trip.agents.pois2agent import POIsAgent

ValidationError = Dict[str, Any]
ValidationResult = Dict[str, Any]

PLANNER_SHORT_INSTRUCTION = """
You are a schedule-generation LLM.

You are given a FIXED, PRE-STRUCTURED multi-day trip plan skeleton.
Your job is ONLY to fill meals and attractions.
You MUST NOT change cities, transportation, or accommodation.

======================
INPUT_JSON STRUCTURE
======================

The input JSON contains:

1. "days": a list of day objects, EACH already containing:
   - day (number, starting from 1)
   - current_city (ALREADY resolved, do NOT change)
   - transportation (ALREADY resolved or "-")
   - accommodation (ALREADY resolved or "-")
   - breakfast, lunch, dinner, attraction (empty or "-")

2. "cities": a list of city blocks, each containing:
   - city
   - restaurants_ranked (VALID restaurants for that city)
   - attractions_ranked (VALID attractions for that city)

Transportation, city transitions, and accommodation placement
are ALREADY CORRECT in the input.
YOU MUST NOT modify them.
***Do NOT repeat the attractions and restaurant names ,  While adding check the restaurant name or attraction name is present in other place or not . If not available then place it otherwise try with other.***

======================
YOUR TASK (STRICT)
======================

For EACH day object:

YOU MUST NOT MODIFY:
- day
- current_city
- transportation
- accommodation

YOU MAY ONLY FILL OR UPDATE:
- breakfast
- lunch
- dinner
- attraction

FIELD COMPLETENESS RULE (ABSOLUTE):

Each day object MUST contain ALL fields:

- day
- current_city
- transportation
- breakfast
- attraction
- lunch
- dinner
- accommodation

You MUST NOT omit ANY field.

If ANY field is missing:
→ OUTPUT IS INVALID

Use ONLY restaurants and attractions belonging to the city of that day.
***Do NOT repeat the attractions and restaurant names ,  While adding check the restaurant name or attraction name is present in other place or not . If not available then place it otherwise try with other.***

HARD CONSTRAINT (VERY IMPORTANT):

Some fields in the provided days skeleton are marked as "-".
These indicate IMPOSSIBLE activities.

YOU MUST:
- NEVER replace "-" with any value
- NEVER add meals, attractions, or accommodation where "-" is present
- Only fill fields that are EMPTY ("") and NOT "-"
***Do NOT repeat the attractions and restaurant names ,  While adding check the restaurant name or attraction name is present in other place or not . If not available then place it otherwise try with other.***

If you violate this, the output is INVALID.
VERY IMPORTANT CLARIFICATION:

If a meal field is EMPTY ("") in the input skeleton, it means the meal
IS FEASIBLE and SHOULD be filled.

You MUST NOT convert an EMPTY ("") meal field into "-".
Only fields that are ALREADY "-" may remain "-".
If the skeleton value is "", you MUST fill it.
If the skeleton value is "-", you MUST set it to "-".
If allowed options are not provided, choose ANY valid option from the city data.


LOCAL CONSTRAINT SATISFACTION (IMPORTANT):

- While selecting restaurants and attractions, you SHOULD TRY to satisfy local constraints whenever possible.
- For restaurants:
  → Prefer options that match the required cuisine (if provided)
- For attractions:
  → Prefer options that match the required attraction category (if provided)
PRIORITY ORDER:
1. MUST follow skeleton feasibility rules
2. SHOULD satisfy local constraints when valid options exist
3. If multiple valid options exist → choose one that satisfies constraints

FALLBACK RULE:
- If NO valid option satisfies local constraints:
  → Choose the best available option
  → DO NOT leave field empty
  → DO NOT violate skeleton rules

IMPORTANT:
- Do NOT ignore valid constraint matches
- Do NOT randomly pick options if a matching option exists

======================
DAY PATTERN (REFERENCE ONLY)
======================

The schedule ALWAYS follows exactly one of these patterns:

3 DAYS:
- Day 1: origin → city1 (TRAVEL DAY)
- Day 2: city1 (NON-TRAVEL DAY)
- Day 3: city1 → origin (TRAVEL DAY)

5 DAYS:
- Day 1: origin → city1 (TRAVEL DAY)
- Day 2: city1 (NON-TRAVEL DAY)
- Day 3: city1 → city2 (TRAVEL DAY)
- Day 4: city2 (NON-TRAVEL DAY)
- Day 5: city2 → origin (TRAVEL DAY)

7 DAYS:
- Day 1: origin → city1 (TRAVEL DAY)
- Day 2: city1 (NON-TRAVEL DAY)
- Day 3: city1 → city2 (TRAVEL DAY)
- Day 4: city2 (NON-TRAVEL DAY)
- Day 5: city2 → city3 (TRAVEL DAY)
- Day 6: city3 (NON-TRAVEL DAY)
- Day 7: city3 → origin (TRAVEL DAY)

You MUST NOT invent or alter this structure.

======================
TRANSPORTATION RULES
======================

- Transportation is PRE-FILLED.
- If transportation == "-", it is a NON-TRAVEL DAY.
- If transportation != "-", it is a TRAVEL DAY.
- NEVER modify transportation text.
- NEVER invent transportation.
- NEVER add or remove transport legs.

======================
MEAL RULES
======================
When filling meals:
- Always choose the FIRST unused restaurant from restaurants_ranked.

TRAVEL DAYS:
- If a meal field is EMPTY ("") in the skeleton, you MUST FILL it.
- You may use "-" ONLY if the field is ALREADY "-".
- Leaving a field empty is INVALID.

NON-TRAVEL DAYS:
- You SHOULD fill breakfast, lunch, and dinner.
- Restaurants MUST NOT repeat across different days.

If unsure:
- Use "-" ONLY if the field is ALREADY "-"
- Otherwise choose any valid option


======================
ATTRACTION RULES
======================

TRAVEL DAYS:
- MAX 1 attraction
- If timing is tight → "-"

NON-TRAVEL DAYS:
- MIN 1 attraction
- MAX 2 attractions
- EXCEPTION:
  If persona contains "Adventure" (case-insensitive),
  MAX 3 attractions are allowed on NON-TRAVEL days ONLY.
  If persona contains "Laid back Traveller" (case-insensitive),
  MAX 1 attractions are allowed on NON-TRAVEL days ONLY.

Rules:
- Use ONLY attractions from that city.
- DO NOT repeat attractions across days.
- Format EXACTLY:
  "Attraction Name, City;"
======================
PERSONA & LOCAL CONSTRAINT RULES
======================

Persona and local constraints provide PREFERENCE, not feasibility.
Skeleton rules ALWAYS override persona and local constraints.

PERSONA EFFECTS (CASE-INSENSITIVE):

Traveler Type:
- If persona contains "Adventure":
  - NON-TRAVEL days may have up to 3 attractions.
- If persona contains "Laidback":
  - Prefer fewer attractions (1 instead of 2 when possible).
  - NEVER exceed default attraction limits.

Purpose of Travel:
- If persona indicates "Cultural Exploration":
  - Prefer museums, landmarks, or cultural attractions WHEN AVAILABLE.
  - If none exist, select any valid attraction.

Spending Preference and Location Preference:
- These DO NOT affect meal or attraction selection at this stage.

LOCAL CONSTRAINTS:

Local constraints (cuisine, attraction category, house rules, transport preferences)
are SOFT hints only.

- NEVER filter out valid restaurants or attractions based on local constraints.
- NEVER modify accommodation, transportation, or cities.
- If a preferred type is unavailable, choose any valid option from ranked lists.

If persona or local constraints conflict with skeleton rules:
→ Skeleton rules WIN.
  
======================
ACCOMMODATION RULES
======================

- Accommodation is PRE-FILLED.
- DO NOT change it.
- LAST DAY accommodation is ALWAYS "-".

======================
CAPITALIZATION & FORMAT
======================

- City names MUST match input capitalization exactly.
- Restaurant format:
  "Restaurant Name, City"
- Attraction format:
  "Attraction Name, City;"

======================
FAIL-SAFE MODE
======================

If a field is EMPTY ("") in the skeleton, you MUST choose a value.
Leaving it empty is INVALID.

Only output "-" if the field is ALREADY "-".
- NEVER invent data.

GENERAL RULES (ABSOLUTE)

The input day skeleton is the source of truth.
You may fill a field ONLY if its value is EMPTY ("").
You MUST NOT change any field whose value is "-".
You MUST NOT leave any EMPTY ("") field unfilled.
Use ONLY restaurants and attractions provided for that city.
Restaurants and attractions MUST NOT repeat across days.

MEAL RULES (TIME-AWARE, SKELETON-FIRST)
ABSOLUTE GLOBAL RULE (DO NOT VIOLATE)
For every meal on every day:
If the skeleton value is "-" → KEEP IT AS "-"
If the skeleton value is "" → YOU MUST FILL IT
NEVER change feasibility
Timing rules below are for CITY SELECTION ONLY

NON-TRAVEL DAY (transportation == "-")
Typical timing context (for understanding):
Full day in one city
No travel constraints
Rules:
Breakfast → MUST be filled
Lunch → MUST be filled
Dinner → MUST be filled
City used: The city of the day (current_city)

ARRIVAL DAY (Day 1 – Travel)
Typical timing context:
Arrival may be early or late depending on transport
Rules (skeleton decides feasibility):
If meal field is "" → MUST be filled
If meal field is "-" → MUST remain "-"
City used: Destination city

(Skeleton already applied rules like):
Breakfast if arrival ≤ ~09:10
Lunch if arrival ≤ ~13:00
Dinner if arrival ≤ ~20:00

DEPARTURE DAY (Last Day – Travel)
Typical timing context:
Departure may be early or late
Rules (skeleton decides feasibility):
If meal field is "" → MUST be filled
If meal field is "-" → MUST remain "-"
City used: Origin city
(Skeleton already applied rules like):
Breakfast if departure ≥ ~09:20
Lunch if departure ≥ ~14:50
Dinner usually not feasible

INTER-CITY TRAVEL DAY (Between Cities)
Typical timing context:
Before departure in origin city
After Arrival in destination city
For each meal:
Breakfast
If skeleton value is "" → MUST be filled
City understanding:
Before departure → origin city
After arrival → destination city

Lunch
If skeleton value is "" → MUST be filled
City understanding:
Arrival ≤ ~13:00 → destination city
Departure ≥ ~14:50 → origin city

Dinner
If skeleton value is "" → MUST be filled
City understanding:
Arrival ≤ ~20:00 → destination city
Late departure → origin city
If none of the timing windows apply, the skeleton already sets "-"
→ DO NOT override it

RESTAURANT SELECTION (STRICT)
Always choose the first unused restaurant from restaurants_ranked
Use restaurants only from the resolved city
Once used, a restaurant MUST NOT be reused

ATTRACTION RULES (TIME-AWARE, SKELETON-FIRST)
ABSOLUTE GLOBAL RULE (DO NOT VIOLATE)
For attractions on every day:
If the skeleton value is "-" → KEEP IT AS "-"
If the skeleton value is "" → YOU MUST FILL IT
NEVER override skeleton feasibility

Timing rules below are ONLY for city selection and count limits

NON-TRAVEL DAY (transportation == "-")
Typical timing context (for understanding):
Full day in one city
No travel constraints
Rules:
If skeleton value is "" → MUST be filled
Pick 1 or 2 attractions
Persona exception:
If persona contains "Adventure" (case-insensitive),
you MAY pick up to 3 attractions
City used: city of the day (current_city)
Attractions MUST belong to that city
Attractions MUST NOT repeat across days

ARRIVAL DAY (Day 1 – Travel)
Typical timing context:
Sightseeing depends on arrival time
Rules (skeleton decides feasibility):
If skeleton value is "" → MUST be filled
If skeleton value is "-" → MUST remain "-"
City used: destination city
Skeleton already applied rules like:
Early arrival → up to 2 attractions
Mid-day arrival → 1 attraction
Late arrival → skeleton sets "-" (DO NOT override)

INTER-CITY TRAVEL DAY (Between Cities, not last day)
Typical timing context (important):
Sightseeing can happen before departure (origin city), after arrival (destination city), or both
Availability depends on departure and arrival windows
Rules (skeleton decides feasibility):
If skeleton value is "" → MUST be filled
If skeleton value is "-" → MUST remain "-"
City resolution (DO NOT invent):
Early arrival window → destination city
Late departure window → origin city
If both windows exist → 1 attraction in origin + 1 in destination
If only one window exists → use that city
If no valid window → skeleton already sets "-"
Maximum attractions: up to 2 (as implied by skeleton logic)

DEPARTURE DAY (Last Day – Travel)
Typical timing context:
Limited sightseeing before departure
Rules (skeleton decides feasibility):
If skeleton value is "" → MUST be filled
If skeleton value is "-" → MUST remain "-"
City used: origin city
Skeleton already applied rules like:
Late departure → 1 attraction
Very late departure → possibly 2 attractions
Early departure → skeleton sets "-" (DO NOT override)

ATTRACTION FORMAT (STRICT)
Each attraction MUST be formatted exactly as:
"Attraction Name, City;"

Multiple attractions MUST be separated by a single space:
"Attraction Name, City; Attraction Name, City;"

ATTRACTION SELECTION RULES (STRICT)
Use ONLY attractions from attractions_ranked of the resolved city
Attractions MUST NOT repeat across days
Persona affects count only, never feasibility
Skeleton feasibility always wins

======================
OUTPUT FORMAT (STRICT)
======================

You MUST return ONLY valid JSON.
NO explanations.
NO markdown.
NO extra keys.

The output MUST EXACTLY follow this structure:

{
  "days": [
    {
      "day": 1,
      "current_city": "from Origin to City",
      "transportation": "TRANSPORT STRING OR '-'",
      "breakfast": "Restaurant Name, City OR '-'",
      "attraction": "Attraction Name, City; OR '-'",
      "lunch": "Restaurant Name, City OR '-'",
      "dinner": "Restaurant Name, City OR '-'",
      "accommodation": "Accommodation Name, City OR '-'"
    }
  ]
}

- The number of objects in "days" MUST equal the number of input days.
- Keys MUST appear exactly as shown.
- Order of keys inside each day MUST be preserved.

CRITICAL LENGTH CONSTRAINT (HIGHEST PRIORITY)

The input contains EXACTLY {n_days} days.

You MUST return EXACTLY {n_days} objects inside "days".

- NOT LESS
- NOT MORE
- EXACTLY {n_days}

If you return fewer or more days, the output is INVALID.

DO NOT STOP EARLY.
DO NOT OMIT ANY DAY.
YOU MUST GENERATE ALL {n_days} DAYS.

Example for 3-day trip:
[
  { "day": 1, ... },
  { "day": 2, ... },
  { "day": 3, ... }
]

======================
SELF-CHECK BEFORE OUTPUT
======================

Before returning JSON, VERIFY:

- Did I change transportation? → MUST be NO
- Did I change current_city? → MUST be NO
- Did I invent a restaurant? → MUST be NO
- Did I invent an attraction? → MUST be NO
- Did I repeat any restaurant or attraction? → MUST be NO
- Did I respect travel vs non-travel rules? → MUST be YES
- Did I keep the same number of days? → MUST be YES
- Did I use persona and local constraints only as preference (not feasibility)? → MUST be YES
- Count number of objects in "days"
- If count != {n_days}, FIX BEFORE OUTPUT
- Final output MUST contain EXACTLY {n_days} days

END OF INSTRUCTIONS.

"""

class FinalScheduleAgent:
    def __init__(self, llm):
        self.llm = llm
        self.debug_dir = "/scratch/sg/Vijay/TripCraftNew/debug"
        try:
            os.makedirs(self.debug_dir, exist_ok=True)
        except Exception:
            pass

    # -------------------------
    # Utility helpers
    # -------------------------
    def _serialize_for_prompt(self, structured: dict) -> str:
        return json.dumps(structured, indent=2, ensure_ascii=False)

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not isinstance(text, str):
            return None
        t = text.strip()
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        # direct load
        try:
            return json.loads(t)
        except Exception:
            pass
        # fallback: outermost JSON
        m = re.search(r"\{[\s\S]*\}$", t)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None
   
    def _match_choice_in_list(self, choice: str, items: List[Dict[str, Any]]) -> bool:
        if not choice or choice in ("-", "Not available in given data"):
            return True
        name = str(choice).split(",")[0].strip().lower()
        for r in items:
            if isinstance(r, dict) and r.get("name") and r["name"].strip().lower() == name:
                return True
        return False

    def validate_plan(self, skeleton_days, llm_days, cities,persona=None):
        errors = []
        is_adventure = bool(persona and "adventure" in persona.lower())


        # -------------------- allowed names --------------------
        all_restaurants = {
            r["name"].lower()
            for c in cities
            for r in c.get("restaurants_ranked", [])
        }

        all_attractions = {
            a["name"].lower()
            for c in cities
            for a in c.get("attractions_ranked", [])
        }
        # -------------------- city-wise attractions --------------------
        attractions_by_city = {
            c["city"].lower(): {
                a["name"].lower()
                for a in c.get("attractions_ranked", [])
            }
            for c in cities
        }

        used_attractions_by_city = {
            city: set() for city in attractions_by_city
        }


        # -------------------- helpers --------------------
        def parse_city(val):
            if not val:
                return ""
            parts = [p.strip() for p in val.split(",") if p.strip()]
            return parts[-1] if len(parts) >= 2 else ""

        def parse_name(val):
            return val.rsplit(",", 1)[0].strip().lower() if val else ""

        def norm(s):
            return s.lower().strip() if s else ""

        n_days = len(skeleton_days)

        # ======================================================
        # MAIN LOOP
        # ======================================================
        for i, (skel, out) in enumerate(zip(skeleton_days, llm_days)):
            day = skel["day"]

            is_first = i == 0
            is_last = i == n_days - 1
            has_transport = skel["transportation"] != "-"

            origin = dest = None
            if has_transport:
                m = re.search(r"from\s+(.*?)\s+to\s+(.*?)(,|$)", skel["transportation"])
                if m:
                    origin, dest = m.group(1), m.group(2)

            # ==================================================
            # DAY TYPE 1️⃣ — NON-TRAVEL DAY
            # ==================================================
            if not has_transport:
                allowed_city = norm(skel["current_city"])
                max_attractions = 3 if is_adventure else 2

                # ---------- meals ----------
                for meal in ("breakfast", "lunch", "dinner"):
                    sk = skel[meal]
                    val = out.get(meal, "-")

                    if sk == "-" and val != "-":
                        out[meal] = "-"
                        continue

                    if sk == "" and val in ("-", ""):
                        errors.append({"day": day, "field": meal, "reason": "Meal required by skeleton"})
                        continue

                    if val == "-":
                        continue

                    if parse_name(val) not in all_restaurants:
                        errors.append({"day": day, "field": meal, "reason": "Invalid restaurant"})
                    elif norm(parse_city(val)) != allowed_city:
                        errors.append({"day": day, "field": meal, "reason": "Wrong meal city"})

                # ---------- attractions ----------
                val = out.get("attraction", "-")

                if skel["attraction"] == "-" and val != "-":
                    out["attraction"] = "-"
                    continue

                if skel["attraction"] == "" and val in ("-", ""):
                    remaining = (
                        attractions_by_city.get(allowed_city, set())
                        - used_attractions_by_city.get(allowed_city, set())
                    )

                    if remaining:
                        errors.append({
                            "day": day,
                            "field": "attraction",
                            "reason": "Attraction required (available in this city)"
                        })
                    continue


                if val in ("-", ""):
                    continue

                parts = [p.strip() for p in val.split(";") if p.strip()]
                if len(parts) > max_attractions:
                    errors.append({
                        "day": day,
                        "field": "attraction",
                        "reason": f"Too many attractions (max {max_attractions} allowed)"
                    })

                for p in parts:
                    if parse_name(p) not in all_attractions:
                        errors.append({"day": day, "field": "attraction", "reason": "Invalid attraction"})
                    elif norm(parse_city(p)) != allowed_city:
                        errors.append({"day": day, "field": "attraction", "reason": "Wrong attraction city"})
                    else:
                        used_attractions_by_city[allowed_city].add(parse_name(p))

            # ==================================================
            # DAY TYPE 2️⃣ — FIRST DAY (ARRIVAL)
            # ==================================================
            elif is_first:
                allowed_city = norm(dest)

                # ---------------- parse arrival time ----------------
                arr_min = None
                arr = re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", skel["transportation"])
                if arr:
                    h, m = map(int, arr.group(1).split(":"))
                    arr_min = h * 60 + m

                # ---------------- determine attraction limit ----------------
                if arr_min is not None and arr_min <= 8 * 60 + 10:
                    max_attractions = 2
                elif arr_min is not None and arr_min <= 16 * 60 + 45:
                    max_attractions = 1
                else:
                    max_attractions = 0

                # ---------------- meals ----------------
                for meal in ("breakfast", "lunch", "dinner"):
                    sk = skel[meal]
                    val = out.get(meal, "-")

                    if sk == "-" and val != "-":
                        out[meal] = "-"
                        continue

                    if sk == "" and val in ("-", ""):
                        errors.append({"day": day, "field": meal, "reason": "Meal required by skeleton"})
                        continue

                    if val == "-":
                        continue

                    if parse_name(val) not in all_restaurants:
                        errors.append({"day": day, "field": meal, "reason": "Invalid restaurant"})
                    elif norm(parse_city(val)) != allowed_city:
                        errors.append({"day": day, "field": meal, "reason": "Meal must be in destination"})

                # ---------------- attractions ----------------
                val = out.get("attraction", "-")

                if skel["attraction"] == "-" and val != "-":
                    out["attraction"] = "-"
                    continue

                if skel["attraction"] == "" and val in ("-", ""):
                    if max_attractions > 0:
                        remaining = (
                            attractions_by_city.get(allowed_city, set())
                            - used_attractions_by_city.get(allowed_city, set())
                        )
                        if remaining:
                            errors.append({
                                "day": day,
                                "field": "attraction",
                                "reason": "Attraction required (available in this city)"
                            })
                    continue

                if val in ("-", ""):
                    continue

                parts = [p.strip() for p in val.split(";") if p.strip()]
                if len(parts) > max_attractions:
                    errors.append({
    "day": day,
    "field": "attraction",
    "reason": f"Too many attractions (max {max_attractions} allowed)"
})


                for p in parts:
                    name = parse_name(p)
                    city = norm(parse_city(p))

                    if name not in all_attractions:
                        errors.append({"day": day, "field": "attraction", "reason": "Invalid attraction"})
                    elif city != allowed_city:
                        errors.append({"day": day, "field": "attraction", "reason": "Attraction must be destination"})
                    else:
                        used_attractions_by_city[allowed_city].add(name)

            # ==================================================
            # DAY TYPE 3️⃣ — LAST DAY (DEPARTURE)
            # ==================================================
            elif is_last:
                allowed_city = norm(origin)

                # ---------------- parse departure time ----------------
                dep_min = None
                dep = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", skel["transportation"])
                if dep:
                    h, m = map(int, dep.group(1).split(":"))
                    dep_min = h * 60 + m

                # ---------------- determine attraction limit ----------------
                if dep_min is not None and dep_min >= 18 * 60 + 30:
                    max_attractions = 2
                elif dep_min is not None and dep_min >= 13 * 60 + 20:
                    max_attractions = 1
                else:
                    max_attractions = 0

                # ---------------- meals ----------------
                for meal in ("breakfast", "lunch", "dinner"):
                    sk = skel[meal]
                    val = out.get(meal, "-")

                    if sk == "-" and val != "-":
                        out[meal] = "-"
                        continue

                    if sk == "" and val in ("-", ""):
                        errors.append({"day": day, "field": meal, "reason": "Meal required by skeleton"})
                        continue

                    if val == "-":
                        continue

                    if parse_name(val) not in all_restaurants:
                        errors.append({"day": day, "field": meal, "reason": "Invalid restaurant"})
                    elif norm(parse_city(val)) != allowed_city:
                        errors.append({"day": day, "field": meal, "reason": "Meal must be in origin"})

                # ---------------- attractions ----------------
                val = out.get("attraction", "-")

                if skel["attraction"] == "-" and val != "-":
                    out["attraction"] = "-"
                    continue

                if skel["attraction"] == "" and val in ("-", ""):
                    if max_attractions > 0:
                        remaining = (
                            attractions_by_city.get(allowed_city, set())
                            - used_attractions_by_city.get(allowed_city, set())
                        )
                        if remaining:
                            errors.append({
                                "day": day,
                                "field": "attraction",
                                "reason": "Attraction required (available in this city)"
                            })
                    continue

                if val in ("-", ""):
                    continue

                parts = [p.strip() for p in val.split(";") if p.strip()]
                if len(parts) > max_attractions:
                    errors.append({
    "day": day,
    "field": "attraction",
    "reason": f"Too many attractions (max {max_attractions} allowed)"
})


                for p in parts:
                    name = parse_name(p)
                    city = norm(parse_city(p))

                    if name not in all_attractions:
                        errors.append({"day": day, "field": "attraction", "reason": "Invalid attraction"})
                    elif city != allowed_city:
                        errors.append({"day": day, "field": "attraction", "reason": "Attraction must be origin"})
                    else:
                        used_attractions_by_city[allowed_city].add(name)


            # ==================================================
            # DAY TYPE 4️⃣ — INTER-CITY DAY
            # ==================================================
            else:
                max_attractions = 2

                # ---------------- parse arrival & departure ----------------
                arr_min = dep_min = None

                arr = re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", skel["transportation"])
                if arr:
                    h, m = map(int, arr.group(1).split(":"))
                    arr_min = h * 60 + m

                dep = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", skel["transportation"])
                if dep:
                    h, m = map(int, dep.group(1).split(":"))
                    dep_min = h * 60 + m

                # ---------------- meals ----------------
                for meal in ("breakfast", "lunch", "dinner"):
                    sk = skel[meal]
                    val = out.get(meal, "-")

                    if sk == "-" and val != "-":
                        out[meal] = "-"
                        continue

                    if sk == "" and val in ("-", ""):
                        errors.append({"day": day, "field": meal, "reason": "Meal required by skeleton"})
                        continue

                    if val == "-":
                        continue

                    if parse_name(val) not in all_restaurants:
                        errors.append({"day": day, "field": meal, "reason": "Invalid restaurant"})
                        continue

                    city = norm(parse_city(val))
                    expected = dest if (arr_min is not None and arr_min <= 21 * 60) else origin

                    if city != norm(expected):
                        errors.append({
                            "day": day,
                            "field": meal,
                            "reason": f"{meal.capitalize()} must be in {expected}"
                        })

                # ---------------- attraction city windows (MANUAL PARITY) ----------------
                origin_window = dep_min is not None and dep_min >= 13 * 60 + 20
                dest_window   = arr_min is not None and arr_min <= 16 * 60 + 45

                strong_origin = dep_min is not None and dep_min >= 18 * 60 + 30
                strong_dest   = arr_min is not None and arr_min <= 8 * 60 + 10

                if strong_origin:
                    allowed_cities = [norm(origin)]
                elif strong_dest:
                    allowed_cities = [norm(dest)]
                elif origin_window and dest_window:
                    allowed_cities = [norm(origin), norm(dest)]   # MIXED CASE
                elif origin_window:
                    allowed_cities = [norm(origin)]
                elif dest_window:
                    allowed_cities = [norm(dest)]
                else:
                    allowed_cities = []

                # ---------------- attractions ----------------
                val = out.get("attraction", "-")

                if skel["attraction"] == "-" and val != "-":
                    out["attraction"] = "-"
                    continue

                if skel["attraction"] == "" and val in ("-", ""):
                    if allowed_cities:
                        remaining = set()
                        for c in allowed_cities:
                            remaining |= (
                                attractions_by_city.get(c, set())
                                - used_attractions_by_city.get(c, set())
                            )

                        if remaining:
                            errors.append({
                                "day": day,
                                "field": "attraction",
                                "reason": "Attraction required (available in allowed city)"
                            })
                    continue

                if val in ("-", ""):
                    continue

                parts = [p.strip() for p in val.split(";") if p.strip()]
                if len(parts) > max_attractions:
                    errors.append({
    "day": day,
    "field": "attraction",
    "reason": f"Too many attractions (max {max_attractions} allowed)"
})


                # enforce 1 per city in mixed case
                seen_city_count = {}

                for p in parts:
                    name = parse_name(p)
                    city = norm(parse_city(p))

                    if name not in all_attractions:
                        errors.append({"day": day, "field": "attraction", "reason": "Invalid attraction"})
                        continue

                    if city not in allowed_cities:
                        errors.append({
                            "day": day,
                            "field": "attraction",
                            "reason": f"Attraction must be in one of {allowed_cities}"
                        })
                        continue

                    seen_city_count[city] = seen_city_count.get(city, 0) + 1
                    if len(allowed_cities) == 2 and seen_city_count[city] > 1:
                        errors.append({
                            "day": day,
                            "field": "attraction",
                            "reason": "Only one attraction per city allowed on inter-city day"
                        })
                        continue

                    used_attractions_by_city[city].add(name)


        return {
            "days": llm_days,
            "errors": errors,
            "is_valid": len(errors) == 0
        }

    def build_repair_prompt(
        self,
        skeleton: Dict[str, Any],
        previous_output: Dict[str, Any],
        validation_errors: List[Dict[str, Any]]
    ) -> str:
        lines = [
            "You previously generated an INVALID schedule.",
            "Fix ONLY the listed issues.",
            "Do NOT change transportation, current_city, or accommodation.",
            "",
            "=== SKELETON ===",
            json.dumps(skeleton, indent=2),
            "",
            "=== YOUR PREVIOUS OUTPUT ===",
            json.dumps(previous_output, indent=2),
            "",
            "=== VALIDATION ERRORS ==="
        ]

        for i, e in enumerate(validation_errors, 1):
            lines.append(f"{i}. Day {e.get('day')} – {e['field']}")
            lines.append(f"   Reason: {e['reason']}")
            if "allowed_options" in e:
                lines.append("   Allowed options:")
                for opt in e["allowed_options"]:
                    lines.append(f"   - {opt}")
            lines.append("")

        # ---------------- INSTRUCTIONS ----------------
        lines.append(
            "INSTRUCTIONS:\n"
            "- Fix ONLY the fields mentioned above.\n"
            "- For any field NOT mentioned in the validation errors, you MUST copy the value EXACTLY from the PREVIOUS OUTPUT.\n"
            "- If allowed options are provided, use ONLY those options.\n"
            '- If the skeleton value is "", you MUST fill it.\n'
            '- If the skeleton value is "-", you MUST set it to "-".\n'
            "- If allowed options are not provided, choose ANY valid option from the city data.\n"
            "- Do NOT reintroduce fields that were removed by validation.\n"
            "- Do NOT repeat the attractions and restaurant names, While adding check the restaurant name or attraction name is present in other place or not . If not available then place it otherwise try with other.\n"
            "- Do NOT add, remove, or rename keys.\n"
            "- Return ONLY valid JSON in EXACTLY this format:\n\n"
            "{\n"
            '  "days": [ ... ]\n'
            "}\n"
            "- DO NOT include 'cities' or any other keys.\n"
        )

        # ---------------- EXAMPLES ----------------
        lines.append(
            "EXAMPLES (HOW TO FIX VALIDATION ERRORS):\n\n"

            "EXAMPLE 1: REQUIRED ATTRACTION\n"
            "Error:\n"
            "  Day 3 – attraction\n"
            "  Reason: Attraction required by skeleton\n\n"
            "Skeleton shows:\n"
            '{ "attraction": "" }\n\n'
            "Correct fix:\n"
            '{ "attraction": "Some Valid Attraction, CityName" }\n\n'

            "EXAMPLE 2: REQUIRED MEAL\n"
            "Error:\n"
            "  Day 2 – lunch\n"
            "  Reason: Meal required by skeleton\n\n"
            "Skeleton shows:\n"
            '{ "lunch": "" }\n\n'
            "Correct fix:\n"
            '{ "lunch": "Some Valid Restaurant, CityName" }\n\n'

            "EXAMPLE 3: WRONG MEAL CITY\n"
            "Error:\n"
            "  Day 1 – breakfast\n"
            "  Reason: Meal must be in destination\n\n"
            "Skeleton allows breakfast:\n"
            '{ "breakfast": "" }\n\n'
            "Correct fix:\n"
            '{ "breakfast": "Some Valid Restaurant, DestinationCity" }\n\n'

            "EXAMPLE 4: TOO MANY ATTRACTIONS\n"
            "Error:\n"
            "  Day 4 – attraction\n"
            "  Reason: Too many attractions\n\n"
            "Correct fix:\n"
            '{ "attraction": " Valid Attraction(s), CityName" }\n'
        )

        return "\n".join(lines)

    def validate_skeleton(self, skeleton_days):
        """
        FINAL skeleton builder.
        ""  -> LLM MUST fill
        "-" -> LLM MUST NOT fill

        Day types handled:
        1. Non-travel day
        2. First day (arrival-based)
        3. Last day (departure-based)
        4. Inter-city travel day
        """

        import re

        def hhmm_to_min(t):
            if not t:
                return None
            h, m = map(int, t.split(":"))
            return h * 60 + m

        n_days = len(skeleton_days)

        for i, skel in enumerate(skeleton_days):
            has_transport = skel.get("transportation") != "-"
            is_first = i == 0
            is_last = i == n_days - 1

            arr_min = dep_min = None

            if has_transport:
                arr = re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", skel["transportation"])
                dep = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", skel["transportation"])
                if arr:
                    arr_min = hhmm_to_min(arr.group(1))
                if dep:
                    dep_min = hhmm_to_min(dep.group(1))

            # ==================================================
            # 1️⃣ NON-TRAVEL DAY
            # ==================================================
            if not has_transport:
                skel["breakfast"] = ""
                skel["lunch"] = ""
                skel["dinner"] = ""
                skel["attraction"] = ""
                continue

            # ==================================================
            # 2️⃣ FIRST DAY (ARRIVAL DAY)
            # ==================================================
            if is_first:
                if (
                    dep_min is not None and
                    arr_min is not None and
                    arr_min < dep_min
                ):
                    skel["breakfast"] = "-"
                    skel["lunch"] = "-"
                    skel["dinner"] = "-"
                    skel["attraction"] = "-"
                    continue
                skel["breakfast"] = "" if arr_min is not None and arr_min <= 8*60+10  else "-"
                skel["lunch"]     = "" if arr_min is not None and arr_min <= 13*60 else "-"
                skel["dinner"]    = "" if arr_min is not None and arr_min  <= 20 * 60  else "-"
                skel["attraction"]= "" if arr_min is not None and arr_min <= 16*60 + 45 else "-"
                continue

            # ==================================================
            # 3️⃣ LAST DAY (DEPARTURE DAY)
            # ==================================================
            if is_last:
                skel["breakfast"] = "" if dep_min is not None and dep_min >= 9*60 + 20 else "-"
                skel["lunch"]     = "" if dep_min is not None and dep_min >= 14*60 + 50 else "-"
                skel["dinner"]    = "" if dep_min is not None and dep_min >= 20*60 + 45 else "-"
                skel["attraction"]= "" if dep_min is not None and dep_min >= 13*60 + 20 else "-"
                continue

            # ==================================================
            # 4️⃣ INTER-CITY TRAVEL DAY
            # ==================================================

            # Breakfast
            skel["breakfast"] = "" if (
                (arr_min is not None and arr_min <= 8*60 + 10) or
                (dep_min is not None and dep_min >= 9*60 + 20)
            ) else "-"

            # Lunch
            skel["lunch"] = "" if (
                (arr_min is not None and arr_min <= 13*60) or
                (dep_min is not None and dep_min >= 14*60 + 50)
            ) else "-"

            # Dinner
            skel["dinner"] = "" if (
                (arr_min is not None and arr_min <= 20*60) or
                (dep_min is not None and dep_min >= 20*60 + 45)
            ) else "-"

            # Attraction
            skel["attraction"] = "" if (
                (arr_min is not None and arr_min <= 16*60 + 45) or
                (dep_min is not None and dep_min >= 13*60 + 20)
            ) else "-"

        return skeleton_days


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
                        dep = "16:00"
                    else:
                        dep = "16:00"
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
                    dep_min = hhmm_to_min(dep)

                    # Arrival after midnight → next calendar day
                    if (
                        dep_min is not None and
                        arr_min is not None and
                        arr_min < dep_min
                    ):
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
                if dep_min is None or dep_min < 14 * 60 + 50:
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
                (dep_min is not None and dep_min >= 14 * 60 + 50)
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

    def _cities_for_prompt(self, cities):
        clean = []

        for c in cities:
            c2 = {
                "city": c["city"],

                # ✅ KEEP restaurants (compressed)
                "restaurants_ranked": [
                    {
                        "name": r.get("name"),
                        "cuisine": (
                            r.get("cuisines")[0]
                            if isinstance(r.get("cuisines"), list) and r.get("cuisines")
                            else r.get("cuisines")
                        ),
                        "avg_cost": r.get("avg_cost"),
                        "rating": r.get("aggregate_rating"),
                    }
                    for r in c.get("restaurants_ranked", [])
                ],

                # ✅ KEEP attractions (compressed)
                "attractions_ranked": [
                    {
                        "name": a.get("name"),
                        "category": (
                            a.get("categories")[0]
                            if isinstance(a.get("categories"), list) and a.get("categories")
                            else a.get("categories")
                        )
                    }
                    for a in c.get("attractions_ranked", [])
                ],

                # ❌ REMOVE heavy junk
                # raw_transit_rows already removed
                # descriptions removed
                # lat/long removed
            }

            clean.append(c2)

        return clean

    # -------------------------
    # Main entry
    # -------------------------
    def generate_final_schedule_from_structured_input(
        self, structured_input: Dict[str, Any], query: str = "",
    retry_attempt: int = 1
    ) -> Dict[str, Any]:

        """
        This version is compatible with the NEW `combined` schema and supports
        3 / 5 / 7 day trips using LLM-based scheduling.
        """

        # ------------------------------------------------------------
        # 1. Basic extraction
        # ------------------------------------------------------------
        dates = structured_input.get("dates", [])
        n_days = len(dates)
        cities = structured_input.get("cities", [])
        # print(cities)
        transport_legs = structured_input.get("transportation", {}).get("legs", [])
        origin_city = structured_input.get("origin", "")
        people = int(structured_input.get("people_number") or 1)
        budget = float(structured_input.get("budget") or 0)

        if n_days not in (3, 5, 7):
            return {"error": f"Unsupported trip length: {n_days}"}

        # ------------------------------------------------------------
        # 2. Build DAY → CITY MAP (YOUR RULES)
        # ------------------------------------------------------------
        day_city = []

        if n_days == 3:
            day_city = [
                cities[0]["city"],  # Day 1 (travel)
                cities[0]["city"],  # Day 2
                cities[0]["city"],  # Day 3 (travel)
            ]

        elif n_days == 5:
            day_city = [
                cities[0]["city"],  # Day 1 (travel)
                cities[0]["city"],  # Day 2
                cities[0]["city"],  # Day 3 (travel city1→city2)
                cities[1]["city"],  # Day 4
                cities[1]["city"],  # Day 5 (travel)
            ]

        elif n_days == 7:
            day_city = [
                cities[0]["city"],  # Day 1 (travel)
                cities[0]["city"],  # Day 2
                cities[0]["city"],  # Day 3 (travel)
                cities[1]["city"],  # Day 4
                cities[1]["city"],  # Day 5 (travel)
                cities[2]["city"],  # Day 6
                cities[2]["city"],  # Day 7 (travel)
            ]


        # ------------------------------------------------------------
        # 3. Index helpers
        # ------------------------------------------------------------
        city_map = {c["city"]: c for c in cities}
        transport_by_day = {leg["day"]: leg for leg in transport_legs}
        # ------------------------------------------------------------
        # 4. Build SKELETON DAYS (structure only)
        # ------------------------------------------------------------
        accommodation_by_city = {
            c["city"]: f'{c["accommodation"]["name"]}, {c["city"]}'
            for c in cities
        }
        # print(n_days,dates,day_city,transport_legs,accommodation_by_city)

        days_skeleton = self.build_days_skeleton(
            n_days=n_days,
            dates=dates,
            day_city=day_city,
            transport_legs=transport_legs,
            accommodation_by_city=accommodation_by_city
        )
        days_skeleton = self.validate_skeleton(days_skeleton)
        # print("Days Skeleton:",days_skeleton)

        # ------------------------------------------------------------
        # 5. LLM PROMPT (LLM FILLS MEALS + ATTRACTIONS ONLY)
        # ------------------------------------------------------------
        prompt = (
            PLANNER_SHORT_INSTRUCTION
            + "\n\nYou are given a fixed day-by-day skeleton.\n"
            + "DO NOT change transportation, current_city, or accommodation.\n"
            + "Only fill meals and attractions.\n\n"

            + "ABSOLUTE RULES:\n"
            + "- Skeleton is the source of truth\n"
            + "- If a field is '-', keep it '-'\n"
            + "- If a field is '', you MUST fill it\n"
            + "- Persona and local constraints influence selection ONLY, not feasibility\n\n"

            # -------- PERSONA --------
            + "PERSONA (PREFERENCE CONTEXT):\n"
            + f"{structured_input.get('persona', 'None')}\n"
            + "Use persona ONLY to:\n"
            + "- Decide attraction count on NON-TRAVEL days\n"
            + "- Bias attraction types and pacing\n"
            + "- NEVER override skeleton timing or feasibility\n\n"

            # -------- LOCAL CONSTRAINTS --------
            + "LOCAL CONSTRAINTS (FILTER CONTEXT):\n"
            + self._serialize_for_prompt(
                structured_input.get("constraints", {})
            )
            + "\nRules for local constraints:\n"
            + "- Apply only when choosing among VALID options\n"
            + "- If constraint conflicts with skeleton → IGNORE constraint\n"
            + "- If no option matches constraint → choose best available option\n"
            + "- NEVER invent or remove cities, transport, or accommodation\n\n"

            # -------- INPUT JSON --------
            + "INPUT_JSON:\n"
            + self._serialize_for_prompt({
                "days": days_skeleton,
                "cities": self._cities_for_prompt(cities)
            })

            + f"\n\nQUERY:\n{query}\n\n"
            + f"\nReturn ONLY valid JSON.\nREMEMBER: EXACTLY {n_days} days required."
        )

        # print(prompt)
        # ---------------- DEBUG PROMPT SIZE ----------------
        # prompt_text = prompt

        # print("========== PROMPT DEBUG ==========")
        # print("Prompt characters:", len(prompt_text))
        # print("Approx tokens:", len(prompt_text) // 4)

        # with open("/scratch/sg/Vijay/TripCraft/debug/prompt.txt", "w", encoding="utf-8") as f:
        #     f.write(prompt)

        # print("✅ Prompt saved to debug/prompt.txt")

        # print("Prompt saved to planner_prompt_debug.txt")
        # print("==================================")


        raw = self.llm.generate(prompt)
        # print("Response:",raw)
        parsed = self._extract_json(raw)

        if not parsed or "days" not in parsed:
            # print("Hi")
            if len(parsed["days"]) != len(days_skeleton):
                return {
                    "error": "LLM day count mismatch",
                    "expected_days": len(days_skeleton),
                    "raw": raw
                }

            return {"error": "LLM returned invalid JSON", "raw": raw}

        days = parsed["days"]
        #  HARD FIX: Preserve accommodation from skeleton
        for i in range(len(days)):
            days[i]["accommodation"] = days_skeleton[i]["accommodation"]

        validation = self.validate_plan(
            skeleton_days=days_skeleton,
            llm_days=days,
            cities=cities,
            persona=structured_input.get("persona")
        )
        days = validation["days"]
        # print("Validation result:", validation)
        if not validation["is_valid"]:
            # 🔧 Expose required-but-missing fields as empty ("") so LLM can fill them
            for err in validation["errors"]:
                day_idx = err["day"] - 1
                field = err["field"]

                # if skeleton requires a value, unblock LLM by setting ""
                if days_skeleton[day_idx][field] == "":
                    days[day_idx][field] = ""

            repair_prompt = self.build_repair_prompt(
                skeleton={
                    "days": days_skeleton,
                    "cities": self._cities_for_prompt(cities)
                },
                previous_output=parsed,
                validation_errors=validation["errors"]
            )
            # print("Retry Prompt:",repair_prompt)
            # with open("/scratch/sg/Vijay/TripCraft/debug/repair_prompt.txt", "w", encoding="utf-8") as f:
            #     f.write(repair_prompt)

            # print("✅ Repair prompt saved to debug/repair_prompt.txt")

            raw_retry = self.llm.generate(repair_prompt)
            # print("Retry Response:",raw_retry)
            parsed_retry = self._extract_json(raw_retry)
            

            if not parsed_retry or "days" not in parsed_retry:
                return {
                    "error": "LLM retry failed to return valid JSON",
                    "validation_errors": validation["errors"]
                }

            # validate again (ONLY ONCE)
            retry_validation = self.validate_plan(
                skeleton_days=days_skeleton,
                llm_days=parsed_retry["days"],
                cities=cities,
                persona=structured_input.get("persona")
            )
            days=retry_validation["days"]
            #  Preserve accommodation again after retry
            for i in range(len(days)):
                days[i]["accommodation"] = days_skeleton[i]["accommodation"]

            if not retry_validation["is_valid"]:
                if retry_attempt >= 3:
                    # ✅ FINAL ATTEMPT FALLBACK:
                    # return partially corrected days instead of error
                    parsed = parsed_retry
                    parsed["days"] = days
                    parsed["_agent_warnings"] = (
                        parsed.get("_agent_warnings", [])
                        + ["Final retry: schedule returned with unresolved validation issues"]
                    )
                else:
                    return {
                        "error": "LLM failed validation after retry",
                        "validation_errors": retry_validation["errors"]
                    }
            else:
                # ✅ retry succeeded
                parsed = parsed_retry
                days = parsed["days"]

            # ✅ retry succeeded
            # parsed = parsed_retry
            # days = parsed["days"]




        # ------------------------------------------------------------
        # 6. VALIDATION (restaurants & attractions per city)
        # ------------------------------------------------------------
        # ------------------------------------------------------------
        # ADD EVENTS (DATE + CITY BASED, DETERMINISTIC)
        # ------------------------------------------------------------
        city_event_map = {}

        for city_obj in cities:
            for e in city_obj.get("events_ranked", []):
                city_event_map.setdefault(
                    (e["city"], e["date"]), []
                ).append(e)

        EVENING_START = 18 * 60 + 30
        EVENING_END = 20 * 60

        for i, day in enumerate(days):
            day_date = dates[i]

            # Resolve city name (destination for travel days)
            if "from " in day["current_city"]:
                city = day["current_city"].split(" to ")[-1]
            else:
                city = day["current_city"]

            # Extract timing again if needed
            transport = day["transportation"]
            dep_min = arr_min = None

            if transport != "-":
                dep = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", transport)
                arr = re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", transport)

                if dep:
                    h, m = map(int, dep.group(1).split(":"))
                    dep_min = h * 60 + m
                if arr:
                    h, m = map(int, arr.group(1).split(":"))
                    arr_min = h * 60 + m

            # ---------- EVENT ELIGIBILITY CHECK ----------
            remove_event = False

            # First day / inter-city arrival too late
            if arr_min is not None and arr_min >= EVENING_START:
                remove_event = True

            # Last day / inter-city departure in evening
            if dep_min is not None and EVENING_START <= dep_min <= EVENING_END:
                remove_event = True

            if remove_event:
                day["event"] = "-"
                continue

            # ---------- ASSIGN EVENT ----------
            events_today = city_event_map.get((city, day_date), [])
            if events_today:
                e = events_today[0]
                day["event"] = f'{e["name"]}, {city}'
            else:
                day["event"] = "-"
        
        pois_agent=POIsAgent(llm=self.llm)
        # print(parsed["days"])
        poi_result = pois_agent.generate_poi_list(
            days=parsed["days"],
            structured_input=structured_input
        )

        parsed["point_of_interest_list"] = poi_result
        for idx, day in enumerate(parsed["days"]):
            day["point_of_interest_list"] = poi_result.get(idx + 1, "")

        warnings = []

        for i, day in enumerate(days):
            city = day_city[i]
            city_block = city_map[city]
            restaurants = city_block.get("restaurants_ranked", [])
            attractions = city_block.get("attractions_ranked", [])

            # Meals
            for meal in ("breakfast", "lunch", "dinner"):
                val = day.get(meal)
                if val and val not in ("-", ""):

                    # split ONLY on last comma → separates city correctly
                    if "," in val:
                        name_part = val.rsplit(",", 1)[0].strip()
                    else:
                        name_part = val.strip()

                    # compare against restaurant names
                    matched = False
                    for r in restaurants:
                        if r["name"].strip().lower() == name_part.lower():
                            matched = True
                            break

                    if not matched:
                        warnings.append(f"Removed invalid restaurant '{val}' on day {i+1}")
                        # day[meal] = "-"


            # Attractions
            attr = day.get("attraction", "-")
            if attr not in ("-", ""):
                parts = [p.strip().rstrip(";") for p in attr.split(";") if p.strip()]
                keep = []
                for p in parts:
                    name = p.split(",")[0].strip()
                    if self._match_choice_in_list(name, attractions):
                        keep.append(f"{name}, {city}")
                # day["attraction"] = "; ".join(keep) + (";" if keep else "-")

        # ------------------------------------------------------------
        # 7. BUDGET COMPUTATION (CORRECT)
        # ------------------------------------------------------------
        total_cost = 0.0
        # print(warnings,days)
        # print(structured_input)

        # Flights
        for leg in transport_legs:
            mode = leg.get("mode", "").lower()

            if mode == "flight" and "price" in leg["details"]:
                total_cost += leg["details"]["price"] * people

            elif mode == "self-driving":
                cost = leg["details"].get("cost")
                if cost is not None:
                    total_cost += cost * ((people + 4) // 5)

            elif mode == "taxi":
                cost = leg["details"].get("cost")
                if cost is not None:
                    total_cost += cost * ((people + 3) // 4)


        # Accommodation
        for c in cities:
            acc = c["accommodation"]
            nights = sum(
                1 for i, d in enumerate(days)
                if i != n_days - 1
                and d["accommodation"] != "-"
                and c["city"] in d["accommodation"]
            )

            max_occ = acc.get("maximum_occupancy", 1)
            units = (people + max_occ - 1) // max_occ

            total_cost += acc["price_per_night"] * nights * units


        # Meals
        for d in days:
            if "from " in d["current_city"]:
                continue  # skip travel days

            city = d["current_city"]

            # Fix travel-day city
            if city.startswith("from "):
                city = city.split(" to ")[-1].strip()

            for meal in ("breakfast", "lunch", "dinner"):
                val = d.get(meal)
                if not val or val == "-":
                    continue

                # FIX: split on LAST comma only
                name = val.rsplit(",", 1)[0].strip().lower()

                for r in city_map.get(city, {}).get("restaurants_ranked", []):
                    if r["name"].lower() == name:
                        total_cost += float(r["avg_cost"]) * people
                        break



        parsed["budget_used"] = round(total_cost, 2)
        parsed["budget_remaining"] = round(budget - total_cost, 2)
        parsed["budget_ok"] = parsed["budget_remaining"] >= 0

        # if warnings:
            # print("Hi")
            # parsed["_agent_warnings"] = warnings
        # print("Parsed",parsed,warnings)

        return parsed
