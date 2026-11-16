"""Run offline inside the pinned Transformers worker image."""
from transformers import AutoModelForCausalLM, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("/input", local_files_only=True, trust_remote_code=False)
model = AutoModelForCausalLM.from_pretrained("/input", torch_dtype="auto", local_files_only=True, trust_remote_code=False)
model.save_pretrained("/output", safe_serialization=True, max_shard_size="2GB")
tokenizer.save_pretrained("/output")
