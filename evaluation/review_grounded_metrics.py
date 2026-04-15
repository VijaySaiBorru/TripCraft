import json
import pandas as pd
import numpy as np
import argparse
import math
from rapidfuzz import fuzz

from itertools import product

location_types = [
"beach locations",
"city locations",
"forest and wildlife locations",
"mountain locations"
]

travel_purposes = [
"adventure travel",
"cultural exploration",
"nature exploration",
"relaxation travel"
]

spending_types = [
"economical stays",
"luxury stays"
]

traveler_types = [
"adventure traveler",
"laidback traveler"
]


def build_persona_index():

    personas = []

    for loc,purpose,spend,traveler in product(
        location_types,
        travel_purposes,
        spending_types,
        traveler_types
    ):

        personas.append((traveler,purpose,spend,loc))

    return personas

def parse_json_persona(persona_text):

    p = persona_text.lower()

    # =========================
    # TRAVELER TYPE
    # =========================
    if "laidback" in p:
        traveler = "laidback traveler"
    else:
        traveler = "adventure traveler"


    # =========================
    # PURPOSE
    # =========================
    if "cultural" in p:
        purpose = "cultural exploration"

    elif "nature" in p:
        purpose = "nature exploration"

    elif "relax" in p:
        purpose = "relaxation travel"

    elif "adventure" in p or "adveture" in p:
        purpose = "adventure travel"

    else:
        purpose = "adventure travel"


    # =========================
    # SPENDING
    # =========================
    if "luxury" in p:
        spend = "luxury stays"

    elif "economical" in p or "budget" in p:
        spend = "economical stays"

    else:
        spend = "economical stays"


    # =========================
    # LOCATION
    # =========================
    if "beach" in p:
        location = "beach locations"

    elif "mountain" in p:
        location = "mountain locations"

    elif "forest" in p or "wildlife" in p:
        location = "forest and wildlife locations"

    elif "city" in p or "cities" in p:
        location = "city locations"

    else:
        location = "city locations"


    return traveler, purpose, spend, location

def get_persona_index(persona_text):

    traveler,purpose,spend,location = parse_json_persona(persona_text)

    personas = build_persona_index()

    target = (traveler,purpose,spend,location)

    for i,p in enumerate(personas):

        if p == target:
            return i + 1

    return 1

# =========================================================
# TEXT NORMALIZATION
# =========================================================

def norm(x):
    if pd.isna(x):
        return ""
    return str(x).strip().lower()


# =========================================================
# LOAD TABLES
# =========================================================

def load_tables(accom_file, attr_file, rest_file):

    accom_df = pd.read_csv(accom_file)
    attr_df = pd.read_csv(attr_file)
    rest_df = pd.read_csv(rest_file)

    return accom_df, attr_df, rest_df


# =========================================================
# ENTITY PARSER
# =========================================================

def parse_entity(text):

    if not text or text == "-":
        return None, None

    if "," in text:
        name, city = text.rsplit(",",1)
        return name.strip(), city.strip()

    return text.strip(), ""


# =========================================================
# ROBUST MATCHING
# =========================================================

def find_entity_matches(name, city, df, name_col="Name", city_col="City", threshold=85):

    name = norm(name)
    city = norm(city)

    df_city = df[df[city_col].str.lower().str.strip() == city]

    if len(df_city) == 0:
        return None

    # exact match
    exact = df_city[df_city[name_col].str.lower().str.strip() == name]
    if len(exact) > 0:
        return exact

    # substring match
    contains = df_city[df_city[name_col].str.lower().str.contains(name, na=False)]
    if len(contains) > 0:
        return contains

    # fuzzy match
    matches = []

    for i,row in df_city.iterrows():

        score = fuzz.token_sort_ratio(name, row[name_col].lower())

        if score >= threshold:
            matches.append(i)

    if len(matches) > 0:
        return df_city.loc[matches]

    return None


# =========================================================
# SIGNAL EXTRACTION
# =========================================================

def accom_signals(rows, persona):

    Q = rows["accommodation_quality"].mean()

    noise = rows["noise_risk"].mean()
    safety = rows["safety_risk"].mean()
    neg = rows["extreme_neg_ratio"].mean()

    R = 0.7*noise + 1.0*safety + 0.8*neg

    U = rows[f"persona_{persona}_utility"].mean()

    n = rows["num_reviews"].mean()

    return Q,R,U,n,"accommodation"


def attr_signals(rows, persona):

    Q = rows["attraction_quality"].mean()

    crowd = rows["crowd_risk"].mean()
    safety = rows["safety_risk"].mean()
    neg = rows["extreme_neg_ratio"].mean()

    R = 0.7*crowd + 1.0*safety + 0.8*neg

    U = rows[f"persona_{persona}_utility"].mean()

    n = rows["num_reviews"].mean()

    return Q,R,U,n,"attraction"


def rest_signals(rows, persona):

    Q = rows["restaurant_quality"].mean()

    wait = rows["wait_risk"].mean()
    hygiene = rows["hygiene_risk"].mean()
    neg = rows["extreme_neg_ratio"].mean()

    R = 0.7*wait + 1.0*hygiene + 0.8*neg

    U = rows[f"persona_{persona}_utility"].mean()

    n = rows["num_reviews"].mean()

    return Q,R,U,n,"restaurant"


# =========================================================
# PLAN EVALUATION
# =========================================================

