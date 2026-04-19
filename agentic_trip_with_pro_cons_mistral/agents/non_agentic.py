# agentic_trip/agents/non_agentic.py
import json
import re
import os
from typing import Any, Dict, List, Optional
import copy
from pathlib import Path

def travel_plan_text_to_json(text: str) -> dict:
    days = []

    # Split into day blocks
    blocks = re.split(r"\nDay\s+(\d+):\s*", text)
    blocks = blocks[1:]  # drop header

    for i in range(0, len(blocks), 2):
        day_number = int(blocks[i])
        block = blocks[i + 1]

        def extract(field):
            m = re.search(rf"{field}:\s*(.+)", block)
            return m.group(1).strip() if m else "-"

        day = {
            "day": day_number,
            "current_city": extract("Current City"),
            "transportation": extract("Transportation"),
            "breakfast": extract("Breakfast"),
            "attraction": extract("Attraction"),
            "lunch": extract("Lunch"),
            "dinner": extract("Dinner"),
            "accommodation": extract("Accommodation"),
            "event": extract("Event"),
            "point_of_interest_list": extract("Point of Interest List"),
        }

        days.append(day)

    return {"days": days}

PLANNER_INSTRUCTION_PARAMETER_INFO_7DAY = """You are a proficient planner. Based on the provided information, query and persona, please give a detailed travel plan, including specifics such as flight numbers (e.g., F0123456), restaurant names, and accommodation names. Note that all the information in your plans should be derived from the provided data. You must adhere to the format given in the example. Additionally, all details should align with common sense. The symbol '-' indicates that information is unnecessary. For example, in the provided sample, you do not need to plan after returning to the departure city. When you travel to two cities in one day, you should note it in the "Current City" section as in the example (i.e., from A to B). Include events happening on that day, if any. Provide a Point of Interest List, which is an ordered list of places visited throughout the day. This list should include accommodations, attractions, or restaurants and their starting and ending timestamps. Each day must start and end with the accommodation where the traveler is staying. Breakfast is ideally scheduled at 9:40 AM and lasts about 50 minutes. Lunch is best planned for 2:20 PM, with a duration of around an hour. Dinner should take place at 8:45 PM, lasting approximately 1 hour and 15 minutes. Laidback Travelers typically explore one attraction per day and sometimes opt for more, while Adventure Seekers often visit 2 or 3 attractions, occasionally exceeding that number.
 
****** Example ******  

Query: Could you create a travel plan for 7 people from Ithaca to Charlotte spanning 3 days, from March 8th to March 14th, 2022, with a budget of $30,200?  
Traveler Persona:
Traveler Type: Laidback Traveler;
Purpose of Travel: Relaxation;
Spending Preference: Economical Traveler;
Location Preference: Beaches
  
Travel Plan:  
Day 1:
Current City: from Milwaukee to Greensboro
Transportation: Self-driving, Duration: 940.56 mins, Distance: 1301.4765 km, Estimated Cost: $65.07
Breakfast: -
Attraction: -
Lunch: -
Dinner: -
Accommodation: The Stratford Guesthouse, Greensboro
Event: -
Point of Interest List:The Stratford Guesthouse, stay from 22:00 to 09:00, nearest transit: Battleground@McDonalds, 197.62m away.

Day 2:
Current City: Greensboro
Transportation: -
Breakfast: Chez Genese, Greensboro
Attraction: Greensboro Coliseum Complex, Greensboro; Antique Market Place, Greensboro
Lunch: Lucky 32 Southern Kitchen, Greensboro
Dinner: At Elm St Grill, Greensboro
Accommodation: The Stratford Guesthouse, Greensboro
Event: -
Point of Interest List:The Stratford Guesthouse, stay from 09:00 to 10:00, nearest transit: Battleground@McDonalds, 197.62m away; Chez Genese, visit from 10:30 to 11:00, nearest transit: Elm/Lewis, 86.23m away; Greensboro Coliseum Complex, visit from 12:00 to 14:00, nearest transit: Gate City Blvd/Chapman, 246.81m away; Lucky 32 Southern Kitchen, visit from 15:00 to 15:30, nearest transit: Westover Ave/Lucky 32, 53.35m away; Antique Market Place, visit from 16:30 to 19:00, nearest transit: Swing Rd/Swing Court, 3568.71m away; At Elm St Grill, visit from 20:00 to 21:30, nearest transit: Elm/Pisgah Church Road, 186.31m away; The Stratford Guesthouse, stay from 22:00 to 08:00, nearest transit: Battleground@McDonalds, 197.62m away.

Day 3:
Current City: from Greensboro to Wilmington
Transportation: Self-driving from Greensboro to Wilmington, Duration: 238.51 mins, Distance: 334.28 km, Estimated Cost: $16.71
Breakfast: Stamey's Barbecue, Greensboro
Attraction: Tanger Family Bicentennial Garden, Greensboro
Lunch: -
Dinner: Elijah's Restaurant, Wilmington
Accommodation: Clarity at The Cove, Wilmington
Event: -
Point of Interest List:The Stratford Guesthouse, stay from 08:00 to 08:30, nearest transit: Battleground@McDonalds, 197.62m away; Stamey's Barbecue, visit from 09:30 to 10:30, nearest transit: Gate City/Patterson, 46.58m away; Tanger Family Bicentennial Garden, visit from 11:00 to 12:30, nearest transit: West Friendly/Hobbs, 685.91m away; Circa 1922, visit from 13:00 to 14:00, nearest transit: Front St SB at Market St, 33.43m away; Elijah's Restaurant, visit from 20:30 to 22:00, nearest transit: Front St SB at Ann St, 93.74m away; Clarity at The Cove, stay from 23:00 to 08:00, nearest transit: Nutt St SB at Convention Center, 160.95m away.

Day 4:
Current City: Wilmington
Transportation: -
Breakfast: Casey's Buffet Barbecue & Home Cookin, Wilmington
Attraction: Sea Turtle Camp, Wilmington; Riverwalk, Wilmington; Henrietta III, Wilmington
Lunch: The George on the Riverwalk, Wilmington
Dinner: Pilot House, Wilmington
Accommodation: Clarity at The Cove, Wilmington
Event: -
Point of Interest List:Clarity at The Cove, stay from 08:00 to 09:00, nearest transit: Nutt St SB at Convention Center, 160.95m away; Casey's Buffet Barbecue & Home Cookin, visit from 09:30 to 10:00, nearest transit: Oleander Dr EB at Dogwood Ln, 157.69m away; Sea Turtle Camp, visit from 11:00 to 13:00, nearest transit: Gordon Rd WB at Military Cutoff Rd, 1499.62m away; The George on the Riverwalk, visit from 14:30 to 15:00, nearest transit: Front St SB at Orange St, 85.08m away; Riverwalk, visit from 16:00 to 18:00, nearest transit: Front St SB at Market St, 105.98m away; Henrietta III, visit from 18:30 to 20:00, nearest transit: Front St SB at Orange St, 148.70m away; Pilot House, visit from 20:30 to 22:00, nearest transit: Front St SB at Ann St, 112.21m away; Clarity at The Cove, stay from 23:00 to 08:00, nearest transit: Nutt St SB at Convention Center, 160.95m away.

Day 5:
Current City: from Wilmington to Charlotte
Transportation: Self-driving, Duration: 245.71 mins, Distance: 318.6171 km, Estimated Cost: $15.93
Breakfast: Roko Italian Cuisine, Wilmington
Attraction: Bellamy Mansion, Wilmington
Lunch: Winnie's Tavern, Wilmington
Dinner: Rooster's Wood-Fired Kitchen - Uptown, Charlotte
Accommodation: Tippah Treehouse Retreat, Charlotte
Event: -
Point of Interest List:Clarity at The Cove, stay from 08:00 to 09:00, nearest transit: Nutt St SB at Convention Center, 160.95m away; Roko Italian Cuisine, visit from 09:30 to 10:00, nearest transit: Military Cutoff Rd NB at Drysdale Dr, 407.21m away; Bellamy Mansion, visit from 11:00 to 13:00, nearest transit: Market St WB at 4th St, 135.15m away; Winnie's Tavern, visit from 14:30 to 15:00, nearest transit: Carolina Beach Rd SB at North Carolina Ave, 552.62m away; Rooster's Wood-Fired Kitchen - Uptown, visit from 21:00 to 22:00, nearest transit: Trade St & College St, 139.39m away; Tippah Treehouse Retreat, stay from 23:00 to 08:00, nearest transit: The Plaza & Marguerite Ave, 381.54m away.

Day 6:
Current City: Charlotte
Transportation: -
Breakfast: Mert's Heart and Soul, Charlotte
Attraction: Levine Museum of the New South, Charlotte; Truist Field, Charlotte; Wing Haven, Charlotte
Lunch: The Capital Grille, Charlotte
Dinner: The Fig Tree Restaurant, Charlotte
Accommodation: Tippah Treehouse Retreat, Charlotte
Event: -
Point of Interest List:Tippah Treehouse Retreat, stay from 08:00 to 09:00, nearest transit: The Plaza & Marguerite Ave, 381.54m away; Mert's Heart and Soul, visit from 09:30 to 10:00, nearest transit: College St & 6th St, 64.34m away; Levine Museum of the New South, visit from 11:00 to 13:00, nearest transit: Tryon St & 2nd St, 38.18m away; The Capital Grille, visit from 14:00 to 14:30, nearest transit: Tryon St & 6th St, 103.97m away; Truist Field, visit from 15:00 to 17:30, nearest transit: 4th St & Graham St, 146.25m away; Wing Haven, visit from 18:30 to 20:30, nearest transit: Selwyn Ave & Sterling Rd, 345.69m away; The Fig Tree Restaurant, visit from 21:30 to 22:30, nearest transit: 7th St & Armory Dr, 103.61m away; Tippah Treehouse Retreat, stay from 23:00 to 06:00, nearest transit: The Plaza & Marguerite Ave, 381.54m away.

Day 7:
Current City: from Charlotte to Milwaukee
Transportation: Self-driving, Duration: 979.69 mins, Distance: 1344.2727 km, Estimated Cost: $67.21
Breakfast: -
Attraction: -
Lunch: -
Dinner: -
Accommodation: Tippah Treehouse Retreat, Charlotte
Event: -
Point of Interest List:Tippah Treehouse Retreat, stay from 06:00 to 06:30, nearest transit: The Plaza & Marguerite Ave, 381.54m away.

****** Example Ends ******
***Output must match the example format exactly, in plain text only (no JSON)***
***Output must match the example format exactly, in plain text only (no JSON). All timings must be strictly respected. Once the traveler departs from a city, no further activities are allowed in that city. Activities in the destination city are permitted only after arrival.***
Given information: {text}
Query: {query}
Traveler Persona:
{persona}
Output: """


