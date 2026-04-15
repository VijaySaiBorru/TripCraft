from huggingface_hub import hf_hub_download

file_path = hf_hub_download(
    repo_id="microsoft/Phi-4",
    filename="config.json"
)

print("Actual file path:", file_path)