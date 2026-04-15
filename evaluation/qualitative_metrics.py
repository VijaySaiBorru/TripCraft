import json
import pandas as pd
import numpy as np
import torch
from transformers import BertTokenizer, BertModel
from sklearn.metrics.pairwise import cosine_similarity
import math
import numpy as np
from scipy.stats import multivariate_normal, poisson
import argparse


# Load the cleaned attractions data
import os, sys
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_DIR = os.path.join(BASE_DIR, "TripCraft_database")

attractions_data = pd.read_csv(
    os.path.join(DB_DIR, "attraction", "cleaned_attractions_final.csv")
)


def get_mu_d_type(attraction, city, attractions_data):
    """
    Get the visit duration (mu_d_type) for a given attraction and city.

    Args:
        attraction (str): The name of the attraction.
        city (str): The city of the attraction.
        attractions_data (pd.DataFrame): DataFrame containing attraction information.

    Returns:
        float: The visit duration (mu_d_type) for the matching attraction and city.
    """
    # Filter rows that match both the attraction name and city
    match = attractions_data[
        (attractions_data["City"].str.strip().str.lower() == city.strip().lower()) &
        (attractions_data["name"].str.strip().str.lower() == attraction.strip().lower())
    ]
    
    # If a match is found, return the visit duration
    if not match.empty:
        return int(match.iloc[0]["visit_duration"])
    else:
        # Handle the case where no match is found (default or raise an error)
        raise ValueError(f"No matching entry found for attraction '{attraction}' in city '{city}'.")

def get_bert_embedding(text, tokenizer, model):
    """Encodes text into a BERT embedding."""
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state.mean(dim=1).squeeze(0).numpy()


def compute_persona_score(travel_plan, bert_model, bert_tokenizer):
    """Compute the persona score for the travel plan."""
    # Extract persona details
    persona = travel_plan["JSON"].get("persona", "")

    persona_components = {
        "Traveler Type": None,
        "Purpose of Travel": None,
        "Spending Preference": None,
        "Location Preference": None
    }

    for key in persona_components.keys():
        start_idx = persona.find(key + ":") + len(key) + 1
        end_idx = persona.find(";", start_idx)
        if end_idx == -1:  # Last component
            end_idx = len(persona)
        persona_components[key] = persona[start_idx:end_idx].strip()

    # Encode persona components
    persona_embeddings = {
        key: get_bert_embedding(value, bert_tokenizer, bert_model)
        for key, value in persona_components.items()
    }

    # Initialize counters
    total_score = 0
    total_pois = 0

    # Iterate through all days in the plan
    for day in travel_plan["plan"]:
        poi_list = day["point_of_interest_list"].split(";")
        # all_events = day["event"].split(";")

        for poi in poi_list:
            # Extract PoI name (up to first comma)
            # poi_name = poi.split(",")[0].strip()
            if "stay" in poi:
                poi_name = poi.split("stay")[0].strip()[:-1]
            else:
                poi_name = poi.split("visit")[0].strip()[:-1]

            poi_embedding = get_bert_embedding(poi_name, bert_tokenizer, bert_model)

            # Compute similarity for each persona component
            poi_score = 0
            for key, persona_embedding in persona_embeddings.items():
                poi_score += cosine_similarity([persona_embedding], [poi_embedding])[0][0]

            # Average similarity over persona components
            poi_score /= len(persona_components)

            # Add to total score and increment counter
            total_score += poi_score
            total_pois += 1

    # Final persona score (average over all PoIs)
    avg_persona_score = total_score / total_pois if total_pois > 0 else 0

    return avg_persona_score

def calculate_persona_score(travel_plan):
    persona = travel_plan.get("JSON", {}).get("persona", "")
    if not persona:
        return -1
    tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")
    model = BertModel.from_pretrained("bert-base-uncased")
    return compute_persona_score(travel_plan, model, tokenizer)


# Function to calculate Weighted Edit Distance (WED)
def calculate_wed(gen_sequence, anno_sequence, weight_fn):
    m, n = len(gen_sequence), len(anno_sequence)
    dp = np.full((m + 1, n + 1), np.inf)  # Initialize the DP matrix
    dp[0][0] = 0  # Base case: no cost for empty sequences
    
    # Fill DP table with the edit distance calculation
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = weight_fn(gen_sequence[i - 1], anno_sequence[j - 1])
            dp[i][j] = cost + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    return dp[m][n]

