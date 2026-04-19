# agentic_trip/agenticplanner.py
import json
from copy import deepcopy
import asyncio
from typing import Any, Dict, List, Optional, Tuple
import math
import statistics
import re

from agentic_trip_with_pro_cons_mistral.reference_refiner.refine_reference_json import refine_reference_json
from agentic_trip_with_pro_cons_mistral.agents.transportagent import TransportAgent
from agentic_trip_with_pro_cons_mistral.agents.accommodationagent import AccommodationAgent
from agentic_trip_with_pro_cons_mistral.agents.mealsagent import MealsAgent
from agentic_trip_with_pro_cons_mistral.agents.attractionagent import AttractionAgent
from agentic_trip_with_pro_cons_mistral.agents.eventsagent import EventAgent
from agentic_trip_with_pro_cons_mistral.agents.finalscheduleagent import FinalScheduleAgent
from agentic_trip_with_pro_cons_mistral.final_schedule_builder_dur import FinalScheduleBuilder
from agentic_trip_with_pro_cons_mistral.agents.non_agentic import FinalAgent


class AgenticPlanner:
    MAX_RETRIES = 3
    # How many times to retry an individual micro-agent (selective rerun)
    AGENT_RERUNS = 2

    # Dynamic negotiation controls
    DYN_MAX_ITERS = 4  # number of negotiation iterations
    DYN_SHRINK_MEALS_PCT = 0.20
    DYN_SHRINK_ACCOM_PCT = 0.10
    DYN_SHRINK_TRANSPORT_PCT = 0.15

    def __init__(self, dm=None, llm=None):
        self.dm = dm
        self.llm = llm
        self.final_agent: Optional[FinalScheduleAgent] = None

    def _retry(self, func, retries=None):
        # FIX: "retries or X" breaks when retries=0. We want explicit None-check.
        if retries is None:
            retries = self.MAX_RETRIES

        for _ in range(retries):
            try:
                res = func()
            except Exception as e:
                res = {"error": str(e)}

            if res and "error" not in res:
                return res

        return None
    
    def _retry_with_attempt(self, func, retries=3):
        last_res = None

        for attempt in range(1, retries + 1):
            try:
                res = func(attempt)
            except Exception as e:
                res = {"error": str(e)}

            last_res = res

            # stop early if success
            if res and "error" not in res:
                return res

        # FINAL fallback: return last attempt result
        return last_res



    # -----------------------
    # Budgeting helpers
    # -----------------------
    def _safe_float(self, v, default=0.0):
        try:
            if v is None:
                return float(default)
            return float(v)
        except Exception:
            try:
                return float(str(v).replace("$", "").strip())
            except Exception:
                return float(default)

    def _estimate_accommodation_total(self, accom_obj: Any, nights: int, people: int) -> float:
        """Estimate total accommodation cost for the trip given an accommodation object."""
        if not isinstance(accom_obj, dict):
            return 0.0
        # price per night field heuristics
        for k in ("price_per_night", "price", "avg_rate_per_night"):
            if k in accom_obj and accom_obj.get(k) not in (None, ""):
                p = self._safe_float(accom_obj.get(k), 0.0)
                # compute rooms needed using maximum occupancy if available
                max_occ = accom_obj.get("maximum_occupancy") or accom_obj.get("max_occupancy") or accom_obj.get("maximum occupancy") or accom_obj.get("max_guests") or 1 or accom_obj.get("max_occupancy") or accom_obj.get("maximum occupancy") or accom_obj.get("max_guests") or 1
                try:
                    occ = int(max_occ) if max_occ else 1
                except:
                    occ = 1
                rooms = math.ceil(max(1, people) / max(1, occ))
                return p * max(0, int(nights)) * rooms
        return 0.0

    def _estimate_transport_cost_from_agent(
        self, transport_res: Dict[str, Any], people: int
    ) -> float:
        """
        Transport cost estimation aligned EXACTLY with evaluation logic:
        - Flight: per person
        - Taxi: 1 taxi per 4 people
        - Self-driving: 1 car per 5 people
        """
        total = 0.0
        if not transport_res:
            return 0.0

        legs = transport_res.get("legs", [])
        if not isinstance(legs, list):
            return 0.0

        for leg in legs:
            mode = leg.get("mode")
            details = leg.get("details", {})

            if not isinstance(details, dict):
                continue

            # ✈️ Flight (per person)
            if mode == "flight" and "price" in details:
                price = self._safe_float(details.get("price"), 0.0)
                total += price * max(1, people)

            # 🚗 Self-driving (1 car per 5 people)
            elif mode == "self-driving" and "cost" in details:
                cost = self._safe_float(details.get("cost"), 0.0)
                cars = math.ceil(max(1, people) / 5)
                total += cost * cars

            # 🚕 Taxi (1 taxi per 4 people)
            elif mode == "taxi" and "cost" in details:
                cost = self._safe_float(details.get("cost"), 0.0)
                taxis = math.ceil(max(1, people) / 4)
                total += cost * taxis

        return round(total, 2)

    def _estimate_meals_total_from_restaurants_ranked(
        self, restaurants_ranked: List[Dict[str, Any]], people: int
    ) -> float:
        if not restaurants_ranked:
            return 0.0

        TOP_MEALS = 8  # fixed: 2 days → 8 meals

        costs = []
        for r in restaurants_ranked:
            if isinstance(r, dict):
                for k in ("avg_cost", "Average Cost", "estimated_cost", "price"):
                    if r.get(k) not in (None, ""):
                        costs.append(self._safe_float(r.get(k)))
                        break

        if not costs:
            return 20.0 * TOP_MEALS * max(1, people)

        # 🔒 SAFETY: sort only for calculation (original list untouched)
        highest_costs = sorted(costs, reverse=True)[:TOP_MEALS]

        return sum(highest_costs) * max(1, people)

    def _estimate_attractions_total(self, attractions_ranked: List[Dict[str, Any]], days: int) -> float:
        """Estimate attractions total: DIAGNOSTIC ONLY — not part of enforced budget."""
        if not attractions_ranked:
            return 0.0
        ticket_costs = []
        for a in attractions_ranked:
            if isinstance(a, dict):
                for k in ("ticket_price", "price", "estimated_cost"):
                    if a.get(k) not in (None, ""):
                        ticket_costs.append(self._safe_float(a.get(k)))
        if ticket_costs:
            return statistics.median(ticket_costs) * float(days) * 1.0
        return 0.0

    # -----------------------
    # Budget split algorithm (dynamic) — attractions excluded
    # -----------------------
    def _compute_dynamic_caps(
        self,
        total_budget: float,
        nights: int,
        people: int,
        accommodation_obj: Optional[Dict[str, Any]],
        restaurants_ranked: List[Dict[str, Any]],
        transport_est: float,
        meals_est: float
    ) -> Dict[str, float]:
        """
        Compute caps for transport and meals given already-estimated transport and meals costs.
        Accommodation is treated separately (we still estimate it if available).
        Attractions are intentionally excluded from budget caps.
        """
        total_budget = float(total_budget or 0.0)
        buffer_pct = 0.06  # 6% safety buffer
        buffer_amount = total_budget * buffer_pct
        usable_budget = max(0.0, total_budget - buffer_amount)

        # accommodation estimated total (if supplied)
        accom_est = self._estimate_accommodation_total(accommodation_obj, nights, people) if accommodation_obj else 0.0

        # remaining after accommodation (accom may change later)
        after_accom = max(0.0, usable_budget - accom_est)

        # If transport/meals already estimated, try to honor their estimates but allocate flexibly
        # We compute a conservative transport_cap = min(est_transport * 1.1, after_accom * 0.5)
        transport_cap = min(round(transport_est * 1.1, 2), round(after_accom * 0.6, 2))
        # meals cap is remaining after reserving transport (but ensure some minimum)
        remaining = max(0.0, after_accom - transport_cap)
        meals_cap_total = round(max(0.0, meals_est * 1.05), 2)
        # if meals_cap_total > remaining, clamp it to remaining; if it's small, give reasonable fraction
        if meals_cap_total > remaining:
            meals_cap_total = round(remaining, 2)
        else:
            # leave a bit of slack for accommodation adjustments
            pass

        # If accommodation wasn't provided, set an accommodation cap (e.g. 35% of usable budget) as hint
        if not accommodation_obj:
            accom_cap_total = round(usable_budget * 0.35, 2)
        else:
            accom_cap_total = round(accom_est, 2)

        caps = {
            "total_budget": round(total_budget, 2),
            "buffer_amount": round(buffer_amount, 2),
            "accom_cap_total": float(accom_cap_total),
            "transport_cap": float(max(0.0, transport_cap)),
            "meals_cap_total": float(max(0.0, meals_cap_total)),
            # attractions intentionally excluded from caps (diagnostic only)
            "attractions_cap_total": 0.0,
        }
        return caps

    # -----------------------
    # Utility: extract estimates (defensive)
    # -----------------------
    def _extract_agent_estimates(self, transport_res, acc_res, meals_res, attr_res, nights, people, restaurants_ranked, attractions_ranked):
        # accommodation
        accom_est = 0.0
        if acc_res and acc_res.get("hotel"):
            accom_est = self._estimate_accommodation_total(acc_res.get("hotel"), nights, people)

        # transport
        transport_est = 0.0
        if transport_res:
            if isinstance(transport_res, dict) and transport_res.get("estimated_cost") is not None:
                transport_est = self._safe_float(transport_res.get("estimated_cost"), 0.0)
            else:
                transport_est = self._estimate_transport_cost_from_agent(transport_res, people)

        # meals
        meals_est = 0.0
        ranked = meals_res.get("restaurants_ranked") if isinstance(meals_res, dict) and meals_res.get("restaurants_ranked") else restaurants_ranked
        meals_est = self._estimate_meals_total_from_restaurants_ranked(ranked or [], nights + 1, people)

        # attractions (diagnostic only)
        attr_est = 0.0
        ranked_a = attr_res.get("attractions_ranked") if isinstance(attr_res, dict) and attr_res.get("attractions_ranked") else attractions_ranked
        attr_est = self._estimate_attractions_total(ranked_a or [], nights + 1)

        # estimated_total used for budget logic = accom + transport + meals (NOT attractions)
        estimated_total = round(accom_est + transport_est + meals_est, 2)

        return {
            "accom_est": round(accom_est, 2),
            "transport_est": round(transport_est, 2),
            "meals_est": round(meals_est, 2),
            "attr_est": round(attr_est, 2),
            "estimated_total": estimated_total
        }

    # -----------------------
    # Main pipeline run (TRANSPORT -> MEALS -> ACCOMMODATION -> ATTRACTIONS)
    # Enhanced: dynamic negotiation loop between the three cost agents.
    # -----------------------
    async def run_full_pipeline(
        self,
        trip_json: Dict[str, Any],
        reference_json: Dict[str, Any] = None
    ) -> Dict[str, Any]:

        # ------------------------------------------------------------
        # BASIC INPUTS
        # ------------------------------------------------------------
        persona = trip_json.get("persona", {}) or {}
        local_constraints = trip_json.get("local_constraint", {}) or {}
        origin = trip_json.get("org")
        dates = trip_json.get("dates") or []
        people = int(trip_json.get("people_number", 1))
        total_budget = float(trip_json.get("budget") or 0.0)
        trip_days = int(trip_json["days"])
    

        transport_agent = TransportAgent(llm=self.llm)
        accommodation_agent = AccommodationAgent(llm=self.llm)
        meals_agent = MealsAgent(llm=self.llm)
        attraction_agent = AttractionAgent(llm=self.llm)
        event_agent = EventAgent(llm=self.llm)


        # ------------------------------------------------------------
        # 0️⃣ REFINE REFERENCE
        # ------------------------------------------------------------
        reference_json = refine_reference_json(reference_json or {})
        # print("Refined ",reference_json)

        all_cities = list(reference_json.get("cities", {}).keys())
        if not all_cities:
            return {"status": "error", "reason": "No cities found"}

        # ------------------------------------------------------------
        # CITY COUNT LOGIC
        # ------------------------------------------------------------
        if trip_days == 3:
            num_cities = 1
        elif trip_days == 5:
            num_cities = 2
        elif trip_days == 7:
            num_cities = 3
        else:
            num_cities = 1

        selected_cities = all_cities[:num_cities]
        nights_per_city = max(1, (trip_days - 1) // num_cities)
        # ------------------------------------------------------------
        # CITY → EVENT DATES (CORE LOGIC)
        # ------------------------------------------------------------
        city_event_dates = {}

        # Ignore last day (departure day)
        usable_dates = dates[:-1]

        idx = 0
        for city in selected_cities:
            city_event_dates[city] = usable_dates[idx: idx + 2]
            idx += 2


        remaining_budget = total_budget
        # print(city_event_dates)

        # ------------------------------------------------------------
        # 1️⃣ ACCOMMODATION — ALL CITIES FIRST
        # ------------------------------------------------------------
        city_accommodations = []

        for city in selected_cities:
            city_ref = reference_json["cities"][city]

            acc_res = self._retry(
                lambda: accommodation_agent.choose_accommodation(
                    city_ref, persona, trip_json, local_constraints,city
                ),
                retries=3
            )

            if not acc_res or "hotel" not in acc_res:
                return {"status": "error", "reason": f"Accommodation failed for {city}"}

            hotel = acc_res["hotel"]
            accom_cost = self._estimate_accommodation_total(
                hotel, nights_per_city, people
            )

            remaining_budget -= accom_cost
            if remaining_budget < 0:
                return {"status": "error", "reason": "Budget exhausted by accommodation"}

            city_accommodations.append({
                "city": city,
                "accommodation": hotel,
                "cost": accom_cost
            })
        # print(city_accommodations)
        # ------------------------------------------------------------
        # 2️⃣ RESERVE MEALS + TRANSPORT BUDGET
        # ------------------------------------------------------------
        meals_cap_total = remaining_budget * 0.15
        transport_cap = max(0.0, remaining_budget - meals_cap_total)
        # ------------------------------------------------------------
        # TRANSPORT DATES (LEG DATES)
        # ------------------------------------------------------------
        if trip_days == 3:
            travel_day_indices = [0, 2]
        elif trip_days == 5:
            travel_day_indices = [0, 2, 4]
        elif trip_days == 7:
            travel_day_indices = [0, 2, 4, 6]
        else:
            travel_day_indices = []

        travel_dates = [dates[i] for i in travel_day_indices]
        city_sequence = selected_cities


        # ------------------------------------------------------------
        # 3️⃣ TRANSPORT — GLOBAL (ONLY ONCE)
        # ------------------------------------------------------------
        transport_res = self._retry(
            lambda: transport_agent.choose_transport(
                reference_json["transportation"],
                persona,
                trip_json,
                people,
                city_sequence,
                travel_dates,
                local_constraints,
                caps={"transport_cap": transport_cap}
            ),
            retries=3
        )

        if not transport_res:
            return {"status": "error", "reason": "Transport failed"}

        transport_cost = self._estimate_transport_cost_from_agent(
            transport_res, people
        )
        # print(transport_res)

        remaining_budget -= transport_cost
        if remaining_budget < 0:
            return {"status": "error", "reason": "Budget exhausted by transport"}

        # ------------------------------------------------------------
        # 4️⃣ RESTAURANTS — ALL CITIES
        # ------------------------------------------------------------
        city_restaurants = []
        meals_cap_per_city = remaining_budget / num_cities

        for city in selected_cities:
            city_ref = reference_json["cities"][city]

            meals_res = self._retry(
                lambda: meals_agent.choose_restaurants(
                    city_ref,
                    persona,
                    trip_json,
                    local_constraints,
                    city,
                    caps={"meals_cap_total": meals_cap_per_city}
                ),
                retries=3
            ) 
            if not meals_res or not meals_res.get("restaurants_ranked"):
                raise Exception(f"MealsAgent failed for city {city}")

            city_restaurants.append({
                "city": city,
                "restaurants_ranked": meals_res.get("restaurants_ranked", [])
            })
        # print(city_restaurants)
        # ------------------------------------------------------------
        # 4️⃣.5️⃣ MEALS COST CALCULATION (
        # ------------------------------------------------------------
        total_meals_cost = 0.0

        for city_data in city_restaurants:
            city_meals_cost = self._estimate_meals_total_from_restaurants_ranked(
                city_data["restaurants_ranked"],
                people
            )
            total_meals_cost += city_meals_cost
        # print("Total meals cost estimated:", total_meals_cost)

        remaining_budget -= total_meals_cost

        # ------------------------------------------------------------
        # 5️⃣ ATTRACTIONS — ALL CITIES
        # ------------------------------------------------------------
        city_attractions = []

        for city in selected_cities:
            city_ref = reference_json["cities"][city]

            attr_res = self._retry(
                lambda: attraction_agent.choose_attractions(
                    city_ref, persona, trip_json, local_constraints,city
                ),
                retries=3
            )
            if not attr_res or not attr_res.get("attractions_ranked"):
                raise Exception(f"AttractionAgent failed for city {city}")

            city_attractions.append({
                "city": city,
                "attractions_ranked": attr_res.get("attractions_ranked", [])
            })
        # print(city_attractions)
        # ------------------------------------------------------------
        # 5️⃣.5️⃣ EVENTS — OPTIONAL, ALL CITIES
        # ------------------------------------------------------------
        city_events = []

        for city in selected_cities:
            city_ref = reference_json["cities"][city]
            # print(city_ref)

            # If no events for this city, skip safely
            if not city_ref.get("events"):
                city_events.append({
                    "city": city,
                    "events_ranked": []
                })
                continue

            event_dates = city_event_dates.get(city, [])
            # print(city_ref,event_dates)

            event_res = self._retry(
                lambda: event_agent.choose_events(
                    city_ref,
                    persona,
                    trip_json,
                    local_constraints,
                    city,
                    event_dates=event_dates   # 👈 THIS IS THE CHANGE
                ),
                retries=3
            )


            if not event_res:
                city_events.append({
                    "city": city,
                    "events_ranked": []
                })
            else:
                city_events.append({
                    "city": city,
                    "events_ranked": event_res.get("events", [])
                })
        # print(city_events)
        # ------------------------------------------------------------
        # 6️⃣ ACCOMMODATION RETRY (ONLY UPGRADE LOGIC)
        # ------------------------------------------------------------
        leftover = remaining_budget
        # print("Leftover budget before accommodation upgrade:", leftover)
        # print(city_accommodations)

        if leftover > 100 and selected_cities:
            per_city_upgrade_budget = leftover / len(selected_cities)

            for idx, city in enumerate(selected_cities):
                current_hotel = city_accommodations[idx]["accommodation"]
                current_cost = city_accommodations[idx]["cost"]

                # Each city has a STRICT upgrade cap
                upgrade_cap = current_cost + per_city_upgrade_budget

                upgraded_acc = self._retry(
                    lambda: accommodation_agent.choose_accommodation_upgrade(
                        persona=persona,
                        trip_json=trip_json,
                        local_constraints=local_constraints,
                        city=city,
                        current_hotel_name=current_hotel["name"],
                        leftover_budget=per_city_upgrade_budget,
                    ),
                    retries=1
                )

                # ---- SAFETY: if anything fails, KEEP OLD HOTEL ----
                if not upgraded_acc or not upgraded_acc.get("hotel"):
                    continue

                new_hotel = upgraded_acc["hotel"]
                new_cost = self._estimate_accommodation_total(
                    new_hotel, nights_per_city, people
                )

                # ---- STRICT VALIDATION ----
                if new_cost <= current_cost:
                    continue

                if new_cost > upgrade_cap:
                    continue

                # ---- APPLY UPGRADE ----
                city_accommodations[idx]["accommodation"] = new_hotel
                city_accommodations[idx]["cost"] = new_cost

                leftover -= (new_cost - current_cost)

                if leftover <= 0:
                    break

        remaining_budget = leftover

        # ------------------------------------------------------------
        # 7️⃣ BUILD FINAL CITY OBJECTS
        # ------------------------------------------------------------
        final_cities = []

        for city in selected_cities:
            final_cities.append({
                "city": city,
                "days": nights_per_city + 1,
                "accommodation": next(
                    x["accommodation"] for x in city_accommodations if x["city"] == city
                ),
                "restaurants_ranked": next(
                    x["restaurants_ranked"] for x in city_restaurants if x["city"] == city
                ),
                "attractions_ranked": next(
                    x["attractions_ranked"] for x in city_attractions if x["city"] == city
                ),
                "events_ranked": next(
                    x["events_ranked"] for x in city_events if x["city"] == city
                ),
               "raw_transit_rows": city_ref.get("raw_transit_rows", [])
            })

        # ------------------------------------------------------------
        # 8️⃣ FINAL OUTPUT
        # ------------------------------------------------------------
        combined = {
            "transportation": transport_res,
            "cities": final_cities,
            "origin": origin,
            "dates": dates,
            "people_number": people,
            "budget": total_budget,
            "persona": persona,
            "constraints": local_constraints
        }
        # print("Combined data sent to schedulers:",combined)

        # final_agent = FinalScheduleAgent(llm=self.llm)
        # llm_raw = self._retry_with_attempt(
        #     lambda attempt: final_agent.generate_final_schedule_from_structured_input(
        #         combined,
        #         trip_json.get("query", ""),
        #         retry_attempt=attempt
        #     ),
        #     retries=3
        # )
        USE_LLM_FINAL = True

        if USE_LLM_FINAL:
            final_agent = FinalScheduleAgent(llm=self.llm)
            llm_raw = self._retry_with_attempt(
                lambda attempt: final_agent.generate_final_schedule_from_structured_input(
                    combined,
                    trip_json.get("query", ""),
                    retry_attempt=attempt
                ),
                retries=3
            )
        else:
            llm_raw = None

        # print(llm_raw)

        scheduler = FinalScheduleBuilder(persona=persona)
        manual_plan = scheduler.build_plan_from_combined(combined,)

        # non_agentic = FinalAgent(llm=self.llm)
        # non_agentic_plan = non_agentic.generate_final_schedule(structured_input=combined,query=trip_json.get("query",""))

        return {
            "status": "ok",
            "combined_reference": combined,
            "llm_raw": llm_raw,
            "manual_plan": manual_plan,
            # "non_agentic_plan": non_agentic_plan
        }
