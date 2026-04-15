# agentic_trip/tools/poihelper.py

import json
import sys
import os
from pathlib import Path
from typing import Any, Dict, List,Optional

from core.llm_backend import init_llm
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


class POIsAgent:
    """
    LLM-based POI scheduler (evaluation agent).
    Standalone helper with DAY-TYPE–AWARE prompting.
    """

    def __init__(self, llm):
        self.llm = llm

    # ----------------------------------------------------------
    # Transit resolver (deterministic)
    # ----------------------------------------------------------
    def resolve_transit_for_poi(self, poi_name: str, raw_rows: list):
        poi_l = poi_name.lower()
        best = None
        best_dist = float("inf")

        for row in raw_rows:
            try:
                head, lat, lon, dist = row.rsplit(" ", 3)
                dist_val = float(dist)
            except ValueError:
                continue

            if poi_l not in head.lower():
                continue

            if dist_val > 5000:
                continue

            if dist_val < best_dist:
                best = {
                    "stop": head,
                    "distance": round(dist_val, 2)
                }
                best_dist = dist_val

        return best

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
    # Example injector (INTENTIONALLY EMPTY FOR NOW)
    # ----------------------------------------------------------
    def get_examples_block(self, day_type: str) -> str:
        """
        IMPORTANT:
        This is intentionally LEFT BLANK.
        We will fill this AFTER discussing each day type.

        Each block will contain:
        - 2 abstract examples
        - NO real cities
        - NO real POIs
        """

        if day_type == "FIRST_DAY":
            return """
            On FIRST_DAY, take the arrival time directly from the transportation details and set it as the initial current_time. Apply a mandatory transportation buffer of exactly 30 minutes, so current_time = arrival_time + 30 minutes. Immediately after this buffer, place the arrival accommodation stay, which is compulsory and lasts exactly 30 minutes, and output it as <Accommodation Name>, stay from <current_time> to <current_time + 30 minutes>;. After this stay, update current_time = arrival_time + 60 minutes. The arrival stay and the overnight stay are two distinct and separate records and must never be merged, even if their times are contiguous. If at this point current_time ≥ 21:10, no meals or attractions are allowed, meal feasibility logic is fully disabled, and you must directly place the overnight accommodation stay starting at current_time and ending exactly at 08:00 the next day, which must be the final entry of the day. If current_time < 21:10, evaluate meals and attractions strictly in the order breakfast, attraction 1, lunch, attraction 2, and dinner, placing each only if it fully fits within its respective time window, respects a minimum 4-hour gap between consecutive meals, does not overlap with any other activity, and preserves future meal feasibility; meals must be scheduled at their ideal times when possible, otherwise at any valid time within the window. A mandatory 30-minute transition buffer must be applied after every meal or attraction, but never between consecutive stays at the same accommodation. After all feasible meals and attractions have been evaluated, you must place the overnight accommodation stay as a separate final record starting exactly at the last current_time and ending exactly at 08:00 the next day; this overnight stay must never be shortened, back-calculated, merged with the arrival stay, or preceded by a buffer. 
          
            FIRST_DAY ORDERING RULE (ABSOLUTE):

On FIRST_DAY, planning MUST proceed in this exact order:

1) Arrival check-in stay (30 minutes)
2) Meals and attractions (if feasible)
3) Overnight stay (FINAL entry)

You are STRICTLY FORBIDDEN from placing the overnight stay
before all feasible meals and attractions are evaluated.

            We will have the checkin stay after 30 minutes of arrival its compulsory and not skippable you can see provided reference examples for it.
            OVERNIGHT STAY RULE (MANDATORY):
- If accommodation exists, you MUST output an overnight stay.
- The overnight stay MUST be the final entry of the day.
- The overnight stay MUST start immediately after the last activity.
- The overnight stay MUST end at:
  - 08:00 next day, OR
  - earlier if constrained by NEXT DAY transportation.
- You are NOT allowed to omit the overnight stay.
            FIRST_DAY ARRIVAL BUFFER RULE (HARD CONSTRAINT):

On FIRST_DAY, arrival buffer is applied EXACTLY ONCE.

Let:
arrival_time = time from transportation

You MUST compute:
arrival_stay_start = arrival_time + 30 minutes
arrival_stay_end   = arrival_stay_start + 30 minutes

Rules:
- You MUST NOT apply any other buffer before the first stay
- You MUST NOT apply a transition buffer between arrival buffer and arrival stay
- arrival_stay_start MUST be exactly arrival_time + 30 minutes
- Any additional buffer before the first stay is INVALID

FIRST_DAY ACCOMMODATION STRUCTURE (ABSOLUTE — NON-NEGOTIABLE)

If accommodation exists on FIRST_DAY:

You MUST ALWAYS create EXACTLY TWO stay blocks, in this order:

1) Arrival stay
2) Overnight stay

This rule applies EVEN IF:
- No meals are feasible
- No attractions exist
- Arrival is very late
- The day contains ONLY accommodation

You are STRICTLY FORBIDDEN from:
- Merging these two stays
- Omitting either stay
- Replacing them with a single stay

If TWO separate stay entries are not present,
the output is INVALID.
FIRST_DAY STAY IDENTITY RULE (ABSOLUTE — HARD):

On FIRST_DAY, the arrival stay and overnight stay are TWO DISTINCT RECORDS.

- The arrival stay MUST be a standalone 30-minute stay block
- The overnight stay MUST be a separate stay block
- Even if arrival_stay_end == overnight_start, they MUST be output as TWO lines
- You are NOT allowed to merge contiguous stays
- Contiguous time ranges do NOT imply a single stay

If the output contains only ONE stay on FIRST_DAY,
the output is INVALID.


FIRST_DAY MEAL OVERRIDE (ABSOLUTE — HARD):

On FIRST_DAY, if arrival_time  ≥ 20:00:

- You MUST NOT schedule breakfast, lunch, or dinner
- You MUST proceed directly to the overnight stay
- Meal feasibility logic is DISABLED
- This rule OVERRIDES all meal windows and ideal times

----------------------------------------------------
FIRST_DAY OVERNIGHT DURATION RULE (ABSOLUTE)
----------------------------------------------------

On FIRST_DAY ONLY:

- The overnight stay has NO FIXED DURATION
- It is NOT a 30-minute stay
- It MUST start EXACTLY at the end of the arrival stay
- It MUST end EXACTLY at 08:00 next day

Therefore:
overnight_start = arrival_stay_end
overnight_end   = 08:00

You are STRICTLY FORBIDDEN from:
- Treating overnight stay as STAY_DURATION
- Back-calculating overnight_start
- Shortening the overnight stay

----------------------------------------------------
FIRST_DAY OVERNIGHT FINALITY RULE (CRITICAL — HARD)
----------------------------------------------------

On FIRST_DAY:

- The overnight stay MUST end at exactly 08:00 next day
- You MUST NOT shorten the overnight stay
- You MUST NOT back-calculate overnight_start from 08:00
- You MUST NOT apply NEXT_DAY, LAST_DAY, or departure logic
- You MUST NOT subtract STAY_DURATION or BUFFER from 08:00

The overnight stay on FIRST_DAY is FIXED:
- overnight_end = 08:00 (absolute)
- This rule OVERRIDES all other timing logic


            REASONING STYLE (HOW TO THINK)

Planning proceeds strictly forward in time.

Start from the arrival time mentioned in transportation.
Compute earliest usable time as:
arrival time + 30-minute transition buffer.


If accommodation exists:
- Allocate a 30-minute stay at the earliest usable time.
- Advance current time to the end of the stay.
After arrival stay:
- current_time = arrival_stay_end
- You MUST NOT apply any buffer unless a NON-STAY activity is placed
- Overnight stay is NOT preceded by a buffer
FIRST_DAY INVARIANT (NON-NEGOTIABLE):

arrival_stay_end == overnight_start



For each meal in order:
- Check whether current time + meal duration fits fully inside the meal window.
- If it fits, schedule the meal near its ideal time, but not earlier than current time.
- After the meal, advance time and apply a 30-minute transition buffer.
- If it does not fit, skip the meal.

For attractions:
- Tentatively place the attraction at the current time.
- Verify that placing it does not prevent the next required meal.
- Keep the attraction only if future meals remain feasible.
- Apply a transition buffer afterward.

End the day with an overnight accommodation stay until 08:00 next day.
CRITICAL RULE (MUST FOLLOW):
If accommodation exists on FIRST_DAY:
- You MUST output TWO stay entries:
  1) arrival-buffer stay (30 minutes)
  2) overnight stay ending at 08:00 next day
- The overnight stay is REQUIRED even if no other activities exist.
- NEVER omit the overnight stay.
- NEVER attach transit info to accommodation stays.

FIRST DAY STAY RULE (CRITICAL):
- If arrival time is after 18:00
- AND accommodation exists
- You MUST create TWO stay blocks:
  1) Arrival stay: 30 minutes after arrival + buffer
  2) Overnight stay: from end of arrival stay to 08:00
- NEVER merge these into a single stay


Ensure:
- No overlaps
- All buffers applied
- Meal gaps respected
- Output order strictly follows PLACES order

If nearest transit is available:
- Include it in output
If nearest transit is unknown:
- Omit transit info

NOTE:
The following examples are for learning the scheduling pattern only.
They are NOT related to the current input day.
Place names are generic.
Places are written strictly in PLACES order.

====================================================
REFERENCE EXAMPLES (FOR LEARNING ONLY)
====================================================

EXAMPLE 1 — FIRST DAY (EARLY ARRIVAL, FULL DAY, WITH TRANSIT)

PLAN (INPUT DAY)
{
  "day": 1,
  "current_city": "from CityA to CityB",
  "transportation": "Flight, Arrival Time: 07:45",
  "breakfast": "Breakfast X",
  "lunch": "Lunch Y",
  "dinner": "Dinner Z",
  "attraction": "Attraction A; Attraction B;",
  "accommodation": "Hotel H",
  "event": "-"
}

REASONING
Arrival is early, so a full-day plan is possible.
After arrival buffer, accommodation stay is placed.
Breakfast fits and is scheduled near ideal.
Attraction A is placed only if lunch remains feasible.
Lunch fits and is scheduled.
Attraction B is placed only if dinner remains feasible.
Dinner fits and is scheduled.
Overnight stay ends the day.

OUTPUT
Hotel H, stay from 08:15 to 08:45;
Breakfast X, visit from 09:30 to 10:20;
Attraction A, visit from 10:50 to 12:50;
Lunch Y, visit from 14:40 to 15:40;
Attraction B, visit from 16:10 to 18:10;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 08:00;

----------------------------------------------------

EXAMPLE 2 — FIRST DAY (AFTERNOON ARRIVAL, PARTIAL DAY, WITH TRANSIT)

PLAN (INPUT DAY)
{
  "day": 1,
  "current_city": "from CityA to CityB",
  "transportation": "Road travel, Arrival Time: 14:15",
  "breakfast": "-",
  "lunch": "-",
  "dinner": "Dinner Z",
  "attraction": "Attraction A;",
  "accommodation": "Hotel H",
  "event": "-"
}

REASONING
Arrival occurs after breakfast and lunch windows.
Accommodation stay is placed first.
Attraction A is placed only if dinner remains feasible.
Dinner fits and is scheduled.
Overnight stay ends the day.

OUTPUT
Hotel H, stay from 14:45 to 15:15;
Attraction A, visit from 15:45 to 17:45;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 08:00;

----------------------------------------------------

EXAMPLE 3 — FIRST DAY (MIDDAY ARRIVAL, NO TRANSIT)

PLAN (INPUT DAY)
{
  "day": 1,
  "current_city": "from CityA to CityB",
  "transportation": "Flight, Arrival Time: 13:30",
  "breakfast": "-",
  "lunch": "Lunch Y",
  "dinner": "Dinner Z",
  "attraction": "Attraction A;",
  "accommodation": "Hotel H",
  "event": "-"
}

REASONING
Arrival occurs after breakfast window.
Accommodation stay is placed.
Lunch fits and is scheduled.
Attraction A is placed only if dinner remains feasible.
Dinner fits and is scheduled.
Overnight stay ends the day.

OUTPUT
Hotel H, stay from 14:00 to 14:30;
Lunch Y, visit from 14:40 to 15:40;
Attraction A, visit from 16:10 to 18:10;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 08:00;

----------------------------------------------------

EXAMPLE 4 — FIRST DAY (VERY LATE ARRIVAL, STAY ONLY)

PLAN (INPUT DAY)
{
  "day": 1,
  "current_city": "from CityA to CityB",
  "transportation": "Flight, Arrival Time: 23:55",
  "breakfast": "-",
  "lunch": "-",
  "dinner": "-",
  "attraction": "-",
  "accommodation": "Hotel H",
  "event": "-"
}

REASONING
Arrival occurs after all meal windows.
Only accommodation stays are feasible.

OUTPUT
Hotel H, stay from 00:25 to 00:55;
Hotel H, stay from 00:55 to 08:00;

----------------------------------------------------

EXAMPLE 5 — FIRST DAY (EVENING ARRIVAL, DINNER ONLY, WITH TRANSIT)

PLAN (INPUT DAY)
{
  "day": 1,
  "current_city": "from CityA to CityB",
  "transportation": "Road travel, Arrival Time: 19:30",
  "breakfast": "-",
  "lunch": "-",
  "dinner": "Dinner Z",
  "attraction": "-",
  "accommodation": "Hotel H",
  "event": "-"
}

REASONING
Arrival occurs after breakfast and lunch windows.
Accommodation stay is placed first.
Dinner fits within its window.
No attractions fit safely afterward.

OUTPUT
Hotel H, stay from 20:00 to 20:30;
Dinner Z, visit from 21:00 to 22:15;
Hotel H, stay from 22:15 to 08:00;
    """

        elif day_type == "NON_TRAVEL_DAY":
            return """
            OVERNIGHT STAY RULE (MANDATORY):
- If accommodation exists, you MUST output an overnight stay.
- The overnight stay MUST be the final entry of the day.
- The overnight stay MUST start immediately after the last activity.
- The overnight stay MUST end at:
  - 08:00 next day, OR
  - earlier if constrained by NEXT DAY transportation.
- You are NOT allowed to omit the overnight stay.
    REASONING STYLE (HOW TO THINK)

This is a NON-TRAVEL DAY.
There is NO arrival today and the city does NOT change.

----------------------------------------------------
STEP 1 — Day start
----------------------------------------------------
The day always starts at 08:00.

If accommodation exists:
- Place a morning stay from 08:00 to 08:30.

Set:
current_time = 08:30

----------------------------------------------------
STEP 2 — Breakfast
----------------------------------------------------
Breakfast rules:
- Breakfast MUST START between 08:00 and 10:30
- Breakfast duration is fixed
- A 30-minute buffer is required after breakfast

Check feasibility:
If current_time + breakfast_duration ≤ 10:30:
- Schedule breakfast near the ideal time
- breakfast_start = max(current_time, breakfast_ideal)
- breakfast_end   = breakfast_start + duration
- current_time    = breakfast_end + 30 minutes
Else:
- Skip breakfast

----------------------------------------------------
STEP 3 — Pre-lunch attraction (AT MOST ONE)
----------------------------------------------------
Tentatively try placing ONE attraction before lunch.

Compute:
attraction_start = current_time
attraction_end   = attraction_start + attraction_duration

This attraction is allowed ONLY IF:
attraction_end ≤ lunch_ideal_time

If allowed:
- Place attraction
- current_time = attraction_end + 30 minutes
Else:
- Skip pre-lunch attraction

----------------------------------------------------
STEP 4 — Lunch
----------------------------------------------------
Lunch rules:
- Lunch MUST START between 12:00 and 15:30
- Lunch duration is fixed
- Meal gap must be respected

Check feasibility:
If current_time + lunch_duration ≤ 15:30:
- lunch_start = max(current_time, lunch_ideal)
- lunch_end   = lunch_start + duration
- current_time = lunch_end + 30 minutes
Else:
- Skip lunch

----------------------------------------------------
STEP 5 — Post-lunch attractions (UP TO TOTAL 2)
----------------------------------------------------
Attractions after lunch:
- Total attractions for the day ≤ 2
- Each attraction must finish BEFORE dinner window starts

For each remaining attraction:
- attraction_start = current_time
- attraction_end   = attraction_start + attraction_duration

If attraction_end ≤ dinner_window_start:
- Place attraction
- current_time = attraction_end + 30 minutes
Else:
- Stop adding attractions

----------------------------------------------------
STEP 6 — Dinner
----------------------------------------------------
Dinner rules:
- Dinner MUST START between 18:30 and 22:30

Check feasibility:
If current_time + dinner_duration ≤ 22:30:
- dinner_start = max(current_time, dinner_ideal)
- dinner_end   = dinner_start + duration
- current_time = dinner_end
Else:
- Skip dinner

----------------------------------------------------
STEP 7 — Overnight stay (CRITICAL NEXT-DAY LOGIC)
----------------------------------------------------
By default:
overnight_start = max(current_time, 22:00)

CRITICAL OVERNIGHT START RULE (HARD):

- overnight_start is FINAL once computed
- You MUST NOT modify overnight_start later
- You MUST NOT shift overnight_start backward
- You MUST NOT recompute overnight_start from overnight_end
- overnight_start is NEVER affected by next-day departure logic


IMPORTANT:
You are NOT allowed to decide overnight_end yet.
overnight_end MUST be computed in STEP 8.


----------------------------------------------------
STEP 8 — NEXT DAY CONSTRAINT (IMPORTANT)
----------------------------------------------------
If the NEXT DAY has transportation:
CRITICAL OVERRIDE RULE:

If the NEXT DAY has transportation,
you MUST compute overnight_end using arithmetic.
You are STRICTLY FORBIDDEN from defaulting to 08:00.
REMINDER (ABSOLUTE):

During NEXT DAY calculations:
- You MUST NOT change overnight_start
- You are ONLY allowed to compute overnight_end
- Any attempt to shift overnight_start is INVALID


Let:
next_departure_time = departure time on next day
BUFFER = 30 minutes
STAY_DURATION = 30 minutes

Compute absolute next-day departure:
next_departure_abs = next_departure_time (on next day)

--------------------------------
Breakfast feasibility next day
--------------------------------

Breakfast window next day:
08:00 → 10:30

Definitions:
- BUFFER = 30 minutes
- STAY_DURATION = 30 minutes
- BREAKFAST_DURATION = 50 minutes

Compute the latest possible breakfast start time:

latest_bf_start =
min(
  10:30,
  next_departure_abs − BUFFER − BREAKFAST_DURATION
)

If latest_bf_start ≥ 08:00:
- Breakfast next day IS feasible
Else:
- Breakfast next day is NOT feasible
NO-BUFFER-BEFORE-OVERNIGHT RULE (CRITICAL):

- You MUST NOT apply a 30-minute buffer
  between the last activity and overnight stay
- overnight_start MUST be exactly current_time
  (or 22:00, whichever is later)
- Applying any buffer before overnight is INVALID


--------------------------------
Overnight end calculation (MANDATORY — TWO CASES ONLY)
--------------------------------

You MUST choose EXACTLY ONE of the following cases.
You are STRICTLY FORBIDDEN from inventing any other formula.

--------------------------------
CASE 1 — Breakfast IS feasible next day
--------------------------------

If breakfast_feasible == TRUE:

Compute overnight_end as:

overnight_end =
next_departure_abs
− STAY_DURATION
− BUFFER
− BREAKFAST_DURATION
− BUFFER

(Exactly 4 subtractions:
1 × STAY_DURATION
2 × BUFFER
1 × BREAKFAST_DURATION)

--------------------------------
CASE 2 — Breakfast is NOT feasible next day
--------------------------------

If breakfast_feasible == FALSE:

Compute overnight_end as:

overnight_end =
next_departure_abs
− STAY_DURATION
− BUFFER

(Exactly 2 subtractions:
1 × STAY_DURATION
1 × BUFFER)

CASE FINALITY RULE (ABSOLUTE — HARD):

- Once CASE 1 or CASE 2 is selected,
  you MUST use ONLY the formula for that case.
- You MUST NOT add, remove, or adjust any subtraction.
- You MUST NOT override overnight_end after computing it.
- You MUST NOT clamp, normalize, or replace overnight_end
  with departure time or 08:00.
If you compute an overnight_end that is earlier than expected,
that is NOT an error.
Do NOT "fix" it.

--------------------------------
STRICT FORBIDDEN ACTIONS (CRITICAL)
--------------------------------

- You MUST NOT subtract BUFFER more times than specified above
- You MUST NOT add a “checkout buffer”
- You MUST NOT add a “final buffer”
- You MUST NOT reuse or double-count buffers from earlier steps
- You MUST NOT merge or average the two cases

BUFFER COUNT SANITY RULE (MANDATORY):

- CASE 1: BUFFER must appear exactly 2 times
- CASE 2: BUFFER must appear exactly 1 time

Any other buffer count is INVALID.

--------------------------------
Final safety check
--------------------------------

Ensure:
overnight_end ≥ overnight_start

If not, set:
overnight_end = overnight_start


----------------------------------------------------
FINAL GUARANTEES
----------------------------------------------------
- No overlaps
- All buffers applied
- Meal windows strictly enforced
- Attractions ≤ 2
- Output order strictly follows PLACES
- Overnight timing correctly respects NEXT DAY departure

====================================================
REFERENCE EXAMPLES (FOR LEARNING ONLY)
====================================================

EXAMPLE 1 — NON-TRAVEL DAY (FULL DAY, NEXT DAY EARLY DEPARTURE)

PLAN (INPUT DAY)
{
  "day": 2,
  "current_city": "CityX",
  "transportation": "-",
  "breakfast": "Breakfast X",
  "lunch": "Lunch Y",
  "dinner": "Dinner Z",
  "attraction": "Attraction A1; Attraction A2;",
  "accommodation": "Hotel H",
  "event": "-"
}

NEXT DAY (FOR CONTEXT)
{
  "day": 3,
  "current_city": "from CityX to CityY",
  "transportation": "Flight, Departure Time: 08:25"
}

REASONING
Day starts at 08:00 with a morning accommodation stay.
Breakfast fits and is scheduled near ideal time.
One attraction fits safely before lunch.
Lunch is scheduled near ideal time.
A second attraction fits before the dinner window.
Dinner is scheduled.
Next day has an early departure, so overnight stay is shortened to allow stay + buffer (+ breakfast feasibility check).

OUTPUT
Hotel H, stay from 08:00 to 08:30;
Breakfast X, visit from 09:30 to 10:20;
Attraction A1, visit from 10:50 to 12:50;
Lunch Y, visit from 14:40 to 15:40;
Attraction A2, visit from 16:10 to 18:10;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 07:25;

----------------------------------------------------

EXAMPLE 2 — NON-TRAVEL DAY (FULL DAY, NEXT DAY EXISTS BUT DOES NOT CONSTRAIN)

PLAN (INPUT DAY)
{
  "day": 2,
  "current_city": "CityX",
  "transportation": "-",
  "breakfast": "Breakfast X",
  "lunch": "Lunch Y",
  "dinner": "Dinner Z",
  "attraction": "Attraction A1; Attraction A2;",
  "accommodation": "Hotel H",
  "event": "-"
}

NEXT DAY (FOR CONTEXT)
{
  "day": 3,
  "current_city": "from CityX to CityY",
  "transportation": "Flight, Departure Time: 12:30"
}

REASONING
The day starts at 08:00 in the same city.

A morning accommodation stay is placed from 08:00 to 08:30.

Breakfast fits within the breakfast window and is scheduled near the ideal time.
A transition buffer is applied after breakfast.

One attraction fits safely before the ideal lunch time and is placed.
A buffer is applied after the attraction.

Lunch fits within the lunch window and is scheduled near the ideal time.
A buffer is applied after lunch.

A second attraction fits before the dinner window and is placed.
A buffer is applied afterward.

Dinner fits within the dinner window and is scheduled near the ideal time.

The next day has transportation, so the departure time is checked.
Because the departure is late in the day, there is no constraint on the overnight stay.
The overnight accommodation stay therefore continues until 08:00 next day.

All buffers, attraction limits, meal gaps, and ordering constraints are respected.

OUTPUT
Hotel H, stay from 08:00 to 08:30;
Breakfast X, visit from 09:30 to 10:20;
Attraction A1, visit from 10:50 to 12:50;
Lunch Y, visit from 14:40 to 15:40;
Attraction A2, visit from 16:10 to 18:10;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 08:00;

----------------------------------------------------

EXAMPLE 3 — NON-TRAVEL DAY (NEXT DAY VERY EARLY DEPARTURE)

PLAN (INPUT DAY)
{
  "day": 2,
  "current_city": "CityX",
  "transportation": "-",
  "breakfast": "Breakfast X",
  "lunch": "Lunch Y",
  "dinner": "Dinner Z",
  "attraction": "Attraction A1;",
  "accommodation": "Hotel H",
  "event": "-"
}

NEXT DAY (FOR CONTEXT)
{
  "day": 3,
  "current_city": "from CityX to CityY",
  "transportation": "Road travel, Departure Time: 06:00"
}

REASONING
Morning stay and daytime scheduling proceed normally.
Breakfast, one attraction, lunch, and dinner all fit.
Next-day departure is very early.
Overnight stay is cut short to allow stay + buffer before departure.
Breakfast next day is not feasible.

OUTPUT
Hotel H, stay from 08:00 to 08:30;
Breakfast X, visit from 09:30 to 10:20;
Attraction A1, visit from 10:50 to 12:50;
Lunch Y, visit from 14:40 to 15:40;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 05:00;

----------------------------------------------------

EXAMPLE 4 — NON-TRAVEL DAY (FULL DAY, NEXT DAY EARLY DEPARTURE)

PLAN (INPUT DAY)
{
  "day": 2,
  "current_city": "CityX",
  "transportation": "-",
  "breakfast": "Breakfast X",
  "lunch": "Lunch Y",
  "dinner": "Dinner Z",
  "attraction": "Attraction A1; Attraction A2;",
  "accommodation": "Hotel H",
  "event": "-"
}

NEXT DAY (FOR CONTEXT)
{
  "day": 3,
  "current_city": "from CityX to CityY",
  "transportation": "Flight, Departure Time: 08:27"
}

REASONING
Day starts at 08:00 with a morning accommodation stay.
Breakfast fits and is scheduled near ideal time.
One attraction fits safely before lunch.
Lunch is scheduled near ideal time.
A second attraction fits before the dinner window.
Dinner is scheduled.
Next day has an early departure, so overnight stay is shortened to allow stay + buffer (+ breakfast feasibility check).

OUTPUT
Hotel H, stay from 08:00 to 08:30;
Breakfast X, visit from 09:30 to 10:20;
Attraction A1, visit from 10:50 to 12:50;
Lunch Y, visit from 14:40 to 15:40;
Attraction A2, visit from 16:10 to 18:10;
Dinner Z, visit from 20:45 to 22:00;
Hotel H, stay from 22:00 to 07:27;

    """

        elif day_type == "INTER_CITY_DAY":
            return """
    ====================================================
INTER_CITY_DAY RULES (ABSOLUTE — HARD CONSTRAINTS)
====================================================

This is an INTER_CITY_DAY.
The day consists of TWO STRICT PHASES executed IN ORDER:

1) ORIGIN CITY (before departure)
2) DESTINATION CITY (after arrival)

You MUST complete ORIGIN CITY planning FIRST,
then DESTINATION CITY planning.
You are STRICTLY FORBIDDEN from interleaving activities
between origin and destination.

----------------------------------------------------
INTER_CITY DAY STAY STRUCTURE (ABSOLUTE — NON-NEGOTIABLE)
----------------------------------------------------

If destination accommodation exists:

You MUST ALWAYS create EXACTLY TWO stay blocks
at the DESTINATION, in this order:

1) Arrival check-in stay (30 minutes)
2) Overnight stay (until 08:00 next day)

This rule applies EVEN IF:
- No meals are feasible
- No attractions exist
- Arrival is very late
- The day contains ONLY accommodation

You are STRICTLY FORBIDDEN from:
- Merging these two stays
- Omitting either stay
- Replacing them with a single stay

If TWO separate destination stay entries are not present,
the output is INVALID.

----------------------------------------------------
ARRIVAL TIME SOURCE RULE (ABSOLUTE — HARD)
----------------------------------------------------

If Arrival Time is provided in transportation:

- You MUST use it EXACTLY as given
- You MUST NOT recompute arrival time from duration
- You MUST NOT adjust or round it

----------------------------------------------------
ARRIVAL CHECK-IN RULE (ABSOLUTE — HARD)
----------------------------------------------------

On INTER_CITY_DAY, arrival check-in is COMPULSORY.

Let:
arrival_time = time from transportation

You MUST compute:
arrival_stay_start = arrival_time + 30 minutes
arrival_stay_end   = arrival_stay_start + 30 minutes

Rules:
- You MUST NOT place any activity before arrival_stay_start
- You MUST NOT skip the arrival stay
- You MUST NOT attach transit info to accommodation stays
- Arrival stay and overnight stay MUST be separate records

----------------------------------------------------
INTER_CITY ORDERING RULE (CRITICAL — HARD)
----------------------------------------------------

On INTER_CITY_DAY, planning MUST proceed in this exact order:

1) Origin checkout stay
2) Origin meals and attractions (if feasible)
3) Arrival check-in stay
4) Destination meals and attractions (if feasible)
5) Overnight stay (FINAL entry)

You are STRICTLY FORBIDDEN from:
- Placing the overnight stay before evaluating meals/attractions
- Scheduling any activity after the overnight stay

----------------------------------------------------
OVERNIGHT STAY RULE (ABSOLUTE — HARD)
----------------------------------------------------

On INTER_CITY_DAY:

- The overnight stay MUST be the FINAL entry
- overnight_start = end of last activity
- overnight_end   = 08:00 next day (FIXED)
- You MUST NOT shorten overnight stay
- You MUST NOT back-calculate overnight_start
- You MUST NOT apply next-day departure logic

----------------------------------------------------
DEPARTURE CUTOFF RULE (ORIGIN CITY — HARD)
----------------------------------------------------

Let:
departure_time = time from transportation
BUFFER = 30 minutes

origin_cutoff = departure_time − BUFFER

NO origin-city activity may END after origin_cutoff.
Even 1 minute over is INVALID.

----------------------------------------------------
ORIGIN CITY START (PREVIOUS DAY DEPENDENCY)
----------------------------------------------------

You MUST take the PREVIOUS DAY final stay end EXACTLY.

Let:
previous_stay_end = end time of last stay from previous day

If origin accommodation exists:

You MUST create a checkout stay:
checkout_start = previous_stay_end
checkout_end   = checkout_start + 30 minutes

Then compute:
origin_ready_time = checkout_end + 30-minute buffer

You MUST NOT:
- Skip origin checkout stay
- Recompute previous_stay_end
- Normalize or round times

----------------------------------------------------
ORIGIN MEALS (STRICT ORDER)
----------------------------------------------------

Breakfast (origin):
- Allowed ONLY if:
  origin_ready_time + 50 ≤ min(10:30, origin_cutoff)
- Ideal time MUST be used if feasible

Lunch (origin):
- Allowed ONLY if:
  max(origin_ready_time, last_meal_end + 240) + 60
  ≤ min(15:40, origin_cutoff)
- Ideal time MUST be used if feasible

Dinner (origin — rare):
- Allowed ONLY if:
  dinner_end ≤ origin_cutoff
- Try ideal time first
- Fallback to latest feasible
- Otherwise skip

----------------------------------------------------
ORIGIN ATTRACTIONS (MEAL-PROTECTIVE)
----------------------------------------------------

You may schedule AT MOST TWO origin attractions.

Each attraction is allowed ONLY IF:
- attraction_end ≤ origin_cutoff
- It does NOT prevent the next required meal

Valid origin attraction patterns:
- 0 attractions
- 1 attraction
- 2 attractions
- 1 before lunch + 1 after lunch

----------------------------------------------------
DESTINATION CITY START
----------------------------------------------------

After arrival:

current_time = arrival_time + 30 minutes

You MUST place arrival check-in stay IMMEDIATELY.

----------------------------------------------------
DESTINATION MEALS (CARRY-OVER AWARE)
----------------------------------------------------

If a meal was already consumed at ORIGIN:
- You MUST NOT repeat it at DESTINATION

Breakfast (destination):
- Only if not eaten at origin
- Must fit breakfast window

Lunch (destination):
- Only if not eaten at origin
- Must fit lunch window
- Respect current_time first

Dinner (destination):
- Only if not eaten at origin
- Must finish before overnight stay

----------------------------------------------------
DESTINATION ATTRACTIONS
----------------------------------------------------

You may schedule destination attractions ONLY IF:
- They do not block the next required meal
- They finish before dinner cutoff

Valid destination attraction patterns:
- 0 attractions
- 1 attraction
- 2 attractions

----------------------------------------------------
STRICT FORBIDDEN ACTIONS
----------------------------------------------------

You are STRICTLY FORBIDDEN from:
- Skipping origin checkout stay
- Skipping arrival check-in stay
- Merging arrival stay and overnight stay
- Scheduling destination activity before arrival buffer
- Exceeding origin departure cutoff
- Repeating meals across cities
- Inventing places
- Creating zero-duration stays

====================================================
REFERENCE EXAMPLES (FOR LEARNING ONLY)
====================================================

EXAMPLE 1 — INTER CITY (EARLY DEPARTURE, DESTINATION-HEAVY)

PLAN (INPUT DAY)

{
  "day": 3,
  "current_city": "from CityA to CityB",
  "transportation": "Self-Driving, Departure Time: 06:00, Arrival Time: 08:57",
  "breakfast": "-",
  "lunch": "Lunch X",
  "dinner": "Dinner Y",
  "attraction": "Attraction D;",
  "accommodation": "Hotel B",
  "event": "-"
}


REASONING
The previous day ends with an overnight stay ending at 05:00.
A mandatory origin checkout stay is placed from 05:00 to 05:30.
After a 30-minute buffer, origin_ready_time is 06:00, which coincides with the departure time, so no origin meals or attractions are possible.

Arrival time is 08:57.
Arrival check-in stay is compulsory and placed from 09:27 to 09:57.

Breakfast was skipped at origin, but arrival is too late for breakfast window, so breakfast is skipped entirely.

A destination attraction is placed only if lunch remains feasible.
Attraction D fits safely before lunch.

Lunch and dinner both fit at their ideal times.

An overnight stay is placed as the final entry until 08:00 next day.

OUTPUT

Hotel A, stay from 05:00 to 05:30;
Hotel B, stay from 09:27 to 09:57;
Attraction D, visit from 11:47 to 13:47;
Lunch X, visit from 14:40 to 15:40;
Dinner Y, visit from 20:45 to 22:00;
Hotel B, stay from 22:00 to 08:00;

EXAMPLE 2 — INTER CITY (MID DEPARTURE, 1 ORIGIN + 1 DESTINATION ATTRACTION)

PLAN (INPUT DAY)

{
  "day": 3,
  "current_city": "from CityA to CityB",
  "transportation": "Train, Departure Time: 11:30, Arrival Time: 14:30",
  "breakfast": "Breakfast O",
  "lunch": "-",
  "dinner": "-",
  "attraction": "Attraction O; Attraction D;",
  "accommodation": "Hotel B",
  "event": "-"
}


REASONING
The previous day ends at 08:00.
Origin checkout stay is placed from 08:00 to 08:30.
After buffer, origin_ready_time is 09:00.

Breakfast fits within the breakfast window and is scheduled at the ideal time.

One origin attraction is placed safely before departure cutoff.

Arrival occurs at 14:30.
Arrival check-in stay is placed from 15:00 to 15:30.

Lunch was not consumed at origin but arrival is too late to fit lunch window safely, so lunch is skipped.

One destination attraction is placed before dinner feasibility is checked.

Overnight stay is placed as final entry.

OUTPUT

Hotel A, stay from 08:00 to 08:30;
Breakfast O, visit from 09:30 to 10:20;
Attraction O, visit from 10:50 to 12:50;
Hotel B, stay from 15:00 to 15:30;
Attraction D, visit from 16:00 to 18:00;
Hotel B, stay from 18:00 to 08:00;

EXAMPLE 3 — INTER CITY (LATE DEPARTURE, 2 ORIGIN ATTRACTIONS)

PLAN (INPUT DAY)

{
  "day": 3,
  "current_city": "from CityA to CityB",
  "transportation": "Flight, Departure Time: 18:30, Arrival Time: 22:15",
  "breakfast": "Breakfast O",
  "lunch": "-",
  "dinner": "-",
  "attraction": "Attraction O1; Attraction O2;",
  "accommodation": "Hotel B",
  "event": "-"
}


REASONING
Previous day ends at 08:00.
Checkout stay is placed from 08:00 to 08:30, origin_ready_time becomes 09:00.

Breakfast fits and is scheduled.

Two origin attractions fit safely before the departure cutoff without blocking meals.

Arrival is late at 22:15.
Arrival check-in stay is placed from 22:45 to 23:15.

No meals or attractions are feasible after arrival.

Overnight stay is placed immediately after arrival stay.

OUTPUT

Hotel A, stay from 08:00 to 08:30;
Breakfast O, visit from 09:30 to 10:20;
Attraction O1, visit from 10:50 to 12:50;
Attraction O2, visit from 13:20 to 15:20;
Hotel B, stay from 22:45 to 23:15;
Hotel B, stay from 23:15 to 08:00;

EXAMPLE 4 — INTER CITY (NO ATTRACTIONS, STAYS ONLY)

PLAN (INPUT DAY)

{
  "day": 3,
  "current_city": "from CityA to CityB",
  "transportation": "Bus, Departure Time: 07:00, Arrival Time: 23:00",
  "breakfast": "-",
  "lunch": "-",
  "dinner": "-",
  "attraction": "-",
  "accommodation": "Hotel B",
  "event": "-"
}


REASONING
Previous day ends at 05:00.
Checkout stay is placed from 05:00 to 05:30.
No meals or attractions fit before departure.

Arrival occurs at 23:00.
Arrival check-in stay is placed from 23:30 to 00:00.

No activities are feasible afterward.

Overnight stay ends the day.

OUTPUT

Hotel A, stay from 05:00 to 05:30;
Hotel B, stay from 23:30 to 00:00;
Hotel B, stay from 00:00 to 08:00;
    """

        elif day_type == "LAST_DAY":
            return """
            ----------------------------------------------------
ABSOLUTE SOURCE RULE (CRITICAL — HARD)
----------------------------------------------------

The value `previous_stay_end` MUST be taken EXACTLY
from the PREVIOUS DAY itinerary.

- You MUST copy the time verbatim
- You MUST NOT recompute it
- You MUST NOT round it
- You MUST NOT normalize it
- You MUST NOT align it to 30-minute boundaries

If the previous day ends at 07:27,
then previous_stay_end = 07:27 exactly.

Any modification of this value is INVALID.

----------------------------------------------------
CHECKOUT FINALITY RULE (CRITICAL — HARD STOP)
----------------------------------------------------
On Last day there will be no overnight stay only checkout stay is possible. **Checkout stay is compulsory if accommodation exists or reused from previous day.**
If a checkout stay is placed:

- checkout_start and checkout_end are FINAL
- You MUST NOT extend checkout_end
- You MUST NOT add buffer time to the checkout stay
- You MUST NOT convert checkout into a normal overnight stay
- checkout_end MUST equal checkout_start + 30 minutes EXACTLY
- checkout_end MUST NOT exceed departure_cutoff

If checkout_end == departure_cutoff:
- This is a VALID exact fit
- You MUST output the stay ending exactly at departure_cutoff
- You MUST NOT add any extra minutes

        REASONING STYLE (HOW TO THINK)

        This is the LAST DAY of the trip.
        Planning is constrained by a HARD DEPARTURE TIME.
        Nothing is allowed to extend beyond the departure cutoff.

        ----------------------------------------------------
        STEP 1 — Compute the hard cutoff time
        ----------------------------------------------------
        Let:
        departure_time = time mentioned in transportation
        BUFFER = 30 minutes

        departure_cutoff = departure_time − BUFFER

        All activities (stays, meals, attractions) must END
        at or before departure_cutoff.

        ----------------------------------------------------
        STEP 2 — Determine previous night context
        ----------------------------------------------------
        Look at the PREVIOUS DAY itinerary.

        Find the end time of the final accommodation stay
        from the previous day:
        previous_stay_end = end time of last "stay" block

        This is the earliest possible starting point
        for checkout on the last day.

        ----------------------------------------------------
        STEP 3 — Checkout stay placement
        ----------------------------------------------------
        If accommodation exists (or is reused from previous day):

        checkout_start = previous_stay_end
        checkout_end   = checkout_start + 30 minutes

        Checkout is VALID only if:
        checkout_end ≤ departure_cutoff
        If checkout_end ≤ departure_cutoff:
        - Place exactly ONE checkout stay
        Else:
        - Checkout is INVALID
        - You MUST discard the checkout stay
        - You MUST output NOTHING for this day
        - STOP immediately


        If valid:
        - Place exactly ONE checkout stay (30 minutes)
        - Use ONLY the previous day’s accommodation name

        If not valid:
        - Skip checkout entirely
        - No other activity is allowed

        ----------------------------------------------------
        STEP 4 — Apply transition buffer after checkout
        ----------------------------------------------------
        If checkout was placed:

        current_time = checkout_end + 30 minutes

        If no checkout was placed:

        current_time = previous_stay_end
        ----------------------------------------------------
CRITICAL STOP RULE (HARD — MUST FOLLOW)
----------------------------------------------------

After checkout and buffer application:

If current_time ≥ departure_cutoff:

- You MUST STOP planning immediately
- You MUST NOT schedule breakfast, lunch, dinner, or attractions
- You MUST NOT schedule an overnight stay
- You MUST output ONLY the checkout stay (if placed)
- Any activity starting at or after departure_cutoff is INVALID
- You MUST NOT modify or extend the checkout stay after it is placed

This rule OVERRIDES all meal windows and ideal times.


        ----------------------------------------------------
        STEP 5 — Evaluate activities (STRICT ORDER)
        ----------------------------------------------------
        For each place in PLACES order:

        For a MEAL:
        - Check it fits inside its time window
        - Check (start_time + duration) ≤ departure_cutoff
        - Check meal gap constraints
        - If ANY check fails → skip meal

        For an ATTRACTION:
        - start_time = current_time
        - end_time   = start_time + attraction_duration
        - If end_time ≤ departure_cutoff → place attraction
        - Else → skip

        After placing any activity:
        current_time = end_time + 30 minutes

        ----------------------------------------------------
        STEP 6 — Stop conditions
        ----------------------------------------------------
        - The moment no activity fits safely → STOP
        - NEVER exceed departure_cutoff
        - NEVER reorder PLACES
        - NEVER invent accommodation names

        ----------------------------------------------------
        LAST DAY ACCOMMODATION RULE (CRITICAL)
        ----------------------------------------------------
        If accommodation is "-" on LAST_DAY:
        - You MUST reuse the accommodation from the previous day
        - You may ONLY output a checkout stay
        - NEVER invent a new hotel name
        
        LAST_DAY TIME PRECISION RULE (CRITICAL):

- You MUST use the exact departure time and exact buffer subtraction.
- You are NOT allowed to round to 08:00.
- If the cutoff is 07:57, the latest allowed end time is exactly 07:57.
- Any activity ending after the cutoff is INVALID and must be skipped or shortened.


        ====================================================
        REFERENCE EXAMPLES (FOR LEARNING ONLY)
        ====================================================

        EXAMPLE 1 — LAST DAY (EARLY FLIGHT, BREAKFAST ONLY)

        PLAN (INPUT DAY)
        {
        "day": 5,
        "current_city": "from CityA to CityB",
        "transportation": "Flight, Departure Time: 12:15",
        "breakfast": "Breakfast X",
        "lunch": "-",
        "dinner": "-",
        "attraction": "-",
        "accommodation": "-"
        }

        REASONING (WITH CALCULATIONS)

        departure_time   = 12:15
        departure_cutoff = 12:15 − 00:30 = 11:45

        previous_stay_end = 08:00

        checkout:
        08:00 → 08:30 (valid because 08:30 ≤ 11:45)

        buffer:
        current_time = 08:30 + 00:30 = 09:00

        breakfast:
        09:00 → 09:50
        09:50 ≤ 11:45 → allowed

        No other activity can finish before 11:45.

        OUTPUT
        Hotel H, stay from 08:00 to 08:30;
        Breakfast X, visit from 09:00 to 09:50;

        ----------------------------------------------------

        EXAMPLE 2 — LAST DAY (AFTERNOON DEPARTURE, BREAKFAST + ATTRACTION + LUNCH)

        PLAN (INPUT DAY)
        {
        "day": 5,
        "current_city": "from CityC to CityD",
        "transportation": "Self-Driving, Departure Time: 15:30",
        "breakfast": "Breakfast Y",
        "lunch": "Lunch Z",
        "dinner": "-",
        "attraction": "Attraction A;",
        "accommodation": "-"
        }

        REASONING (WITH CALCULATIONS)

        departure_time   = 15:30
        departure_cutoff = 15:30 − 00:30 = 15:00

        previous_stay_end = 08:00

        checkout:
        08:00 → 08:30

        buffer:
        current_time = 08:30 + 00:30 = 09:00

        breakfast:
        09:00 → 09:50
        09:50 ≤ 15:00 → allowed

        buffer:
        current_time = 09:50 + 00:30 = 10:20

        attraction:
        10:20 → 12:20
        12:20 ≤ 15:00 → allowed

        buffer:
        current_time = 12:20 + 00:30 = 12:50

        lunch:
        12:50 → 13:50
        13:50 ≤ 15:00 → allowed

        Dinner would exceed cutoff → skipped.

        OUTPUT
        Hotel Q, stay from 08:00 to 08:30;
        Breakfast Y, visit from 09:00 to 09:50;
        Attraction A, visit from 10:20 to 12:20;
        Lunch Z, visit from 12:50 to 13:50;

        ----------------------------------------------------

        EXAMPLE 3 — LAST DAY (VERY EARLY DEPARTURE, STAY ONLY)

        PLAN (INPUT DAY)
        {
        "day": 3,
        "current_city": "from CityE to CityF",
        "transportation": "Flight, Departure Time: 08:30",
        "breakfast": "-",
        "lunch": "-",
        "dinner": "-",
        "attraction": "-",
        "accommodation": "-"
        }

        REASONING (WITH CALCULATIONS)

        departure_time   = 08:30
        departure_cutoff = 08:30 − 00:30 = 08:00

        previous_stay_end = 07:30

        checkout:
        07:30 → 08:00
        08:00 ≤ 08:00 → allowed (exact fit)

        No buffer or activity can be added.

        OUTPUT
        Hotel R, stay from 07:30 to 08:00;
        """

        else:
            return ""

    # ----------------------------------------------------------
    # Prompt builder (DAY-AWARE, CoT-STYLE, EVAL-SAFE)
    # ----------------------------------------------------------

    def extract_prev_stay_context(self, prev_itinerary: str):
        """
        Returns (previous_accommodation, previous_stay_end)
        """
        if not prev_itinerary:
            return None, None

        stays = re.findall(
            r"^(.*?), stay from (\d{2}:\d{2}) to (\d{2}:\d{2})",
            prev_itinerary,
            flags=re.MULTILINE
        )

        if not stays:
            return None, None

        last_place, _, last_end = stays[-1]
        return last_place.strip(), last_end

    def build_prompt(
        self,
        day: Dict[str, Any],
        pois: List[str],
        stops: List[str],
        distances: List[float],
        day_type: str,
        next_day: Optional[Dict[str, Any]] = None,
        previous_accommodation: Optional[str] = None,
        previous_stay_end: Optional[str] = None,
    ) -> str:

        examples_block = self.get_examples_block(day_type)
        previous_context = ""

        if day_type in ("INTER_CITY_DAY", "LAST_DAY") \
        and previous_accommodation \
        and previous_stay_end:
            previous_context = f"""
        ====================================================
        PREVIOUS DAY CONTEXT (ABSOLUTE — HARD SOURCE)
        ====================================================

        previous_accommodation = "{previous_accommodation}"
        previous_stay_end      = "{previous_stay_end}"

        Rules:
        - You MUST use previous_accommodation for checkout stay
        - Checkout MUST start EXACTLY at previous_stay_end
        - Checkout duration is EXACTLY 30 minutes
        - You MUST NOT infer or recompute these values
        - You MUST NOT extract times from itinerary text
        """


        # --------------------------------------------------
        # Context blocks (ONLY when needed)
        # --------------------------------------------------
        temporal_context = ""

        if day_type == "NON_TRAVEL_DAY" and next_day:
            temporal_context = f"""
====================================================
NEXT DAY (FOR OVERNIGHT STAY CONSTRAINT)
====================================================
{json.dumps(next_day, indent=2)}
"""

        

        return f"""
You are an expert travel scheduler.

Your task is to PLAN FIRST, then FORMAT.
Think carefully before answering.

Donot round of the minutes keep the calculations exact.

TIME PRECISION RULE (CRITICAL — HARD CONSTRAINT):

All times MUST be computed using exact minute arithmetic.

- You are STRICTLY FORBIDDEN from rounding, snapping, or normalizing times.
- You MUST NOT round to :00, :15, or :30.
- If a calculation results in 07:27, you MUST keep 07:27.
- Any rounding, even by 1 minute, is INVALID.
All times MUST be HH:MM. Seconds are forbidden.

You MUST show exact subtraction and addition of minutes.
Preserve all minute values exactly as computed.
TIME ARITHMETIC REQUIREMENT (MANDATORY):

You MUST explicitly compute times step-by-step.

Example:
- arrival_time = 21:22
- arrival_buffer = 30 min
- arrival_stay_start = 21:52
- arrival_stay_end = 22:22

If your computed time jumps by more than the defined buffer or duration,
your reasoning is INVALID.


====================================================
CRITICAL GLOBAL CONSTRAINT (MUST FOLLOW)
====================================================
- You MUST output places in EXACTLY the same order as the PLACES list.
- DO NOT reorder places for any reason.
- ORDER correctness is MORE IMPORTANT than time intuition.
- DO NOT invent places.

====================================================
DAY TYPE (IMPORTANT)
====================================================
This day is classified as:

DAY TYPE: {day_type}

You MUST follow rules appropriate for this day type.

====================================================
GENERAL RULES (ALWAYS APPLY)
====================================================
- No overlapping time ranges
- Buffer between any two activities: 30 minutes
- Minimum gap between meals: 240 minutes
- Use "stay" ONLY for accommodation
- Use "visit" ONLY for meals and attractions
- NEVER use the word "check-in"

If nearest transit stop is "Unknown":
- Assume walking or nearby
- DO NOT include transit info in output

Accommodation rules:
- Each stay block is at least 30 minutes
- ALWAYS write accommodation using "stay"



MEAL TIME CONSTANTS (HARD & FIXED):
- Breakfast ideal start: 09:30
- Lunch ideal start: 14:40
- Dinner ideal start: 20:45

MEAL WINDOWS (HARD & FIXED):
- Breakfast window: 08:00 – 10:30
- Lunch window: 12:00 – 15:40
- Dinner window: 18:30 – 22:00

MEAL DURATIONS (HARD & FIXED):
- Breakfast: 50 minutes
- Lunch: 60 minutes
- Dinner: 75 minutes

RULE:
If the ideal start time is feasible (after buffers and gaps),
you MUST use the ideal time.
You may use a later time ONLY if the ideal time is impossible.


ANTI-HALLUCINATION RULE (CRITICAL):
- You MUST ONLY use place names that appear in the PLACES list.
- You are STRICTLY FORBIDDEN from using example place names.
- If a place is not present in PLACES, DO NOT output it.

ORDER VIOLATION = INVALID OUTPUT:
- If the output order does not exactly match PLACES order,
  the output is considered WRONG.
- Even if time intuition suggests otherwise, NEVER reorder.

SKIPPING RULE (CRITICAL):
- If a place cannot be scheduled, you MUST still preserve its position.
- You may OMIT the place entirely, but you may NOT move later places earlier.
- You are NOT allowed to output a later place before an earlier place.

ORDER INTERPRETATION RULE (CRITICAL):
- PLACES order defines OUTPUT SEQUENCE ONLY
- It does NOT imply chronological adjacency
- Times may go forward even if the next place is later in the day
- NEVER move attractions after dinner unless explicitly allowed

BUFFER RULE (CRITICAL):

A 30-minute buffer is applied ONLY when transitioning
between DIFFERENT activities or DIFFERENT places.

DO NOT apply a buffer:
- Between two consecutive stays at the SAME accommodation
- Between arrival buffer and the overnight stay
- When there is no intervening activity

TIMELINE RULE (CRITICAL — MUST FOLLOW):

You MUST maintain a single variable called current_time.

- current_time always moves forward
- current_time is the ONLY source of truth
- You may NEVER schedule an activity that starts before current_time
- You may NEVER schedule overlapping activities

Every activity MUST follow this pattern:

1) start_time = max(current_time, ideal_start_if_any)
2) end_time = start_time + fixed_duration
3) If end_time violates a window or cutoff → SKIP the activity
4) If placed:
   - current_time = end_time
   - then apply buffer if required

MEAL FEASIBILITY TEST (ABSOLUTE — ORDERED):

You MUST follow this sequence EXACTLY:

STEP 1:
Compute:
start_time = max(current_time, ideal_start_time)

STEP 2:
Compute:
end_time = start_time + duration

STEP 3:
Check feasibility:
- start_time ≥ window_start
- end_time   ≤ window_end

IMPORTANT:
- You MUST NOT evaluate feasibility before STEP 1
- You MUST NOT use current_time + duration for feasibility
- You MUST NOT skip directly to a later start_time

MEAL IDEAL-TIME GUARANTEE (NON-NEGOTIABLE):

If:
- ideal_start_time ≥ current_time
AND
- ideal_start_time ≥ window_start
AND
- ideal_start_time + duration ≤ window_end

THEN:
- The meal MUST be scheduled at ideal_start_time
- You are STRICTLY FORBIDDEN from choosing any other start time
- You MUST NOT skip the meal
MEAL WINDOW END IS INCLUSIVE.
An end_time equal to window_end is VALID.

If no meals or attractions were placed during the day,
you MUST still output the overnight stay.

You MUST preserve the meal → attraction → meal structure shown in the REFERENCE EXAMPLES.

====================================================
REFERENCE EXAMPLES (FOR LEARNING ONLY)
====================================================
{examples_block}
{temporal_context}
{previous_context}
====================================================
INPUT DAY (DO NOT MODIFY)
====================================================
{json.dumps(day, indent=2)}

PLACES (ORDER IS FIXED — INDEX MATTERS):
{json.dumps(pois)}

====================================================
OUTPUT FORMAT (STRICT — MACHINE READABLE)
====================================================

You MUST output TWO sections in this EXACT order.

====================================================
REASONING (MANDATORY — DO NOT SKIP)
====================================================
You MUST explain your reasoning step by step.
Explain your reasoning step by step in plain English.
This section is for humans.
You may explain calculations and decisions.
Do NOT invent places.
Explain:
- How you determined the start time of the day
- Why each meal was scheduled or skipped
- Why each attraction was scheduled or skipped
- How buffers were applied
- How overnight or checkout stay was determined
- How NEXT DAY or PREVIOUS DAY context affected decisions (if provided)
Rules:
- Write in plain English
- Do NOT include timestamps inside code blocks
- Do NOT invent places
- Do NOT format this section as the final answer
In the REASONING section, you MUST:

- Explicitly show current_time changes
- Show window checks (pass/fail)
- Show cutoff comparisons for LAST_DAY
- Mention why an activity was skipped (window or overlap)

If current_time is not mentioned, the reasoning is INVALID.

END REASONING

--------------------
ITINERARY
--------------------
This section is for machines.
This section MUST contain ONLY itinerary entries.
NO explanations. NO extra text.

FORMAT (ONE LINE ONLY):

<Place>, <visit/stay> from <HH:MM> to <HH:MM>;

RULES FOR ITINERARY:
- Each entry MUST end with a semicolon (;)
- Entries MUST be separated by semicolons
- NO line breaks
- NO text before or after
- Follow PLACES order EXACTLY

FORMAT VIOLATION = INVALID OUTPUT:
- Each entry MUST end with a semicolon (;)
- Commas are NOT valid entry separators
- Do NOT use line breaks

Rules:
- Follow PLACES order exactly
- Separate entries using semicolons
- Return ONLY the itinerary string

The ITINERARY section MUST be the LAST thing in your response.
Do NOT write anything after it.

SELF-CORRECTION RULE (MANDATORY):

You MUST follow this internal process:

STEP A — First Attempt
- Build a full itinerary using the rules.
- Track a single variable called current_time.
- Assign start and end times to all activities.

STEP B — Validate the Attempt
Check ALL of the following:
1) No two activities overlap in time
2) Every meal starts AND ends within its meal window
3) Buffers are respected
4) LAST_DAY activities do not exceed the departure cutoff

STEP C — Repair If Invalid
If ANY rule fails:
- Adjust timings (start later, shorten, or skip activities)
- Rebuild the itinerary from the point of failure onward
- Repeat validation

You MUST repeat STEP B and STEP C until the plan is valid.

IMPORTANT:
- This retry happens internally.
- You MUST NOT output invalid attempts.
- You MUST output ONLY the final valid itinerary.
REPAIR STRATEGY (USE IN THIS ORDER):

When fixing an invalid plan, apply fixes in this priority:

1) Shift the activity later in time (respecting windows)
2) If shifting fails, SKIP the activity
3) NEVER move an activity earlier to fix an overlap
4) NEVER violate meal windows to keep an attraction
====================================================
FINAL VALIDATION PASS (ABSOLUTE — NON-NEGOTIABLE)
====================================================

After you have built the itinerary, you MUST perform a FULL SECOND PASS
using a NEW variable called:

final_time

This pass is NOT optional.

----------------------------------------------------
FINAL VALIDATION PROCEDURE (MANDATORY)
----------------------------------------------------

1) Initialize:
- final_time = day_start_time
  (08:00 for NON_TRAVEL_DAY and LAST_DAY,
   arrival_stay_end for FIRST_DAY)

2) Iterate through EACH itinerary entry IN ORDER:

For each entry:
- Verify entry.start_time ≥ final_time
  - If not, the itinerary is INVALID
- Verify entry.end_time > entry.start_time
  - If not, the itinerary is INVALID
- Verify (entry.end_time − entry.start_time)
  matches the fixed duration for that activity
- Verify meal windows again (start AND end)
- Verify LAST_DAY cutoff:
  entry.end_time ≤ departure_cutoff

3) Buffer validation:
- If the NEXT entry exists AND both entries are NOT stays at the same accommodation:
  - Verify next.start_time = entry.end_time + 30 minutes
- If this condition fails → INVALID

4) Update:
- final_time = entry.end_time
- If buffer applies, final_time += 30 minutes

FINAL TIMELINE VALIDATION (ABSOLUTE — HARD):

After producing a candidate itinerary, you MUST perform a FINAL VALIDATION PASS.

You MUST re-simulate the entire itinerary from scratch using a NEW variable:

    validate_time

Rules for validation pass:

1) Initialize:
   - If NON_TRAVEL_DAY or LAST_DAY: validate_time = 08:00
   - If FIRST_DAY: validate_time = arrival_time + 30 minutes

2) Iterate through itinerary entries IN ORDER:
   For each entry:
   - entry_start MUST equal validate_time
     OR
     entry_start MUST be ≥ validate_time
   - If entry_start < validate_time → INVALID

   - Compute expected_end = entry_start + duration
   - entry_end MUST equal expected_end
     (NO rounding, NO adjustment)

   - Update validate_time:
     - If next entry is a DIFFERENT place or activity:
         validate_time = entry_end + 30 minutes
     - Else:
         validate_time = entry_end

3) Overnight stay validation:
   - overnight_start MUST equal the validate_time at that moment
   - overnight_end MUST be ≥ overnight_start
   - overnight_start MUST NEVER be recomputed from overnight_end

4) NEXT DAY logic:
   - overnight_end may be shortened
   - overnight_start is FINAL and IMMUTABLE

If ANY rule fails:
- The itinerary is INVALID
- You MUST discard it
- You MUST rebuild the plan from the first invalid entry onward
- Repeat validation until the itinerary PASSES

----------------------------------------------------
FAILURE HANDLING (CRITICAL)
----------------------------------------------------

If ANY check fails:
- You MUST discard the entire itinerary
- You MUST rebuild the plan from scratch
- You MUST repeat validation
- You MUST NOT output a partially-fixed plan

You are STRICTLY FORBIDDEN from:
- Adjusting only one activity
- Skipping validation
- Assuming correctness

The FINAL itinerary MUST pass this validation pass.

OUTPUT FORMAT HARD RULE (ABSOLUTE):

- You MUST NOT output JSON
- You MUST NOT wrap output in code blocks
- You MUST NOT use keys like "reasoning" or "itinerary"
- You MUST output plain text sections exactly as specified
- JSON output is INVALID

"""
    
    def attach_transits_post_llm(
        self,
        itinerary: str,
        pois: List[str],
        stops: List[str],
        distances: List[float],
    ) -> str:

        entries = [e.strip() for e in itinerary.split(";") if e.strip()]
        place_to_index = {p: i for i, p in enumerate(pois)}
        final_entries = []

        for entry in entries:
            place = entry.split(",")[0].strip()

            # Accommodation → NEVER attach transit
            if " stay from " in entry:
                final_entries.append(entry + ";")
                continue

            idx = place_to_index.get(place)
            if idx is None:
                final_entries.append(entry + ";")
                continue

            stop = stops[idx]
            dist = distances[idx]

            if stop != "Unknown" and dist > 0:
                entry = f"{entry}, nearest transit: {stop}, {dist}m away"

            final_entries.append(entry + ";")

        return " ".join(final_entries)

    # ----------------------------------------------------------
    # MAIN LOGIC
    # ----------------------------------------------------------
    def generate_poi_list(
        self,
        days: List[Dict[str, Any]],
        structured_input: Dict[str, Any],
    ) -> Dict[int, str]:

        cities_data = structured_input.get("cities", [])
        city_map = {c["city"]: c for c in cities_data}
        result: Dict[int, str] = {}

        for idx, original_day in enumerate(days):
            day = dict(original_day)  # 🔒 work on a copy

            # --------------------------------------------------
            # Classify day
            # --------------------------------------------------
            day_type = self.classify_day(day, idx, days)

            # --------------------------------------------------
            # Inject LAST_DAY accommodation from previous day
            # --------------------------------------------------
            if day_type == "LAST_DAY" and day.get("accommodation") in ("", "-"):
                if idx > 0:
                    prev_day = days[idx - 1]
                    if prev_day.get("accommodation") not in ("", "-"):
                        day["accommodation"] = prev_day["accommodation"]

            # --------------------------------------------------
            # Build POIs (ORDER MATTERS)
            # --------------------------------------------------
            pois = self.build_poi_inputs(day)

            # --------------------------------------------------
            # Skip LLM only when truly nothing is schedulable
            # --------------------------------------------------
            if not pois and day_type != "LAST_DAY":
                result[idx + 1] = "-"
                continue

            # --------------------------------------------------
            # Temporal context
            # --------------------------------------------------
            # print("result:", result)
            next_day = days[idx + 1] if idx + 1 < len(days) else None
            prev_itinerary = result.get(idx) if idx > 0 else None

            previous_accommodation = None
            previous_stay_end = None

            if day_type in ("INTER_CITY_DAY", "LAST_DAY") and prev_itinerary:
                previous_accommodation, previous_stay_end = (
                    self.extract_prev_stay_context(prev_itinerary)
                )


            # --------------------------------------------------
            # Resolve city
            # --------------------------------------------------
            city = day.get("current_city", "")
            if city.lower().startswith("from "):
                city = city.split(" to ")[-1].strip()

            city_block = city_map.get(city, {})
            raw_rows = city_block.get("raw_transit_rows", [])

            # --------------------------------------------------
            # Resolve transit PER POI (aligned by index)
            # --------------------------------------------------
            stops: List[str] = []
            distances: List[float] = []

            for p in pois:
                transit = self.resolve_transit_for_poi(p, raw_rows)
                if transit:
                    stops.append(transit["stop"])
                    distances.append(transit["distance"])
                else:
                    stops.append("Unknown")
                    distances.append(0)

            # --------------------------------------------------
            # Clean input before LLM
            # --------------------------------------------------
            clean_day = dict(day)
            clean_day.pop("point_of_interest_list", None)

            # --------------------------------------------------
            # Build prompt (NO TRANSITS INSIDE LLM)
            # --------------------------------------------------
            prompt = self.build_prompt(
                clean_day,
                pois,
                [],          # 🚫 NO stops passed to LLM
                [],          # 🚫 NO distances passed to LLM
                day_type,
                next_day=next_day.pop("point_of_interest_list", None) if next_day else None,
                previous_accommodation=previous_accommodation,
                previous_stay_end=previous_stay_end,
            )

            # --------------------------------------------------
            # Save prompt (DEBUG)
            # --------------------------------------------------
            prompt_dir = (
                Path("/scratch/sg/Vijay/TripCraft/output_agentic/agentic")
                / "qwen2.5"
                / "3day"
                / "1"
            )
            prompt_dir.mkdir(parents=True, exist_ok=True)

            prompt_file = f"day_{idx + 1}_{day_type}_prompt.txt"
            # with open(prompt_dir / prompt_file, "w", encoding="utf-8") as f:
            #     f.write(prompt)

            # --------------------------------------------------
            # Call LLM
            # --------------------------------------------------
            response = self.llm.generate(prompt)
            print(
                f"[DEBUG] LLM response for day {idx + 1} ({day_type}):\n{response}\n"
            )

            if "ITINERARY" not in response:
                raise RuntimeError("Missing ITINERARY section from LLM")

            # _, itinerary = response.split("ITINERARY", 1)
            # itinerary = itinerary.strip()
            itinerary = extract_itinerary(response)


            if not itinerary:
                raise RuntimeError("Empty itinerary from LLM")

            # --------------------------------------------------
            # 🧠 POST-PROCESS: Attach transits deterministically
            # --------------------------------------------------
            itinerary = self.attach_transits_post_llm(
                itinerary,
                pois,
                stops,
                distances,
            )

            result[idx + 1] = itinerary

        return result





