import json
from datasets import Dataset
from unsloth import FastLanguageModel
import torch
from transformers import TrainingArguments
from trl import SFTTrainer

# Load training data
with open("training_data/eli_conversations_7b.jsonl", "r") as f:
    examples = [json.loads(line)["text"] for line in f]

dataset = Dataset.from_list([{"text": ex} for ex in examples])

# Load model with 4‑bit quantization
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "./mistral-7b-base",  # local path
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)

# Add LoRA adapters
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
    use_rslora = False,
    loftq_config = None,
)

# Training arguments – 7B can handle larger batch size
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = 2048,
    dataset_num_proc = 2,
    args = TrainingArguments(
        per_device_train_batch_size = 4,
        gradient_accumulation_steps = 2,
        warmup_steps = 10,
        max_steps = 200,
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 42,
        output_dir = "lora_outputs_7b",
        report_to = "none",
    ),
)

# Train
trainer.train()

# Save the adapter
model.save_pretrained("eli-lora-adapter-7b")
tokenizer.save_pretrained("eli-lora-adapter-7b")
print("✅ LoRA adapter saved to ./eli-lora-adapter-7b")
