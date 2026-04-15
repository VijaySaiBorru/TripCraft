# core/llm_backend.py

import os
import torch
from dataclasses import dataclass
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers import BitsAndBytesConfig
import time

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
    def generate(self, prompt, max_new_tokens=2000, temperature=0.6, top_p=0.9):
        backend = self.backend

        # -------------------------------
        # 1. OpenAI (modern API)
        # -------------------------------
        if backend == "openai":
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=top_p,
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
            return self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()


        # -------------------------------
        # SPECIAL HANDLING FOR PHI-4 (Chat format)
        # -------------------------------
        if is_phi4:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]

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
                    temperature=temperature,
                    top_p=top_p,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )

            text = self.tokenizer.decode(output_ids[0], skip_special_tokens=True)
            return text[len(self.tokenizer.decode(input_ids[0], skip_special_tokens=True)):].strip()

        # -------------------------------
        # SPECIAL HANDLING FOR LLAMA (STRICT JSON MODE)
        # -------------------------------
        if is_llama:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a STRICT JSON generator.\n"
                        "You must output ONLY valid JSON.\n"
                        "Do NOT add explanations.\n"
                        "Do NOT repeat answers.\n"
                        "Do NOT add markdown.\n"
                        "Stop after the JSON object."
                    )
                },
                {"role": "user", "content": prompt}
            ]

            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            # print(text)

            inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
            # print("INPUT TOKENS:", inputs.input_ids.shape[1])

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=2000,     # ✅ enough for 8–12 items
                    do_sample=False,         # ✅ allow model to expand list
                    repetition_penalty=1.1, # ✅ avoids repetition loops
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )
            # print("OUTPUT TOKENS:", output_ids.shape[1])
            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            text = self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
            # print("Output",text)

            # 🔥 CRITICAL FIX — extract ONLY valid JSON
            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]
            else:
                raise ValueError("Invalid JSON from LLaMA")

            return text
        # -------------------------------
        # SPECIAL HANDLING FOR DEEPSEEK (STRICT JSON ONLY)
        # -------------------------------
        if is_deepseek:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You must NOT output reasoning.\n"
                        "Do NOT use <think> tags.\n"
                        "Output ONLY ONE valid JSON object.\n"
                        "STOP after the first JSON."
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

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=3000,          # 🔥 REDUCED (CRITICAL FIX)
                    do_sample=False,             # 🔒 deterministic
                    repetition_penalty=1.1,      # 🔥 prevents loops
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            text = self.tokenizer.decode(gen_ids, skip_special_tokens=True)
            print("\n====== RAW DEEPSEEK OUTPUT ======\n")
            print(text)
            print("\n=================================\n")

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

            json_block = extract_first_json(text)

            if not json_block:
                raise ValueError("DeepSeek did not return valid JSON")

            return json_block.strip()

        # -------------------------------
        # SPECIAL HANDLING FOR MISTRAL
        # -------------------------------
        if "mistral" in mn:

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
                    temperature=temperature,
                    top_p=top_p,
                    repetition_penalty=1.1,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            gen_ids = output_ids[0][inputs.input_ids.shape[-1]:]
            print("MISTRAL RAW OUTPUT:", self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip())

            return self.tokenizer.decode(gen_ids, skip_special_tokens=True).strip()



        # -------------------------------
        # NORMAL HF MODELS (Phi etc.)
        # -------------------------------
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        print("INPUT TOKENS:", inputs.input_ids.shape[1])

        with torch.no_grad():
            gen = self.model.generate(
                **inputs,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        print("OUTPUT TOKENS:", gen.shape[1],"OUTPUT:", self.tokenizer.decode(gen[0], skip_special_tokens=True).strip())
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
        "qwen3": "Qwen/Qwen3-14B",
        "phi4": "microsoft/Phi-4",
        "phi3": "microsoft/Phi-3-mini-4k-instruct",
        "qwen30b":"Qwen/Qwen3-30B-A3B-Instruct-2507",
        "llama": "meta-llama/Llama-3.1-70B-Instruct",
        "codellama" : "codellama/CodeLlama-7b-Instruct-hf",
        "mistral": "mistralai/Mistral-Nemo-Instruct-2407", # mistral 7b mistralai/Ministral-3-14B-Instruct-2512 
        "deepseek": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"

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

    # -------------------------------
    # Load model
    # -------------------------------
    if is_llama:
        print("🚀 Loading LLaMA with 4-bit (GPU ONLY)")

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
            device_map={"": 0},   # ✅ GPU ONLY
            dtype=torch.float16,
            token=os.environ.get("HF_TOKEN")
        )

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