# Define a basic weight function for cost calculation
def weight_fn(a, b):
    if a == b:
        return 0
    if {a, b} == {"x", "y"} or {a, b} == {"y", "z"} or {a, b} == {"x", "z"}:
        return 1  # Unweighted ED # Mismatched types with high cost
    return 1  # Default cost for other mismatches

def get_poi_sequence(plan_day):
    poi_list = plan_day["point_of_interest_list"]
    
    # Extract names from the relevant fields using rsplit to get rid of extra details
    accommodation = plan_day.get("accommodation", "").rsplit(",", 1)[0].strip()
    breakfast = plan_day.get("breakfast", "").rsplit(",", 1)[0].strip()
    lunch = plan_day.get("lunch", "").rsplit(",", 1)[0].strip()
    dinner = plan_day.get("dinner", "").rsplit(",", 1)[0].strip()
    # attractions_list = [attraction.rsplit(",", 1)[0].strip() for attraction in plan_day.get("attraction", "").split(";")]

    seq = []
    
    # Split the poi_list into items based on semicolons
    for poi in poi_list.split(";"):
        if breakfast in poi:
            seq.append("y")  # Restaurant (breakfast)
        elif lunch in poi:
            seq.append("y")  # Restaurant (lunch)
        elif dinner in poi:
            seq.append("y")  # Restaurant (dinner)
        elif accommodation in poi:
            seq.append("x")  # Accommodation
        else:
            seq.append("z")  # Attraction
    
    return seq


# Function to calculate average WED over days in the travel plan
def calculate_ordering_score(travel_plan, gen_travel_plan):
    if len(travel_plan["plan"]) < 3 or len(gen_travel_plan["plan"]) < 3:
        return -1

    total_wed = 0
    num_days = len(travel_plan["plan"])

    for day in travel_plan["plan"][:2]:  # First 2 days of travel_plan
        for day_dash in gen_travel_plan["plan"][:2]:  # First 2 days of gen_travel_plan
            gen_sequence = get_poi_sequence(day_dash)
            anno_sequence = get_poi_sequence(day)
        
            # Calculate WED and add to total
            wed = calculate_wed(gen_sequence, anno_sequence, weight_fn)
            total_wed += wed

    # Add WED for day 3 of travel_plan with day 3 of gen_travel_plan
    gen_sequence_day3 = get_poi_sequence(gen_travel_plan["plan"][2])  # Day 3 of gen_travel_plan
    anno_sequence_day3 = get_poi_sequence(travel_plan["plan"][2])  # Day 3 of travel_plan
    wed_day3 = calculate_wed(gen_sequence_day3, anno_sequence_day3, weight_fn)

    # Add to total WED
    total_wed += wed_day3

    # Average WED over all days
    # average_wed = total_wed / (num_days*num_days)
    # average_wed = total_wed / (num_days)
    average_wed = total_wed / ((num_days-1)*(num_days-1) + 1)
    return 1 - (average_wed / max(len(gen_sequence), len(anno_sequence)))


def calculate_spatial_score(travel_plan):
    def lin_exp_score(distance):
        if distance <= 5000:
            return 1 - 0.5 * (distance / 5000)
        else:
            return 0.5 * np.exp(-0.0002 * (distance - 5000))

    total_days_score = 0
    total_days = 0

    for day in travel_plan["plan"]:
        point_of_interest_list = day["point_of_interest_list"]
        pois = point_of_interest_list.split(";")
        day_scores = []

        for poi in pois:
            if "nearest transit:" in poi:
                transit_info = poi.split("nearest transit:")[1].strip()
                if "," in transit_info:
                    distance_str = transit_info.split(",")[-1].strip().split("m")[0].strip()
                    try:
                        distance = float(distance_str)
                        day_scores.append(lin_exp_score(distance))
                    except ValueError:
                        continue  # Skip if distance cannot be parsed

        if day_scores:
            average_day_score = np.mean(day_scores)
            total_days_score += average_day_score
            total_days += 1

    if total_days > 0:
        overall_average_score = total_days_score / total_days
    else:
        overall_average_score = 0  # Default to 0 if no valid data found

    return overall_average_score


