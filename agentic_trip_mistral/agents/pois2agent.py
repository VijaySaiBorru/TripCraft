import json
import sys
import os
from pathlib import Path
from typing import Any, Dict, List,Optional

import re

def extract_itinerary(response: str) -> str:
    # 1️⃣ Find ITINERARY header (case-insensitive)
    match = re.search(r"\bITINERARY\b|\bItinerary\b", response)
    if not match:
        raise RuntimeError("Missing ITINERARY section from LLM")

    itinerary = response[match.end():].strip()

    # 2️⃣ Remove leading markdown junk
    # Remove leading colons, dashes, or headers
    itinerary = re.sub(r"^[\s:\-]+", "", itinerary)

    # 3️⃣ If wrapped in triple backticks, unwrap them
    if itinerary.startswith("```"):
        # remove opening fence
        itinerary = re.sub(r"^```[a-zA-Z]*\n?", "", itinerary)
        # remove closing fence
        itinerary = re.sub(r"\n?```$", "", itinerary)

    itinerary = itinerary.strip()

    # 4️⃣ Final sanity check
    if not itinerary:
        raise RuntimeError("Empty itinerary from LLM")

    return itinerary

def extract_city_from_poi(poi: str):
    if "," not in poi:
        return None
    return poi.rsplit(",", 1)[-1].strip()

def collect_day_pois_with_city(day: dict):
    pois = []

    # Accommodation
    if day.get("accommodation") and day["accommodation"] != "-":
        pois.append(day["accommodation"])

    # Meals
    for meal in ("breakfast", "lunch", "dinner"):
        if day.get(meal) and day[meal] != "-":
            pois.append(day[meal])

    # Attractions (semicolon separated)
    if day.get("attraction") and day["attraction"] != "-":
        for a in day["attraction"].split(";"):
            a = a.strip()
            if a:
                pois.append(a)

    # Events
    if day.get("event") and day["event"] != "-":
        for e in day["event"].split(";"):
            e = e.strip()
            if e:
                pois.append(e)

    return pois


