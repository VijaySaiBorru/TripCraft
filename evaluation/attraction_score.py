import json
import numpy as np
import pandas as pd
from scipy.stats import poisson
import argparse
import os

# ------------------ LOAD ATTRACTION DATA ------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_DIR = os.path.join(BASE_DIR, "TripCraft_database")

attractions_data = pd.read_csv(
    os.path.join(DB_DIR, "attraction", "cleaned_attractions_final.csv")
)

# ------------------ HELPERS ------------------
def get_mu_d_type(attraction, city):
    match = attractions_data[
        (attractions_data["City"].str.strip().str.lower() == city.strip().lower()) &
        (attractions_data["name"].str.strip().str.lower() == attraction.strip().lower())
    ]
    if match.empty:
        raise ValueError
    return float(match.iloc[0]["visit_duration"])


def parse_duration(poi):
    if "from" not in poi or "to" not in poi:
        return None
    try:
        time_info = poi.split("from")[1].split("to")
    except:
        time_info = poi.rsplit("from", 1)[1].split("to")

    start = time_info[0].strip()
    end = time_info[1].split(",")[0].strip()

    sh = int(start.split(":")[0]) + int(start.split(":")[1]) / 60
    eh = int(end.split(":")[0]) + int(end.split(":")[1]) / 60
    return eh - sh


def pause():
    input("\n▶ Press ENTER to continue...\n")


# ------------------ INTERACTIVE ATTRACTION SCORE ------------------
def debug_attraction_temporal_score(travel_plan):
    lambda_laidback = 1.11
    lambda_adventurous = 1.82
    sigma_d = 53.82 / 60
    mu_d_max = 4
    mu_d_min = 0
    k = 16.61 / 60

    persona = travel_plan.get("JSON", {}).get("persona", "")
    is_adventurous = "Adventure Seeker" in persona

    print("\n================ NEW QUERY ================")
    print("Persona:", persona)
    pause()

    all_day_scores = []

    for day in travel_plan.get("plan", []):
        print(f"\n========== DAY {day.get('day')} ==========")

        attractions = [
            a.strip() for a in day.get("attraction", "").split(";")
            if a.strip() and a.strip() != "-"
        ]

        num_attractions = len(attractions)
        print("Attractions:", attractions)
        print("Num attractions:", num_attractions)
        pause()

        day_scores = []

        for attraction in attractions:
            if "," in attraction:
                attraction, city = attraction.rsplit(",", 1)
                attraction, city = attraction.strip(), city.strip()
            else:
                city = ""

            print(f"\n--- Attraction: {attraction} ({city}) ---")

            for poi in day.get("point_of_interest_list", "").split(";"):
                if attraction not in poi:
                    continue

                duration = parse_duration(poi)
                if duration is None:
                    print("❌ No valid time window")
                    continue

                try:
                    mu_d_type = get_mu_d_type(attraction, city)
                except:
                    print("❌ Not found in dataset")
                    continue

                if is_adventurous:
                    mu_d = mu_d_type - k * (num_attractions - mu_d_min)
                    poisson_prob = poisson.pmf(num_attractions, lambda_adventurous)
                    persona_type = "Adventurous"
                else:
                    mu_d = mu_d_type + k * (mu_d_max - num_attractions)
                    poisson_prob = poisson.pmf(num_attractions, lambda_laidback)
                    persona_type = "Laid-back"

                gaussian = np.exp(-((duration - mu_d) ** 2) / (2 * sigma_d ** 2))
                final_score = gaussian * poisson_prob

                print(f"Persona type     : {persona_type}")
                print(f"Actual duration  : {duration:.2f} h")
                print(f"Base mu_d_type   : {mu_d_type:.2f} h")
                print(f"Adjusted mu_d    : {mu_d:.2f} h")
                print(f"Gaussian score   : {gaussian:.6f}")
                print(f"Poisson prob     : {poisson_prob:.6f}")
                print(f"FINAL SCORE     : {final_score:.8f}")

                day_scores.append(final_score)
                pause()
                break

        if day_scores:
            day_mean = np.mean(day_scores)
            print(f"\n✅ Day mean attraction score: {day_mean:.8f}")
            all_day_scores.append(day_mean)
            pause()

    final = float(np.mean(all_day_scores)) if all_day_scores else 0.0
    print("\n================ FINAL RESULT ================")
    print(f"FINAL ATTRACTION TEMPORAL SCORE: {final:.8f}")
    print("=============================================\n")

    return final


# ------------------ MAIN ------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--idx", type=int, default=None,
                        help="Optional: debug only a specific idx")
    args = parser.parse_args()

    with open(args.input_file, "r", encoding="utf-8") as f:
        for line in f:
            plan = json.loads(line)
            if args.idx is not None and plan.get("idx") != args.idx:
                continue
            debug_attraction_temporal_score(plan)
            break
