import json
from pathlib import Path
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("./phi-3-mini-base")

conv_paths = list(Path("eli/artifacts/conversations").glob("*.json"))
conv_paths += list(Path("eli/gui/artifacts/conversations").glob("*.json"))

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
        pass

with open("training_data/eli_conversations_phi3.jsonl", "w") as f:
    for ex in training_examples:
        f.write(json.dumps({"text": ex}) + "\n")

print(f"✅ Extracted {len(training_examples)} training examples.")