class POIsAgent:
    """
    LLM-based POI scheduler (evaluation agent).
    Standalone helper with DAY-TYPE–AWARE prompting.
    """

    def __init__(self, llm):
        self.llm = llm

    def to_min(self, t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    def get_attraction_duration(self, name, attraction_duration_map):
        return attraction_duration_map.get(name, 120)
    
    def extract_departure_time(self, day: dict) -> Optional[int]:
        import re
        t = day.get("transportation", "")
        m = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", t)
        return self.to_min(m.group(1)) if m else None
    
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

    # ----------------------------------------------------------
    # Build STRICT POI inputs (ORDER MATTERS)
    # ----------------------------------------------------------
    @staticmethod
    def build_poi_inputs(day: Dict[str, Any]) -> List[str]:
        pois: List[str] = []

        if day.get("accommodation") not in ("", "-"):
            pois.append(day["accommodation"].rsplit(",", 1)[0])

        for key in ("breakfast", "lunch", "dinner"):
            value = day.get(key)
            if value and value not in ("", "-"):
                pois.append(value.rsplit(",", 1)[0])

        attr = day.get("attraction")
        if attr and attr not in ("", "-"):
            for a in attr.split(";"):
                a = a.strip()
                if a:
                    pois.append(a.rsplit(",", 1)[0])

        return pois

    # ----------------------------------------------------------
    # Transit resolver (deterministic)
    # ----------------------------------------------------------
    def resolve_transit_for_poi(self, poi_name: str, city: str, raw_rows: list):
        """
        Resolve nearest transit stop for a POI.

        NOTE:
        - `raw_rows` is intentionally ignored (kept for backward compatibility)
        - CSV is the single source of truth
        """

        import os
        import csv

        # ---------------- path resolution (dynamic) ----------------
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        CSV_PATH = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/public_transit_gtfs/all_poi_nearest_stops.csv"
            )
        )

        poi = poi_name.strip().lower()
        city_l = city.strip().lower()

        best = None
        best_dist = float("inf")

        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                if not row.get("PoI") or not row.get("City"):
                    continue

                # ✅ POI match (unchanged)
                if row["PoI"].strip().lower() != poi:
                    continue

                # ✅ CITY FILTER (ONLY NEW LOGIC)
                if row["City"].strip().lower() != city_l:
                    continue

                # ---- parse distance ----
                try:
                    dist_val = float(row.get("nearest_stop_distance"))
                except Exception:
                    continue

                # sanity cap (same rule as before)
                if dist_val > 10000:
                    continue

                if dist_val < best_dist:
                    best = {
                        "stop": row.get("nearest_stop_name"),
                        "distance": dist_val,
                        "latitude": row.get("nearest_stop_latitude"),
                        "longitude": row.get("nearest_stop_longitude"),
                    }
                    best_dist = dist_val

        return best


    # ----------------------------------------------------------
    # Day type classifier (MIRRORS MANUAL LOGIC)
    # ----------------------------------------------------------

    @staticmethod
    def classify_day(day: Dict[str, Any], idx: int, days: List[Dict[str, Any]]) -> str:
        is_first = idx == 0
        is_last = idx == len(days) - 1
        is_travel = "from " in day.get("current_city", "").lower()

        if is_first and is_travel:
            return "FIRST_DAY"
        elif is_last and is_travel:
            return "LAST_DAY"
        elif is_travel:
            return "INTER_CITY_DAY"
        else:
            return "NON_TRAVEL_DAY"
    # ----------------------------------------------------------
    # Prompt builder (DAY-AWARE, CoT-STYLE, EVAL-SAFE)
    # ----------------------------------------------------------
    def extract_prev_stay_context(self, itinerary: str):
        import re

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
    ) -> Dict[str, int]:
        """
        Evaluator-aligned, persona-aware attraction duration logic.
        MUST match FinalScheduleBuilder exactly.
        """

        # ---------- constants (MATCH FINAL SCHEDULER) ----------
        MIN_DUR = 60          # minutes
        MAX_DUR = 300         # minutes
        K_SHIFT = 16.61       # minutes
        MU_D_MAX = 4

        persona = (self.persona or "").lower()
        is_adventure = "adventure" in persona

        # ---------- extract attractions ----------
        attractions = [
            self.clean_place_name(a.strip(), self.cities)
            for a in day.get("attraction", "").split(";")
            if a.strip() and a.strip() != "-"
        ]

        if not attractions:
            return {}

        # ---------- GLOBAL max attractions per day (CRITICAL) ----------
        max_atts_day = max(
            len([
                x for x in d.get("attraction", "").split(";")
                if x.strip() and x.strip() != "-"
            ])
            for d in self.days   # 👈 IMPORTANT: GLOBAL, not today
        ) or 1

        adjusted = {}

        for a in attractions:
            raw_base = base_duration_map.get(a, 120)

            # hard clamp (dataset safety)
            base = max(MIN_DUR, min(raw_base, MAX_DUR))

            if is_adventure:
                # evaluator formula
                mu_d = base - (K_SHIFT * (max_atts_day - 1))
            else:
                mu_d = base + (K_SHIFT * (MU_D_MAX - max_atts_day))

            # final clamp
            mu_d = max(MIN_DUR, min(mu_d, MAX_DUR))

            adjusted[a] = int(round(mu_d))

        return adjusted


    def resolve_inter_city_ownership(self, day: dict):
        route = day.get("current_city", "")
        route_l = route.lower().strip()

        # -------------------------------
        # Robust route detection
        # -------------------------------
        if route_l.startswith("from "):
            route_clean = route[5:].strip()   # remove leading "from "
        elif " from " in route_l:
            route_clean = route.split("from", 1)[1].strip()
        else:
            raise ValueError(f"Invalid inter-city route: {route}")

        # STRICT split — space-sensitive (SAFE for Sacramento etc.)
        if " to " not in route_clean:
            raise ValueError(f"Invalid inter-city route: {route}")

        origin_city, dest_city = route_clean.split(" to ", 1)
        origin_city = origin_city.strip()
        dest_city = dest_city.strip()

        # -------------------------------
        # Split attractions
        # -------------------------------
        origin_atts, dest_atts = [], []

        for a in day.get("attraction", "").split(";"):
            a = a.strip()
            if not a:
                continue

            if origin_city in a:
                origin_atts.append(a)
            elif dest_city in a:
                dest_atts.append(a)

        # -------------------------------
        # Meal ownership
        # -------------------------------
        def meal_loc(meal):
            if not meal or meal == "-":
                return None
            if origin_city in meal:
                return "ORIGIN"
            if dest_city in meal:
                return "DESTINATION"
            return None

        return (
            origin_atts,
            dest_atts,
            meal_loc(day.get("breakfast")),
            meal_loc(day.get("lunch")),
            meal_loc(day.get("dinner")),
        )

    def attach_transits_post_llm(
        self,
        itinerary: str,
        transit_map: dict,
    ) -> str:

        final_entries = []

        for entry in itinerary.split(";"):
            entry = entry.strip()
            if not entry:
                continue

            # NEVER attach transit to stay steps
            if " stay from " in entry:
                final_entries.append(entry + ";")
                continue

            place = entry.split(", visit from ", 1)[0].strip()


            transit = transit_map.get(place)
            if transit:
                stop = transit.get("stop")
                dist = transit.get("distance")

                if stop and dist and dist > 0:
                    entry = f"{entry}, nearest transit: {stop}, {dist}m away"

            final_entries.append(entry + ";")

        return " ".join(final_entries)

    def build_first_day_execution_hints(
        self,
        day: dict,
        day_type: str,
        attraction_duration_map: dict,
    ) -> str:
        """
        Build NATURAL-LANGUAGE EXECUTION INSTRUCTIONS for the LLM.

        KEY FIX:
        - Arrival buffer + check-in stay timings are FIXED and GIVEN
        - LLM starts scheduling ONLY after check-in
        """

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

        # 🔒 FIXED TIMES (KNOWN)
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

        # STEP 2 — Breakfast
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

        # STEP 3 — Pre-lunch attraction
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

        # STEP 4 — Lunch
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

        # STEP 5 — Post-lunch attraction
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

        # STEP 6 — Dinner
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

        # STEP 7 — Overnight stay
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

    def build_non_travel_execution_hints(
        self,
        day: dict,
        day_type: str,
        attraction_duration_map: dict,
        next_day_departure_time: Optional[str] = None,
        next_day_breakfast_same_city: bool = False,
    ) -> str:
        """
        Build NATURAL-LANGUAGE EXECUTION INSTRUCTIONS for NON_TRAVEL_DAY.

        LOGIC IS UNCHANGED.
        ONLY FIXES:
        - Minutes only (no HH:MM)
        - Attraction durations injected
        """

        if day_type != "NON_TRAVEL_DAY":
            return ""

        accommodation = day.get("accommodation")
        breakfast = day.get("breakfast")
        lunch = day.get("lunch")
        dinner = day.get("dinner")

        attractions = [
            self.clean_place_name(a.strip(), self.cities)
            for a in day.get("attraction", "").split(";")
            if a.strip() and a.strip() != "-"
        ]
        # print(f"[POI] NON_TRAVEL_DAY attractions: {attractions}")

        # 🔹 Inject attraction durations explicitly
        duration_block = "\n".join(
            f"- {a} = {attraction_duration_map.get(a, 120)}"
            for a in attractions
        )
        # print(f"[POI] NON_TRAVEL_DAY attraction durations:\n{duration_block}\n{'='*40}\n")

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

    This is NON_TRAVEL_DAY.

    ALL time values are INTEGER MINUTES.

    AUTHORITATIVE INPUTS (DO NOT MODIFY):

    ATTRACTION DURATIONS (minutes):
    {duration_block}

    You MUST maintain:
    - current_time
    - last_meal_end (initialize as NONE)
    - used_attractions = 0

    Constants:
    - BUFFER = 30(**Maintain a 30-minute buffer before each activity**)
    - STAY_DURATION = 30
    - MAX_ATTRACTIONS = 3

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
    """

        # STEP 0 — Day start
        instructions += STEP("Day start") + """
    - current_time = 480
    """

        # STEP 1 — Morning accommodation stay
        if accommodation and accommodation != "-":
            instructions += STEP("Morning accommodation stay") + f"""
    - stay_start = 480
    - stay_end = stay_start + STAY_DURATION
    - Add POI EXACTLY as follows:
    "{self.clean_place_name(accommodation.strip(), self.cities)}", stay from stay_start to stay_end;
    - current_time = stay_end
    **Add morning accommodation stay POI exactly as above and add it only once dont add more times**
    """

        # STEP 2 — Breakfast (LONG-ATTRACTION AWARE)
        if breakfast and breakfast != "-":
            instructions += STEP("Breakfast (LONG-ATTRACTION AWARE)") + f"""
    Breakfast timing:
    - Window: 480 to 630
    - Ideal start: 570
    - Duration: 50

    Execution:
    - If there is at least one attraction:
    - Let first_attraction_duration be its PROVIDED duration
    - If first_attraction_duration >= 180:
        - Try breakfast as early as possible:
        breakfast_start >= current_time + BUFFER
        breakfast_start >= 480
    - Otherwise:
    - Use normal ideal-based breakfast logic

    If feasible:
    - breakfast_end = breakfast_start + 50
    - Add POI EXACTLY as follows:
    "{self.clean_place_name(breakfast.strip(), self.cities)}", visit from breakfast_start to breakfast_end;
    - last_meal_end = breakfast_end
    - current_time = breakfast_end
    Else:
    - Skip breakfast
    """

        # STEP 3 — Pre-lunch attraction
        if attractions:
            instructions += STEP("Pre-lunch attraction (ONLY IF SAFE)") + """
            CRITICAL LUNCH AVAILABILITY CHECK (ABSOLUTE):

