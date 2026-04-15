from typing import Any, Dict, List,Optional
import re

class LASTDAYPOIAGENT:
    def __init__(self):
        pass

    def to_min(self, t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    def extract_departure_time(self, day: dict) -> Optional[int]:
        t = day.get("transportation", "")
        m = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", t)
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

    def extract_prev_stay_context(self, itinerary: str):
        m = re.findall(
            r'(.+?), stay from (\d{2}:\d{2}) to (\d{2}:\d{2});',
            itinerary
        )
        if not m:
            return None, None
        place, start, end = m[-1]
        def to_min(t):
            h, m = map(int, t.split(":"))
            return h * 60 + m
        return place.strip(), to_min(end)

    def build_day_adjusted_duration_map(
        self,
        day: Dict[str, Any],
        base_duration_map: Dict[str, int],
        all_days: List[Dict[str, Any]],
    ) -> Dict[str, int]:
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

    def build_last_day_execution_hints(
        self,
        day: dict,
        day_type: str,
        previous_accommodation: str,
        previous_stay_end_min: int,
        departure_time_min: int,
        attraction_duration_map: dict,
    ) -> str:
        if day_type != "LAST_DAY":
            return ""
        breakfast = day.get("breakfast")
        lunch = day.get("lunch")
        dinner = day.get("dinner")
        attractions = [
            self.clean_place_name(a.strip(), self.cities)
            for a in day.get("attraction", "").split(";")
            if a.strip() and a.strip() != "-"
        ]
        attraction_block = ""
        if attractions:
            attraction_block = "\n".join(
                f"- {a} = {attraction_duration_map.get(a, 120)}"
                for a in attractions
            )
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

    This is LAST_DAY.

    ALL time values are INTEGER MINUTES.

    AUTHORITATIVE INPUTS (DO NOT MODIFY):

    ATTRACTION DURATIONS (minutes):
    {attraction_block}

    You MUST maintain:
    - current_time
    - last_meal_end (initialize as NONE)
    - used_attractions = 0

    Constants:
    - BUFFER = 30
    - STAY_DURATION = 30
    - MEAL_GAP = 240

    POI OUTPUT FORMAT (MANDATORY):
    <Place Name>, <visit|stay> from <START_MIN> to <END_MIN>;

    IMPORTANT:
    - START_MIN and END_MIN must be integers
    - DO NOT output HH:MM
    - DO NOT use ":"
    IMPORTANT MEAL RULES:
    - Ideal start is OPTIONAL
    - Ideal start is a PREFERENCE ONLY
    - Not using the ideal start does NOT invalidate the meal
    - Any start time inside the window that satisfies feasibility rules is VALID
    - Do not skip melas for long attractions instead start early or late within the window

    PREVIOUS DAY CONTEXT (ABSOLUTE — DO NOT MODIFY):
    - previous_accommodation = {previous_accommodation}
    - previous_stay_end = {previous_stay_end_min}
    """

        instructions += STEP("Hard departure cutoff") + f"""
    - departure_time = {departure_time_min}
    - departure_absolute = departure_time + 1440
    - day_end = departure_absolute - BUFFER
    - NO activity may end after day_end
    """

        instructions += STEP("Checkout stay (TAIL STAY)") + f"""
    - tail_start = previous_stay_end
    - tail_end = min(previous_stay_end + STAY_DURATION, day_end)

    If tail_end > tail_start:
    - Add POI EXACTLY as follows:
    {previous_accommodation}, stay from tail_start to tail_end;
    - current_time = tail_end
    - BUFFER MUST be applied before any subsequent STEP
    Else:
    - current_time = previous_stay_end
    - BUFFER MUST be applied before any subsequent STEP
    """

        instructions += STEP("Day start anchor") + """
    - current_time = max(current_time + BUFFER, 480)
    - day_anchor = current_time
    """

        if breakfast and breakfast != "-":
            instructions += STEP("Breakfast (EARLY ONLY IF REQUIRED)") + f"""
        Breakfast timing:
        - Window: 480 to 630
        - Ideal start: 570
        - Duration: 50

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define bounds:
        - earliest_allowed = max(day_anchor, 480)
        - latest_allowed_end = min(630, day_end)

        Define candidates:
        - Candidate A (IDEAL) = 570
        - Candidate B (EARLIEST) = earliest_allowed

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= earliest_allowed
        - candidate + 50 <= latest_allowed_end

        Decision rule (ABSOLUTE):
        - First evaluate Candidate A
        - If Candidate A is feasible → breakfast_start = Candidate A
        - Else evaluate Candidate B
        - If Candidate B is feasible → breakfast_start = Candidate B
        - Else → Skip breakfast

        If breakfast is executed:
        - breakfast_end = breakfast_start + 50
        - Add POI EXACTLY as follows:
        {self.clean_place_name(breakfast.strip(), self.cities)}, visit from breakfast_start to breakfast_end;
        - last_meal_end = breakfast_end
        - current_time = breakfast_end
        Else:
        - Skip breakfast
        """

        if attractions:
            instructions += STEP("Pre-lunch attraction") + """
    - Select FIRST attraction
    - duration = PROVIDED attraction duration
    - start = current_time + BUFFER
    If ALL of the following hold:
    - start + duration <= day_end
    - After this attraction, lunch must still have at least ONE feasible start
    If start + duration <= day_end:
    - Add POI EXACTLY as follows:
    <attraction>, visit from start to start + duration;
    - current_time = start + duration
    - used_attractions = 1
    Else:
    - Skip pre-lunch attraction
    """

        if lunch and lunch != "-":
            instructions += STEP("Lunch") + f"""
        Lunch timing:
        - Window: 720 to 940
        - Ideal start: 880
        - Duration: 60

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define bounds:
        - earliest_allowed = max(
            720,
            current_time + BUFFER,
            last_meal_end + MEAL_GAP if last_meal_end exists else 720
        )
        - latest_end = min(940, day_end)

        Define candidates:
        - Candidate A (IDEAL) = 880
        - Candidate B (EARLIEST) = earliest_allowed

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= earliest_allowed
        - candidate + 60 <= latest_end

        Decision rule (ABSOLUTE):
        - First evaluate Candidate A
        - If Candidate A is feasible → lunch_start = Candidate A
        - Else evaluate Candidate B
        - If Candidate B is feasible → lunch_start = Candidate B
        - Else → Skip lunch

        If lunch is executed:
        - lunch_end = lunch_start + 60
        - Add POI EXACTLY as follows:
        {self.clean_place_name(lunch.strip(), self.cities)}, visit from lunch_start to lunch_end;
        - last_meal_end = lunch_end
        - current_time = lunch_end
        Else:
        - Skip lunch
        """

        if attractions:
            instructions += STEP("Post-lunch attraction") + """
    If used_attractions < number of attractions:
    - Select NEXT attraction
    - duration = PROVIDED attraction duration
    - start = current_time + BUFFER

    If start + duration <= day_end:
    - Add POI EXACTLY as follows:
    <attraction>, visit from start to start + duration;
    - current_time = start + duration
    - used_attractions += 1
    Else:
    - Skip post-lunch attraction
    """
        if dinner and dinner != "-":
            instructions += STEP("Dinner (ONLY IF VERY LATE DEPARTURE)") + f"""
        Dinner timing:
        - Window: 1110 to 1350
        - Ideal start: 1230
        - Duration: 75

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define bounds:
        - earliest_allowed = max(
            1110,
            current_time + BUFFER,
            last_meal_end + MEAL_GAP if last_meal_end exists else 1110
        )
        - latest_allowed_end = min(1350, day_end)

        Define candidates:
        - Candidate A (IDEAL) = 1230
        - Candidate B (EARLIEST) = earliest_allowed

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= earliest_allowed
        - candidate + 75 <= latest_allowed_end

        Decision rule (ABSOLUTE):
        - First evaluate Candidate A
        - If Candidate A is feasible → dinner_start = Candidate A
        - Else evaluate Candidate B
        - If Candidate B is feasible → dinner_start = Candidate B
        - Else → Skip dinner

        If dinner is executed:
        - dinner_end = dinner_start + 75
        - Add POI EXACTLY as follows:
        {self.clean_place_name(dinner.strip(), self.cities)}, visit from dinner_start to dinner_end;
        - last_meal_end = dinner_end
        - current_time = dinner_end
        Else:
        - Skip dinner
        """

        instructions += """
    ----------------------------------------------------
    FINAL GUARANTEES
    ----------------------------------------------------
    - NO overnight stay on LAST_DAY
    - NO activity may exceed day_end
    - Only previous accommodation may be used
    - Attractions use PROVIDED durations
    - Order strictly follows execution
    """
        return instructions.strip()

    def generate_last_day_poi(
        self,
        last_day: Dict[str, Any],
        previous_itinerary: str,
        previous_day: Dict[str, Any],
        structured_input: Dict[str, Any],
        all_days: List[Dict[str, Any]],
    ) -> str:
        self.persona = structured_input.get("JSON", {}).get("persona", "")
        self.cities = structured_input.get("cities", [])
        cities = structured_input.get("cities", [])
        self.cities = cities
        attraction_duration_map: Dict[str, int] = {}
        previous_accommodation, previous_stay_end = (
            self.extract_prev_stay_context(previous_itinerary)
        )

        if previous_accommodation is None or previous_stay_end is None:
            raise RuntimeError("Could not extract previous stay context")

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
        
        
        day = dict(last_day) 
        if day.get("accommodation") in ("", "-", None):
            prev_acc = previous_day.get("accommodation")
            if prev_acc not in ("", "-", None):
                day["accommodation"] = prev_acc

        self.days = [day]
        for c in cities:
            for a in c.get("attractions_ranked", []):
                name = clean(a.get("name"))
                dur_hr = a.get("visit_duration")
                if name and dur_hr:
                    attraction_duration_map[name] = int(dur_hr * 60)
        
        day_duration_map = self.build_day_adjusted_duration_map(
            day,
            attraction_duration_map,
            all_days
        )

        departure_time = self.extract_departure_time(day)

        execution_prompt = self.build_last_day_execution_hints(
            day,
            "LAST_DAY",
            previous_accommodation,
            previous_stay_end,
            departure_time,
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
        "cities": [
            {
            "city": "Baltimore",
            "days": 3,
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
    previous_day = days[1]      
    last_day = days[2]          
    previous_itinerary = """
Large comfortable space w/ private entrance & bath, stay from 20:00 to 08:00;
"""
    agent = LASTDAYPOIAGENT()
    try:
        result = agent.generate_last_day_poi(
            last_day,
            previous_itinerary,
            previous_day,
            structured_input,
            all_days=days
        )
        print(result)
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