# ----------------------------------------------------------
# CLI runner
# ----------------------------------------------------------
def main():
    if len(sys.argv) != 4:
        print("Usage: python poihelper.py <query_number> <model_name> <api_key>")
        sys.exit(1)

    query_no = sys.argv[1]
    model_name = sys.argv[2]
    api_key = sys.argv[3]

    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["GEMINI_API_KEY"] = api_key
    os.environ["GOOGLE_API_KEY"] = api_key

    llm = init_llm(model_name, api_key)
    agent = POIsAgent(llm)

    base = Path(
        "/scratch/sg/Vijay/TripCraft/output_agentic/agentic"
    ) / "qwen2.5" / "5day" / query_no

    combined_ref_path = base / "combined_reference.json"
    manual_plan_path = base / "tripcraft_response.json"
    output_path = base / "poi_itinerary.json"

    with open(combined_ref_path) as f:
        combined = json.load(f)

    with open(manual_plan_path) as f:
        manual = json.load(f)

    days = manual.get("days") if isinstance(manual, dict) else manual

    result = agent.generate_poi_list(days, combined)

    # with open(output_path, "w") as f:
    #     json.dump(result, f, indent=2)

    print(f"[DONE] POI itinerary saved → {output_path}")


if __name__ == "__main__":
    main()