PLANNER_INSTRUCTION_PARAMETER_INFO_5DAY = """You are a proficient planner. Based on the provided information, query and persona, please give a detailed travel plan, including specifics such as flight numbers (e.g., F0123456), restaurant names, and accommodation names. Note that all the information in your plans should be derived from the provided data. You must adhere to the format given in the example. Additionally, all details should align with common sense. The symbol '-' indicates that information is unnecessary. For example, in the provided sample, you do not need to plan after returning to the departure city. When you travel to two cities in one day, you should note it in the "Current City" section as in the example (i.e., from A to B). Include events happening on that day, if any. Provide a Point of Interest List, which is an ordered list of places visited throughout the day. This list should include accommodations, attractions, or restaurants and their starting and ending timestamps. Each day must start and end with the accommodation where the traveler is staying. Breakfast is ideally scheduled at 9:40 AM and lasts about 50 minutes. Lunch is best planned for 2:20 PM, with a duration of around an hour. Dinner should take place at 8:45 PM, lasting approximately 1 hour and 15 minutes. Laidback Travelers typically explore one attraction per day and sometimes opt for more, while Adventure Seekers often visit 2 or 3 attractions, occasionally exceeding that number.
 
****** Example ******  

Query: Could you create a travel plan for 7 people from Ithaca to Charlotte spanning 3 days, from March 8th to March 14th, 2022, with a budget of $30,200?  
Traveler Persona:
Traveler Type: Laidback Traveler;
Purpose of Travel: Relaxation;
Spending Preference: Economical Traveler;
Location Preference: Beaches
  
Travel Plan:  
Day 1:
Current City: from New York to Wilmington
Transportation: Flight Number: F3198598, from New York to Wilmington, Departure Time: 08:37, Arrival Time: 10:13
Breakfast: -
Attraction: Jungle Rapids Family Fun Park, Wilmington; The Cotton Exchange, Wilmington
Lunch: Savorez, Wilmington
Dinner: Roko Italian Cuisine, Wilmington
Accommodation: The Zen Den - A quaint Private Oasis room w/ Bath, Wilmington
Event: -
Point of Interest List:The Zen Den - A quaint Private Oasis room w/ Bath, stay from 11:00 to 11:30, nearest transit: Market St WB at 12th St, 326.90m away; Jungle Rapids Family Fun Park, visit from 12:30 to 01:30, nearest transit: Oleander Dr EB at Hawthorne Dr, 165.14m away; Savorez, visit from 14:00 to 14:45, nearest transit: 4th St SB at Chestnut St, 39.22m away; The Cotton Exchange, visit from 16:00 to 19:00, nearest transit: Front St NB at Grace St, 73.32m away; Roko Italian Cuisine, visit from 19:30 to 20:15, nearest transit: Military Cutoff Rd NB at Drysdale Dr, 407.21m away; The Zen Den - A quaint Private Oasis room w/ Bath, stay from 20:30 to 09:00, nearest transit: Market St WB at 12th St, 326.90m away.

Day 2:
Current City: Wilmington
Transportation: -
Breakfast: The Basics, Wilmington
Attraction: Cameron Art Museum, Wilmington; Downtown Wilmington, Wilmington
Lunch: Szechuan 132, Wilmington
Dinner: Casey's Buffet Barbecue & Home Cookin, Wilmington
Accommodation: The Zen Den - A quaint Private Oasis room w/ Bath, Wilmington
Event: -
Point of Interest List:The Zen Den - A quaint Private Oasis room w/ Bath, stay from 09:00 to 10:00, nearest transit: Market St WB at 12th St, 326.90m away; The Basics, visit from 10:30 to 11:30, nearest transit: Front St NB at Grace St, 96.37m away; Cameron Art Museum, visit from 12:00 to 15:00, nearest transit: 17th St NB at Independence Blvd (CAM), 185.73m away; Szechuan 132, visit from 15:30 to 16:00, nearest transit: College Rd SB at Randall Pkwy, 115.10m away; Downtown Wilmington, visit from 17:00 to 19:00, nearest transit: Front St SB at Chestnut St, 66.26m away; Casey's Buffet Barbecue & Home Cookin, visit from 21:00 to 21:30, nearest transit: Oleander Dr EB at Dogwood Ln, 157.69m away; The Zen Den - A quaint Private Oasis room w/ Bath, stay from 22:00 to 09:00, nearest transit: Market St WB at 12th St, 326.90m away.

Day 3:
Current City: from Wilmington to Charlotte
Transportation: Flight Number: F2171134, from Wilmington to Charlotte, Departure Time: 12:48, Arrival Time: 14:09
Breakfast: Elijah's Restaurant, Wilmington
Attraction: Riverwalk, Wilmington
Lunch: -
Dinner: Cabo Fish Taco Baja Seagrill, Charlotte
Accommodation: Comfy private bed and bath, Charlotte
Event: -
Point of Interest List:
The Zen Den - A quaint Private Oasis room w/ Bath, stay from 09:00 to 09:30, nearest transit: Market St WB at 12th St, 326.90m away; Elijah's Restaurant, visit from 10:00 to 10:30, nearest transit: Front St SB at Ann St, 93.74m away; Riverwalk, visit from 11:00 to 12:00, nearest transit: Front St SB at Market St, 105.98m away; Comfy private bed and bath, stay from 15:00 to 18:30, nearest transit: The Plaza & Glenfiddich Dr, 419.92m away; Cabo Fish Taco Baja Seagrill, visit from 19:00 to 20:30, nearest transit: Davidson & 35th, 57.25m away; Comfy private bed and bath, stay from 21:00 to 09:00, nearest transit: The Plaza & Glenfiddich Dr, 419.92m away.

Day 4:
Current City: Charlotte
Transportation: -
Breakfast: The Fig Tree Restaurant, Charlotte
Attraction: Levine Museum of the New South, Charlotte; NASCAR Hall of Fame, Charlotte
Lunch: The Capital Grille, Charlotte
Dinner: Pinky's Westside Grill, Charlotte
Accommodation: Comfy private bed and bath, Charlotte
Event: -
Point of Interest List:Comfy private bed and bath, stay from 09:00 to 09:30, nearest transit: The Plaza & Glenfiddich Dr, 419.92m away; The Fig Tree Restaurant, visit from 10:00 to 10:30, nearest transit: 7th St & Armory Dr, 103.61m away; Levine Museum of the New South, visit from 11:30 to 14:00, nearest transit: Tryon St & 2nd St, 38.18m away; The Capital Grille, visit from 14:30 to 15:30, nearest transit: Tryon St & 6th St, 103.97m away; NASCAR Hall of Fame, visit from 16:00 to 18:30, nearest transit: Caldwell St & 3rd St, 96.74m away; Pinky's Westside Grill, visit from 19:30 to 21:30, nearest transit: Morehead St & Grandin Rd, 166.98m away; Comfy private bed and bath, stay from 22:00 to 09:00, nearest transit: The Plaza & Glenfiddich Dr, 419.92m away.

Day 5:
Current City: from Charlotte to New York
Transportation: Flight Number: F0167255, from Charlotte to New York, Departure Time: 13:27, Arrival Time: 15:11
Breakfast: Mac's Speed Shop, Charlotte
Attraction: Discovery Place Science, Charlotte
Lunch: -
Dinner: -
Accommodation: -
Event: -
Point of Interest List:Comfy private bed and bath, stay from 09:00 to 09:30, nearest transit: The Plaza & Glenfiddich Dr, 419.92m away; Mac's Speed Shop, visit from 10:00 to 10:30, nearest transit: New Bern Station, 544.51m away; Discovery Place Science, visit from 11:00 to 12:30, nearest transit: Church St & 6th St, 53.42m away.

****** Example Ends ******
***Output must match the example format exactly, in plain text only (no JSON)***
***Output must match the example format exactly, in plain text only (no JSON). All timings must be strictly respected. Once the traveler departs from a city, no further activities are allowed in that city. Activities in the destination city are permitted only after arrival.***
Given information: {text}
Query: {query}
Traveler Persona:
{persona}
Output: """