# def calculate_temporal_score(travel_plan):
#     results = []

#     # Parameters for restaurants
#     restaurant_params = {
#         "breakfast": {"mean_time": 9.84, "mean_duration": 50.71/60, "std_time": 1.34, "std_duration": 14.09/60, "beta": 0.03},
#         "lunch": {"mean_time": 14.44, "mean_duration": 59.19/60, "std_time": 1.07, "std_duration": 15.82/60, "beta": 0.30},
#         "dinner": {"mean_time": 20.42, "mean_duration": 69.27/60, "std_time": 1.66, "std_duration": 69.07/60, "beta": -0.07},
#     }

#     lambda_laidback = 1.11
#     lambda_adventurous = 1.82
#     sigma_d = 53.82 / 60
#     mu_d_max = 4
#     mu_d_min = 0
#     k = 16.61 / 60

#     # print("\n================ NEW PLAN ================")

#     for day_plan in travel_plan["plan"]:
#         day_result = {"day": day_plan["day"]}

#         # print(f"\n--- Day {day_plan['day']} ---")
#         # print(f"Raw attraction field: {day_plan['attraction']}")

#         # ---------------- RESTAURANTS (unchanged, no debug) ----------------
#         for meal in ["breakfast", "lunch", "dinner"]:
#             if meal in day_plan and day_plan[meal] != "-":
#                 poi_info = day_plan["point_of_interest_list"].split(";")
#                 for poi in poi_info:
#                     if "," in day_plan[meal]:
#                         day_plan_meal, city = day_plan[meal].rsplit(",", 1)
#                         day_plan_meal = day_plan_meal.strip()
#                     else:
#                         day_plan_meal = day_plan[meal].strip()

#                     if day_plan_meal in poi:
#                         if "from" not in poi or "to" not in poi:
#                             # print(
#                             #     "[TEMPORAL-ERROR][MEAL]",
#                             #     "Day:", day_plan["day"],
#                             #     "Meal:", meal,
#                             #     "POI:", poi
#                             # )
#                             continue
#                         try:
#                             time_info = poi.split("from")[1].split("to")
#                         except:
#                             time_info = poi.rsplit("from", 1)[1].split("to")
#                         if len(time_info) < 2:
#                             continue

#                         start_time = time_info[0].strip()
#                         end_time = time_info[1].split(",")[0].strip()
                        

#                         start_hour = int(start_time.split(":")[0]) + int(start_time.split(":")[1]) / 60
#                         end_hour = int(end_time.split(":")[0]) + int(end_time.split(":")[1]) / 60
#                         midpoint = (start_hour + end_hour) / 2
#                         duration = end_hour - start_hour

#                         params = restaurant_params[meal]
#                         mu = [params["mean_time"], params["mean_duration"]]
#                         cov = [
#                             [params["std_time"] ** 2, params["beta"] * params["std_time"] * params["std_duration"]],
#                             [params["beta"] * params["std_time"] * params["std_duration"], params["std_duration"] ** 2],
#                         ]

#                         score = multivariate_normal.pdf([midpoint, duration], mean=mu, cov=cov)
#                         max_pdf = 1 / np.sqrt((2 * np.pi) ** 2 * np.linalg.det(cov))
#                         day_result[f"{meal}_score"] = score / max_pdf
#                         break

#         # ---------------- ATTRACTIONS (FULL DEBUG) ----------------
#         attractions = day_plan["attraction"].split(";")
#         num_attractions = len([a for a in attractions if a.strip() and a.strip() != "-"])
#         attraction_scores = []

#         for attraction in attractions:
#             attraction = attraction.strip()
#             if not attraction or attraction == "-":
#                 continue

#             if "," in attraction:
#                 attraction, city = attraction.rsplit(",", 1)
#                 attraction = attraction.strip()
#                 city = city.strip()
#             else:
#                 city = ""

#             for poi in day_plan["point_of_interest_list"].split(";"):
#                 if attraction in poi:
#                     if "from" not in poi or "to" not in poi:
#                         continue
#                     try:
#                         time_info = poi.split("from")[1].split("to")
#                     except:
#                         time_info = poi.rsplit("from", 1)[1].split("to")
#                     if len(time_info) < 2:
#                         continue

