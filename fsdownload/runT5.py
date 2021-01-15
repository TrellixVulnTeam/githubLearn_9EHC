import functools
import t5
import torch
import transformers
import os

if torch.cuda.is_available():
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # 只看到第2块gpu
    device = torch.device("cuda")
    print("gpu.....")
else:
    device = torch.device("cpu")
    print("cpu....")

model = t5.models.HfPyTorchModel("t5-base", "/tmp/hft5/", device)

# Evaluate the pre-trained checkpoint, before further fine-tuning
model.eval(
    "glue_mrpc_v002",
    sequence_length={"inputs": 64, "targets": 4},
    batch_size=128,
)

# Run 1000 steps of fine-tuning
model.train(
    mixture_or_task_name="glue_mrpc_v002",
    steps=1000,
    save_steps=100,
    sequence_length={"inputs": 64, "targets": 4},
    split="train",
    batch_size=32,
    optimizer=functools.partial(transformers.AdamW, lr=1e-4),
)

# Evaluate after fine-tuning
model.eval(
    "glue_mrpc_v002",
    checkpoint_steps="all",
    sequence_length={"inputs": 64, "targets": 4},
    batch_size=128,
)

# Generate some predictions
inputs = [
    "cola sentence: This is a totally valid sentence.",
    "cola sentence: A doggy detail was walking famously.",
]
model.predict(
    inputs,
    sequence_length={"inputs": 32},
    batch_size=2,
    output_file="/hft5/example_predictions.txt",
)