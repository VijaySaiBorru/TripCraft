import sys
import json
import re
from copy import deepcopy
from pathlib import Path

class POIBuilder:

    # ------------------- DUMMY transit resolver -------------------
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

            # name match (robust)
            if poi_l not in head.lower():
                continue

            # sanity cap
            if dist_val > 5000:
                continue

            if dist_val < best_dist:
                stop = head[len(poi_name):].strip()
                best = {
                    "stop": stop or head,
                    "distance": dist,
                    "latitude": lat,
                    "longitude": lon
                }
                best_dist = dist_val

        return best


    # ------------------- YOUR FUNCTION (UNCHANGED) -------------------
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
                    transit = self.resolve_transit_for_poi(clean(name), rows)
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
                if(last_meal_end>24*60):
                    last_meal_end-=24*60
                
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

    # ------------------- YOUR REQUESTED FUNCTION -------------------
    def build_plan_from_combined(self, combined, days):
        ref = deepcopy(combined or {})
        cities = ref.get("cities", [])

        for i, day in enumerate(days):
            self._build_poi_list_for_day(
                day=day,
                day_index=i,
                days=days,
                cities=cities
            )

        # PRINT ONLY POIs
        print("\n===== POI OUTPUT =====")
        for d in days:
            # if d.get('day')==3:
            print(f"Day {d.get('day')}: {d.get('point_of_interest_list','-')}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python poi_runner.py <query_number>")
        sys.exit(1)

    query_no = sys.argv[1]

    base = Path(
        "/scratch/sg/Vijay/TripCraft/output_agentic/agentic/qwen2.5/3day"
    ) / query_no

    tripcraft_path = base / "tripcraft_response.json"
    combined_path = base / "combined_reference.json"

    if not tripcraft_path.exists():
        raise FileNotFoundError(tripcraft_path)
    if not combined_path.exists():
        raise FileNotFoundError(combined_path)

    with open(tripcraft_path) as f:
        tripcraft = json.load(f)

    with open(combined_path) as f:
        combined = json.load(f)

    days = tripcraft.get("days", [])
    if not days:
        raise ValueError("No days found")

    builder = POIBuilder()
    builder.build_plan_from_combined(combined, days)


if __name__ == "__main__":
    main()