PLANNER_INSTRUCTION_PARAMETER_INFO_3DAY = """You are a proficient planner. Based on the provided information, query and persona, please give a detailed travel plan, including specifics such as flight numbers (e.g., F0123456), restaurant names, and accommodation names. Note that all the information in your plans should be derived from the provided data. You must adhere to the format given in the example. Additionally, all details should align with common sense. The symbol '-' indicates that information is unnecessary. For example, in the provided sample, you do not need to plan after returning to the departure city. When you travel to two cities in one day, you should note it in the "Current City" section as in the example (i.e., from A to B). Include events happening on that day, if any. Provide a Point of Interest List, which is an ordered list of places visited throughout the day. This list should include accommodations, attractions, or restaurants and their starting and ending timestamps. Each day must start and end with the accommodation where the traveler is staying. Breakfast is ideally scheduled at 9:40 AM and lasts about 50 minutes. Lunch is best planned for 2:20 PM, with a duration of around an hour. Dinner should take place at 8:45 PM, lasting approximately 1 hour and 15 minutes. Laidback Travelers typically explore one attraction per day and sometimes opt for more, while Adventure Seekers often visit 2 or 3 attractions, occasionally exceeding that number.
 
****** Example ******  

Query: Could you create a travel plan for 7 people from Ithaca to Charlotte spanning 3 days, from March 8th to March 14th, 2022, with a budget of $30,200?  
Traveler Persona:
Traveler Type: Laidback Traveler;
Purpose of Travel: Relaxation;
Spending Preference: Economical Traveler;
Location Preference: Beaches
  
Travel Plan:  
Day 1:  
Current City: from Ithaca to Charlotte  
Transportation: Flight Number: F3633413, from Ithaca to Charlotte, Departure Time: 05:15, Arrival Time: 07:28  
Breakfast: Nagaland's Kitchen, Charlotte  
Attraction: The Charlotte Museum of History, Charlotte  
Lunch: Cafe Maple Street, Charlotte
Dinner: Bombay Vada Pav, Charlotte
Accommodation: Affordable Spacious Refurbished Room in Bushwick!, Charlotte
Event: -  
Point of Interest List: Affordable Spacious Refurbished Room in Bushwick!, stay from 08:00 to 08:30, nearest transit: Bushwick Stop, 100m away; Nagaland's Kitchen, visit from 09:00 to 09:45, nearest transit: Uptown Station, 200m away; The Charlotte Museum of History, visit from 10:30 to 13:30, nearest transit: Museum Station, 300m away; Cafe Maple Street, visit from 14:00 to 15:00, nearest transit: Maple Avenue Stop, 100m away; Bombay Vada Pav, visit from 19:00 to 20:00, nearest transit: Bombay Stop, 150m away; Affordable Spacious Refurbished Room in Bushwick!, stay from 21:00 to 07:00, nearest transit: Bushwick Stop, 100m away.  

Day 2:  
Current City: Charlotte  
Transportation: -  
Breakfast: Olive Tree Cafe, Charlotte  
Attraction: The Mint Museum, Charlotte; Romare Bearden Park, Charlotte  
Lunch: Birbal Ji Dhaba, Charlotte  
Dinner: Pind Balluchi, Charlotte  
Accommodation: Affordable Spacious Refurbished Room in Bushwick!, Charlotte  
Event: -  
Point of Interest List: Affordable Spacious Refurbished Room in Bushwick!, stay from 07:00 to 08:30, nearest transit: Bushwick Stop, 100m away; Olive Tree Cafe, visit from 09:00 to 09:45, nearest transit: Cafe Station, 250m away; The Mint Museum, visit from 10:30 to 13:00, nearest transit: Mint Stop, 200m away; Birbal Ji Dhaba, visit from 14:00 to 15:30, nearest transit: Dhaba Stop, 120m away; Romare Bearden Park, visit from 16:00 to 18:00, nearest transit: Park Stop, 150m away; Pind Balluchi, visit from 19:30 to 21:00, nearest transit: Pind Stop, 150m away; Affordable Spacious Refurbished Room in Bushwick!, stay from 21:30 to 07:00, nearest transit: Bushwick Stop, 100m away.  

Day 3:  
Current City: from Charlotte to Ithaca  
Transportation: Flight Number: F3786167, from Charlotte to Ithaca, Departure Time: 21:42, Arrival Time: 23:26  
Breakfast: Subway, Charlotte  
Attraction: Books Monument, Charlotte  
Lunch: Olive Tree Cafe, Charlotte  
Dinner: Kylin Skybar, Charlotte  
Accommodation: -  
Event: -  
Point of Interest List: Affordable Spacious Refurbished Room in Bushwick!, stay from 07:00 to 08:30, nearest transit: Bushwick Stop, 100m away; Subway, visit from 09:00 to 10:00, nearest transit: Subway Station, 150m away; Books Monument, visit from 10:30 to 13:30, nearest transit: Central Library Stop, 200m away; Olive Tree Cafe, visit from 14:00 to 15:00, nearest transit: Cafe Station, 250m away; Kylin Skybar, visit from 19:00 to 20:00, nearest transit: Skybar Stop, 180m away.  

****** Example Ends ******
***Output must match the example format exactly, in plain text only (no JSON)***
***Output must match the example format exactly, in plain text only (no JSON). All timings must be strictly respected. Once the traveler departs from a city, no further activities are allowed in that city. Activities in the destination city are permitted only after arrival.***
Given information: {text}
Query: {query}
Traveler Persona:
{persona}
Output: """