def evaluate_plan(plan, persona, accom_df, attr_df, rest_df, type_means):

    Q_list=[]
    R_list=[]
    U_list=[]
    REU_list=[]

    for day in plan:

        # accommodation
        acc = day.get("accommodation")

        name,city = parse_entity(acc)

        if name:

            rows = find_entity_matches(name,city,accom_df)

            if rows is not None:

                Q,R,U,n,t = accom_signals(rows,persona)

                Q_list.append(Q)
                R_list.append(R)
                U_list.append(U)

                REU_list.append(math.log(1 + n/type_means[t]))


        # restaurants
        for meal in ["breakfast","lunch","dinner"]:

            rest = day.get(meal)

            name,city = parse_entity(rest)

            if name:

                rows = find_entity_matches(name,city,rest_df)

                if rows is not None:

                    Q,R,U,n,t = rest_signals(rows,persona)

                    Q_list.append(Q)
                    R_list.append(R)
                    U_list.append(U)

                    REU_list.append(math.log(1 + n/type_means[t]))


        # attractions
        attr = day.get("attraction")

        if attr and attr != "-":

            for a in attr.split(";"):

                name,city = parse_entity(a)

                if name:

                    rows = find_entity_matches(name,city,attr_df)

                    if rows is not None:

                        Q,R,U,n,t = attr_signals(rows,persona)

                        Q_list.append(Q)
                        R_list.append(R)
                        U_list.append(U)

                        REU_list.append(math.log(1 + n/type_means[t]))


    if len(Q_list) == 0:
        return None

    N = len(Q_list)

    RGU = sum(Q_list[i] - 0.5*R_list[i] for i in range(N)) / N
    PGRU = sum(U_list) / N
    RRMS = 1 - sum(R_list)/N
    REU = sum(REU_list)/N
    # print(RGU, PGRU, RRMS, REU)

    return RGU,PGRU,RRMS,REU


# =========================================================
# JSONL LOADER
# =========================================================

def load_jsonl(file):

    data=[]

    with open(file,"r",encoding="utf-8") as f:
        for line in f:
            data.append(json.loads(line))

    return data


# =========================================================
# DATASET EVALUATION
# =========================================================

def evaluate_dataset(gen_file, accom_file, attr_file, rest_file):

    print("\n==============================================")
    print(" Review Grounded Evaluation")
    print("==============================================\n")

    accom_df,attr_df,rest_df = load_tables(accom_file,attr_file,rest_file)

    # mean reviews per entity type (for REU normalization)
    type_means = {
        "accommodation": accom_df["num_reviews"].mean(),
        "attraction": attr_df["num_reviews"].mean(),
        "restaurant": rest_df["num_reviews"].mean()
    }

    plans = load_jsonl(gen_file)

    results=[]

    for p in plans:

        plan=p.get("plan")

        persona_text = p["JSON"].get("persona","")

        persona_id = get_persona_index(persona_text)

        scores = evaluate_plan(
            plan,
            persona_id,
            accom_df,
            attr_df,
            rest_df,
            type_means
        )

        if scores:
            results.append(scores)

    results=np.array(results)

    RGU_vals  = results[:,0]
    PGRU_vals = results[:,1]
    RRMS_vals = results[:,2]
    REU_vals  = results[:,3]

    # =========================================================
    # VARIANCE BASED WEIGHTS
    # =========================================================

    stds=np.array([
        np.std(RGU_vals),
        np.std(PGRU_vals),
        np.std(RRMS_vals),
        np.std(REU_vals)
    ])

    weights = stds / stds.sum()

    alpha,beta,gamma,delta = weights

    RGES_vals = (
        alpha*RGU_vals +
        beta*PGRU_vals +
        gamma*RRMS_vals +
        delta*REU_vals
    )

    print("========== REVIEW GROUNDED METRICS ==========")
    print(f"Samples evaluated        : {len(results)}")
    print("----------------------------------------------")

    print(f"Avg RGU  : {RGU_vals.mean():.4f}")
    print(f"Avg PGRU : {PGRU_vals.mean():.4f}")
    print(f"Avg RRMS : {RRMS_vals.mean():.4f}")
    print(f"Avg REU  : {REU_vals.mean():.4f}")
    print(f"Avg RGES : {RGES_vals.mean():.4f}")

    print("\n------ Learned Weights ------")
    print(f"alpha (RGU)  : {alpha:.4f}")
    print(f"beta  (PGRU) : {beta:.4f}")
    print(f"gamma (RRMS) : {gamma:.4f}")
    print(f"delta (REU)  : {delta:.4f}")

    print("==============================================\n")


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("--gen_file", type=str, required=True)
    parser.add_argument("--accom_file", type=str, required=True)
    parser.add_argument("--attr_file", type=str, required=True)
    parser.add_argument("--rest_file", type=str, required=True)

    args = parser.parse_args()

    evaluate_dataset(
        args.gen_file,
        args.accom_file,
        args.attr_file,
        args.rest_file
    )




# To Run:
# python review_grounded_metrics.py --gen_file /scratch/sg/Vijay/TripCraft/phi4_5day_review_final.jsonl --accom_file /scratch/sg/Vijay/TripCraft/TripCraft_database/review_signal/accomodation_review_summary_with_persona.csv --attr_file /scratch/sg/Vijay/TripCraft/TripCraft_database/review_signal/attraction_review_summary_with_persona.csv --rest_file /scratch/sg/Vijay/TripCraft/TripCraft_database/review_signal/restaurant_review_summary_with_persona.csv
# python jsonl.py --model phi4 --day 3
# python eval.py --set_type 5d --evaluation_file_path /scratch/sg/Vijay/TripCraft/qwen2.5_5day_review_final.jsonl