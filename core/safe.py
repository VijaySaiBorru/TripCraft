# core/llm_backend.py

import os
import torch
from dataclasses import dataclass
from transformers import AutoTokenizer, AutoModelForCausalLM


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
    def generate(self, prompt, max_new_tokens=2000, temperature=0.3, top_p=0.9):
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
        # 2. OpenAI Legacy
        # -------------------------------
        if backend == "openai_legacy":
            out = self.client.ChatCompletion.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_new_tokens,
                top_p=top_p,
            )
            return out["choices"][0]["message"]["content"].strip()

        # -------------------------------
        # 3. Gemini API (google-genai)
        # -------------------------------
        if backend == "gemini":
            try:
                from google import genai
                client = genai.Client(api_key=self.api_key)

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
        if "qwen" in self.model_name.lower():
            messages = [
                {"role": "system", "content": "You MUST output ONLY valid JSON."},
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

            # remove prompt part
            return text[len(self.tokenizer.decode(input_ids[0], skip_special_tokens=True)):].strip()


        # -------------------------------
        # NORMAL HF MODELS (Phi etc.)
        # -------------------------------
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            gen = self.model.generate(
                **inputs,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        return self.tokenizer.decode(gen[0], skip_special_tokens=True).strip()


# ======================================================
# Helper imports
# ======================================================
def _load_openai_client():
    try:
        from openai import OpenAI
        return OpenAI
    except:
        pass

    try:
        import openai
        return openai
    except:
        return None


OPENAI_Client = _load_openai_client()
OPENAI_HINTS = ["gpt", "o1", "o3"]


def _load_gemini_client():
    try:
        from google import genai
        return genai
    except Exception as e:
        print("Gemini import failed:", e)
        return None


GEMINI_Client = _load_gemini_client()
GEMINI_HINTS = ["gemini", "flash", "pro"]


# ======================================================
# PUBLIC: Initialize LLM
# ======================================================
def init_llm(model_name: str, api_key: str):
    mn = model_name.lower()

    # -------------------------------
    # 1. OpenAI
    # -------------------------------
    if any(k in mn for k in OPENAI_HINTS) and OPENAI_Client:
        # Legacy API support
        if hasattr(OPENAI_Client, "ChatCompletion"):
            return LLM(
                backend="openai_legacy",
                model_name=model_name,
                client=OPENAI_Client
            )

        return LLM(
            backend="openai",
            model_name=model_name,
            client=OPENAI_Client(api_key=os.getenv("OPENAI_API_KEY"))
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
        "phi4": "microsoft/Phi-4",
        "phi3": "microsoft/Phi-3-mini-4k-instruct",
        "qwen": "Qwen/Qwen2.5-7B-Instruct",
    }

    repo = repo_map.get(mn, model_name)

    tok = AutoTokenizer.from_pretrained(repo, trust_remote_code=True)

    model = AutoModelForCausalLM.from_pretrained(
        repo,
        trust_remote_code=True,
        device_map="auto",
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32
    )

    return LLM(
        backend="hf",
        model_name=repo,
        tokenizer=tok,
        model=model
    )