class FinalAgent:
    def __init__(self, llm):
        self.llm = llm

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

    def build_prompt(self, reference_json, trip_json, n_days: int) -> str:
        ref_str = json.dumps(reference_json, indent=2)
        persona_str = json.dumps(reference_json.get("persona", ""), indent=2)
        q = reference_json.get("query", "")
        prompt = PLANNER_INSTRUCTION_PARAMETER_INFO_7DAY if n_days == 7 else PLANNER_INSTRUCTION_PARAMETER_INFO_5DAY if n_days ==5 else PLANNER_INSTRUCTION_PARAMETER_INFO_3DAY
        prompt = prompt.replace("{text}", ref_str)
        prompt = prompt.replace("{query}", trip_json)
        prompt = prompt.replace("{persona}", persona_str)
        return prompt
     
    # -------------------------
    # Main entry
    # -------------------------
    def generate_final_schedule(
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
        # 5. LLM PROMPT (LLM FILLS MEALS + ATTRACTIONS ONLY)
        # ------------------------------------------------------------
        prompt = self.build_prompt(structured_input, query,n_days)
        # debug_dir = Path("/scratch/sg/Vijay/TripCraft/debug/poi_llm")
        # debug_dir.mkdir(parents=True, exist_ok=True)
        raw = self.llm.generate(prompt)
        # print("Response:",raw)
        # debug_file = debug_dir / f"day_1_full.txt"
        # with open(debug_file, "w") as f:
        #     f.write("========== PROMPT ==========\n\n")
        #     f.write(prompt)
        #     f.write("\n\n========== RESPONSE ==========\n\n")
        #     f.write(raw)
        # parsed = self._extract_json(raw)
        parsed = travel_plan_text_to_json(raw)
        # print(json.dumps(parsed, indent=2))
        return parsed
