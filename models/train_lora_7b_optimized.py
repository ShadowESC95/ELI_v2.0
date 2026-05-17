import json
from datasets import Dataset
from unsloth import FastLanguageModel
import torch
from transformers import TrainingArguments, BitsAndBytesConfig
from trl import SFTTrainer
import accelerate

# ---------- LOAD TRAINING DATA ----------
with open("training_data/eli_conversations_7b.jsonl", "r") as f:
    examples = [json.loads(line)["text"] for line in f]

dataset = Dataset.from_list([{"text": ex} for ex in examples])

# ---------- 4-BIT CONFIG WITH CPU OFFLOADING ----------
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    llm_int8_enable_fp32_cpu_offload=True,          # ⚡ CPU offload enabled
)

# ---------- LOAD MODEL WITH DEVICE MAP ----------
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="./mistral-7b-base",
    max_seq_length=1024,           # ⚡ Reduced from 2048 to save memory
    dtype=None,
    load_in_4bit=True,
    device_map="sequential",       # ⚡ Required for CPU offloading
    max_memory={0: "5.5GiB", "cpu": "20GiB"},  # ⚡ Reserve 5.5GB GPU, rest on CPU
    quantization_config=bnb_config,
)

# ---------- REDUCED LORA RANK ----------
model = FastLanguageModel.get_peft_model(
    model,
    r=8,                           # ⚡ Lower rank = less memory
    lora_alpha=8,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
    use_rslora=False,
    loftq_config=None,
)

# ---------- SMALL BATCH SIZE + ACCUMULATION ----------
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=1024,
    dataset_num_proc=2,
    args=TrainingArguments(
        per_device_train_batch_size=1,      # ⚡ 1 is safe
        gradient_accumulation_steps=8,      # ⚡ Effective batch size = 8
        warmup_steps=10,
        max_steps=200,
        learning_rate=2e-4,
        fp16=True,                         # ⚡ Enable mixed precision
        bf16=False,
        logging_steps=1,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir="lora_outputs_7b",
        report_to="none",
        dataloader_num_workers=0,          # ⚡ Avoid extra memory
    ),
)

# ---------- TRAIN ----------
trainer.train()

# ---------- SAVE ADAPTER ----------
model.save_pretrained("eli-lora-adapter-7b")
tokenizer.save_pretrained("eli-lora-adapter-7b")
print("✅ LoRA adapter saved to ./eli-lora-adapter-7b")