# ====================================================
# GLOBAL EXECUTION MODE (ABSOLUTE — HARD)
# ====================================================

# You are NOT a planner.
# You are an EXECUTOR.

# Your role is to ASSIGN TIMES to the given places
# in the GIVEN ORDER, using STRICT arithmetic rules.

# ----------------------------------------------------
# NO-PLANNING RULE (CRITICAL)
# ----------------------------------------------------

# - You MUST NOT decide which activities exist
# - You MUST NOT invent, remove, or reorder activities
# - You MUST NOT infer missing context
# - You MUST NOT optimize, rearrange, or redesign the day
# - You MUST NOT override Python-provided structure

# Python has ALREADY decided:
# - Which stays exist
# - Which meals exist
# - Which attractions exist
# - The exact order of execution

# You may ONLY:
# - Assign start and end times
# - Apply buffers exactly as defined
# - Skip an activity ONLY if rules explicitly allow skipping

# ----------------------------------------------------
# SOURCE OF TRUTH RULE (ABSOLUTE)
# ----------------------------------------------------

# You MUST use ONLY these sources:
# 1) INPUT DAY
# 2) PLACES (order is FINAL)
# 3) Explicit context blocks (PREVIOUS DAY / NEXT DAY)

# You are STRICTLY FORBIDDEN from:
# - Extracting times from earlier itinerary text
# - Guessing previous-day or next-day state
# - Recomputing arrival or departure times
# - Using example data as real input