- Lunch duration = 60
- Lunch window end = 940

Before scheduling ANY pre-lunch attraction:
- current_time + BUFFER + 60 must be <= 940

If this condition FAILS:
- Skip pre-lunch attraction
- Do NOT modify current_time
- Proceed directly to Lunch

----------------------------------------------------
    - Select the FIRST attraction (shortest duration)
    - Let duration = PROVIDED attraction duration

    Tentative placement:
    - attraction_start >= current_time + BUFFER
    - attraction_end = attraction_start + duration

    Rules:
    - If duration >= 180:
    - attraction_end must be <= 940
    - Else:
    - attraction_end must be <= 880

    If rules pass:
    - Add POI EXACTLY as follows:
    "<attraction>", visit from attraction_start to attraction_end;
    - current_time = attraction_end
    - used_attractions = 1
    Else:
    SPECIAL PRE-LUNCH FULL-BLOCK ATTRACTION RULE (ABSOLUTE):

If NO attraction can be scheduled and completed early before lunch:

- You MAY schedule exactly ONE attraction that occupies the full pre-lunch time block
- This attraction MUST:
    - Start at current_time + BUFFER
    - End NO LATER than 850 (14:10)
- The attraction duration is implicitly determined by this window
- After this attraction:
    - Do NOT schedule any other pre-lunch attractions
    - Proceed directly to Lunch
    
    If Still not possible then
    - Skip pre-lunch attraction
    

    """

        # STEP 4 — Lunch
        if lunch and lunch != "-":
            instructions += STEP("Lunch") + f"""
        Lunch timing:
        - Window: 720 to 940
        - Ideal start: 880
        - Duration: 60

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define candidates:
        - Candidate A (IDEAL) = 880
        - Candidate B (EARLIEST) = current_time + BUFFER

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= 720
        - candidate + 60 <= 940
        - candidate >= current_time + BUFFER

        Decision rule (ABSOLUTE):
        - First evaluate Candidate A
        - If Candidate A is feasible → lunch_start = Candidate A
        - Else evaluate Candidate B
        - If Candidate B is feasible → lunch_start = Candidate B
        - Else → Skip lunch

        If lunch is executed:
        - lunch_end = lunch_start + 60
        - Add POI EXACTLY as follows:
        "{self.clean_place_name(lunch.strip(), self.cities)}", visit from lunch_start to lunch_end;
        - last_meal_end = lunch_end
        - current_time = lunch_end
        Else:
        - Skip lunch
        """

        # STEP 5 — Post-lunch attractions
        if attractions:
            instructions += STEP("Post-lunch attractions (MAX 2 TOTAL)") + """
            CRITICAL DINNER AVAILABILITY CHECK (ABSOLUTE):

- Dinner duration = 75
- Dinner window end = 1350

Before scheduling ANY post-lunch attraction:
- current_time + BUFFER + 75 must be <= 1350

If this condition FAILS:
- Stop adding attractions immediately
- Do NOT modify current_time
- Proceed directly to Dinner

    While:
    - used_attractions < MAX_ATTRACTIONS
    - AND more attractions remain

    For each next attraction:
    - Let duration = PROVIDED attraction duration
    - attraction_start >= current_time + BUFFER
    - attraction_end = attraction_start + duration

    Rule:
    - attraction_end + BUFFER <= 1320

    If rule passes:
    - Add POI EXACTLY as follows:
    "<attraction>", visit from attraction_start to attraction_end;
    - current_time = attraction_end
    - used_attractions += 1
    Else:
    - Stop adding attractions
    """

        # STEP 6 — Dinner
        if dinner and dinner != "-":
            instructions += STEP("Dinner") + f"""
        Dinner timing:
        - Window: 1110 to 1350
        - Ideal start: 1245
        - Duration: 75

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define candidates:
        - Candidate A (IDEAL) = 1245
        - Candidate B (EARLIEST) = current_time + BUFFER

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= 1110
        Dinner MUST NOT start before 1110 under any condition.
        If Candidate B < 1110, it is INVALID.
        - candidate + 75 <= 1350
        - candidate >= current_time + BUFFER

        Decision rule (ABSOLUTE):
        - First evaluate Candidate A
        - If Candidate A is feasible → dinner_start = Candidate A
        - Else evaluate Candidate B
        - If Candidate B is feasible → dinner_start = Candidate B
        - Else → Skip dinner

        If dinner is executed:
        - dinner_end = dinner_start + 75
        - Add POI EXACTLY as follows:
        "{self.clean_place_name(dinner.strip(), self.cities)}", visit from dinner_start to dinner_end;
        - last_meal_end = dinner_end
        - current_time = dinner_end
        Else:
        - Skip dinner
        """

        # STEP 7 — Overnight stay (NEXT DAY AWARE)
        # Decide ONCE in code
        if next_day_breakfast_same_city:
            overnight_formula = (
                "departure_abs - (BUFFER + BREAKFAST_DURATION + BUFFER + STAY_DURATION)"
            )
        else:
            overnight_formula = (
                "departure_abs - (BUFFER + STAY_DURATION)"
            )

        instructions += STEP("Overnight stay (NEXT DAY AWARE)") + f"""
