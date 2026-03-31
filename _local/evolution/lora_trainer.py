"""
LoRA fine-tuning pipeline for CT-1.
Activates when journal has enough entries (/train command or direct call).
Heavy ML dependencies (torch, peft, trl) are imported lazily —
they are NOT needed for inference.
"""
import json
from pathlib import Path

async def trigger_training(
    dataset_path: str = "ct1/data/dpo_dataset.jsonl",
    adapter_output_dir: str = "ct1/data/adapters/training_output",
    model_name_or_path: str = "Qwen/Qwen3.5-0.8B",
    min_pairs: int = 50,
):
    if not Path(dataset_path).exists():
        print(f"[trainer] No dataset at {dataset_path}. Run /train to extract first.")
        return

    with open(dataset_path, encoding="utf-8") as f:
        pairs = [json.loads(l) for l in f if l.strip()]

    if len(pairs) < min_pairs:
        print(f"[trainer] Only {len(pairs)} pairs. Need {min_pairs} minimum.")
        return

    print(f"[trainer] Training on {len(pairs)} preference pairs...")

    try:
        from datasets import Dataset
        from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
        from peft import LoraConfig, get_peft_model
        from trl import DPOTrainer
    except ImportError:
        print("[trainer] Training deps not installed. Run:")
        print("  pip install -r ct1/requirements-training.txt")
        return

    Path(adapter_output_dir).mkdir(parents=True, exist_ok=True)
    dataset = Dataset.from_list(pairs)

    tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
    model = AutoModelForCausalLM.from_pretrained(model_name_or_path, device_map="auto")

    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    training_args = TrainingArguments(
        output_dir=adapter_output_dir,
        num_train_epochs=1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=5e-5,
        fp16=True,
        save_strategy="no",
        logging_steps=10,
        remove_unused_columns=False,
    )

    trainer = DPOTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
        beta=0.1,
    )

    trainer.train()
    model.save_pretrained(adapter_output_dir)
    tokenizer.save_pretrained(adapter_output_dir)
    print(f"[trainer] Adapter saved to {adapter_output_dir}")