# ----------------------------------------------------
# ORDER RULE (NON-NEGOTIABLE)
# ----------------------------------------------------

# - Output order MUST EXACTLY match PLACES order
# - You MUST process places strictly top-to-bottom
# - You MAY skip a place, but you MAY NOT move later places earlier
# - ORDER correctness is MORE IMPORTANT than time intuition

# ----------------------------------------------------
# TIME ARITHMETIC RULE (ABSOLUTE)
# ----------------------------------------------------

# - All calculations MUST use exact minute arithmetic
# - NO rounding, snapping, or normalization
# - If a time computes to 07:27, you MUST keep 07:27
# - Seconds are FORBIDDEN
# - Format MUST be HH:MM

# ----------------------------------------------------
# CURRENT_TIME RULE (SINGLE SOURCE OF TRUTH)
# ----------------------------------------------------

# You MUST maintain a single variable called current_time.

# - current_time ONLY moves forward
# - No activity may start before current_time
# - Overlapping activities are INVALID

# For every activity:
# 1) start_time = max(current_time, required_minimum)
# 2) end_time   = start_time + fixed_duration
# 3) If end_time violates a hard rule → SKIP the activity
# 4) If placed:
#    - current_time = end_time
#    - Apply buffer ONLY if explicitly allowed

# ----------------------------------------------------
# BUFFER RULE (ABSOLUTE)
# ----------------------------------------------------