#                     start_time = time_info[0].strip()
#                     end_time = time_info[1].split(",")[0].strip()

#                     start_hour = int(start_time.split(":")[0]) + int(start_time.split(":")[1]) / 60
#                     end_hour = int(end_time.split(":")[0]) + int(end_time.split(":")[1]) / 60
#                     duration = end_hour - start_hour

#                     try:
#                         mu_d_type = get_mu_d_type(attraction, city, attractions_data)
#                     except ValueError:
#                         continue

#                     persona = travel_plan.get("JSON", {}).get("persona", "")
#                     if "Adventure Seeker" in persona:
#                         mu_d = mu_d_type - k * (num_attractions - mu_d_min)
#                         poisson_prob = poisson.pmf(num_attractions, lambda_adventurous)
#                     else:
#                         mu_d = mu_d_type + k * (mu_d_max - num_attractions)
#                         poisson_prob = poisson.pmf(num_attractions, lambda_laidback)

#                     gaussian = np.exp(-((duration - mu_d) ** 2) / (2 * sigma_d ** 2))
#                     final_score = gaussian * poisson_prob

#                     # print(
#                     #     f"[Attraction Debug] "
#                     #     f"name='{attraction}', "
#                     #     f"duration={duration:.2f}h, "
#                     #     f"mu_d={mu_d:.2f}h, "
#                     #     f"num_attractions={num_attractions}, "
#                     #     f"gaussian={gaussian:.6f}, "
#                     #     f"poisson={poisson_prob:.6f}, "
#                     #     f"final={final_score:.8f}"
#                     # )

#                     attraction_scores.append(final_score)

#         if attraction_scores:
#             mean_day_score = np.mean(attraction_scores)
#             day_result["attraction_score"] = mean_day_score
#             # print(f"[Day Summary] mean_attraction_score={mean_day_score:.8f}")
#         else:
#             pass
#             # print("[Day Summary] No valid attraction scores")

#         results.append(day_result)

#     # ---------------- AGGREGATION ----------------
#     total_meal_score = 0
#     total_attraction_score = 0
#     meal_count = 0
#     attraction_count = 0

#     for entry in results:
#         for m in ["breakfast_score", "lunch_score", "dinner_score"]:
#             if m in entry:
#                 total_meal_score += entry[m]
#                 meal_count += 1
#         if "attraction_score" in entry:
#             total_attraction_score += entry["attraction_score"]
#             attraction_count += 1

#     return {
#         "meal_score": total_meal_score / meal_count if meal_count > 0 else 0,
#         "attraction_score": total_attraction_score / attraction_count if attraction_count > 0 else 0
#     }

import re

def extract_time_range(poi_string):
    """
    Extracts time from:
    'visit from HH:MM to HH:MM'
    'stay from HH:MM to HH:MM'
    Returns (start_hour, end_hour) or (None, None)
    """
    match = re.search(r'(visit|stay)\s+from\s+(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})', poi_string)
    if not match:
        return None, None

    h1, m1 = map(int, match.group(2).split(":"))
    h2, m2 = map(int, match.group(3).split(":"))

    return h1 + m1/60, h2 + m2/60


