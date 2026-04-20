# core/llm_backend.py

import os
import torch
from dataclasses import dataclass
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers import BitsAndBytesConfig
import time
from transformers import logging
logging.set_verbosity_error()
# ======================================================
# Backend State Dataclass
# ======================================================
@dataclass
class LLM:
    backend: str
    model_name: str
    tokenizer: object = None
    model: object = None
    client: object = None
    api_key: str = None

    # Unified generation function
    def generate(self, prompt, max_new_tokens=2000):
        backend = self.backend

        # -------------------------------
        # 1. OpenAI (modern API)
        # -------------------------------
        if backend == "openai":
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                top_p=0.9,
                max_tokens=max_new_tokens,
            )
            return resp.choices[0].message.content.strip()

        # -------------------------------
        # 3. Gemini API (google-genai)
        # -------------------------------
        if backend == "gemini":
            try:
                from google import genai
                client = genai.Client(api_key=self.api_key)
                print(f"⏳ Waiting 10s before Gemini query to manage quota...")
                time.sleep(10)

                r = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return r.text
            except Exception as e:
                print("\n🔥 GEMINI ERROR:", e)
                return None

        # -------------------------------
        # 4. HuggingFace Local Models
        # -------------------------------

        # SPECIAL HANDLING FOR QWEN (ChatML format)
        mn = self.model_name.lower()

        is_qwen25 = "qwen2.5" in mn
        is_qwen3 = "qwen3" in mn
        is_phi4   = "phi-4" in mn or "phi4" in mn
        is_llama = "llama" in mn
        is_deepseek = "deepseek" in mn
        is_yi = "yi-" in mn or "yi/" in mn
        # print("MODEL NAME:", self.model_name)
        # print("is_deepseek:", is_deepseek)



        if is_qwen25 or is_qwen3:

            system_msg = (
                "Output ONLY valid JSON. No explanations, no markdown."
                if is_qwen3 else
                "You MUST output ONLY valid JSON."
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a strict JSON generator.\n"
                        "You must follow ALL instructions exactly.\n"
                        "You must output ONLY valid JSON.\n"
                        "No explanations. No markdown."
                    )
                },
                {"role": "user", "content": prompt}
            ]
            # print("QWEN PROMPT:", prompt)

            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

            inputs = self.tokenizer(
                text,
                return_tensors="pt"
            ).to(self.model.device)

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=0.6,
                    top_p=0.9,
                    repetition_penalty=1.05,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            # print("QWEN RAW OUTPUT:", self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip())
            return self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()


        # -------------------------------
        # SPECIAL HANDLING FOR PHI-4 (Chat format)
        # -------------------------------
        if is_phi4:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
            # print("PHI-4 PROMPT:", prompt)

            inputs = self.tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt"
            )

            input_ids = inputs.to(self.model.device)
            attention_mask = torch.ones_like(input_ids, device=input_ids.device)

            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=0.6,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )

            text = self.tokenizer.decode(output_ids[0], skip_special_tokens=True)
            # print("PHI-4 RAW OUTPUT:", text)
            return text[len(self.tokenizer.decode(input_ids[0], skip_special_tokens=True)):].strip()

        # -------------------------------
        # SPECIAL HANDLING FOR LLAMA (DUAL MODE: JSON + POI TEXT)
        # -------------------------------
        if is_llama:

            is_poi = "ITINERARY" in prompt and "REASONING" in prompt

            if is_poi:
                # ✅ POI MODE (TEXT OUTPUT)
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "Follow instructions EXACTLY.\n"
                            "Output ONLY TWO sections in this order:\n"
                            "REASONING\n"
                            "ITINERARY\n"
                            "Do NOT output JSON.\n"
                            "Do NOT use markdown.\n"
                            "Do NOT add extra text.\n"
                            "Do NOT include explanations outside these sections.\n"
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
            else:
                # ✅ JSON MODE (OTHER AGENTS)
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a STRICT JSON generator.\n"
                            "You must output ONLY valid JSON.\n"
                            "Do NOT add explanations.\n"
                            "Do NOT repeat answers.\n"
                            "Do NOT add markdown.\n"
                            "Stop after the JSON object.\n"
                        )
                    },
                    {"role": "user", "content": prompt}
                ]

            # -------------------------------
            # TOKENIZATION
            # -------------------------------
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            # print("LLAMA PROMPT:", prompt)

            inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)

            # -------------------------------
            # GENERATION
            # -------------------------------
            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=2000,
                    do_sample=False,
                    repetition_penalty=1.1,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            text = self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
            # print("Output from LLaMA:", text)

            # -------------------------------
            # CLEAN OUTPUT
            # -------------------------------
            import re

            # remove <think> blocks
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

            # remove markdown if any
            text = text.replace("```json", "").replace("```", "").strip()

            # -------------------------------
            # POI MODE → RETURN TEXT
            # -------------------------------
            if is_poi:
                # ensure output starts from REASONING
                match = re.search(r"(REASONING.*)", text, re.DOTALL)
                if match:
                    text = match.group(1)

                return text.strip()

            # -------------------------------
            # JSON MODE → EXTRACT JSON
            # -------------------------------
            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end != -1 and end > start:
                return text[start:end + 1]

            raise ValueError("Invalid JSON from LLaMA")
        # -------------------------------
        # SPECIAL HANDLING FOR DEEPSEEK (STRICT JSON ONLY)
        # -------------------------------
        if is_deepseek:
            import time
            start_time = time.time()
            is_poi = "ITINERARY" in prompt and "REASONING" in prompt
            if is_poi:
                # ✅ TEXT MODE (for POI agent)
                messages =[{
                        "role": "system",
                        "content": (
                            "Do NOT use <think> tags.\n"
                            "Do NOT add any explanation unless asked.\n"
                            "Use ONLY English language.\n"
                            "No extra text.\n"
                            "No markdown.\n"
                            "Do NOT use markdown (no ```).\n"
                            "Do NOT add comments, hashtags, or notes.\n"
                            "Follow instructions EXACTLY.\n"
                            "Output ONLY TWO sections:\n"
                            "REASONING\n"
                            "ITINERARY\n"
                            "Do NOT output JSON.\n"
                            "Do NOT use markdown.\n"
                            "Do NOT add extra text.\n"
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
            else:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You must NOT output reasoning.\n"
                            "Do NOT use <think> tags.\n"
                            "Output ONLY ONE valid JSON object.\n"
                            "STOP after the first JSON.\n"
                            "Do NOT add any explanation unless asked.\n"
                            "Use ONLY English language.\n"\
                            "Do NOT add text before or after JSON.\n"
                            "No extra text.\n"
                            "No markdown.\n"
                            "Do NOT use markdown (no ```).\n"
                            "Do NOT add comments, hashtags, or notes.\n"
                        )
                    },
                    {"role": "user", "content": prompt}
                ]

            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

            inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
            # print("INPUT TOKENS:", inputs.input_ids.shape[1])

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=2000,          # 🔥 REDUCED (CRITICAL FIX)
                    do_sample=False,             # 🔒 deterministic
                    repetition_penalty=1.1,      # 🔥 prevents loops
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            text = self.tokenizer.decode(gen_ids, skip_special_tokens=True)
            # print("\n====== RAW DEEPSEEK OUTPUT ======\n")
            # print(text)
            # print("\n=================================\n")

            # -------------------------------
            # CLEAN OUTPUT
            # -------------------------------
            text = text.replace("```json", "").replace("```", "").strip()

            # 🔥 REMOVE <think> blocks (IMPORTANT)
            import re
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

            # -------------------------------
            # EXTRACT FIRST JSON ONLY (FIX)
            # -------------------------------
            def extract_first_json(s):
                stack = []
                start = None

                for i, ch in enumerate(s):
                    if ch == "{":
                        if start is None:
                            start = i
                        stack.append("{")
                    elif ch == "}":
                        if stack:
                            stack.pop()
                            if not stack:
                                return s[start:i + 1]
                return None

            if is_poi:
                import re
                match = re.search(r"(REASONING.*)", text, re.DOTALL)
                # print("DEEPSEEK POI RAW OUTPUT:", text)
                if match:
                    text = match.group(1)
                # print("PROMPT:", prompt)
                # print("TEXT:", text)
                end_time = time.time()   # ⏱️ END TIMER
                # print(f"⏱️ DeepSeek Generation Time: {end_time - start_time:.2f} seconds")
                return text.strip()
            json_block = extract_first_json(text)

            if not json_block:
                raise ValueError("DeepSeek did not return valid JSON")
            # print("Extracted JSON:", json_block)
            end_time = time.time()   # ⏱️ END TIMER
            # print(f"⏱️ DeepSeek Generation Time: {end_time - start_time:.2f} seconds")
            return json_block.strip()

        # -------------------------------
        # SPECIAL HANDLING FOR MISTRAL
        # -------------------------------
        if "mistral" in mn:
            is_poi = "ITINERARY" in prompt and "REASONING" in prompt

            if is_poi:
                # ✅ POI MODE (STRICT TEXT)
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict instruction-following assistant.\n"
                            "Follow the user request exactly.\n"
                            "Follow instructions EXACTLY.\n"
                            "Do NOT output JSON.\n"
                            "Do NOT use markdown.\n"
                            "Do NOT add extra text.\n"
                            "Output EXACTLY TWO sections:\n"
                            "REASONING\n"
                            "ITINERARY\n"
                            "Nothing else.\n"
                            "Do NOT use markdown (no ```).\n"
                            "Do NOT add comments, hashtags, or notes.\n"
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
            else:
                # ✅ JSON MODE (STRICT)
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict instruction-following assistant.\n"
                            "Follow the user request exactly.\n"
                            "If JSON is requested, output ONLY JSON.\n"
                            "Do not add explanations unless asked."
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
           
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

            inputs = self.tokenizer(
                text,
                return_tensors="pt"
            ).to(self.model.device)

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=2000,
                    do_sample=True,
                    temperature=0.6,
                    top_p=0.9,
                    repetition_penalty=1.1,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            # print("MISTRAL RAW OUTPUT:", self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip())

            return self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()


        # -------------------------------
        # SPECIAL HANDLING FOR YI
        # -------------------------------
        if is_yi:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a STRICT JSON generator.\n"
                        "You must output ONLY ONE valid JSON object.\n"
                        "Do NOT add any explanation.\n"
                        "Use ONLY English language.\n"
                        "Do NOT use Chinese or any other language.\n"
                        "Do NOT add text before or after JSON.\n"
                        "No extra text.\n"
                        "No markdown.\n"
                        "Do NOT use markdown (no ```).\n"
                        "Do NOT add comments, hashtags, or notes.\n"
                        "Stop immediately after closing }.\n"
                        "If output is not JSON, it is considered WRONG."
                    )
                },
                {"role": "user", "content": prompt}
            ]

            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=32000   
            ).to(self.model.device)
            print("INPUT TOKENS:", inputs.input_ids.shape[1])

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=1500,
                    do_sample=True,
                    temperature=0.6,
                    top_p=0.9,
                    repetition_penalty=1.1,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            text = self.tokenizer.decode(gen_ids, skip_special_tokens=True)

            # REMOVE markdown
            text = text.replace("```json", "").replace("```", "").strip()
            print("\n====== RAW YI OUTPUT ======\n")
            print(text)

            # EXTRACT JSON ONLY
            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end != -1:
                text = text[start:end+1]
            else:
                raise ValueError("Invalid JSON output")

            return text
            print("YI RAW OUTPUT:", self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip())
            return self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()

        # -------------------------------
        # NORMAL HF MODELS (Phi etc.)
        # -------------------------------
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        # print("INPUT TOKENS:", inputs.input_ids.shape[1])

        with torch.no_grad():
            gen = self.model.generate(
                **inputs,
                do_sample=True,
                temperature=0.6,
                top_p=0.9,
                max_new_tokens=max_new_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        # print("OUTPUT TOKENS:", gen.shape[1],"OUTPUT:", self.tokenizer.decode(gen[0], skip_special_tokens=True).strip())
        return self.tokenizer.decode(gen[0], skip_special_tokens=True).strip()


# ======================================================
# Helper imports
# ======================================================
from openai import OpenAI
OPENAI_Client = OpenAI

OPENAI_HINTS = ["gpt", "o1", "o3"]


def _load_gemini_client():
    try:
        from google import genai
        return genai
    except Exception as e:
        print("Gemini import failed:", e)
        return None


GEMINI_Client = _load_gemini_client()
GEMINI_HINTS = ["gemini", "flash", "pro","gemma"]


# ======================================================
# PUBLIC: Initialize LLM
# ======================================================
def init_llm(model_name: str, api_key: str):
    mn = model_name.lower()

    # -------------------------------
    # 1. OpenAI
    # -------------------------------
    if any(k in mn for k in OPENAI_HINTS):
        return LLM(
            backend="openai",
            model_name=model_name,
            client=OPENAI_Client(api_key=api_key)
        )


    # -------------------------------
    # 2. Gemini
    # -------------------------------
    if any(k in mn for k in GEMINI_HINTS) and GEMINI_Client:
        return LLM(
            backend="gemini",
            model_name=model_name,
            api_key=api_key
        )

    # -------------------------------
    # 3. HuggingFace Local Models
    # -------------------------------
    repo_map = {
        "qwen2.5": "Qwen/Qwen2.5-7B-Instruct",
        "phi4": "microsoft/Phi-4",
        "llama": "meta-llama/Llama-3.1-70B-Instruct",
        "mistral": "mistralai/Mistral-Nemo-Instruct-2407",
        "deepseek": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"  #google/gemma-3-27b-it
    }


    repo = repo_map.get(mn, model_name)

    tok = AutoTokenizer.from_pretrained(
        repo,
        trust_remote_code=True,
        token=os.environ.get("HF_TOKEN")
    )


    # -------------------------------
    # Detect LLaMA
    # -------------------------------
    is_llama = "llama" in repo.lower()
    is_yi = "yi" in repo.lower()

    # -------------------------------
    # Load model
    # -------------------------------
    if is_llama or is_yi:
        # print("🚀 Loading model with 4-bit (GPU ONLY)")

        from transformers import BitsAndBytesConfig

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4"
        )

        model = AutoModelForCausalLM.from_pretrained(
            repo,
            trust_remote_code=True,
            quantization_config=bnb_config,
            device_map={"": 0},   
            dtype=torch.float16,
            token="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"
        )
        # model = AutoModelForCausalLM.from_pretrained(
        #     repo,
        #     trust_remote_code=True,
        #     device_map="auto",
        #     token="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",
        #     dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32
        # )

    else:
        model = AutoModelForCausalLM.from_pretrained(
            repo,
            trust_remote_code=True,
            device_map="auto",
            token=os.environ.get("HF_TOKEN"),
            dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32
        )

    return LLM(
        backend="hf",
        model_name=repo,
        tokenizer=tok,
        model=model
    )