# - Buffer duration is EXACTLY 30 minutes
# - Apply buffer ONLY between different activities or places

# DO NOT apply buffer:
# - Between consecutive stays at the SAME accommodation
# - Before or after overnight stay (unless explicitly stated)
# - When no intervening activity exists

# ----------------------------------------------------
# STAY RULES (ABSOLUTE)
# ----------------------------------------------------

# - Use "stay" ONLY for accommodation
# - Stay duration is EXACTLY 30 minutes unless overnight
# - Overnight stay has no fixed duration unless stated
# - You MUST NOT merge two stays, even if times are contiguous

# ----------------------------------------------------
# MEAL RULES (ABSOLUTE)
# ----------------------------------------------------

# - Meals have FIXED durations and windows
# - Ideal time MUST be used if feasible
# - Minimum gap between meals = 240 minutes
# - If a meal does not fit fully → SKIP it
# - You MUST NOT move meals to protect attractions

# ----------------------------------------------------
# SKIP RULE (STRICT)
# ----------------------------------------------------

# You may SKIP an activity ONLY IF:
# - A hard window is violated
# - A cutoff is exceeded
# - A required buffer cannot be satisfied

# You MUST NOT:
# - Replace skipped activities
# - Add new activities
# - Reorder remaining activities

# ----------------------------------------------------
# ANTI-HALLUCINATION RULE (CRITICAL)
# ----------------------------------------------------

# - You MUST ONLY use names from PLACES
# - You MUST NOT invent or rename places
# - Example place names are STRICTLY FORBIDDEN

# ----------------------------------------------------
# FINALITY RULE (ABSOLUTE)
# ----------------------------------------------------

# Once a stay, meal, or attraction is placed:
# - Its start and end times are FINAL
# - You MUST NOT adjust earlier entries to fix later conflicts
# - If conflict occurs, SKIP the conflicting activity

# ====================================================
# END GLOBAL RULES
# ====================================================
