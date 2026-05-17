import json
import os
from pathlib import Path

# Load tokenizer from local model
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained("./mistral-7b-base")

# Collect all conversation JSON files
conv_paths = list(Path("eli/artifacts/conversations").glob("*.json"))
conv_paths += list(Path("eli/gui/artifacts/conversations").glob("*.json"))

# Also include .eli_memory.jsonl
memory_path = Path.home() / ".eli_memory.jsonl"
memories = []
if memory_path.exists():
    with open(memory_path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                memories.append(rec.get("text", ""))
            except:
                pass

training_examples = []

for path in conv_paths:
    try:
        with open(path) as f:
            conv = json.load(f)
        messages = []
        for entry in conv:
            if entry.get("source") == "USER":
                messages.append({"role": "user", "content": entry.get("message", "")})
            elif entry.get("source") == "ELI":
                messages.append({"role": "assistant", "content": entry.get("message", "")})
        if len(messages) >= 2:
            chatml = tokenizer.apply_chat_template(messages, tokenize=False)
            training_examples.append(chatml)
    except Exception as e:
        print(f"Skipping {path}: {e}")

# Add memory recalls as system prompts
for mem in memories[-50:]:
    chatml = f"<|im_start|>system\n{mem}<|im_end|>\n<|im_start|>assistant\nNoted.<|im_end|>"
    training_examples.append(chatml)

with open("training_data/eli_conversations_7b.jsonl", "w") as f:
    for ex in training_examples:
        f.write(json.dumps({"text": ex}) + "\n")

print(f"✅ Extracted {len(training_examples)} training examples.")