def calculate_temporal_score(travel_plan):
    results = []

    # Parameters for restaurants
    restaurant_params = {
        "breakfast": {"mean_time": 9.84, "mean_duration": 50.71/60, "std_time": 1.34, "std_duration": 14.09/60, "beta": 0.03},
        "lunch": {"mean_time": 14.44, "mean_duration": 59.19/60, "std_time": 1.07, "std_duration": 15.82/60, "beta": 0.30},
        "dinner": {"mean_time": 20.42, "mean_duration": 69.27/60, "std_time": 1.66, "std_duration": 69.07/60, "beta": -0.07},
    }

    lambda_laidback = 1.11
    lambda_adventurous = 1.82
    sigma_d = 53.82 / 60
    mu_d_max = 4
    mu_d_min = 0
    k = 16.61 / 60

    # ---------------- POISSON NORMALIZER ----------------
    def poisson_max(lambda_val):
        n0 = int(np.floor(lambda_val))
        n1 = n0 + 1
        return max(poisson.pmf(n0, lambda_val), poisson.pmf(n1, lambda_val))

    for day_plan in travel_plan["plan"]:
        day_result = {"day": day_plan["day"]}

        # ---------------- RESTAURANTS ----------------
        for meal in ["breakfast", "lunch", "dinner"]:
            if meal in day_plan and day_plan[meal] != "-":
                poi_info = day_plan["point_of_interest_list"].split(";")
                for poi in poi_info:
                    if "," in day_plan[meal]:
                        day_plan_meal, city = day_plan[meal].rsplit(",", 1)
                        day_plan_meal = day_plan_meal.strip()
                    else:
                        day_plan_meal = day_plan[meal].strip()

                    if day_plan_meal in poi:
                        start_hour, end_hour = extract_time_range(poi)
                        if start_hour is None or end_hour is None:
                            continue

                        duration = end_hour - start_hour
                        if duration <= 0:
                            continue

                        midpoint = (start_hour + end_hour) / 2


                        params = restaurant_params[meal]
                        mu = [params["mean_time"], params["mean_duration"]]
                        cov = [
                            [params["std_time"] ** 2, params["beta"] * params["std_time"] * params["std_duration"]],
                            [params["beta"] * params["std_time"] * params["std_duration"], params["std_duration"] ** 2],
                        ]

                        score = multivariate_normal.pdf([midpoint, duration], mean=mu, cov=cov)
                        max_pdf = 1 / np.sqrt((2 * np.pi) ** 2 * np.linalg.det(cov))
                        day_result[f"{meal}_score"] = score / max_pdf
                        break

        # ---------------- ATTRACTIONS ----------------
        attraction_field = day_plan.get("attraction", "")
        if not attraction_field:
            continue  # no attractions for this day, skip safely

        attractions = attraction_field.split(";")

        num_attractions = len([a for a in attractions if a.strip() and a.strip() != "-"])

        attraction_scores_normalized = []
        attraction_scores_unnormalized = []

        persona = travel_plan.get("JSON", {}).get("persona", "")
        if "Adventure Seeker" in persona:
            lambda_val = lambda_adventurous
        else:
            lambda_val = lambda_laidback

        poisson_norm = poisson_max(lambda_val)

        for attraction in attractions:
            attraction = attraction.strip()
            if not attraction or attraction == "-":
                continue

            if "," in attraction:
                attraction, city = attraction.rsplit(",", 1)
                attraction = attraction.strip()
                city = city.strip()
            else:
                city = ""

            for poi in day_plan["point_of_interest_list"].split(";"):
                if attraction in poi:
                    start_hour, end_hour = extract_time_range(poi)
                    if start_hour is None or end_hour is None:
                        continue

                    duration = end_hour - start_hour
                    if duration <= 0:
                        continue


                    try:
                        mu_d_type = get_mu_d_type(attraction, city, attractions_data)
                    except ValueError:
                        continue

                    if "Adventure Seeker" in persona:
                        mu_d = mu_d_type - k * (num_attractions - mu_d_min)
                    else:
                        mu_d = mu_d_type + k * (mu_d_max - num_attractions)

                    poisson_prob = poisson.pmf(num_attractions, lambda_val)
                    gaussian = np.exp(-((duration - mu_d) ** 2) / (2 * sigma_d ** 2))

                    # --- BOTH SCORES ---
                    final_score_unnormalized = gaussian * poisson_prob
                    final_score_normalized = gaussian * (poisson_prob / poisson_norm)

                    attraction_scores_unnormalized.append(final_score_unnormalized)
                    attraction_scores_normalized.append(final_score_normalized)

        if attraction_scores_normalized:
            day_result["attraction_score_normalized"] = np.mean(attraction_scores_normalized)
            day_result["attraction_score_unnormalized"] = np.mean(attraction_scores_unnormalized)

        results.append(day_result)

    # ---------------- AGGREGATION ----------------
    total_meal_score = 0
    total_attraction_score_normalized = 0
    total_attraction_score_unnormalized = 0
    meal_count = 0
    attraction_count = 0

    for entry in results:
        for m in ["breakfast_score", "lunch_score", "dinner_score"]:
            if m in entry:
                total_meal_score += entry[m]
                meal_count += 1

        if "attraction_score_normalized" in entry:
            total_attraction_score_normalized += entry["attraction_score_normalized"]
            total_attraction_score_unnormalized += entry["attraction_score_unnormalized"]
            attraction_count += 1

    return {
        "meal_score": total_meal_score / meal_count if meal_count > 0 else 0,
        "attraction_score_normalized":
            total_attraction_score_normalized / attraction_count if attraction_count > 0 else 0,
        "attraction_score_unnormalized":
            total_attraction_score_unnormalized / attraction_count if attraction_count > 0 else 0
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen_file", type=str, default="./")
    parser.add_argument("--anno_file", type=str, default="./")
    args = parser.parse_args()
    
    gen_file_path = args.gen_file
    anno_jsonl_file_path = args.anno_file

    print("\n==============================================")
    print(" Qualitative Evaluation Started")
    print("==============================================")
    print(f"Generated file : {gen_file_path}")
    print(f"Annotation file: {anno_jsonl_file_path}")
    print("----------------------------------------------\n")

    # ---------- LOAD ANNOTATED FILE BY idx ----------
    anno_map = {}
    total_anno = 0
    with open(anno_jsonl_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            obj = json.loads(line)
            if "idx" in obj:
                anno_map[obj["idx"]] = obj
                total_anno += 1

    metrics_list = []
    progress = 0
    total_gen = 0

    # ---------- LOOP OVER GENERATED FILE ----------
    with open(gen_file_path, 'r', encoding='utf-8') as file1:
        for line in file1:
            json_object1 = json.loads(line)
            total_gen += 1

            idx = json_object1.get("idx")
            print(f"[Progress] Generated sample {total_gen}, idx = {idx}")
            if idx is None or idx not in anno_map:
                continue

            json_object2 = anno_map[idx]
            progress += 1

            if not json_object1.get("plan") or len(json_object1["plan"]) == 0:
                metrics_list.append({
                    "temporal_score": -1,
                    "spatial_score": -1,
                    "ordering_score": -1,
                    "persona_score": -1
                })
            else:
                metrics_list.append({
                    "temporal_score": calculate_temporal_score(json_object1),
                    "spatial_score": calculate_spatial_score(json_object1),
                    "ordering_score": calculate_ordering_score(json_object1, json_object2),
                    "persona_score": calculate_persona_score(json_object1)
                })

    # ---------- AGGREGATION ----------
    sum_meal_sc = 0
    sum_attrac_sc_normalized = 0
    sum_attrac_sc_unnormalized = 0
    sum_spatial_sc = 0
    sum_ord_sc = 0
    sum_persona_sc = 0
    num = 0

    for entry in metrics_list:
        if entry["temporal_score"] != -1:
            sum_meal_sc += entry["temporal_score"]["meal_score"]
            sum_attrac_sc_normalized += entry["temporal_score"]["attraction_score_normalized"]
            sum_attrac_sc_unnormalized += entry["temporal_score"]["attraction_score_unnormalized"]
            num += 1

        if entry["spatial_score"] != -1:
            sum_spatial_sc += entry["spatial_score"]

        if entry["ordering_score"] != -1:
            sum_ord_sc += entry["ordering_score"]

        if entry["persona_score"] != -1:
            sum_persona_sc += entry["persona_score"]

    # ---------- PRINT SUMMARY ----------
    print("\n========== QUALITATIVE EVALUATION SUMMARY ==========")
    print(f"Annotated samples        : {total_anno}")
    print(f"Generated samples        : {total_gen}")
    print(f"Samples evaluated        : {num}")
    print("--------------------------------------------------")

    if num > 0:
        print(f"Avg Meal Temporal Score              : {sum_meal_sc / num:.4f}")
        print(f"Avg Attraction Temporal (Normalized) : {sum_attrac_sc_normalized / num:.6f}")
        print(f"Avg Attraction Temporal (Unnormalized): {sum_attrac_sc_unnormalized / num:.6f}")
        print(f"Avg Spatial Score                    : {sum_spatial_sc / num:.4f}")
        print(f"Avg Persona Alignment                 : {sum_persona_sc / num:.4f}")
        print(f"Avg Ordering Score                    : {sum_ord_sc / num:.4f}")
    else:
        print("No valid samples evaluated.")

    print("==================================================\n")
