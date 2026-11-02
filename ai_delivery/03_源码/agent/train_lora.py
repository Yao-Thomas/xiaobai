"""
train_lora.py —— 任务 D：LoRA 微调 Qwen2.5-0.5B-Instruct（本地 agent 小模型）

★ 本文件是少数允许 import torch/transformers/peft 的脚本。
★ 环境（lab415）：torch 2.5.1+cu118 / transformers 4.46.3 / peft 0.13.2 / datasets 3.1.0。
★ 模型缓存强制放到 /data（根分区 100% 满，不能用默认 ~/.cache）。

数据：build_corpus.py 产出的 lora_data/{train,val}.jsonl（sharegpt 风格：
    {"conversations":[{"from":"human","value":...},{"from":"gpt","value":...}], "source":...}）

用法：
    python train_lora.py --data lora_data --out lora_model --epochs 3
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import time

# ★ 必须先设置镜像与缓存，再 import transformers（否则会去访问默认 ~/.cache）
_HF_CACHE = os.environ.get("HF_HOME", "/data/pengyc_fzu/fpga2026_ai/.cache/hf")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", _HF_CACHE)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(_HF_CACHE, "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(_HF_CACHE, "hub"))
# ★ 容错：在没有 /data 的机器（比如 Windows 开发机）上 import 本模块不应该直接崩，
#   否则连 to_messages() 这种纯函数都没法单测。真正训练时目标路径一定可写。
try:
    os.makedirs(_HF_CACHE, exist_ok=True)
except OSError:
    pass

import torch  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments,
    DataCollatorForSeq2Seq)
from datasets import Dataset  # noqa: E402
from peft import LoraConfig, get_peft_model, TaskType  # noqa: E402

SYSTEM_PROMPT = (
    "你是「系统管家小白」，一个运行在 Zynq-7020 开发板上的自主助手。"
    "你只依据项目资料回答 FPGA/音频/示波器/CNN 等相关问题；"
    "资料里没有答案的，要明确说“这个问题不在我的知识范围内”。"
)

DEFAULT_BASE = "Qwen/Qwen2.5-0.5B-Instruct"


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def to_messages(conv):
    """sharegpt(human/gpt) → Qwen chat 消息列表。

    ★ 兼容两种入参（第一版这里踩了坑，导致真机上直接 TypeError）：
      · 整条记录 {"conversations": [...], ...}
      · 直接就是会话列表 [...]
    """
    if isinstance(conv, dict):
        conv = conv["conversations"]
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in conv:
        role = "user" if m["from"] == "human" else "assistant"
        msgs.append({"role": role, "content": m["value"]})
    return msgs


def tokenize_fn(examples, tokenizer, max_len):
    """逐条用 chat template 编码，仅对 assistant 段计算 loss（其余 labels=-100）。

    依赖 Qwen2.5 的 chat template 特殊 token（<|im_start|> / <|im_end|>）定位 assistant 段；
    若 tokenizer 不含这些标记则退化为"整段都参与 loss"（仍可训练，只是略次优）。
    """
    input_ids, labels = [], []
    im_start = im_end = None
    try:
        im_start = tokenizer.convert_tokens_to_ids("<|im_start|>")
        im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
    except Exception:
        pass

    for msgs in examples["messages"]:
        ids = tokenizer.apply_chat_template(
            msgs, tokenize=True, add_generation_prompt=False,
            truncation=True, max_length=max_len)
        # ★ transformers 5.x 的 apply_chat_template(tokenize=True) 返回的是
        #   **dict/BatchEncoding**（{'input_ids': [...], 'attention_mask': [...]}），
        #   而不是 4.x 的 list[int]。直接迭代会拿到字符串键名 'input_ids'
        #   ⇒ 必须先判断类型再取值。这是本项目在 5.x 上踩的第 4 个 API 变更。
        if hasattr(ids, "keys") and not isinstance(ids, (list, tuple)):
            ids = ids["input_ids"]
        if hasattr(ids, "tolist"):
            ids = ids.tolist()
        if isinstance(ids, str):
            ids = tokenizer.encode(ids, add_special_tokens=False)
        while ids and isinstance(ids[0], (list, tuple, dict)):
            ids = ids[0]
        if hasattr(ids, "keys"):
            ids = ids["input_ids"]
        ids = [int(t) for t in ids]
        lab = [-100] * len(ids)
        if im_start is not None and im_end is not None and im_start in ids:
            i = 0
            while i < len(ids):
                if ids[i] == im_start and i + 1 < len(ids):
                    role = tokenizer.decode([ids[i + 1]]).strip()
                    j = i + 2
                    while j < len(ids) and ids[j] != im_end:
                        j += 1
                    if "assistant" in role:
                        lab[i + 2:j] = ids[i + 2:j]
                    i = j + 1
                else:
                    i += 1
        else:
            lab = list(ids)   # 退化：整段参与 loss
        input_ids.append(ids)
        labels.append(lab)
    # ★ 显式给出 attention_mask：transformers 5.x 的 DataCollatorForSeq2Seq
    #   在缺少它时会抛 "type of {...} unknown: <class 'dict'>"
    return {"input_ids": input_ids,
            "attention_mask": [[1] * len(x) for x in input_ids],
            "labels": labels}


class PadCollator:
    """
    ★ 自己写一个与版本无关的 padding collator。

    为什么不用 `DataCollatorForSeq2Seq`：transformers 5.x 改了 collator 的调用约定
    （会把整批当 dict 传给 tokenizer.pad，直接抛
     `ValueError: type of {...} unknown: <class 'dict'>`）。
    这里手工右侧补齐，4.x / 5.x 行为完全一致，也便于板端对齐。
    """

    def __init__(self, pad_token_id=0):
        self.pad_token_id = pad_token_id

    def __call__(self, features):
        # ★ 容错：无论上游给了什么列，只取这三列并强制成 int
        def _ints(v):
            if hasattr(v, "tolist"):
                v = v.tolist()
            if isinstance(v, str):
                raise ValueError("collator 收到字符串而非 token id")
            if v and isinstance(v[0], (list, tuple)):
                v = list(v[0])
            return [int(t) for t in v]

        maxlen = max(len(_ints(f["input_ids"])) for f in features)
        ids, am, lb = [], [], []
        for f in features:
            ii = _ints(f["input_ids"])
            n = maxlen - len(ii)
            ids.append(ii + [self.pad_token_id] * n)
            aa = _ints(f["attention_mask"]) if "attention_mask" in f else [1] * len(ii)
            am.append(aa + [0] * n)
            ll = _ints(f["labels"]) if "labels" in f else [-100] * len(ii)
            lb.append(ll + [-100] * n)
        return {
            "input_ids": torch.tensor(ids, dtype=torch.long),
            "attention_mask": torch.tensor(am, dtype=torch.long),
            "labels": torch.tensor(lb, dtype=torch.long),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="lora_data")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out", default="lora_model")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=20261001)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    print("=" * 70)
    print(" 任务 D：LoRA 微调  base=%s" % args.base)
    print(f" data={args.data}  epochs={args.epochs}  lr={args.lr}  seed={args.seed}")
    print(f" HF cache={_HF_CACHE}  endpoint={os.environ['HF_ENDPOINT']}")
    print("=" * 70)

    tokenizer = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_rows = load_jsonl(os.path.join(args.data, "train.jsonl"))
    val_rows = load_jsonl(os.path.join(args.data, "val.jsonl"))
    print(f"训练 {len(train_rows)} 条 / 验证 {len(val_rows)} 条")

    def prep(rows):
        return Dataset.from_list([{"messages": to_messages(r["conversations"])} for r in rows])

    ds_train = prep(train_rows)
    ds_val = prep(val_rows)

    def tok(examples):
        return tokenize_fn(examples, tokenizer, args.max_len)
    ds_train = ds_train.map(tok, batched=True, remove_columns=["messages"])
    ds_val = ds_val.map(tok, batched=True, remove_columns=["messages"])

    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, trust_remote_code=True)
    model.enable_input_require_grads()

    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.r, lora_alpha=args.alpha, lora_dropout=args.dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        bias="none",
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    # ★ 兼容 transformers 4.x / 5.x：
    #   5.x 把 `warmup_ratio` 删掉了（只留 `warmup_steps`），
    #   直接传会 TypeError。这里按实际签名过滤，两代都能跑。
    n_steps = max(1, (772 // max(1, args.batch * args.grad_accum)) * args.epochs)
    _kw = dict(
        output_dir=os.path.join(args.out, "checkpoint"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        warmup_ratio=0.03,
        warmup_steps=max(1, int(0.03 * n_steps)),
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="epoch",
        bf16=True,
        seed=args.seed,
        report_to=[],
    )
    try:
        _accepted = set(inspect.signature(TrainingArguments.__init__).parameters)
        _drop = [k for k in _kw if k not in _accepted]
        for k in _drop:
            print("  [兼容] TrainingArguments 不接受 %s，已丢弃" % k)
            _kw.pop(k)
    except Exception:
        _kw.pop("warmup_ratio", None)
    training_args = TrainingArguments(**_kw)

    trainer = Trainer(
        model=model, args=training_args,
        train_dataset=ds_train, eval_dataset=ds_val,
        data_collator=PadCollator(pad_token_id=getattr(tokenizer, "pad_token_id", 0) or 0),
    )
    t0 = time.time()
    trainer.train()
    print(f"训练耗时 {time.time()-t0:.0f} s")

    # 保存 adapter + 合并模型
    trainer.model.save_pretrained(os.path.join(args.out, "adapter"))
    tokenizer.save_pretrained(os.path.join(args.out, "adapter"))
    merged = trainer.model.merge_and_unload()
    merged.save_pretrained(os.path.join(args.out, "merged"))
    tokenizer.save_pretrained(os.path.join(args.out, "merged"))

    hyper = {
        "base": args.base, "epochs": args.epochs, "batch": args.batch,
        "grad_accum": args.grad_accum, "lr": args.lr, "max_len": args.max_len,
        "lora_r": args.r, "lora_alpha": args.alpha, "dropout": args.dropout,
        "seed": args.seed, "n_train": len(train_rows), "n_val": len(val_rows),
        "system_prompt": SYSTEM_PROMPT,
    }
    with open(os.path.join(args.out, "hyper.json"), "w", encoding="utf-8") as f:
        json.dump(hyper, f, ensure_ascii=False, indent=2)
    print(f"adapter → {os.path.join(args.out, 'adapter')}")
    print(f"merged  → {os.path.join(args.out, 'merged')}")
    print("TRAIN_LORA_DONE")


if __name__ == "__main__":
    main()
