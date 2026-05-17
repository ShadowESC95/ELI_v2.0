import json
from datasets import Dataset
from unsloth import FastLanguageModel
import torch
from transformers import TrainingArguments
from trl import SFTTrainer

with open("training_data/eli_conversations_phi3.jsonl", "r") as f:
    examples = [json.loads(line)["text"] for line in f]

dataset = Dataset.from_list([{"text": ex} for ex in examples])

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "./phi-3-mini-base",
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    lora_alpha = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 42,
)

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = 2048,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 10,
        max_steps = 200,
        learning_rate = 2e-4,
        fp16 = True,
        logging_steps = 1,
        optim = "adamw_8bit",
        output_dir = "lora_outputs_phi3",
        report_to = "none",
    ),
)

trainer.train()
model.save_pretrained("eli-lora-adapter-phi3")
tokenizer.save_pretrained("eli-lora-adapter-phi3")
print("✅ LoRA adapter saved.")
