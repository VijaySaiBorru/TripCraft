import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import os
model_id = "meta-llama/Meta-Llama-3-70B-Instruct-AWQ"

tokenizer = AutoTokenizer.from_pretrained(
    model_id,
    use_fast=True,
    token=os.environ["HF_TOKEN"]
)

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    device_map="auto",
    torch_dtype=torch.float16,
    trust_remote_code=True,
    token=os.environ["HF_TOKEN"]
)

prompt = "Explain why lunch must not be skipped."

inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=300,
        temperature=0.6,
        top_p=0.9
    )

print(tokenizer.decode(outputs[0], skip_special_tokens=True))
