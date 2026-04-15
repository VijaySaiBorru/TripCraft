# agentic_trip/final_schedule_builder.py
from copy import deepcopy
from typing import  Optional
import re
from data_manager.attraction_loader import AttractionLoader


class FinalScheduleBuilder:
    """
    Deterministic builder:
      - persona-driven attraction count (default 1-2)
      - respect available time per day when selecting attractions
      - last-day departure rules
      - budget calculation (meals × people)
      - restaurant + attraction de-duplication
      - NO fabricated times, NO stringified dicts
    """
    def __init__(self, persona: Optional[dict] = None):
        self.persona = persona or {"type": "Default"}

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
                "../TripCraft_database/public_transit_gtfs/all_poi_nearest_stops.csv"
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

                if row["PoI"].strip().lower() != poi:
                    continue

                # ✅ city filter (ONLY addition)
                if row["City"].strip().lower() != city_l:
                    continue

                # ---- parse distance ----
                try:
                    dist_val = float(row.get("nearest_stop_distance"))
                except Exception:
                    continue

                # sanity cap (same rule as before)
                if dist_val > 5000:
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

    def _build_poi_list_for_day(self, day, day_index, days, cities):
        import re

        poi_entries = []

        # ===================== helpers =====================
        def clean(x):
            if not x:
                return x
            for c in cities:
                city = c.get("city")
                if city and x.endswith(f", {city}"):
                    return x.replace(f", {city}", "").strip()
            return x.strip()

        def to_min(t):
            h, m = map(int, t.split(":"))
            return h * 60 + m

        def to_hhmm(m):
            m = m % (24 * 60)
            return f"{m // 60:02d}:{m % 60:02d}"

        def add_stay(name, start, end):
            if name in ("", "-") or start is None or end is None:
                return
            if start >= end:
                return
            poi_entries.append(
                f"{clean(name)}, stay from {to_hhmm(start)} to {to_hhmm(end)}"
            )

        # ===================== constants =====================
        BUFFER = 30
        STAY_DUR = 30
        MEAL_GAP = 240

        BREAKFAST_WIN = (8 * 60, 10 * 60 + 30)
        LUNCH_WIN = (12 * 60, 15 * 60 + 40)
        DINNER_WIN = (18 * 60 + 30, 22 * 60 + 30)

        BREAKFAST_IDEAL = 9 * 60 + 30
        LUNCH_IDEAL = 14 * 60 + 40
        DINNER_IDEAL = 20 * 60 + 45

        BREAKFAST_DUR = 50
        LUNCH_DUR = 60
        DINNER_DUR = 75
        ATTRACTION_DUR = 120
        LARGE_ATT_DUR = 180
        attraction_duration_map = {}

        for c in cities:
            for a in c.get("attractions_ranked", []):
                name = clean(a.get("name"))
                dur_hr = a.get("visit_duration")
                if name and dur_hr:
                    attraction_duration_map[name] = int(dur_hr * 60)


        # ===================== transport parse =====================
        transport = day.get("transportation", "")
        arr_min = dep_min = None

        if m := re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", transport):
            arr_min = to_min(m.group(1))
        if m := re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", transport):
            dep_min = to_min(m.group(1))

        # ===================== resolve case =====================
        # ---------------- arrival day classification ----------------
        arrival_next_day = False

        if arr_min is not None:
            # hard cutoff: 23:30 or later is next-day arrival
            if arr_min >= (23 * 60 + 30):
                arrival_next_day = True

        is_first = day_index == 0
        is_last = day_index == len(days) - 1
        is_travel = "from " in day.get("current_city", "")
        DAY_OFFSET = day_index * 24 * 60


        if is_first and is_travel:
            case = "FIRST_DAY"
        elif is_last and is_travel:
            case = "LAST_DAY"
        elif is_travel:
            case = "INTER_CITY"
        else:
            case = "NON_TRAVEL"

        # ===================== state =====================
        current_time = 8 * 60
        last_meal_end = None
        meals_done = set()

        curr_acc = clean(day.get("accommodation", "-"))
        attractions = [clean(x) for x in day.get("attraction", "").split(";") if x.strip()]

        effective_acc = curr_acc
        if effective_acc in ("", "-") and day_index > 0:
            prev = days[day_index - 1].get("accommodation", "-")
            if prev not in ("", "-"):
                effective_acc = clean(prev)

        # ===================== shared helpers =====================
        def fits_before_departure(start, dur):
            return dep_min is not None and start + dur <= dep_min - BUFFER
        
        def get_attraction_dur(name):
            return attraction_duration_map.get(clean(name), ATTRACTION_DUR)


        def pick_meal_start(now, win_start, win_end, ideal):
            # print(f"pick_meal_start called with now={now}, win_start={win_start}, win_end={win_end}, ideal={ideal}")
            earliest = max(now + BUFFER, win_start)
            if earliest <= ideal <= win_end:
                return ideal
            if earliest <= win_end:
                return earliest
            return None

        def add(name, start, dur, is_meal=False, meal_type=None,is_inter=False):
           
            nonlocal current_time, last_meal_end
            if name in ("", "-") or start is None:
                return

            if is_meal:
                if meal_type in meals_done:
                    return
                if last_meal_end is not None:
                    start = max(start, last_meal_end + MEAL_GAP)
 

            start = max(start, current_time)
            end = start + dur

            transit_str = ""
            for c in cities:
                rows = c.get("raw_transit_rows")
                if rows:
                    city = c.get("city")
                    if city:
                        transit = self.resolve_transit_for_poi(clean(name), city, rows)
                    else:
                        transit = None
                    if transit:
                        transit_str = (
                            f", nearest transit: {transit['stop']}, "
                            f"{transit['distance']}m away"
                        )
                        break

            poi_entries.append(
                f"{clean(name)}, visit from {to_hhmm(start)} to {to_hhmm(end)}{transit_str}"
            )

            current_time = end
            if is_meal:
                last_meal_end = end
                meals_done.add(meal_type)

        # ===================== CASE HANDLERS =====================
        def handle_first_day():
            nonlocal current_time

            # 🚫 If arrival is considered next day, do NOTHING here
            # if arrival_next_day:
            #     return

            # ---------------- same-day arrival logic ----------------
            current_time = arr_min + BUFFER

            # ---------------- CHECK-IN (UNCHANGED) ----------------
            if effective_acc not in ("", "-"):
                add_stay(effective_acc, current_time, current_time + STAY_DUR)
                current_time += STAY_DUR

            # ---------------- breakfast ----------------
            bf = pick_meal_start(current_time, *BREAKFAST_WIN, BREAKFAST_IDEAL)
            if bf and day.get("breakfast") not in ("", "-"):
                add(day.get("breakfast"), bf, BREAKFAST_DUR, True, "breakfast")

            # ======================================================
            # ATTRACTION BEFORE LUNCH (ONLY IF SAFE)
            # ======================================================
            pre_lunch_attraction_added = False

            if attractions:
                att = attractions[0]
                dur = attraction_duration_map.get(clean(att), ATTRACTION_DUR)
                tentative_start = current_time + BUFFER
                tentative_end = tentative_start + dur

                # Check whether lunch will still be possible
                lunch_after = pick_meal_start(
                    tentative_end,
                    *LUNCH_WIN,
                    LUNCH_IDEAL
                )

                if lunch_after:
                    add(attractions[0], tentative_start, dur)
                    pre_lunch_attraction_added = True

            # ---------------- lunch ----------------
            ln = pick_meal_start(current_time, *LUNCH_WIN, LUNCH_IDEAL)
            if ln and day.get("lunch") not in ("", "-"):
                add(day.get("lunch"), ln, LUNCH_DUR, True, "lunch")

            # ======================================================
            # ATTRACTION AFTER LUNCH (IF NEEDED)
            # ======================================================
            if attractions:
                idx = 1 if pre_lunch_attraction_added else 0

                if idx < len(attractions):
                    att = attractions[idx]
                    dur = attraction_duration_map.get(clean(att), ATTRACTION_DUR)
                    post_start = current_time + BUFFER
                    post_end = post_start + dur

                    # Must not affect dinner
                    if post_end+BUFFER < DINNER_WIN[1]:
                        add(attractions[idx], post_start, dur)

            # ---------------- dinner ----------------
            dn = pick_meal_start(current_time, *DINNER_WIN, DINNER_IDEAL)
            if dn and day.get("dinner") not in ("", "-"):
                add(day.get("dinner"), dn, DINNER_DUR, True, "dinner")

            # ---------------- OVERNIGHT STAY (UNCHANGED) ----------------
            if effective_acc not in ("", "-"):
                add_stay(effective_acc, current_time, 8 * 60 + 24 * 60)

        def handle_non_travel():
            nonlocal current_time
            if attractions:
                attractions.sort(
                    key=lambda a: get_attraction_dur(a)
                )

            # ---------------- morning stay (UNCHANGED) ----------------
            if effective_acc not in ("", "-"):
                add_stay(effective_acc, 8 * 60, 8 * 60 + STAY_DUR)

            # ---------------- breakfast ----------------
            # bf = pick_meal_start(current_time, *BREAKFAST_WIN, BREAKFAST_IDEAL)
            bf = None

            if attractions:
                first_dur = get_attraction_dur(attractions[0])

                # long attraction → pull breakfast earlier (but respect buffer)
                if first_dur >= 180:  # 3 hours
                    earliest_bf = current_time + BUFFER
                    bf = pick_meal_start(
                        earliest_bf,
                        *BREAKFAST_WIN,
                        BREAKFAST_WIN[0]  # force earliest
                    )

            # fallback to normal behavior
            if bf is None:
                bf = pick_meal_start(current_time, *BREAKFAST_WIN, BREAKFAST_IDEAL)

            if bf and day.get("breakfast") not in ("", "-"):
                add(day.get("breakfast"), bf, BREAKFAST_DUR, True, "breakfast")

            used = 0  # number of attractions placed

            # ==================================================
            # PRE-LUNCH ATTRACTION (ONLY IF SAFE)
            # ==================================================
            if attractions:
                att = attractions[0]
                dur = attraction_duration_map.get(clean(att), ATTRACTION_DUR)

                tentative_start = current_time + BUFFER
                tentative_end = tentative_start + dur
                # long attraction must be consumed before lunch
                if dur >= 180 and tentative_end <= LUNCH_WIN[1]:
                    add(att, tentative_start, dur)
                    used = 1

                # fallback: short attraction rule
                elif tentative_end <= LUNCH_IDEAL:
                    add(att, tentative_start, dur)
                    used = 1

                # Must comfortably finish before ideal lunch
                # if tentative_end <= LUNCH_IDEAL:
                #     add(attractions[0], tentative_start, dur)
                #     used = 1

            # ---------------- lunch ----------------
            ln = pick_meal_start(current_time, *LUNCH_WIN, LUNCH_IDEAL)
            if ln and day.get("lunch") not in ("", "-"):
                add(day.get("lunch"), ln, LUNCH_DUR, True, "lunch")

            # ==================================================
            # POST-LUNCH ATTRACTIONS (UP TO 2 TOTAL)
            # ==================================================
            while used < len(attractions) and used < 2:
                att = attractions[used]
                dur = attraction_duration_map.get(clean(att), ATTRACTION_DUR)

                post_start = current_time + BUFFER
                post_end = post_start + dur

                # Must finish before dinner window
                if post_end + BUFFER <= DINNER_WIN[1]:
                    add(attractions[used], post_start, dur)
                    used += 1
                else:
                    break

            # ---------------- dinner ----------------
            dn = pick_meal_start(current_time, *DINNER_WIN, DINNER_IDEAL)
            if dn and day.get("dinner") not in ("", "-"):
                add(day.get("dinner"), dn, DINNER_DUR, True, "dinner")

            # ---------------- overnight stay (UNCHANGED) ----------------
            overnight_end = 8 * 60 + 24 * 60  # soft upper bound

            if day_index + 1 < len(days):
                t = days[day_index + 1].get("transportation", "")
                if m := re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", t):
                    next_dep = to_min(m.group(1))
                    next_dep_abs = next_dep + 24 * 60

                    # ---- breakfast feasibility check ----
                    bf_win_start = 8 * 60 + 24 * 60
                    bf_win_end = 10 * 60 + 24 * 60

                    latest_bf_start = min(
                        bf_win_end,
                        next_dep_abs - BUFFER - BREAKFAST_DUR
                    )

                    breakfast_feasible = bf_win_start <= latest_bf_start

                    if breakfast_feasible:
                        # stay + buffer + breakfast + buffer
                        leave_time = next_dep_abs - (
                            BUFFER +
                            BREAKFAST_DUR +
                            BUFFER +
                            STAY_DUR
                        )
                    else:
                        # stay + buffer only
                        leave_time = next_dep_abs - (BUFFER + STAY_DUR)

                    overnight_end = min(overnight_end, leave_time)

            # safety
            overnight_end = max(overnight_end, current_time)

            if effective_acc not in ("", "-"):
                add_stay(effective_acc, current_time, overnight_end)

        def handle_inter_city():
            nonlocal current_time, last_meal_end

            # =============================
            # RESET
            # =============================
            bf_done = ln_done = dn_done = False
            bf_start = bf_end = None
            ln_start = ln_end = None
            last_meal_end=None

            if dep_min is None:
                return

            # =============================
            # ORIGIN / DEST CITY
            # =============================
            route = day.get("current_city", "")

            if " from " in route.lower() or route.lower().startswith("from"):
                route_clean = route.replace("from", "", 1).strip()

                parts = route_clean.split(" to ")

                if len(parts) == 2:
                    origin_city = parts[0].strip()
                    dest_city = parts[1].strip()
                else:
                    raise ValueError(f"Invalid route format: {route}")


            # =============================
            # SPLIT ATTRACTIONS
            # =============================
            inter_attractions = [x for x in day.get("attraction", "").split(";") if x.strip()]
            origin_atts, dest_atts = [], []
            for a in inter_attractions:
                if origin_city in a:
                    origin_atts.append(a)
                elif dest_city in a:
                    dest_atts.append(a)

            # ==================================================
            # ORIGIN CITY
            # ==================================================
            dep_abs = dep_min + 24 * 60
            day_end = dep_abs - BUFFER

            prev_day = days[day_index - 1]
            prev_pois = prev_day.get("point_of_interest_list", "")
            prev_acc = prev_day.get("accommodation", "")

            prev_stay_end = None
            if prev_pois:
                import re
                m = re.findall(r"stay from (\d{2}:\d{2}) to (\d{2}:\d{2})", prev_pois)
                if m:
                    _, end = m[-1]
                    prev_stay_end = to_min(end) + 24 * 60

            if prev_stay_end is None:
                prev_stay_end = 8 * 60 + 24 * 60

            if prev_acc not in ("", "-"):
                ts = prev_stay_end
                te = min(ts + STAY_DUR, day_end)
                if te > ts:
                    add_stay(prev_acc, ts, te)

            origin_ready = prev_stay_end + STAY_DUR + BUFFER

            # ---------------- ORIGIN MEALS ----------------
            last_meal_end = None

            # -------- breakfast (OK) --------
            bf_earliest = max(origin_ready, BREAKFAST_WIN[0] + 24 * 60)
            bf_latest   = min(BREAKFAST_WIN[1] + 24 * 60, dep_abs - BUFFER)

            if bf_earliest + BREAKFAST_DUR <= bf_latest:
                bf_start = BREAKFAST_IDEAL + 24 * 60 if bf_earliest <= BREAKFAST_IDEAL + 24 * 60 <= bf_latest else bf_earliest
                add(day.get("breakfast"), bf_start, BREAKFAST_DUR, True, "breakfast")
                last_meal_end = bf_start + BREAKFAST_DUR
                bf_done = True


            # -------- FIRST ORIGIN ATTRACTION (fixed) --------
            # -------- FIRST ORIGIN ATTRACTION (BUFFER SAFE) --------
            if origin_atts:
                start = max(
                    origin_ready,
                    (last_meal_end + BUFFER) if last_meal_end else origin_ready
                )
                att = origin_atts[0]
                dur = get_attraction_dur(att)
                end = start + dur
                after_attr = end + BUFFER

                # 🔒 HARD CHECK — transport buffer
                if end > dep_abs - BUFFER:
                    pass
                    # print("❌ Skipped: violates 30-min transport buffer")
                else:
                    # soft lunch logic (optional)
                    ln_earliest_after_attr = max(
                        after_attr,
                        last_meal_end + MEAL_GAP if last_meal_end else after_attr,
                        LUNCH_WIN[0] + 24 * 60
                    )
                    ln_latest_start = (LUNCH_WIN[1] + 24 * 60) - LUNCH_DUR

                    if ln_earliest_after_attr <= ln_latest_start:
                        pass
                        # print("→ Lunch safe")
                    else:
                        pass
                        # print("→ Lunch impossible anyway, allowing attraction")

                    add(origin_atts.pop(0), start, dur)
                    current_time = current_time + BUFFER

            # -------- lunch (fixed earliest) ---------
            ln_earliest = max(
                current_time,
                last_meal_end + MEAL_GAP if last_meal_end else current_time,
                LUNCH_WIN[0] + 24 * 60
            )
            
            ln_latest = min(LUNCH_WIN[1] + 24 * 60, dep_abs - BUFFER)


            if ln_earliest + LUNCH_DUR <= ln_latest:
                ln_start = LUNCH_IDEAL + 24 * 60 if ln_earliest <= LUNCH_IDEAL + 24 * 60 <= ln_latest else ln_earliest
                add(day.get("lunch"), ln_start, LUNCH_DUR, True, "lunch")
                ln_done = True
                last_meal_end = ln_start + LUNCH_DUR
            
            # -------- SECOND ORIGIN ATTRACTION (AFTER LUNCH, BUFFER SAFE) --------
            while origin_atts:
                start = max(
                    current_time if current_time else origin_ready,
                    last_meal_end + BUFFER if last_meal_end else origin_ready
                )
                att = origin_atts[0]
                dur = get_attraction_dur(att)

                end = start + dur
                after_attr = end + BUFFER

                # 🔒 HARD CHECK: transport buffer
                if end > dep_abs - BUFFER:
                    break

                # ---- Dinner feasibility check ----
                earliest_dn_start = max(
                    after_attr,
                    last_meal_end + MEAL_GAP if last_meal_end else after_attr,
                    DINNER_WIN[0] + 24 * 60
                )

                latest_dn_start = min(
                    DINNER_WIN[1] + 24 * 60 - DINNER_DUR,
                    dep_abs - BUFFER - DINNER_DUR
                )

                if earliest_dn_start > latest_dn_start:
                    break

                # ✅ Attraction is safe
                add(origin_atts.pop(0), start, dur)
                current_time = after_attr

            # ---------------- ORIGIN DINNER (IDEAL → LATEST FALLBACK) ----------------

            latest_dinner_end = dep_abs - BUFFER
            latest_dn_start = latest_dinner_end - DINNER_DUR

            earliest_dn_start = max(
                origin_ready,
                last_meal_end + MEAL_GAP if last_meal_end else origin_ready,
                DINNER_WIN[0] + 24 * 60
            )

            window_latest_start = DINNER_WIN[1] + 24 * 60 - DINNER_DUR

            candidate = None

            # ---- 1️⃣ TRY IDEAL DINNER FIRST ----
            ideal_start = DINNER_IDEAL + 24 * 60

            if (
                ideal_start >= earliest_dn_start and
                ideal_start <= window_latest_start and
                ideal_start <= latest_dn_start
            ):
                candidate = ideal_start

            # ---- 2️⃣ FALLBACK: USE LATEST POSSIBLE ----
            else:
                fallback_start = min(latest_dn_start, window_latest_start)

                if earliest_dn_start <= fallback_start:
                    candidate = fallback_start
                else:
                    pass
                    # print("→ no feasible dinner slot")

            # ---- 3️⃣ ADD DINNER IF POSSIBLE ----
            if candidate is not None:
                add(day.get("dinner"), candidate, DINNER_DUR, True, "dinner")
                dn_done = True
                last_meal_end = candidate + DINNER_DUR
            else:
                pass
                # print(" Dinner skipped")

            # ==================================================
            # DESTINATION CITY
            # ==================================================
            if arr_min is None:
                return

            current_time = arr_min + BUFFER

            if curr_acc not in ("", "-"):
                add_stay(curr_acc, current_time, current_time + STAY_DUR)
                current_time += STAY_DUR 
                if dest_atts or (not bf_done) or (not ln_done) or (not dn_done):
                    current_time += BUFFER
            after_dest_arrival=False

            # ---------------- BREAKFAST ----------------
            if not bf_done:
                bf_start = pick_meal_start(current_time- BUFFER, *BREAKFAST_WIN, BREAKFAST_IDEAL)
                if bf_start is not None:
                    bf_end = bf_start + BREAKFAST_DUR
                    add(day.get("breakfast"), bf_start, BREAKFAST_DUR, True, "breakfast")
                    current_time = bf_end + BUFFER
                    after_dest_arrival=True
                # else: just skip breakfast

           # ---------------- FIRST ATTRACTION (LUNCH-SAFE) ----------------
            if dest_atts:
                start = current_time
                att = dest_atts[0]
                dur = get_attraction_dur(att)
                end = start + dur
                after_attr = end + BUFFER

                # can lunch still fit after this attraction?
                raw_ln = pick_meal_start(after_attr, *LUNCH_WIN, LUNCH_IDEAL)

                if raw_ln is not None:
                    # lunch is still possible → allow attraction
                    add(dest_atts.pop(0), start, dur)
                    after_dest_arrival=True
                    current_time = after_attr
                # else: skip attraction, protect lunch

            # ---------------- LUNCH (NO DOUBLE BUFFER) ----------------
            # force lunch to respect current_time first
            

            if not ln_done:
                raw_ln = pick_meal_start(current_time, *LUNCH_WIN, LUNCH_IDEAL)
            else:
                raw_ln = None


            if raw_ln is not None:
                # 🔑 DO NOT allow pick_meal_start to push forward
                if LUNCH_IDEAL >= current_time:
                    candidate = LUNCH_IDEAL
                else:
                    candidate = current_time

                if candidate + LUNCH_DUR <= DINNER_WIN[1]:
                    ln_start = candidate
                else:
                    ln_start = current_time

            else:
                ln_start = None

            if ln_start:
                ln_end = ln_start + LUNCH_DUR
                add(day.get("lunch"), ln_start%(24*60), LUNCH_DUR, True, "lunch",True)
                after_dest_arrival=True
                current_time = ln_end + BUFFER
            else:
                pass
                # print("LUNCH SKIPPED")


            # ---------------- SECOND ATTRACTION ----------------
            # ---------------- DESTINATION ATTRACTIONS (AFTER LUNCH / NO-LUNCH) ----------------
            while dest_atts:
                start = current_time
                att = dest_atts[0]
                dur = get_attraction_dur(att)
                end = start + dur

                dinner_cutoff = DINNER_WIN[1] - DINNER_DUR

                # stop if next attraction would block dinner
                if end + BUFFER > dinner_cutoff:
                    break

                add(dest_atts.pop(0), start, dur)
                after_dest_arrival=True
                current_time = end + BUFFER


            # ---------------- DINNER ----------------
            if not dn_done:
                # print(current_time//60,current_time%60,last_meal_end//60-24,last_meal_end%60,max(current_time+(24*60), last_meal_end + MEAL_GAP if last_meal_end else current_time)//60-24)
                raw_dn = pick_meal_start(
                    max(current_time+(24*60), last_meal_end + MEAL_GAP if last_meal_end else current_time)-24*60,
                    *DINNER_WIN,
                    DINNER_IDEAL
                )
            else:
                raw_dn = None

            if raw_dn is not None:
                if last_meal_end is not None and last_meal_end > 24*60:
                    last_meal_end -= 24*60

                
                candidate = max(
                    raw_dn,
                    last_meal_end + MEAL_GAP if last_meal_end else raw_dn
                )

                overnight_start = 8 * 60 + 24 * 60

                if candidate + DINNER_DUR <= overnight_start:
                    dn_start = candidate
                else:
                    dn_start = None
            else:
                dn_start = None

            if dn_start:
                add(day.get("dinner"), dn_start, DINNER_DUR, True, "dinner")
                after_dest_arrival=True
                current_time = dn_start + DINNER_DUR 
                dn_done = True
                last_meal_end = dn_start + DINNER_DUR



            # ---------------- OVERNIGHT STAY ----------------
            if curr_acc not in ("", "-"):
                if not after_dest_arrival:
                    current_time -= BUFFER
                add_stay(curr_acc, current_time, 8 * 60 + 24 * 60)

        def handle_last_day():
            nonlocal current_time, last_meal_end

            # reset meal tracking for last day
            last_meal_end = None
            meals_done.clear()

            if dep_min is None:
                return

            # --------------------------------------------------
            # HARD DEPARTURE CONSTRAINT (ABSOLUTE)
            # --------------------------------------------------
            dep_abs = dep_min + 24 * 60
            day_end = dep_abs - BUFFER

            # --------------------------------------------------
            # FIND PREVIOUS DAY STAY END
            # --------------------------------------------------
            prev_day = days[day_index - 1]
            prev_pois = prev_day.get("point_of_interest_list", "")

            prev_stay_end = None
            if prev_pois:
                import re
                matches = re.findall(
                    r"stay from (\d{2}:\d{2}) to (\d{2}:\d{2})",
                    prev_pois
                )
                if matches:
                    _, end = matches[-1]
                    prev_stay_end = to_min(end) + 24 * 60

            if prev_stay_end is None:
                prev_stay_end = 8 * 60 + 24 * 60

            # --------------------------------------------------
            # TAIL STAY (CHECKOUT)
            # --------------------------------------------------
            if effective_acc not in ("", "-"):
                tail_start = prev_stay_end
                tail_end = min(prev_stay_end + STAY_DUR, day_end)
                if tail_end > tail_start:
                    add_stay(effective_acc, tail_start, tail_end)

            # --------------------------------------------------
            # DAY START = checkout + transition buffer
            # --------------------------------------------------
            current_time = max(prev_stay_end + STAY_DUR + BUFFER, 8 * 60)
            day_anchor = current_time
            # ==================================================
            # BREAKFAST (EARLY ONLY IF NEEDED FOR LARGE ATTRACTION)
            # ==================================================
            bf_earliest = max(day_anchor, BREAKFAST_WIN[0] + 24 * 60)
            bf_end_limit = min(BREAKFAST_WIN[1] + 24 * 60, day_end)

            bf_start = None
            need_early_breakfast = False

            # check if a large attraction exists
            if attractions:
                max_dur = max(get_attraction_dur(a) for a in attractions)

                if max_dur >= 180:  # 3 hours
                    # simulate EARLY breakfast
                    early_attr_start = bf_earliest + BREAKFAST_DUR + BUFFER
                    early_attr_end = early_attr_start + max_dur

                    # simulate IDEAL breakfast
                    ideal_bf = (
                        BREAKFAST_IDEAL + 24 * 60
                        if bf_earliest <= BREAKFAST_IDEAL + 24 * 60 <= bf_end_limit
                        else bf_earliest
                    )
                    ideal_attr_start = ideal_bf + BREAKFAST_DUR + BUFFER
                    ideal_attr_end = ideal_attr_start + max_dur

                    if (
                        early_attr_end <= dep_abs - BUFFER and
                        ideal_attr_end > dep_abs - BUFFER
                    ):
                        need_early_breakfast = True

            # choose breakfast time
            if bf_earliest + BREAKFAST_DUR <= bf_end_limit:
                if need_early_breakfast:
                    bf_start = bf_earliest
                else:
                    bf_start = (
                        BREAKFAST_IDEAL + 24 * 60
                        if bf_earliest <= BREAKFAST_IDEAL + 24 * 60
                        and BREAKFAST_IDEAL + 24 * 60 + BREAKFAST_DUR <= bf_end_limit
                        else bf_earliest
                    )

            if bf_start:
                add(day.get("breakfast"), bf_start, BREAKFAST_DUR, True, "breakfast")


            # ==================================================
            # PRE-LUNCH ATTRACTION
            # ==================================================
            used = 0
            if attractions:
                att = attractions[0]
                dur = get_attraction_dur(att)
                start = current_time + BUFFER
                if start + dur <= day_end:
                    add(attractions[0], start, dur)
                    used = 1

            # ==================================================
            # LUNCH
            # ==================================================
            ln_earliest = max(day_anchor, LUNCH_WIN[0] + 24 * 60)
            ln_end_limit = min(LUNCH_WIN[1] + 24 * 60, day_end)

            if ln_earliest + LUNCH_DUR <= ln_end_limit:
                if (
                    ln_earliest <= LUNCH_IDEAL + 24 * 60
                    and LUNCH_IDEAL + 24 * 60 + LUNCH_DUR <= ln_end_limit
                ):
                    ln_start = LUNCH_IDEAL + 24 * 60
                else:
                    ln_start = ln_earliest

                # 🔒 FINAL SAFETY CHECK (MEAL GAP AWARE)
                effective_ln_start = ln_start
                if last_meal_end is not None:
                    effective_ln_start = max(ln_start, last_meal_end + MEAL_GAP)

                if effective_ln_start + LUNCH_DUR <= ln_end_limit:
                    add(day.get("lunch"), ln_start, LUNCH_DUR, True, "lunch")




            # ==================================================
            # POST-LUNCH ATTRACTION  ✅ RESTORED
            # ==================================================
            if used < len(attractions):
                att = attractions[used]
                dur = get_attraction_dur(att)
                start = current_time + BUFFER
                if start + dur <= day_end:
                    add(attractions[used], start, dur)
                    used += 1

            # ==================================================
            # DINNER (only if very late departure)
            # ==================================================
            dn_earliest = max(day_anchor, DINNER_WIN[0] + 24 * 60)
            dn_end_limit = min(DINNER_WIN[1] + 24 * 60, day_end)

            if dn_earliest + DINNER_DUR <= dn_end_limit:
                dn_start = (
                    DINNER_IDEAL + 24 * 60
                    if dn_earliest <= DINNER_IDEAL + 24 * 60
                    and DINNER_IDEAL + 24 * 60 + DINNER_DUR <= dn_end_limit
                    else dn_earliest
                )
                add(day.get("dinner"), dn_start, DINNER_DUR, True, "dinner")

        # ===================== dispatch =====================
        if case == "FIRST_DAY":
            handle_first_day()
        elif case == "NON_TRAVEL":
            handle_non_travel()
        elif case == "INTER_CITY":
            handle_inter_city()
        elif case == "LAST_DAY":
            handle_last_day()

        day["point_of_interest_list"] = "; ".join(poi_entries)

    # -------------------- helpers --------------------
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

    def prune_plan_by_poi(self, days):
        for day in days:
            poi = day.get("point_of_interest_list", "")

            # extract visited POI names
            visited = set()
            for entry in poi.split(";"):
                entry = entry.strip()
                if not entry:
                    continue
                name = entry.split(",")[0].strip().lower()
                visited.add(name)

            # -------- prune meals --------
            for meal in ("breakfast", "lunch", "dinner"):
                val = day.get(meal, "-")
                if val in ("", "-"):
                    continue
                name = val.split(",")[0].strip().lower()
                if name not in visited:
                    day[meal] = "-"

            # -------- prune attractions (INDIVIDUAL) --------
            val = day.get("attraction", "-")
            if val not in ("", "-"):
                kept = []
                for a in val.split(";"):
                    a = a.strip()
                    if not a:
                        continue
                    name = a.split(",")[0].strip().lower()
                    if name in visited:
                        kept.append(a)

                day["attraction"] = "; ".join(kept) + ";" if kept else "-"


    # -------------------- main builder --------------------
    def build_plan_from_combined(self, reference):
        ref = deepcopy(reference or {})
        # print("Ref:", ref)

        # ------------------------------------------------------------
        # 1. Basic extraction
        # ------------------------------------------------------------
        dates = ref.get("dates", [])
        n_days = len(dates)

        cities = ref.get("cities", [])
        transport_legs = ref.get("transportation", {}).get("legs", [])

        people = int(ref.get("people_number", 1))
        budget = float(ref.get("budget", 0))

        restaurants_by_city = {
            c["city"]: c.get("restaurants_ranked", [])
            for c in cities
        }

        attractions_by_city = {
            c["city"]: c.get("attractions_ranked", [])
            for c in cities
        }

        # ------------------------------------------------------------
        # 2. DAY → CITY MAP (NON-TRAVEL DAYS ONLY)
        # ------------------------------------------------------------
        if n_days == 3:
            day_city = [cities[0]["city"]] * 3
        elif n_days == 5:
            day_city = [cities[0]["city"]] * 3 + [cities[1]["city"]] * 2
        elif n_days == 7:
            day_city = (
                [cities[0]["city"]] * 3 +
                [cities[1]["city"]] * 2 +
                [cities[2]["city"]] * 2
            )
        else:
            return {"error": f"Unsupported trip length: {n_days}"}

        # ------------------------------------------------------------
        # 3. Accommodation map
        # ------------------------------------------------------------
        accommodation_by_city = {
            c["city"]: f'{c["accommodation"]["name"]}, {c["city"]}'
            for c in cities
        }

        # ------------------------------------------------------------
        # 4. Build skeleton (SOURCE OF TRUTH)
        # ------------------------------------------------------------
        days = self.build_days_skeleton(
            n_days=n_days,
            dates=dates,
            day_city=day_city,
            transport_legs=transport_legs,
            accommodation_by_city=accommodation_by_city
        )
        # print("Skeleton:", days)

        # ------------------------------------------------------------
        # 5. Manual filling (ALL CASES EXPLICIT)
        # ------------------------------------------------------------
        used_restaurants = set()
        used_attractions = set()

        for i, day in enumerate(days):

            is_first_day = i == 0
            is_last_day = i == n_days - 1
            has_transport = day["transportation"] != "-"

            transport = day["transportation"]

            origin = dest = None
            dep_min = arr_min = None

            if has_transport:
                m = re.search(r"from\s+(.*?)\s+to\s+(.*?)(,|$)", transport)
                if m:
                    origin = m.group(1)
                    dest = m.group(2)

                dep = re.search(r"Departure Time:\s*(\d{1,2}:\d{2})", transport)
                arr = re.search(r"Arrival Time:\s*(\d{1,2}:\d{2})", transport)

                if dep:
                    h, m_ = map(int, dep.group(1).split(":"))
                    dep_min = h * 60 + m_
                if arr:
                    h, m_ = map(int, arr.group(1).split(":"))
                    arr_min = h * 60 + m_

            # ---------------- Meals ----------------
            for meal in ("breakfast", "lunch", "dinner"):
                if day[meal] != "":
                    continue
                # ---------------- NORMAL DAY ----------------
                if not has_transport:
                    meal_city = day_city[i]
                # ---------------- FIRST DAY ----------------
                elif is_first_day:
                    meal_city = dest
                # ---------------- LAST DAY ----------------
                elif is_last_day:
                    meal_city = origin
                # ---------------- INTER-TRAVEL DAY ----------------
                else:
                    # -------- BREAKFAST --------
                    if meal == "breakfast":
                        if arr_min is not None and arr_min <= 8 * 60 + 10:
                            meal_city = dest
                        elif dep_min is not None and dep_min >= 9 * 60 + 20:
                            meal_city = origin
                        else:
                            day[meal] = "-"
                            continue

                    # -------- LUNCH --------
                    elif meal == "lunch":
                        if arr_min is not None and arr_min <= 13 * 60:
                            meal_city = dest
                        elif dep_min is not None and dep_min >= 14 * 60 + 50:
                            meal_city = origin
                        else:
                            day[meal] = "-"
                            continue

                    # -------- DINNER --------
                    elif meal == "dinner":
                        if arr_min is not None and arr_min <= 20 * 60:
                            meal_city = dest
                        elif dep_min is not None and dep_min >= 20 * 60 + 45:
                            meal_city = origin
                        else:
                            day[meal] = "-"
                            continue

                for r in restaurants_by_city.get(meal_city, []):
                    name = r["name"]
                    if name.lower() not in used_restaurants:
                        used_restaurants.add(name.lower())
                        day[meal] = f"{name}, {meal_city}"
                        break
                else:
                    day[meal] = "-"

            # ---------------- Attractions ----------------
            if day["attraction"] == "":
                # ---------------- NORMAL DAY ----------------
                if not has_transport:
                    city = day_city[i]

                    all_city_attractions = attractions_by_city.get(city, [])
                    remaining = [
                        a for a in all_city_attractions
                        if a["name"].lower() not in used_attractions
                    ]

                    # count how many NORMAL days remain for this city (including today)
                    remaining_days = sum(
                        1 for j in range(i, n_days)
                        if day_city[j] == city and days[j]["transportation"] == "-"
                    )

                    if not remaining:
                        day["attraction"] = "-"
                        continue

                    # allow 2 only if enough attractions exist
                    if len(remaining) >= remaining_days * 2:
                        limit = 2
                    else:
                        limit = 1
                # ---------------- FIRST DAY (ARRIVAL) ----------------
                elif is_first_day:
                    # Attraction only if early arrival
                    if arr_min is not None and arr_min <= 8 * 60 + 10:
                        city = dest
                        limit = 2
                    elif arr_min is not None and arr_min <= 16 * 60 + 45:
                        city = dest
                        limit = 1
                    else:
                        day["attraction"] = "-"
                        continue

                # ---------------- INTER-CITY DAY ----------------
                # ---------------- INTER-CITY DAY ----------------
                elif not is_last_day:
                    # Windows
                    origin_window = dep_min is not None and dep_min >= 13 * 60 + 20
                    dest_window = arr_min is not None and arr_min <= 16 * 60 + 45

                    # Strong windows (for 2 in same city)
                    strong_origin = dep_min is not None and dep_min >= 18 * 60 + 30
                    strong_dest = arr_min is not None and arr_min <= 8 * 60 + 10

                    # ---- CASE 1: Two in origin city ----
                    if strong_origin:
                        city = origin
                        limit = 2

                    # ---- CASE 2: Two in destination city ----
                    elif strong_dest:
                        city = dest
                        limit = 2

                    # ---- CASE 3: One in origin + one in destination (MIXED) ----
                    elif origin_window and dest_window:
                        # Special marker: handled below while picking
                        city = None
                        limit = 2

                    # ---- CASE 4: One in origin only ----
                    elif origin_window:
                        city = origin
                        limit = 1

                    # ---- CASE 5: One in destination only ----
                    elif dest_window:
                        city = dest
                        limit = 1

                    # ---- CASE 6: No attractions ----
                    else:
                        day["attraction"] = "-"
                        continue


                # ---------------- LAST DAY (DEPARTURE) ----------------
                else:  # LAST DAY
                    if dep_min is not None and dep_min >= 18 * 60 + 30:
                        city = origin
                        limit = 2
                    elif dep_min is not None and dep_min >= 13 * 60 + 20:
                        city = origin
                        limit = 1
                    else:
                        day["attraction"] = "-"
                        continue


                # ---------------- PICK ATTRACTIONS ----------------
                picked = []

                if city is None:
                    # MIXED CASE: origin first, then destination

                    # pick 1 from origin
                    for a in attractions_by_city.get(origin, []):
                        if a["name"].lower() not in used_attractions:
                            used_attractions.add(a["name"].lower())
                            picked.append(f'{a["name"]}, {origin}')
                            break

                    # pick 1 from destination
                    for a in attractions_by_city.get(dest, []):
                        if a["name"].lower() not in used_attractions:
                            used_attractions.add(a["name"].lower())
                            picked.append(f'{a["name"]}, {dest}')
                            break

                else:
                    # SAME CITY CASE
                    for a in attractions_by_city.get(city, []):
                        if a["name"].lower() not in used_attractions:
                            used_attractions.add(a["name"].lower())
                            picked.append(f'{a["name"]}, {city}')
                        if len(picked) == limit:
                            break

                day["attraction"] = "; ".join(picked) + ";" if picked else "-"

        # ------------------------------------------------------------
        # MAP EVENTS TO DAYS (DATE-BASED, CORRECT)
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
                continue

            # ---------- ASSIGN EVENT ----------
            events_today = city_event_map.get((city, day_date), [])
            if events_today:
                e = events_today[0]
                day["event"] = f'{e["name"]}, {city}'


        # ------------------------------------------------------------
        # 5.5 Build Point of Interest List
        # ------------------------------------------------------------
        # print("Building POI lists...,and input ",cities,days)
        for i, day in enumerate(days):
            self._build_poi_list_for_day(
                day=day,
                day_index=i,
                days=days,
                cities=cities
            )
        self.prune_plan_by_poi(days)


        # ------------------------------------------------------------
        # 6. Budget calculation (UNCHANGED)
        # ------------------------------------------------------------
        budget_used = 0.0

        for leg in transport_legs:
            mode = leg.get("mode", "").lower()

            # Flight
            if mode == "flight" and "price" in leg["details"]:
                budget_used += leg["details"]["price"] * people

            # Self-driving
            elif mode == "self-driving":
                cost = leg["details"].get("cost")
                if cost is not None:
                    # evaluator uses 5 people per car
                    budget_used += cost * ((people + 4) // 5)

            # Taxi (if ever used)
            elif mode == "taxi":
                cost = leg["details"].get("cost")
                if cost is not None:
                    # evaluator uses 4 people per taxi
                    budget_used += cost * ((people + 3) // 4)


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
            budget_used += acc["price_per_night"] * nights * units

        for day in days:
            for meal in ("breakfast", "lunch", "dinner"):
                val = day[meal]
                if val == "-" or val == "":
                    continue

                name, city = [x.strip() for x in val.rsplit(",", 1)]
                for r in restaurants_by_city.get(city, []):
                    if r["name"].lower() == name.lower():
                        budget_used += r["avg_cost"] * people
                        break

        budget_used = round(budget_used, 2)
        budget_remaining = round(budget - budget_used, 2)

        # ------------------------------------------------------------
        # 7. Final output
        # ------------------------------------------------------------
        return {
            "days": days,
            "budget_used": budget_used,
            "budget_remaining": budget_remaining,
            "budget_ok": budget_remaining >= 0
        }