AUTHORITATIVE NEXT DAY CONTEXT:
- next_day_departure_time = {next_day_departure_time if next_day_departure_time is not None else "NONE"}

Execution (ABSOLUTE — NO ALTERNATIVES):
- departure_abs = next_day_departure_time + 1440
- overnight_end = {overnight_formula}

CRITICAL (ABSOLUTE):
- overnight_end = min(computed_value, 1920)
- Overnight stay MUST NOT extend past 08:00 under any condition
- overnight_end MUST be used EXACTLY as computed above
- overnight_end MUST NOT be modified
- NO default value exists
- NO safety-based adjustment is allowed
- This STEP produces EXACTLY ONE STAY POI

Final:
- Add POI EXACTLY as follows:
{self.clean_place_name(accommodation.strip(), self.cities)}, stay from current_time to overnight_end;
"""

        return instructions.strip()

    def build_last_day_execution_hints(
        self,
        day: dict,
        day_type: str,
        previous_accommodation: str,
        previous_stay_end_min: int,
        departure_time_min: int,
        attraction_duration_map: dict,
    ) -> str:
        """
        Build NATURAL-LANGUAGE EXECUTION INSTRUCTIONS for LAST_DAY.

        - All calculations MUST be done in MINUTES
        - Buffer is applied BEFORE an activity, never after
        - Attraction durations are PROVIDED (LLM must not infer)
        - Departure cutoff is ABSOLUTE
        """

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

        # -------------------------------
        # Attraction duration injection
        # -------------------------------
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

        # STEP 0 — Hard departure cutoff
        instructions += STEP("Hard departure cutoff") + f"""
    - departure_time = {departure_time_min}
    - departure_absolute = departure_time + 1440
    - day_end = departure_absolute - BUFFER
    - NO activity may end after day_end
    """

        # STEP 1 — Checkout / tail stay
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

        # STEP 2 — Day start anchor
        instructions += STEP("Day start anchor") + """
    - current_time = max(current_time + BUFFER, 480)
    - day_anchor = current_time
    """

        # STEP 3 — Breakfast
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


        # STEP 4 — Pre-lunch attraction
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

        # STEP 5 — Lunch
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

        # STEP 6 — Post-lunch attraction
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

        # STEP 7 — Dinner
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

    def build_inter_city_execution_hints(
        self,
        day: dict,
        day_type: str,
        origin_attractions: list,
        destination_attractions: list,
        breakfast_loc: str,   # "ORIGIN" | "DESTINATION" | None
        lunch_loc: str,
        dinner_loc: str,
        previous_accommodation: str,
        previous_stay_end_min: int,
        departure_time_min: int,
        arrival_time_min: int,
        attraction_duration_map: dict,
    ) -> str:
        """
        EXECUTION-ONLY instructions for INTER_CITY_DAY.
        Python has already decided EVERYTHING.
        """

        if day_type != "INTER_CITY_DAY":
            return ""

        # ---------------------------------
        # Attraction duration injection
        # ---------------------------------
        all_attractions = origin_attractions + destination_attractions
        duration_block = ""
        if all_attractions:
            duration_block = "\n".join(
                f"- {a} = {attraction_duration_map.get(a, 120)}"
                for a in all_attractions
            )

        step = 0
        def STEP(title):
            nonlocal step
            s = f"""
    ----------------------------------------------------
    STEP {step} — {title}
    ----------------------------------------------------
    """
            step += 1
            return s

        txt = f"""
    EXECUTION MODE — FOLLOW EXACTLY
    NO REORDERING. NO INVENTION. NO GUESSING.

    This is INTER_CITY_DAY.

    ALL time values are INTEGER MINUTES.

    AUTHORITATIVE INPUTS (DO NOT MODIFY):

    ATTRACTION DURATIONS (minutes):
    {duration_block}

    You MUST maintain:
    - current_time
    - last_meal_end (initialize as NONE)
    - bf_done, ln_done, dn_done (initialize as FALSE)

    Constants:
    - BUFFER = 30
    - STAY_DUR = 30
    - MEAL_GAP = 240

    POI FORMAT (MANDATORY):
    <Place>, <visit|stay> from <START_MIN> to <END_MIN>;

    IMPORTANT:
    - START_MIN and END_MIN must be integers
    - DO NOT output HH:MM
    - DO NOT use ":"
    ABSOLUTE:
    - You are FORBIDDEN from assuming previous_stay_end or current_time

    IMPORTANT MEAL RULES:
    - Ideal start is OPTIONAL
    - Ideal start is a PREFERENCE ONLY
    - Not using the ideal start does NOT invalidate the meal
    - Any start time inside the window that satisfies feasibility rules is VALID
    - Do not skip melas for long attractions instead start early or late within the window
    """

        # --------------------------------------------------
        txt += STEP("Hard departure cutoff (ORIGIN)") + f"""
    - departure_absolute = {departure_time_min} + 1440
    - day_end = departure_absolute - BUFFER
    - NO origin activity may end after day_end
    """

        # --------------------------------------------------
        txt += STEP("Previous-day checkout (MANDATORY)") + f"""
If previous_accommodation exists:
- stay_start = {previous_stay_end_min}
- stay_end = min(stay_start + STAY_DUR, day_end)

If stay_end > stay_start:
- Add POI EXACTLY as follows:
{self.clean_place_name(previous_accommodation.strip(), self.cities)}, stay from stay_start to stay_end;

- current_time = stay_end
- THIS STEP MUST BE EXECUTED
- SKIPPING THIS STEP IS FORBIDDEN
"""


        # --------------------------------------------------
        txt += STEP("Origin ready time") + """
