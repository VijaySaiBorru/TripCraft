from typing import Any, Dict, List,Optional

class FIRSTDAYPOIAGENT:
    def __init__(self):
        pass

    def to_min(self, t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    
    def extract_arrival_time(self, day: dict) -> Optional[int]:
        import re
        t = day.get("transportation", "")
        m = re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", t)
        return self.to_min(m.group(1)) if m else None

    def clean_place_name(self, name: str, cities: List[Dict[str, Any]]) -> str:
        if not name:
            return name
        name = name.strip()
        for c in cities:
            city = c.get("city")
            if city and name.endswith(f", {city}"):
                return name[: -(len(city) + 2)].strip()
        return name

    def build_day_adjusted_duration_map( self, day: Dict[str, Any], base_duration_map: Dict[str, int],all_days: List[Dict[str, Any]], ) -> Dict[str, int]:
        MIN_DUR = 60         
        MAX_DUR = 360         
        K_SHIFT = 16.61       
        MU_D_MAX = 4
        persona = (self.persona or "").lower()
        is_adventure = "adventure" in persona
        attractions = [
            self.clean_place_name(a.strip(), self.cities)
            for a in day.get("attraction", "").split(";")
            if a.strip() and a.strip() != "-"
        ]
        if not attractions:
            return {}
        max_atts_day = max(
            len([
                x for x in d.get("attraction", "").split(";")
                if x.strip() and x.strip() != "-"
            ])
            for d in all_days  
        ) or 1
        adjusted = {}
        for a in attractions:
            raw_base = base_duration_map.get(a, 120)
            base = max(MIN_DUR, min(raw_base, MAX_DUR))
            if is_adventure:
                mu_d = base - (K_SHIFT * (max_atts_day - 1))
            else:
                mu_d = base + (K_SHIFT * (MU_D_MAX - max_atts_day))
            mu_d = max(MIN_DUR, min(mu_d, MAX_DUR))
            adjusted[a] = int(round(mu_d))
        return adjusted

    def build_first_day_execution_hints( self, day: dict, day_type: str, attraction_duration_map: dict,) -> str:
        if day_type != "FIRST_DAY":
            return ""
        accommodation = day.get("accommodation")
        breakfast = day.get("breakfast")
        lunch = day.get("lunch")
        dinner = day.get("dinner")
        arrival_time = self.extract_arrival_time(day)
        if arrival_time is None:
            raise ValueError("FIRST_DAY requires arrival_time")
        attractions = [
            self.clean_place_name(a.strip(), self.cities)
            for a in day.get("attraction", "").split(";")
            if a.strip() and a.strip() != "-"
        ]
        duration_block = "\n".join(
            f"- {a} = {attraction_duration_map.get(a, 120)} minutes"
            for a in attractions
        )
        BUFFER = 30
        checkin_duration = 30
        arrival_buffer_start = arrival_time
        arrival_buffer_end = arrival_time + BUFFER
        checkin_start = arrival_buffer_end
        checkin_end = checkin_start + checkin_duration
        step = 0
        def STEP(title: str) -> str:
            nonlocal step
            block = f"""
    ----------------------------------------------------
    STEP {step} — {title}
    ----------------------------------------------------
    """
            step += 1
            return block

        instructions = f"""
    EXECUTION MODE — FOLLOW EXACTLY
    NO REORDERING. NO INVENTION. NO SKIPPING.

    This is FIRST_DAY.
    ALL time values are INTEGER MINUTES.

    ==============================
    FIXED AUTHORITATIVE EVENTS
    ==============================

    Arrival buffer (FIXED):
    - arrival_time = {arrival_time}
    - buffer_start = {arrival_buffer_start}
    - buffer_end = {arrival_buffer_end}

    ==============================
    ARRIVAL CHECKIN
    ==============================

    Arrival accommodation check-in (FIXED):
    - stay_start = {checkin_start}
    - stay_end = {checkin_end}

    Add POI EXACTLY as follows: (ALREADY DECIDED — DO NOT MODIFY):
    "{self.clean_place_name(accommodation.strip(), self.cities)}", stay from {checkin_start} to {checkin_end};
    FIXED POI OUTPUT RULE (ABSOLUTE):
    - The arrival check-in POI is a VALID POI and MUST appear in the ITINERARY
    - It MUST be printed BEFORE any STEP-generated POIs
    - It does NOT count as a STEP
    - It MUST appear exactly once

    ==============================
    STATE AFTER CHECK-IN
    ==============================
    - current_time = {checkin_end}
    - last_meal_end = NONE
    - used_attraction_indices = empty set

    YOU MUST BEGIN ALL SCHEDULING FROM THIS STATE.

    ==============================
    ATTRACTION DURATIONS (minutes)
    ==============================
    {duration_block}

    ==============================
    CONSTANTS
    ==============================
    - BUFFER = 30
    - MIN_MEAL_GAP = 240

    POI OUTPUT FORMAT (MANDATORY):
    <Place Name>, <visit|stay> from <START_MIN> to <END_MIN>;
    DO NOT output HH:MM
    DO NOT use colon characters
    """

        if breakfast and breakfast != "-":
            instructions += STEP("Breakfast (CONDITIONAL)") + f"""
    RULES:
    - Window: 480 to 630
    - Ideal start: 570
    - Duration: 50
    - breakfast_start >= current_time + BUFFER
    - breakfast_start >= last_meal_end + MIN_MEAL_GAP (if exists)
    HARD RULE (ABSOLUTE — OVERRIDES IDEAL):
    - breakfast_start MUST be >= current_time + BUFFER
    - If ideal start < current_time + BUFFER, ideal start is INVALID

    EXAMPLE:
    If current_time = 520,
    earliest = 550,
    ideal 570 fits → breakfast 570 to 620.

    If no valid start exists → SKIP breakfast.

    Add POI EXACTLY as follows:
    {self.clean_place_name(breakfast.strip(), self.cities)}, visit from breakfast_start to breakfast_end;
    EXECUTION RULE (ABSOLUTE):
    - If ANY valid breakfast_start exists within the window, this STEP MUST be executed
    - Skipping is permitted ONLY if no valid breakfast_start exists

    """
        if attractions:
            instructions += STEP("Pre-lunch attraction (ONLY IF LUNCH REMAINS POSSIBLE)") + """
           STEP  EXECUTION DEFINITION (ABSOLUTE — OVERRIDES ALL):
        - THIS STEP  MUST NOT be marked as "executed" UNTIL AFTER:
            - attraction_start is computed
            - attraction_end is computed
            - lunch feasibility check PASSES
            - the attraction POI is emitted
            - current_time is updated to attraction_end
        - If lunch feasibility FAILS:
            - THIS STEP  MUST be marked as "skipped"
            - It is FORBIDDEN to mark THIS STEP  as executed in any form


    RULES:
    - Select FIRST unused attraction
    - attraction_start = current_time + BUFFER
    - attraction_end = attraction_start + duration

    LOOK-AHEAD CHECK (ABSOLUTE — MUST BE DONE BEFORE ADDING POI):
    - Compute earliest possible lunch_start AFTER this attraction:
        lunch_start_candidate = attraction_end + BUFFER
    - Lunch is feasible ONLY IF:
        lunch_start_candidate + LUNCH_DURATION <= LUNCH_WINDOW_END

    DECISION RULE (ABSOLUTE):
    - If lunch is NOT feasible after this attraction:
        - This STEP MUST be SKIPPED
        - Do NOT add the attraction here
        - Do NOT adjust attraction timing
        - Do NOT shorten duration
    - If lunch IS feasible:
        - Add the attraction POI

    EXAMPLE:
    If current_time = 700 and duration = 120,
    start = 730, end = 850.
    If lunch can still fit → add attraction.

    Add POI EXACTLY as follows:
    "<attraction>", visit from attraction_start to attraction_end;

    IMPORTANT:
- Skipping this STEP does NOT skip the attraction entirely
- The attraction may still be considered in Post-lunch attraction STEP
    STATE UPDATE (ABSOLUTE):
    - If this STEP is executed:
        - current_time MUST be updated to attraction_end
        - used_attraction_indices MUST be updated immediately


    """
        if lunch and lunch != "-":
            instructions += STEP("Lunch (CONDITIONAL)") + f"""
            CLARIFICATION (ABSOLUTE):
    - Lunch feasibility MUST be evaluated using the current_time produced by the immediately preceding STEP
    - If no STEP updated current_time, lunch feasibility MUST use the unchanged current_time
    RULES:
    - Window: 720 to 940
    - Ideal start: 880
    - Duration: 60
    - lunch_start >= current_time + BUFFER
    - lunch_start >= last_meal_end + MIN_MEAL_GAP (if exists)
    HARD RULE (ABSOLUTE — OVERRIDES IDEAL):
    - lunch_start MUST be >= current_time + BUFFER
    - If ideal start < current_time + BUFFER, ideal start is INVALID
    EXAMPLE:
    If current_time = 820,
    earliest = 850,
    ideal 880 fits → lunch 880 to 940.

    If no valid start exists → SKIP lunch.

    Add POI EXACTLY as follows:
    "{self.clean_place_name(lunch.strip(), self.cities)}", visit from lunch_start to lunch_end;
    EXECUTION RULE (ABSOLUTE):
    - If ANY valid lunch_start exists within the window, this STEP MUST be executed
    - Skipping is permitted ONLY if no valid lunch_start exists

    """
        if attractions:
            instructions += STEP("Post-lunch attraction (ONLY IF DINNER REMAINS POSSIBLE)") + """
    RULES:
    - Select next unused attraction
    - attraction_start >= current_time + BUFFER
    - attraction_end + BUFFER < 1320

    EXAMPLE:
    If current_time = 1000 and duration = 90,
    start = 1030, end = 1120,
    1120 + 30 < 1320 → safe.

    Add POI EXACTLY as follows:
    "<attraction>", visit from attraction_start to attraction_end;
    PRIORITY RULE (ABSOLUTE):
    - This STEP MUST be used for attractions that were skipped in pre-lunch placement
    - Do NOT assume the attraction was already used if Pre lunch Attraction STEP was skipped
    STATE UPDATE (ABSOLUTE):
    - If this STEP is executed:
        - current_time MUST be updated to attraction_end
        - used_attraction_indices MUST be updated immediately

    """
        if dinner and dinner != "-":
            instructions += STEP("Dinner (CONDITIONAL)") + f"""
**Check Ideal Timing Feasibility First , If its not feasible, then use earliest valid time**
RULES:
- Window: 1110 to 1350
- Ideal start: 1245
- Duration: 75
SELF-CHECK (MANDATORY — BEFORE DECISION):
- Did you first evaluate the ideal dinner start (1245) for feasibility?
- If the ideal start was not feasible, did you check for any other valid start within the dinner window before skipping?
** Include this self check whle reasoning this step and then proceed**
HARD RULE (ABSOLUTE — OVERRIDES IDEAL):
- dinner_start MUST be >= current_time + BUFFER
- If ideal start < current_time + BUFFER, ideal start is INVALID and MUST be ignored
- dinner_start >= last_meal_end + MIN_MEAL_GAP (if exists)

EXAMPLE:
If current_time = 1180,
earliest = 1210,
ideal 1245 fits → dinner 1245 to 1320.

Else choose earliest valid time.

Add POI EXACTLY as follows:
"{self.clean_place_name(dinner.strip(), self.cities)}", visit from dinner_start to dinner_end;
EXECUTION RULE (ABSOLUTE):
- If ANY valid dinner_start exists within the window, this STEP MUST be executed
- Skipping is permitted ONLY if no valid dinner_start exists
    """
        instructions += STEP("Overnight stay (FINAL — MANDATORY)") + f"""
    RULES:
    - overnight_start = current_time
    - overnight_end = 1920
    - No BUFFER

    EXAMPLE:
    If current_time = 1350,
    overnight stay = 1350 to 1920.

    **Add POI EXACTLY as follows keep:**
    {self.clean_place_name(accommodation.strip(), self.cities)}, stay from overnight_start to overnight_end;
    """

        return instructions.strip()

    def generate_first_day_poi(
        self,
        first_day: Dict[str, Any],
        structured_input: Dict[str, Any],
        all_days: List[Dict[str, Any]],
    ) -> str:
        self.persona = structured_input.get("JSON", {}).get("persona", "")
        self.cities = structured_input.get("cities", [])
        self.days = [first_day]
        cities = structured_input.get("cities", [])
        attraction_duration_map: Dict[str, int] = {}

        OUTPUT_CONTRACT = """
TIME MUTATION INVARIANT (ABSOLUTE):
- current_time may ONLY change in the following cases:
    1. Arrival buffer step
    2. A STEP that adds a POI is executed
- If a STEP is skipped:
    - current_time MUST remain EXACTLY unchanged
    - last_meal_end MUST remain EXACTLY unchanged
- You are FORBIDDEN from advancing time for:
    - waiting
    - nightfall
    - assumptions
    - preparation
    - implicit transitions
WAITING / GAP RULE (ABSOLUTE — HIGHEST PRIORITY):
- Time gaps caused by BUFFER or feasibility constraints MUST NOT produce POIs
- You are FORBIDDEN from adding "stay", "wait", or any POI to represent idle time
- If an activity starts later than current_time, the gap is implicit and MUST NOT be printed
- current_time MUST remain unchanged until a STEP explicitly adds a POI

STEP TYPE DEFINITIONS (ABSOLUTE — READ CAREFULLY):
There are ONLY THREE types of steps:
1. STAY STEPS
   - Examples: accommodation stay, overnight stay
   - NEVER use used_attraction_indices
   - ONLY update current_time
2. MEAL STEPS
   - Examples: breakfast, lunch, dinner, generic MEAL
   - NEVER use used_attraction_indices
   - May update:
       - current_time
       - last_meal_end
   - MUST NOT interact with attraction logic in any way
   - ** If the ideal meal start time is not feasible, the meal MUST be started at the earliest valid time within the window that satisfies all hard constraints. But if ideal start is checked first then only see for other timings**
3. ATTRACTION STEPS
   - ONLY these steps may use used_attraction_indices
   - ONLY these steps may add/remove indices
   - ONLY these steps consume attraction durations

==================================================
OUTPUT FORMAT — ABSOLUTE (DO NOT VIOLATE)
==================================================
You MUST return EXACTLY TWO sections in this order.
DO NOT output JSON.
DO NOT use braces, brackets, or quotes.
========================
REASONING
========================
- Explain step-by-step which STEPS were executed or skipped
- Track current_time, last_meal_end, and decisions
- Explain WHY a STEP was executed or skipped
- DO NOT output any POIs here
used_attraction_indices:
- MUST be initialized as empty set
- MUST ONLY change during attraction steps
- MUST remain EXACTLY unchanged in all non-attraction steps
For each STEP that adds a POI:
- The POI START_MIN MUST equal the step's entry current_time
- The POI END_MIN MUST equal the updated current_time
POI AUTHORITY RULE (ABSOLUTE):
- POIs are NOT planned independently
- POIs MUST be generated ONLY from STEP execution
- A POI MUST NOT introduce any new time changes
- For each STEP that adds a POI:
    - POI START_MIN = step entry current_time
    - POI END_MIN = step exit current_time
- Any POI not matching a STEP boundary is INVALID

POI NAME IMMUTABILITY RULE (ABSOLUTE):
- POI names are AUTHORITATIVE STRINGS provided in the prompt
- You are FORBIDDEN from renaming, substituting, correcting, or normalizing POI names
- You MUST copy POI names CHARACTER-FOR-CHARACTER exactly as given
- Any deviation in spelling, spacing, or wording is INVALID

CRITICAL (ABSOLUTE):
- The ITINERARY MUST be generated by DIRECTLY PRINTING the POIs implied by STEP execution
- DO NOT re-compute durations when generating POIs
- DO NOT infer or adjust times during ITINERARY generation
- ITINERARY is a PURE SERIALIZATION of STEP results

IMPORTANT:
- POI START_MIN MUST be taken from the STEP ENTRY current_time, not recomputed

POI COUNT RULE (ABSOLUTE):
- The number of POIs in ITINERARY MUST equal the number of STEPs that add a POI

ABSOLUTE OVERRIDE (HIGHEST PRIORITY):
- POIs MUST NOT be generated, inferred, or constructed
- POIs MUST be printed by COPYING the STEP boundaries EXACTLY
- STEP execution is the ONLY source of truth for time
- POIs MUST NOT affect state in any way
- State MUST NEVER be updated based on POIs

REASONING EXECUTION RULES (ABSOLUTE):
- Execution occurs ONLY by following STEP instructions
- Timing assignment IS ALLOWED
- State updates ARE ALLOWED
- Computation and arithmetic ARE ALLOWED
- Each STEP must be handled exactly once

CLARIFICATION (ABSOLUTE):
- Being inside the window is NOT sufficient; the HARD RULE must be satisfied first

STEP EXECUTION COMMIT RULE (ABSOLUTE):
- When a STEP is executed and adds a POI:
    - current_time MUST be updated immediately to the POI end time
    - This updated current_time MUST be used for evaluating the next STEP
- It is FORBIDDEN to evaluate the next STEP using the old current_time

STEP REALIZATION RULE (ABSOLUTE):
- A STEP may be marked as "executed" ONLY IF:
    - All required start and end times for that STEP are explicitly computed
    - The STEP produces exactly one POI
    - current_time is updated to the POI end time
- It is FORBIDDEN to mark a STEP as executed without computing its timings

STEP ATOMICITY RULE (ABSOLUTE):
- STEP execution is ATOMIC and OBSERVABLE
- If a STEP is marked as executed:
    - Exactly ONE POI MUST be emitted for that STEP
    - That POI MUST appear in the ITINERARY
    - The POI START_MIN and END_MIN MUST reflect the computed timings
- It is FORBIDDEN to:
    - Execute a STEP without emitting its POI
    - Emit a POI without executing a STEP
    - Execute a STEP and later suppress its POI

STAY VALIDITY RULE (ABSOLUTE):
- A STAY POI MUST have END_MIN > START_MIN
- Zero-duration STAY POIs are FORBIDDEN

STEP START TIME RULE (ABSOLUTE):
- A STEP may compute a START_MIN that is GREATER than entry current_time
- Such delay represents implicit waiting and MUST NOT produce a POI
- When a STEP is executed:
    - STEP_START = the computed valid start time
    - STEP_END   = STEP_START + duration
    - current_time MUST be updated to STEP_END
- POI START_MIN MUST equal STEP_START
- POI END_MIN MUST equal STEP_END

REASONING FORMAT RULE (ABSOLUTE):
- EXACTLY one bullet per STEP
- Each bullet MUST be in one of the following forms:
  STEP X executed; current_time=<INTEGER>; last_meal_end=<INTEGER or NONE>; used_attraction_indices=<SET>
  STEP X skipped because <reason>; current_time=<INTEGER>; last_meal_end=<INTEGER or NONE>; used_attraction_indices=<SET>

FORBIDDEN IN REASONING (ABSOLUTE):
- DO NOT output POI-formatted lines
- DO NOT output place names
- DO NOT output START_MIN or END_MIN
- DO NOT repeat a STEP number
- DO NOT invent or skip STEPS
========================
ITINERARY
========================
- Output ONLY final POIs
- Follow POI format EXACTLY
- One POI per line
- NO explanations here

POI FORMAT (MANDATORY):
<Place Name>, <visit|stay> from <START_MIN> to <END_MIN>;

IMPORTANT:
- START_MIN and END_MIN must be integers
- DO NOT output HH:MM
- DO NOT use colon characters

ITINERARY ORDER RULE (ABSOLUTE):
- POIs MUST be in STRICTLY increasing START_MIN order
- This order MUST match the execution timeline
- You are FORBIDDEN from reordering POIs arbitrarily

FORMAT ENFORCEMENT (ABSOLUTE):
- The word ITINERARY must appear EXACTLY as:
=======================
ITINERARY
=======================
- DO NOT use markdown headings
- DO NOT use ### or bullet points

SECTION CARDINALITY RULE (ABSOLUTE):
- REASONING section must appear EXACTLY ONCE
- ITINERARY section must appear EXACTLY ONCE
- Repeating section headers is FORBIDDEN
    """

        VERIFY = """
***Hard and very important rules for MEAL timing assignment***
**Always check the corresponding meal timing windows and constraints below before assigning meal times in the main prompt , If meal timing is not in window pls change the schedule or skip the meal**
**If any attraction is causing meal to be not feasible pls adjust attraction timings first before skipping the meal, like u can change it from pre lunch to post lunch and check.**
----------------------------------------------------
REFERENCE EXAMPLE — MEAL TIMING (AUTHORITATIVE)
----------------------------------------------------

This example illustrates how to assign timings for a generic MEAL.
Follow the SAME decision pattern for all MEAL steps.
Context:
- current_time = 500
- last_meal_end = NONE
- BUFFER = 30
- MIN_MEAL_GAP = 240

MEAL definition:
- Window: 480 to 630
- Ideal start: 570
- Duration: 50

Case A — MEAL is FEASIBLE and EXECUTED:
- Earliest possible meal_start is current_time + BUFFER
- meal_start must lie within the window
- If ideal start is feasible, it may be chosen
- meal_end = meal_start + duration

Result:
- MEAL is added
- current_time is updated to meal_end
- last_meal_end is updated to meal_end
--------------------------------------------
Case B — MEAL is NOT FEASIBLE and SKIPPED:

Context:
- current_time = 660
- last_meal_end = NONE

Reason:
- No valid meal_start exists within the window

Result:
- STEP is skipped
- current_time remains unchanged
- last_meal_end remains unchanged

--------------------------------------------

IMPORTANT RULES (ABSOLUTE):
- A MEAL may be skipped ONLY if no valid start exists inside its window
- Ideal start is a preference, not a requirement
- If a MEAL is skipped, NO state variables may change
- If a MEAL is executed, state variables MUST be updated


IMPORTANT:
- POIS names MUST be printed as plain text
- DO NOT wrap place names in quotation marks (" ")
***ABSOLUTE OUTPUT SANITIZATION RULE***:
- You are STRICTLY FORBIDDEN from using quotation marks (", ', `) anywhere in point_of_interest_list.
- Names MUST be emitted as raw text without any enclosing symbols.
- Any output containing quotes is INVALID.
ABSOLUTE:
- If you output markdown headings, bullet points, or explanations, the output is INVALID.

"""

        def clean(x):
            if not x:
                return x
            for c in cities:
                city = c.get("city")
                if city and x.endswith(f", {city}"):
                    return x.replace(f", {city}", "").strip()
            return x.strip()

        for c in cities:
            for a in c.get("attractions_ranked", []):
                name = clean(a.get("name"))
                dur_hr = a.get("visit_duration")
                if name and dur_hr:
                    attraction_duration_map[name] = int(dur_hr * 60)

        day_duration_map = self.build_day_adjusted_duration_map(
            first_day,
            attraction_duration_map,
            all_days
        )
        execution_prompt = self.build_first_day_execution_hints(
            first_day,
            "FIRST_DAY",
            attraction_duration_map=day_duration_map,
        )
        prompt = OUTPUT_CONTRACT + "\n\n" + execution_prompt + "\n\n" + VERIFY
        return prompt
           


def main():
    days = [
        {
        "day": 1,
        "current_city": "from Savannah to Baltimore",
        "transportation": "Flight Number: F2644210, from Savannah to Baltimore, Departure Time: 07:02, Arrival Time: 08:33",
        "breakfast": "-",
        "lunch": "Restaurante Tio Pepe, Baltimore",
        "dinner": "Fogo de Chao Brazilian Steakhouse, Baltimore",
        "attraction": "Federal Hill Park, Baltimore;",
        "accommodation": "Large comfortable space w/ private entrance & bath, Baltimore",
        "event": "-",
         },
        {
        "day": 2,
        "current_city": "Baltimore",
        "transportation": "-",
        "breakfast": "Sotto Sopra, Baltimore",
        "lunch": "La Scala, Baltimore",
        "dinner": "Tagliata, Baltimore",
        "attraction": "Fort McHenry National Monument And Historic Shrine, Baltimore; The Maryland Zoo, Baltimore;",
        "accommodation": "Large comfortable space w/ private entrance & bath, Baltimore",
        "event": "Real Friends, Baltimore",
        },
        {
        "day": 3,
        "current_city": "from Baltimore to Savannah",
        "transportation": "Flight Number: F3581350, from Baltimore to Savannah, Departure Time: 15:05, Arrival Time: 16:52",
        "breakfast": "Rusty Scupper, Baltimore",
        "lunch": "-",
        "dinner": "-",
        "attraction": "National Aquarium, Baltimore;",
        "accommodation": "-",
        "event": "-",
        }
        ]
    structured_input = {
        "transportation": {
            "mode_strategy": "flight",
            "legs": [
            {
                "day": 1,
                "from": "Savannah",
                "to": "Baltimore",
                "mode": "flight",
                "details": {
                "flight_number": "F2644210",
                "price": 136,
                "departure_time": "07:02",
                "arrival_time": "08:33",
                "duration_minutes": 91,
                "date": "2024-11-18",
                "from": "Savannah",
                "to": "Baltimore"
                },
                "departure_time": "07:02",
                "arrival_time": "08:33"
            },
            {
                "day": 3,
                "from": "Baltimore",
                "to": "Savannah",
                "mode": "flight",
                "details": {
                "flight_number": "F3581350",
                "price": 180,
                "departure_time": "15:05",
                "arrival_time": "16:52",
                "duration_minutes": 107,
                "date": "2024-11-20",
                "from": "Baltimore",
                "to": "Savannah"
                },
                "departure_time": "15:05",
                "arrival_time": "16:52"
            }
            ]
        },
        "cities": [
            {
            "city": "Baltimore",
            "days": 3,
            "accommodation": {
                "name": "Large comfortable space w/ private entrance & bath",
                "price_per_night": 52.0,
                "room_type": "private_room",
                "house_rules": "No visitors",
                "minimum_nights": 1,
                "maximum_occupancy": 2,
                "review_rate": 4.95,
                "city": "Baltimore"
            },
            "restaurants_ranked": [
                {
                "name": "Restaurante Tio Pepe",
                "avg_cost": 64.0,
                "cuisines": [
                    "seafood",
                    "spanish"
                ],
                "aggregate_rating": 4.5
                },
                {
                "name": "Fogo de Chao Brazilian Steakhouse",
                "avg_cost": 64.0,
                "cuisines": [
                    "steakhouse",
                    "brazilian"
                ],
                "aggregate_rating": 4.5
                },
                {
                "name": "Sotto Sopra",
                "avg_cost": 64.0,
                "cuisines": [
                    "italian"
                ],
                "aggregate_rating": 4.5
                },
                {
                "name": "La Scala",
                "avg_cost": 64.0,
                "cuisines": [
                    "italian"
                ],
                "aggregate_rating": 4.5
                },
                {
                "name": "Tagliata",
                "avg_cost": 64.0,
                "cuisines": [
                    "italian",
                    "tuscan",
                    "central-italian"
                ],
                "aggregate_rating": 4.5
                },
                {
                "name": "Rusty Scupper",
                "avg_cost": 64.0,
                "cuisines": [
                    "american",
                    "seafood"
                ],
                "aggregate_rating": 4.0
                },
                {
                "name": "Toki Underground Baltimore",
                "avg_cost": 40.0,
                "cuisines": [
                    "japanese",
                    "bar",
                    "asian",
                    "pub",
                    "dining bars"
                ],
                "aggregate_rating": 5.0
                },
                {
                "name": "La Tavola",
                "avg_cost": 40.0,
                "cuisines": [
                    "italian",
                    "seafood"
                ],
                "aggregate_rating": 4.5
                },
                {
                "name": "Dalesio's of Little Italy Restaurant",
                "avg_cost": 40.0,
                "cuisines": [
                    "italian",
                    "northern-italian"
                ],
                "aggregate_rating": 4.5
                }
            ],
            "attractions_ranked": [
                {
                "name": "Federal Hill Park",
                "categories": [
                    "sights & landmarks",
                    "nature & parks"
                ],
                "description": "Former lookout during the Civil War and the War of 1812 is now a scenic park overlooking the Inner Harbor.",
                "visit_duration": 3.75,
                "latitude": 39.27972,
                "longitude": -76.60846,
                "address": "300 Warren Ave, Baltimore, MD 21230",
                "website": "https://www.federalhillpark.com",
                "city": "Baltimore"
                },
                {
                "name": "Fort McHenry National Monument And Historic Shrine",
                "categories": [
                    "sights & landmarks",
                    "nature & parks"
                ],
                "description": "A unit of the National Park Service. Site of the Battle of Baltimore during the War of 1812, where Francis Scott Key was inspired to pen \"The Star-Spangled Banner\" in September of 1814.",
                "visit_duration": 3.75,
                "latitude": 39.264114,
                "longitude": -76.58064,
                "address": "2400 East Fort Avenue, Baltimore, MD 21230-5390",
                "website": "http://www.nps.gov/fomc/index.htm",
                "city": "Baltimore"
                },
                {
                "name": "Inner Harbor",
                "categories": [
                    "nature & parks"
                ],
                "description": "As one of America's oldest seaports, Inner Harbor is now an important landmark and popular tourist destination. Follow the brick promenade through this bustling complex of eateries, stores, museums and entertainment venues. Rent a paddle boat to have some fun in the water with the kids, or take them to the National Aquarium which is one of the nation\u2019s largest. History buffs will enjoy touring the heritage ships anchored in the harbor, while travelers of all ages can soak up the marvelous views from the Top of the World Observation Level. Sightseeing tours and scavenger hunts are two other great activities at the Inner Harbor.",
                "visit_duration": 4.5,
                "latitude": 39.28422,
                "longitude": -76.61298,
                "address": "Baltimore, MD 21202",
                "website": "http://baltimore.org/article/baltimore-inner-harbor",
                "city": "Baltimore"
                },
                {
                "name": "National Aquarium",
                "categories": [
                    "zoos & aquariums",
                    "nature & parks"
                ],
                "description": "Considered one of the world's best aquariums, the National Aquarium's mission is to inspire conservation of the world's aquatic treasures. It champions environmental initiatives by engaging with visitors, volunteers, education groups and schools to actively participate in the preservation of the world's natural resources and living systems. The National Aquarium delivers meaningful experiences through its living collection of more than 20,000 animals from more than 800 species of fish, birds, amphibians, reptiles, marine mammals and sharks, as well as through exclusive behind-the-scenes experiences like sleepovers and tours, science-based education programs and hands-on experiences in the field.",
                "visit_duration": 3.5,
                "latitude": 39.285393,
                "longitude": -76.6084,
                "address": "501 E Pratt St, Baltimore, MD 21202-3194",
                "website": "http://www.aqua.org/",
                "city": "Baltimore"
                },
                {
                "name": "The Maryland Zoo",
                "categories": [
                    "zoos & aquariums",
                    "nature & parks",
                    "outdoor activities"
                ],
                "description": "Visitors meet more than 1,500 animals including chimpanzees, elephants, leopards and warthogs as they journey on an African safari, groom goats in the Farmyard, explore the winding trails through the Lyn P. Myerhoff Maryland Wilderness and watch the polar bears swim next to you at the underwater viewing window. Plus, don't miss the new, award winning Penguin Coast exhibit featuring the most successful breeding colony of endangered African penguins in North America.",
                "visit_duration": 3.6666666666666665,
                "latitude": 39.32253,
                "longitude": -76.64941,
                "address": "1 Safari Pl, Baltimore, MD 21217",
                "website": "http://www.marylandzoo.org",
                "city": "Baltimore"
                },
                {
                "name": "Little Italy",
                "categories": [
                    "sights & landmarks",
                    "other",
                    "nature & parks"
                ],
                "description": "",
                "visit_duration": 3.1666666666666665,
                "latitude": 39.28611,
                "longitude": -76.60167,
                "address": "1020 Stiles Street, Baltimore, MD 21202",
                "website": "http://www.littleitalymd.com",
                "city": "Baltimore"
                },
                {
                "name": "B&O Railroad Museum",
                "categories": [
                    "sights & landmarks",
                    "museums"
                ],
                "description": "The B&O Railroad Museum, a full affiliate of the Smithsonian Institution and the birthplace of American Railroading, is home to the oldest, most comprehensive collection of railroad artifacts in the Western Hemisphere including an unparalleled roster of 19th and 20th century railroad equipment. You\u2019ll enjoy exploring our expansive Museum campus, known as the Mount Clare Shops and Station and was the original railroading complex of the Baltimore and Ohio Railroad (B&O). Founded in 1827, the B&O had a dramatic economic, social, and cultural impact on our society. Its nearly 200-year history is deeply intertwined with the story of America and helped shaped our nation through invention, innovation, and ingenuity. Experience two centuries of American railroading history throughout our campus of historic buildings, exhibitions, interactive displays, and our world-class collection of rolling stock \u2014locomotives, passenger cars, freight cars, and maintenance vehicles. All Aboard!",
                "visit_duration": 3.0,
                "latitude": 39.28547,
                "longitude": -76.632614,
                "address": "901 W Pratt St, Baltimore, MD 21223-2699",
                "website": "http://www.borail.org/",
                "city": "Baltimore"
                },
                {
                "name": "American Visionary Art Museum",
                "categories": [
                    "museums"
                ],
                "description": "The American Visionary Art Museum is the nation's museum for self-taught, intuitive artistry. Three historic buildings house wonders created by farmers, housewives, mechanics, the disabled, the homeless, as well as the occasional neurosurgeon\u2014all inspired by the fire within. From carved roots to embroidered rags, tattoos to toothpicks, \u2018the visionary\u2019 transforms dreams, loss, hopes, and ideals into powerful works of art. \"one of the most fantastic museums anywhere in America\" - CNN \"Best Museum in Maryland\" - USA Today \"a temple of outsider art\" - New York Times. Tickets: $9.95-15.95. Children 6 and under and museum members are free.",
                "visit_duration": 3.0,
                "latitude": 39.280437,
                "longitude": -76.606895,
                "address": "800 Key Hwy, Baltimore, MD 21230-3940",
                "website": "http://www.avam.org",
                "city": "Baltimore"
                },
                {
                "name": "Maryland Science Center",
                "categories": [
                    "museums"
                ],
                "description": "This popular museum is located in Harborplace.",
                "visit_duration": 3.0,
                "latitude": 39.281414,
                "longitude": -76.611916,
                "address": "601 Light St, Baltimore, MD 21230-3803",
                "website": "http://www.mdsci.org/",
                "city": "Baltimore"
                },
                {
                "name": "Baltimore Museum of Art",
                "categories": [
                    "sights & landmarks",
                    "museums"
                ],
                "description": "Over 100 years ago, The Baltimore Museum of Art (BMA) was founded on the belief that access to art and ideas is integral to a vibrant and healthy civic life. This belief is at the heart of the BMA and remains our core value. The BMA has long focused on acquiring the art of the present moment, while maintaining and deepening a historic collection made relevant through vigorous development and reinterpretation in all collecting areas. Through the courageous and risk-taking vision of previous Museum leaders, the BMA assembled and presented one of the most important collections of 18th-, 19th-, and 20th-century art in the United States. These visionary actions established the fundamental character of this Museum. Building on this legacy of excellence, the BMA will form an equally compelling collection for the 21st century. Socially relevant, cutting-edge acquisitions, exhibitions, and programs will lead the way both locally and globally\u2014and historical accuracy, merit, and equity will be",
                "visit_duration": 3.0,
                "latitude": 39.326176,
                "longitude": -76.61934,
                "address": "10 Art Museum Dr, Baltimore, MD 21218-3898",
                "website": "http://www.artbma.org/",
                "city": "Baltimore"
                },
                {
                "name": "The Walters Art Museum",
                "categories": [
                    "museums"
                ],
                "description": "The Walters Art Museum is a cultural hub in the heart of Baltimore. Located in the city\u2019s Mount Vernon neighborhood, the Walters is free for all. The museum\u2019s collection spans more than seven millennia, from 5,000 BCE to the 21st century, and encompasses 36,000 objects from around the world. Walking through the museum\u2019s historic buildings, visitors encounter a stunning panorama of thousands of years of art, from romantic 19th-century images of French gardens to mesmerizing Ethiopian icons, richly illuminated Qur\u2019ans and Gospel books, ancient Roman sarcophagi, and serene images of the Buddha. The Walters' mission has been to bring art and people together and to create a place where people of every background can be touched by art. Admission to the museum and special exhibitions is always free.",
                "visit_duration": 3.0,
                "latitude": 39.296432,
                "longitude": -76.61648,
                "address": "600 N Charles St, Baltimore, MD 21201-5118",
                "website": "http://thewalters.org/",
                "city": "Baltimore"
                },
                {
                "name": "Edgar Allan Poe's Grave Site and Memorial",
                "categories": [
                    "sights & landmarks"
                ],
                "description": "Burial site of the famous author.",
                "visit_duration": 3.0,
                "latitude": 39.29018,
                "longitude": -76.62359,
                "address": "Westminster Cemetery on the southeast corner of Fayette and Greene sts., Baltimore, MD 21201-1768",
                "website": "http://www.eapoe.org/balt/poegrave.htm",
                "city": "Baltimore"
                }
            ],
            "events_ranked": [
                {
                "name": "Real Friends",
                "date": "2024-11-19",
                "categories": [
                    "music",
                    "rock"
                ],
                "address": "1545 East Cary Street",
                "city": "Baltimore",
                "url": "https://www.ticketmaster.com/event/Z7r9jZ1A7CkC_"
                }
            ]
            }
        ],
        "origin": "Savannah",
        "dates": [
            "2024-11-18",
            "2024-11-19",
            "2024-11-20"
        ],
        "people_number": 1,
        "budget": 1500.0,
        "persona": "Traveler Type: Adventure Seeker; Purpose of Travel: Cultural Exploration; Spending Preference: Luxury Traveler; Location Preference: Beaches",
        "constraints": {
            "house rule": None,
            "cuisine": None,
            "room type": None,
            "transportation": None,
            "event": None,
            "attraction": None
        }
        }
    first_day = days[0]
    agent = FIRSTDAYPOIAGENT()
    try:
        result = agent.generate_first_day_poi(first_day, structured_input, all_days=days)
        print(result)
    except Exception as e:
        print(f"\n Error: {e}")
if __name__ == "__main__":
    main()
