import pandas as pd
import torch
import json
import re
from transformers import AutoModelForCausalLM, AutoTokenizer
from ftfy import fix_text
from tqdm import tqdm
from transformers import logging
logging.set_verbosity_error()

# =========================================================
# PATHS
# =========================================================

reviews_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/clean_accomodation_review.csv"
summary_path = "/scratch/sg/Vijay/TripCraft/TripCraft_database/review_signal/accomodation_review_summary_with_persona.csv"

# =========================================================
# LOAD DATA
# =========================================================

df_reviews = pd.read_csv(reviews_path)
df_reviews = df_reviews[df_reviews["Comment"].notna()]

df_summary = pd.read_csv(summary_path)

print(f"Accommodations in summary file: {len(df_summary)}")

# =========================================================
# LOAD DEEPSEEK
# =========================================================

print("\nLoading DeepSeek pros/cons extractor...\n")

model_name = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"

tokenizer = AutoTokenizer.from_pretrained(model_name)

model = AutoModelForCausalLM.from_pretrained(
    model_name,
    dtype=torch.float16,
    device_map="auto"
)

# =========================================================
# CLEAN + DEDUP FUNCTION
# =========================================================

def clean_list(items, max_items=6):
    seen = set()
    cleaned = []

    for item in items:
        key = item.lower().strip()

        if key not in seen and len(key) > 3:
            seen.add(key)
            cleaned.append(item.strip())

    return cleaned[:max_items]

# =========================================================
# PROS / CONS EXTRACTOR
# =========================================================

def get_pros_cons(accom_name: str, comments: list) -> dict:

    # 🔥 NO CAP (as you requested)
    reviews_text = " | ".join(comments)

    prompt = (
        f"Given reviews for '{accom_name}', extract ONLY the most important Pros and Cons.\n"
        "- Maximum 6 Pros and 6 Cons\n"
        "- Merge similar points\n"
        "- Avoid repetition\n"
        "- Focus on meaningful insights only\n\n"
        "Return ONLY valid JSON:\n"
        '{"Pros": ["..."], "Cons": ["..."]}\n\n'
        "Do NOT include explanation or reasoning."
        f"Reviews: {reviews_text}"
    )

    text = f"### Instruction:\n{prompt}\n\n### Response:\n"

    model_inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True
    ).to(model.device)

    generated_ids = model.generate(
        model_inputs.input_ids,
        attention_mask=model_inputs.attention_mask,
        max_new_tokens=512,
        do_sample=False,
        eos_token_id=tokenizer.eos_token_id,
    pad_token_id=tokenizer.eos_token_id
    )

    response = tokenizer.decode(
        generated_ids[0][model_inputs.input_ids.shape[1]:],
        skip_special_tokens=True
    )

    # print("\n[DEBUG RAW RESPONSE]:", response)

    normalized = {"Pros": [], "Cons": []}

    try:
        clean = response.replace("```json", "").replace("```", "").strip()

        matches = re.findall(r"\{[\s\S]*?\}", clean)

        raw = None
        for m in matches:
            try:
                raw = json.loads(m)
                break   # take first valid JSON
            except:
                continue

        if raw:
            pros = raw.get("Pros", raw.get("pros", []))
            cons = raw.get("Cons", raw.get("cons", []))

            if isinstance(pros, str): pros = [pros]
            if isinstance(cons, str): cons = [cons]

            normalized["Pros"] = clean_list(pros)
            normalized["Cons"] = clean_list(cons)

    except Exception as e:
        print("[PARSE ERROR]:", e)

    return normalized

# =========================================================
# RUN EXTRACTION
# =========================================================

DEBUG = False   # set False for full run

pros_list = []
cons_list = []

for _, row in tqdm(df_summary.iterrows(), total=len(df_summary), desc="Extracting Pros/Cons"):

    accom_name  = row["Name"]
    accom_index = row["accommodation_index"]

    df_accom = df_reviews[df_reviews["Name"] == accom_name]
    comments = [fix_text(str(c)) for c in df_accom["Comment"].tolist()]

    if DEBUG:
        print("\n" + "="*60)
        print(f"[DEBUG] Accommodation Name  : {accom_name}")
        print(f"[DEBUG] Accommodation Index : {accom_index}")
        print(f"[DEBUG] Total Comments Found: {len(comments)}")
        print(f"[DEBUG] First 2 Comments    :")
        for c in comments[:2]:
            print(f"         -> {c[:200]}")

    if len(comments) == 0:
        pros_list.append("")
        cons_list.append("")
        if DEBUG:
            print("[DEBUG] No comments found - skipping.")
            break
        continue

    features = get_pros_cons(accom_name, comments)

    if DEBUG:
        print(f"\n[DEBUG] Pros ({len(features['Pros'])}):")
        for p in features["Pros"]:
            print(f"         + {p}")
        print(f"[DEBUG] Cons ({len(features['Cons'])}):")
        for c in features["Cons"]:
            print(f"         - {c}")
        print("="*60)
        break

    pros_list.append("|".join(features["Pros"]))
    cons_list.append("|".join(features["Cons"]))
    # Always show minimal progress (even when DEBUG = False)
    # print("\n" + "-"*50)
    print(f"[{accom_index}] {accom_name}")

    # Show only 2 pros
    # print("Pros:")
    # for p in features["Pros"][:2]:
    #     print(f"  + {p}")

    # # Show only 2 cons
    # print("Cons:")
    # for c in features["Cons"][:2]:
    #     print(f"  - {c}")

    # If empty, explicitly show
    if len(features["Pros"]) == 0:
        print("  + (none)")
    if len(features["Cons"]) == 0:
        print("  - (none)")

# =========================================================
# SAVE
# =========================================================

if not DEBUG:
    df_summary["Pros_Summary"] = pros_list
    df_summary["Cons_Summary"] = cons_list
    df_summary.to_csv(summary_path, index=False, encoding="utf-8")
    print(f"\nDone! Saved to: {summary_path}")
else:
    print("\n[DEBUG] Run complete. CSV not saved.")