- origin_ready = current_time + BUFFER
- current_time = origin_ready
- last_meal_end = NONE
"""


        # --------------------------------------------------
        if breakfast_loc == "ORIGIN" and day.get("breakfast") not in ("", "-"):
            txt += STEP("ORIGIN breakfast") + f"""
    Rules:
    - Window: 1920 to 2070
    - Duration: 50
    - breakfast_start >= current_time
    - breakfast_start >= last_meal_end + MEAL_GAP (if exists)
    - breakfast_end <= day_end

    If feasible:
    Add POI EXACTLY as follows:
    {self.clean_place_name(day.get("breakfast").strip(), self.cities)}, visit from breakfast_start to breakfast_end;
    - bf_done = TRUE
    - last_meal_end = breakfast_end
    - current_time = breakfast_end + BUFFER
    """

        # --------------------------------------------------
        if origin_attractions:
            txt += STEP("ORIGIN attractions (PRE & POST lunch)") + (
                "\n".join(
                    f"- {a} (duration = {attraction_duration_map.get(a, 120)})"
                    for a in origin_attractions
                )
            ) + """
    For EACH attraction in order:

    - start = max(current_time, last_meal_end + BUFFER if exists)
    - end = start + duration

    HARD RULES:
    - end <= day_end
    - After attraction, lunch OR dinner must still be feasible

    If safe:
    - Add attraction
    - current_time = end + BUFFER
    Else:
    - STOP origin attractions
    """

        # --------------------------------------------------
        if lunch_loc == "ORIGIN" and day.get("lunch") not in ("", "-"):
            txt += STEP("ORIGIN lunch") + f"""
    Rules:
    - Window: 2160 to 2380
    - Duration: 60
    - lunch_start >= current_time
    - lunch_start >= last_meal_end + MEAL_GAP
    - lunch_end <= day_end

    If feasible:
    Add POI EXACTLY as follows:
    {self.clean_place_name(day.get("lunch").strip(), self.cities)}, visit from lunch_start to lunch_end;
    - ln_done = TRUE
    - last_meal_end = lunch_end
    - current_time = lunch_end + BUFFER
    """

        # --------------------------------------------------
        if dinner_loc == "ORIGIN" and day.get("dinner") not in ("", "-"):
            txt += STEP("ORIGIN dinner (FINAL at origin)") + f"""
    Rules:
    - Window: 2550 to 2760
    - Duration: 75
    - dinner_start >= last_meal_end + MEAL_GAP
    - dinner_end <= day_end

    Try:
    1) Ideal start
    2) Latest fallback

    If feasible:
    Add POI EXACTLY as follows:
    {self.clean_place_name(day.get("dinner").strip(), self.cities)}, visit from dinner_start to dinner_end;
    - dn_done = TRUE
    - last_meal_end = dinner_end
    """

        # --------------------------------------------------
        txt += STEP("Arrival at destination") + f"""
    - arrival_time = {arrival_time_min}
    - current_time = arrival_time + BUFFER
    """

        # --------------------------------------------------
        if day.get("accommodation") not in ("", "-"):
            txt += STEP("Destination check-in") + f"""
    Add POI EXACTLY as follows:
    {self.clean_place_name(day.get("accommodation").strip(), self.cities)}, stay from current_time to current_time + STAY_DUR;
    - current_time += STAY_DUR
    - Apply BUFFER if anything remains
    """

        # --------------------------------------------------
        if breakfast_loc == "DESTINATION" and day.get("breakfast") not in ("", "-"):
            txt += STEP("DESTINATION breakfast (IF NOT DONE)") + f"""
        Schedule ONLY if bf_done = FALSE.

        Rules:
        - Window: 480 to 630
        - Duration: 50
        - breakfast_start >= current_time
        - breakfast_start >= last_meal_end + MEAL_GAP (if last_meal_end exists)
        - breakfast_end <= 630

        Try in order:
        1) Ideal start (if feasible)
        2) Earliest valid start inside window

        If feasible:
        Add POI EXACTLY as follows:
        {self.clean_place_name(day.get("breakfast").strip(), self.cities)}, visit from breakfast_start to breakfast_end;
        - bf_done = TRUE
        - last_meal_end = breakfast_end
        - current_time = breakfast_end + BUFFER
        Else:
        - Skip breakfast
        """


        # --------------------------------------------------
        if destination_attractions:
            txt += STEP("DESTINATION attractions (PRE-LUNCH & PRE-DINNER)") + (
                "\n".join(
                    f"- {a} (duration = {attraction_duration_map.get(a, 120)})"
                    for a in destination_attractions
                )
            ) + f"""
        For EACH attraction IN ORDER:

        Tentative timing:
        - attraction_start = current_time
        - attraction_end = attraction_start + duration

        HARD FEASIBILITY CHECKS (ALL REQUIRED):
        - attraction_end + BUFFER <= 1920
        - If ln_done = FALSE:
            lunch must still have at least ONE valid start inside its window
        - Dinner must still have at least ONE valid start inside its window

        If ALL checks pass:
        - Add POI EXACTLY as follows:
        <attraction>, visit from attraction_start to attraction_end;
        Dont include the city name in attraction while adding in the poi;
        - current_time = attraction_end + BUFFER
        Else:
        - STOP destination attractions immediately
        - Do NOT modify current_time
        """

        # --------------------------------------------------
        if lunch_loc == "DESTINATION" and day.get("lunch") not in ("", "-"):
            txt += STEP("DESTINATION lunch (IF NOT DONE)") + f"""
        Schedule ONLY if ln_done = FALSE.

        Lunch timing:
        - Window: 720 to 940
        - Ideal start: 880
        - Duration: 60

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define bounds:
        - earliest_allowed = max(
            current_time,
            last_meal_end + MEAL_GAP if last_meal_end exists else current_time
        )
        - latest_allowed_end = 1920

        Define candidates:
        - Candidate A (IDEAL) = 880
        - Candidate B (EARLIEST) = earliest_allowed

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= earliest_allowed
        - candidate >= 720
        - candidate + 60 <= 940
        - candidate + 60 <= latest_allowed_end

        Decision rule (ABSOLUTE):
        - First evaluate Candidate A
        - If Candidate A is feasible → lunch_start = Candidate A
        - Else evaluate Candidate B
        - If Candidate B is feasible → lunch_start = Candidate B
        - Else → Skip lunch

        If lunch is executed:
        - lunch_end = lunch_start + 60
        - Add POI EXACTLY as follows:
        {self.clean_place_name(day.get("lunch").strip(), self.cities)}, visit from lunch_start to lunch_end;
        - ln_done = TRUE
        - last_meal_end = lunch_end
        - current_time = lunch_end + BUFFER
        Else:
        - Skip lunch
        """


        # --------------------------------------------------
        if dinner_loc == "DESTINATION" and day.get("dinner") not in ("", "-"):
            txt += STEP("DESTINATION dinner (FINAL MEAL)") + f"""
        Schedule ONLY if dn_done = FALSE.

        Dinner timing:
        - Window: 1110 to 1350
        - Ideal start: 1245
        - Duration: 75

        Execution (ORDERED — MUST FOLLOW EXACTLY):

        Define bounds:
        - earliest_allowed = max(
            current_time,
            last_meal_end + MEAL_GAP if last_meal_end exists else current_time
        )
        - latest_allowed_end = 1920

        Define candidates:
        - Candidate A (IDEAL) = 1245
        - Candidate B (EARLIEST) = earliest_allowed

        Feasibility check (apply to EACH candidate):
        A candidate is feasible ONLY IF:
        - candidate >= earliest_allowed
        - candidate >= 1110
        - candidate + 75 <= 1350
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
        {self.clean_place_name(day.get("dinner").strip(), self.cities)}, visit from dinner_start to dinner_end;
        - dn_done = TRUE
        - last_meal_end = dinner_end
        - current_time = dinner_end + BUFFER
        Else:
        - Skip dinner
        """


        # --------------------------------------------------
        txt += STEP("Destination overnight stay (FINAL)") + f"""
    Add POI EXACTLY as follows:
    {self.clean_place_name(day.get("accommodation").strip(), self.cities)}, stay from current_time to 1920;
    """

        return txt.strip()

    def min_to_hhmm(self,m: int) -> str:
        m = m % 1440
        h = m // 60
        mi = m % 60
        return f"{h:02d}:{mi:02d}"

    def convert_minutes_to_time(self,itinerary: str) -> str:
        """
        Converts:
        visit from 510 to 640;
        into:
        visit from 08:30 to 10:40;
        """

        lines = []
        for line in itinerary.splitlines():
            match = re.search(r"from\s+(\d+)\s+to\s+(\d+);", line)
            if not match:
                lines.append(line)
                continue

            start_min = int(match.group(1))
            end_min = int(match.group(2))

            start_time = self.min_to_hhmm(start_min)
            end_time = self.min_to_hhmm(end_min)

            line = re.sub(
                r"from\s+\d+\s+to\s+\d+;",
                f"from {start_time} to {end_time};",
                line
            )
            lines.append(line)

        return "\n".join(lines)

    def enforce_monotonic_schedule(self,itinerary: str) -> str:
        entries = []
        for line in itinerary.splitlines():
            m = re.search(r"from (\d+) to (\d+);", line)
            if not m:
                continue
            start = int(m.group(1))
            end = int(m.group(2))
            entries.append((start, end, line))

        # sort by start time
        entries.sort(key=lambda x: x[0])

        # validate monotonicity
        cleaned = []
        prev_end = None
        for start, end, line in entries:
            if prev_end is not None and start < prev_end:
                # ❌ invalid overlap → drop this POI
                continue
            cleaned.append(line)
            prev_end = end

        return "\n".join(cleaned)


    def _add_stay_transit_post_llm(self, result, days, structured_input):
        """
        Post-process LLM itineraries.
        Adds nearest transit ONLY for stay entries.
        Assumes POIs and cities are already correct.
        """

        cities_data = structured_input.get("cities", [])
        city_map = {c["city"]: c for c in cities_data}

        for idx, day in enumerate(days):
            day_number = idx + 1
            itinerary = result.get(day_number)

            if not itinerary:
                continue

            accommodation = day.get("accommodation")
            if not accommodation or accommodation == "-":
                # nothing to resolve for this day
                continue

            poi_city = extract_city_from_poi(accommodation)
            if not poi_city:
                continue

            city_block = city_map.get(poi_city, {})
            raw_rows = city_block.get("raw_transit_rows", [])

            updated_entries = []

            for entry in itinerary.split(";"):
                entry = entry.strip()
                if not entry:
                    continue

                # Only modify stay entries without transit
                if " stay from " in entry and "nearest transit" not in entry:

                    place = entry.split(", stay from ", 1)[0].strip()

                    transit = self.resolve_transit_for_poi(
                        poi_name=place,
                        city=poi_city,
                        raw_rows=raw_rows
                    )

                    if transit:
                        entry = (
                            f"{entry}, nearest transit: "
                            f"{transit['stop']}, "
                            f"{transit['distance']}m away"
                        )

                updated_entries.append(entry + ";")

            result[day_number] = " ".join(updated_entries)

    def build_global_rules_non_travel_block(self) -> str:
        return """
    ==================================================
    GLOBAL DAY STRUCTURE + TIMING RULES (ABSOLUTE)
    ==================================================

    -------------------------------
    1. DAY STRUCTURE (STRICT ORDER)
    -------------------------------
    The itinerary MUST follow EXACTLY this sequence:

    1. Morning STAY
    2. Breakfast
    3. Pre-lunch attraction (optional)
    4. Lunch
    5. Post-lunch attractions (optional)
    6. Dinner
    7. Overnight STAY

    Rules:
    - You are FORBIDDEN from reordering steps
    - You are FORBIDDEN from inserting steps outside this order
    - If a step is skipped, continue forward only (NO reordering)

    --------------------------------
    2. MEALS (MANDATORY — ABSOLUTE)
    --------------------------------
    - Breakfast, Lunch, and Dinner MUST ALWAYS be scheduled
    - Meals MUST NOT be skipped under any condition

    If a meal is not feasible:
        You MUST resolve by:
        1. Adjusting attraction timings
        2. Moving attractions (pre ↔ post meal)
        3. Reducing attraction duration (minimum = 60)

    - Skipping a meal is STRICTLY FORBIDDEN

    ----------------------------------------
    3. MEAL GAP RULE (VERY IMPORTANT)
    ----------------------------------------
    - MIN_MEAL_GAP = 240 minutes (4 hours)

    - If last_meal_end is NOT NONE:
        meal_start MUST satisfy:
        meal_start >= last_meal_end + 240

    - If violated:
        - You MUST adjust schedule
        - You MUST NOT violate the gap

    ----------------------------------------
    4. BUFFER RULE (GLOBAL)
    ----------------------------------------
    - BUFFER = 30 minutes

    - EVERY step MUST satisfy:
        step_start >= current_time + BUFFER

    - Applies to:
        - meals
        - attractions
        - stays (except first stay at 480)

    ----------------------------------------
    5. ATTRACTIONS RULES
    ----------------------------------------
    - MAX_ATTRACTIONS = 3
    - MIN_ATTRACTIONS = 1 (MANDATORY)

    You are FORBIDDEN from:
    - Having zero attractions
    - Exceeding 3 attractions

    Placement rules:
    - Pre-lunch: max 1 attraction
    - Post-lunch: remaining attractions

    Distribution:
    - 1 attraction → post-lunch preferred
    - 2 attractions → 1 pre + 1 post
    - 3 attractions → 1 pre + 2 post

    ----------------------------------------
    6. POST-DINNER RULE
    ----------------------------------------
    - After Dinner:
        - NO attractions allowed
        - ONLY overnight stay is allowed

    ----------------------------------------
    7. PRIORITY ORDER (CRITICAL)
    ----------------------------------------
    Priority hierarchy:

    1. Meals (highest priority — MUST exist)
    2. Minimum one attraction (MUST exist)
    3. Additional attractions (optional)

    Conflict resolution order:
    1. Adjust attraction timing
    2. Reduce attraction duration (>= 60)
    3. Move attraction (pre ↔ post)
    4. Remove extra attractions (but KEEP at least one)

    ----------------------------------------
    8. TIME CONSISTENCY RULES
    ----------------------------------------
    - current_time MUST always increase
    - No overlapping steps allowed
    - Each step must fully complete before next

    ----------------------------------------
    9. EXECUTION GUARANTEES
    ----------------------------------------
    Final itinerary MUST satisfy:

    ✔ All 3 meals present  
    ✔ At least 1 attraction present  
    ✔ Max 3 attractions  
    ✔ Correct step order  
    ✔ ≥ 240 min gap between meals  
    ✔ 30 min buffer before every step  
    ✔ No activity after dinner except stay  

    ==================================================
    """


    # ----------------------------------------------------------
    # MAIN LOGIC
    # ----------------------------------------------------------
    def generate_poi_list(
        self,
        days: List[Dict[str, Any]],
        structured_input: Dict[str, Any],
    ) -> Dict[int, str]:
        self.persona = structured_input.get("JSON", {}).get("persona", "")
        self.cities = structured_input.get("cities", [])



        # --------------------------------------------------
        # GLOBAL OUTPUT CONTRACT (ADDED ONCE)
        # --------------------------------------------------
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
        # --------------------------------------------------
        # Helpers
        # --------------------------------------------------
        def clean(x):
            if not x:
                return x
            for c in cities:
                city = c.get("city")
                if city and x.endswith(f", {city}"):
                    return x.replace(f", {city}", "").strip()
            return x.strip()

        # --------------------------------------------------
        # Build attraction duration map (AUTHORITATIVE)
        # --------------------------------------------------
        cities = structured_input.get("cities", [])
        self.cities = cities
        self.days = days
        attraction_duration_map: Dict[str, int] = {}

        for c in cities:
            for a in c.get("attractions_ranked", []):
                name = clean(a.get("name"))
                dur_hr = a.get("visit_duration")
                if name and dur_hr:
                    attraction_duration_map[name] = int(dur_hr * 60)

        # print(f"[POI] Attraction duration map:\n{attraction_duration_map}\n{'='*40}\n")

        result: Dict[int, str] = {}

        # ==================================================
        # MAIN LOOP
        # ==================================================
        for idx, original_day in enumerate(days):
            day = dict(original_day)  # 🔒 copy

            # --------------------------------------------------
            # 1️⃣ Classify day
            # --------------------------------------------------
            day_type = self.classify_day(day, idx, days)

            # --------------------------------------------------
            # 2️⃣ LAST_DAY accommodation inheritance
            # --------------------------------------------------
            if day_type == "LAST_DAY" and day.get("accommodation") in ("", "-"):
                if idx > 0 and days[idx - 1].get("accommodation") not in ("", "-"):
                    day["accommodation"] = days[idx - 1]["accommodation"]

            # --------------------------------------------------
            # 3️⃣ Previous day context (ONLY when required)
            # --------------------------------------------------
            previous_accommodation = None
            previous_stay_end = None

            if idx > 0 and day_type in ("INTER_CITY_DAY", "LAST_DAY"):
                prev_itinerary = result.get(idx)
                if prev_itinerary:
                    previous_accommodation, previous_stay_end = (
                        self.extract_prev_stay_context(prev_itinerary)
                    )
                    # if idx==2:
                    #     print(previous_accommodation,previous_stay_end,prev_itinerary)

            # --------------------------------------------------
            # 4️⃣ Build EXECUTION PROMPT (CORE LOGIC)
            # --------------------------------------------------
            day_duration_map = self.build_day_adjusted_duration_map(
                day,
                attraction_duration_map,
            )

            if day_type == "FIRST_DAY":
                execution_prompt = self.build_first_day_execution_hints(day, day_type,attraction_duration_map=day_duration_map)

            elif day_type == "NON_TRAVEL_DAY":
                GLOBAL_RULES = self.build_global_rules_non_travel_block()
                next_day = days[idx + 1] if idx + 1 < len(days) else None
                next_day_departure_time = (
                    self.extract_departure_time(next_day) if next_day else None
                )
                next_day_has_breakfast = (
                    next_day is not None
                    and next_day.get("breakfast") not in ("", "-", None)
                )
                next_day_breakfast_city = None
                if next_day_has_breakfast:
                    next_day_breakfast_city = extract_city_from_poi(
                        next_day.get("breakfast")
                    )

                today_city = extract_city_from_poi(day.get("accommodation"))
                next_day_breakfast_same_city = (
                    next_day_has_breakfast
                    and next_day_breakfast_city is not None
                    and today_city == next_day_breakfast_city
                )
                execution_prompt = self.build_non_travel_execution_hints(
                    day,
                    day_type,
                    # next_day_transportation=(
                    #     next_day.get("transportation") if next_day else None
                    # ),
                    next_day_departure_time=next_day_departure_time,
                    attraction_duration_map=day_duration_map,
                    next_day_breakfast_same_city=next_day_breakfast_same_city
                )
                execution_prompt = GLOBAL_RULES + "\n\n" + execution_prompt

            elif day_type == "LAST_DAY":
                execution_prompt = self.build_last_day_execution_hints(
                    day,
                    day_type,
                    previous_accommodation,
                    previous_stay_end,
                    self.extract_departure_time(day),
                    attraction_duration_map=day_duration_map,
                )

            elif day_type == "INTER_CITY_DAY":
                (
                    origin_atts,
                    dest_atts,
                    breakfast_loc,
                    lunch_loc,
                    dinner_loc,
                ) = self.resolve_inter_city_ownership(day)

                execution_prompt = self.build_inter_city_execution_hints(
                    day,
                    day_type,
                    origin_atts,
                    dest_atts,
                    breakfast_loc,
                    lunch_loc,
                    dinner_loc,
                    previous_accommodation,
                    previous_stay_end,
                    self.extract_departure_time(day),
                    self.extract_arrival_time(day),
                    attraction_duration_map=day_duration_map,
                )
            else:
                raise ValueError(f"Unknown day type: {day_type}")

            # --------------------------------------------------
            # 5️⃣ FINAL PROMPT = OUTPUT CONTRACT + EXECUTION PROMPT
            # --------------------------------------------------
            prompt = OUTPUT_CONTRACT + "\n\n" + execution_prompt + "\n\n" + VERIFY
            # if idx == 1:
            #     print(f"[POI] Day {idx + 1} prompt:\n{prompt}\n{'-'*40}\n")
            # debug_dir = Path("/scratch/sg/Vijay/TripCraft/debug/poi_llm")
            # debug_dir.mkdir(parents=True, exist_ok=True)


            # --------------------------------------------------
            # 6️⃣ Call LLM
            # --------------------------------------------------
            response = self.llm.generate(prompt)
            # print("POI Agent for index:",idx,response)

            # debug_file = debug_dir / f"day_{idx+1}_full.txt"
            # with open(debug_file, "w") as f:
            #     f.write("========== PROMPT ==========\n\n")
            #     f.write(prompt)
            #     f.write("\n\n========== RESPONSE ==========\n\n")
            #     f.write(response)

            # if idx == 1:
            #     print(f"[POI] Day {idx + 1} response:\n{response}\n{'-'*40}\n")

            if "ITINERARY" not in response:
                # print(f"[WARN] Day {idx+1}: Missing ITINERARY section")
                result[idx + 1] = ""  
                continue 
                # raise RuntimeError("Missing ITINERARY section from LLM")
        
            itinerary = extract_itinerary(response)
            if not itinerary:
                # print(f"[WARN] Day {idx+1}: Empty itinerary")
                result[idx + 1] = ""  
                continue  
                # raise RuntimeError("Empty itinerary from LLM")

            # --------------------------------------------------
            # 7️⃣ Save result
            # --------------------------------------------------
            itinerary = self.enforce_monotonic_schedule(itinerary)
            itinerary = self.convert_minutes_to_time(itinerary)
            # print(f"[POI] Day {idx + 1} itinerary:\n{itinerary}\n{'='*40}\n")
            # with open(debug_file, "a") as f:
            #     f.write("\n\n========== FINAL ITINERARY (HH:MM) ==========\n\n")
            #     f.write(itinerary)
            # print(f"[POI] Day {idx + 1} itinerary saved to {debug_file}")
        
            result[idx + 1] = itinerary

        cities_data = structured_input.get("cities", [])
        city_map = {c["city"]: c for c in cities_data}
        # ==================================================
        # POST-LMM TRANSIT ATTACHMENT LOOP (NEW LOOP)
        # ==================================================
        # print(result)

        for idx, day in enumerate(days):
            day_number = idx + 1

            itinerary = result.get(day_number)
            if not itinerary:
                continue

            # print("Day:", day)

            # --------------------------------------------------
            # Collect POIs directly from DAY (city preserved)
            # --------------------------------------------------
            pois = collect_day_pois_with_city(day)
            # print("POIS:", pois)

            # --------------------------------------------------
            # Build TRANSIT MAP (keyed by POI NAME)
            # --------------------------------------------------
            transit_map = {}

            for poi in pois:
                poi_city = extract_city_from_poi(poi)
                if not poi_city:
                    continue

                city_block = city_map.get(poi_city, {})
                raw_rows = city_block.get("raw_transit_rows", [])

                transit = self.resolve_transit_for_poi(
                    poi_name=clean(poi),   # remove ", City"
                    city=poi_city,
                    raw_rows=raw_rows
                )

                if transit:
                    transit_map[clean(poi)] = {
                        "stop": transit["stop"],
                        "distance": transit["distance"],
                    }

            # --------------------------------------------------
            # Attach transit ONLY to EXECUTED POIs
            # --------------------------------------------------
            itinerary = itinerary.replace('"', '').replace("'", "")
            itinerary = re.sub(r'(^|\n)\s*-\s*', r'\1', itinerary)
            itinerary = re.sub(r'(^|\n)\s*\d+\.\s*', r'\1', itinerary)
            # print("Transit map:", transit_map)

            itinerary = self.attach_transits_post_llm(
                itinerary,
                transit_map,
            )

            result[day_number] = itinerary

        self._add_stay_transit_post_llm(result, days, structured_input)
        return result
