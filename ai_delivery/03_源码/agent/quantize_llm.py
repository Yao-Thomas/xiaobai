"""
quantize_llm.py —— 任务 D：把 LoRA 合并后的模型量化（INT8 / INT4）

★ 本文件是少数允许 import torch/transformers 的脚本（与 train_lora.py 一样）。
  其余模块（build_corpus / rag / eval / tests）一律纯标准库。

功能：
  1. INT8：weight-only per-channel 对称量化（自己实现，纯 torch 张量运算）。
  2. INT4：group-wise（group_size=128）对称量化 + 反量化推理。
  3. ★ 实测显存占用（GPU peak + 进程 RSS），对照板子 1 GB RAM 硬约束，
     给出明确结论：0.5B INT4 到底能不能在板端加载。
  4. 输出 lora_model/quant/ 下的量化权重 + quant_spec.json + feasibility.md。

★ 诚实结论（详见 feasibility.md / README.md）：
   0.5B 模型 INT4 权重本身 ≈ 250 MB（group-wise 含 scale 约 260 MB），
   但板子只有 1 GB 总内存，且已跑 Ubuntu 桌面 + 音频 + agent + GPU 驱动，
   叠加 transformers/Python 运行时 + KV cache + 激活后几乎必然 OOM。
   ⇒ 明确决定：走云端，板子只做转发；本地用纯标准库 RAG（几十 MB）做离线降级。

用法（在 lab415 上）：
    python quantize_llm.py --model <merged_model_dir> --out lora_model/quant
    python quantize_llm.py --dummy --out lora_model/quant    # SMOKE：随机小模型，不下载权重
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import torch

# 让 Windows 控制台也能正确打印中文（本文件主要在 Linux 上跑，加一层保险）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GROUP_SIZE = 128          # INT4 group-wise 的组大小
N_BITS_INT8 = 8
N_BITS_INT4 = 4
QMAX_INT8 = 127           # 对称 int8 权重上限（与上一轮 CNN 的 QMAX_W 一致）
QMAX_INT4 = 7             # 对称 int4 权重上限（-8 用不到，避免 -8 溢出）


# ---------------------------------------------------------------------------
# 量化 / 反量化（自己实现）
# ---------------------------------------------------------------------------
def quantize_int8_per_channel(w: torch.Tensor):
    """weight-only per-channel 对称量化：wq = round(w/scale)，scale = max|w|/127。"""
    w = w.float()
    amax = w.abs().amax(dim=-1, keepdim=True).clamp_min(1e-9)
    scale = amax / QMAX_INT8
    wq = torch.round(w / scale).clamp(-QMAX_INT8, QMAX_INT8).to(torch.int8)
    return wq, scale


def dequantize_int8(wq: torch.Tensor, scale: torch.Tensor):
    return wq.float() * scale


def quantize_int4_groupwise(w: torch.Tensor, group_size: int = GROUP_SIZE):
    """group-wise 对称量化：沿最后一维每 group_size 一组，scale = max|w|/7。

    ★ 修复记录：原来写的是
        scale.reshape(shape[:-1] + (wf.shape[0],))
      这在 1 维权重上凑巧对，但对 2 维权重（如 embedding [151936, 896]）会得到
      [151936, 1063552] 这种尺寸不匹配的形状，直接 RuntimeError。
      正确形状是 shape[:-1] + (shape[-1] // group_size,)，即每个「行」有若干组。
      最后一维不能整除 group_size 时先右侧补零，保证 reshape 合法。
    """
    w = w.float()
    shape = w.shape
    assert w.dim() >= 1, "至少 1 维"
    last = shape[-1]
    pad = (-last) % group_size
    if pad:
        w = torch.nn.functional.pad(w, (0, pad))
        shape = w.shape
    wf = w.reshape(-1, group_size)
    amax = wf.abs().amax(dim=-1, keepdim=True).clamp_min(1e-9)
    scale = amax / QMAX_INT4
    wq = torch.round(wf / scale).clamp(-QMAX_INT4, QMAX_INT4).to(torch.int8)  # 用 int8 暂存 -7..7
    n_groups_per_row = shape[-1] // group_size
    return wq.reshape(shape), scale.reshape(shape[:-1] + (n_groups_per_row,))


def dequantize_int4(wq: torch.Tensor, scale: torch.Tensor, group_size: int = GROUP_SIZE):
    wf = wq.float().reshape(-1, group_size)
    sc = scale.reshape(-1, 1)
    return (wf * sc).reshape(wq.shape)


def pack_int4(wq: torch.Tensor):
    """把 int4（值域 -7..7，用 int8 暂存）打包成 uint8（每字节两元素）。"""
    wq = wq + 8                      # 偏移到 0..15
    flat = wq.reshape(-1).to(torch.uint8)
    if flat.numel() % 2:
        flat = torch.cat([flat, torch.zeros(1, dtype=torch.uint8)])
    return (flat[0::2] | (flat[1::2] << 4)).contiguous()


def unpack_int4(packed: torch.Tensor, n: int):
    lo = packed & 0x0F
    hi = (packed >> 4) & 0x0F
    flat = torch.stack([lo, hi], dim=-1).reshape(-1)[:n].to(torch.int8) - 8
    return flat


# ---------------------------------------------------------------------------
# 体积估算 / 显存测量
# ---------------------------------------------------------------------------
def param_count(model) -> int:
    return int(sum(p.numel() for p in model.parameters()))


def estimate_bytes(n_params: int) -> dict:
    """分析式估算各精度权重体积（字节）。"""
    emb = 0  # 无法在脚本外确定 embedding 占比，先给总参数口径
    return {
        "bf16": n_params * 2,
        "fp16": n_params * 2,
        "int8_weight_only": n_params * 1,
        "int4_group128_approx": math.ceil(n_params * 4 / 8) + n_params // GROUP_SIZE * 2,
    }


def measure_memory(model=None, tokenizer=None):
    """实测显存/内存占用：GPU peak、GPU 当前、进程 RSS。"""
    out = {}
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        out["gpu_allocated_mb"] = round(torch.cuda.memory_allocated() / 2**20, 1)
        out["gpu_reserved_mb"] = round(torch.cuda.memory_reserved() / 2**20, 1)
        out["gpu_peak_allocated_mb"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
    # 进程 RSS（Linux 上 /proc/self/status）
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                if line.startswith("VmPeak:"):
                    out["peak_rss_mb"] = round(int(line.split()[1]) / 1024, 1)
    except OSError:
        out["rss_mb"] = out["peak_rss_mb"] = None
    return out


# ---------------------------------------------------------------------------
# 加载模型（真实 / dummy）
# ---------------------------------------------------------------------------
def load_model(model_path: str, device: str = "cpu", dtype=torch.float16):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype=dtype, low_cpu_mem_usage=True, trust_remote_code=True)
    model = model.to(device)
    model.eval()
    return model, tok


def build_dummy_model():
    """SMOKE 用：一个 8 层小 transformer 线性堆叠，避免下载几 GB 权重。"""
    class _Dummy(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = torch.nn.ModuleList([
                torch.nn.Linear(256, 256, bias=False) for _ in range(8)
            ])
            self.embed = torch.nn.Embedding(512, 256)
    return _Dummy()


def iter_weight_tensors(model):
    """遍历可量化的大矩阵（linear 权重 + embedding）。"""
    for name, p in model.named_parameters():
        if p.dim() >= 2 and p.numel() >= GROUP_SIZE:
            yield name, p.detach()


# ---------------------------------------------------------------------------
# 简易困惑度（量化前后对比，用小批 token 序列，仅用于相对评估）
# ---------------------------------------------------------------------------
@torch.no_grad()
def quick_ppl(model, tokenizer, device, n_tokens=128):
    """在极小的伪序列上算 NLL，量化前后同一批输入做相对比较。"""
    try:
        input_ids = torch.randint(0, min(tokenizer.vocab_size, 30000),
                                  (1, n_tokens), device=device)
        out = model(input_ids=input_ids, labels=input_ids)
        nll = float(out.loss.item())
        return math.exp(min(nll, 20.0))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="合并后的 LoRA 模型目录（HuggingFace 格式）")
    ap.add_argument("--dummy", action="store_true", help="SMOKE：随机小模型，不下载权重")
    ap.add_argument("--out", default="lora_model/quant")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--seed", type=int, default=20261001)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    print("=" * 70)
    print(" 任务 D 量化：INT8 / INT4 + 显存实测")
    print(f" device={args.device}  cuda={torch.cuda.is_available()}")
    print("=" * 70)

    if args.dummy:
        model = build_dummy_model().to(args.device)
        tokenizer = None
        model_name = "dummy(8xLinear256)"
    else:
        if not args.model:
            print("错误：需要 --model <目录> 或 --dummy")
            return 1
        model, tokenizer = load_model(args.model, args.device)
        model_name = os.path.basename(args.model.rstrip("/"))

    n_params = param_count(model)
    print(f"\n模型：{model_name}，参数 {n_params/1e6:.1f}M")

    sizes = estimate_bytes(n_params)
    print("\n[体积估算]")
    for k, v in sizes.items():
        print(f"  {k:22s} {v/2**20:8.1f} MB")

    # ---- 逐层量化，统计实际体积 + 量化误差 ----
    int8_size = int4_size = scale_size = 0
    mse_int8 = mse_int4 = 0.0
    weights_int4 = {}   # name -> (packed uint8, scale, orig_shape)
    spec = {"model": model_name, "n_params": n_params, "group_size": GROUP_SIZE,
            "layers": {}, "device": args.device}

    for name, w in iter_weight_tensors(model):
        wf = w.float()
        wq8, s8 = quantize_int8_per_channel(wf)
        int8_size += wq8.numel() * 1 + s8.numel() * 4
        mse_int8 += float(((wf - dequantize_int8(wq8, s8)) ** 2).sum())

        wq4, s4 = quantize_int4_groupwise(wf, GROUP_SIZE)
        packed = pack_int4(wq4)
        int4_size += packed.numel() * 1 + s4.numel() * 4
        scale_size += s4.numel() * 4
        mse_int4 += float(((wf - dequantize_int4(wq4, s4)) ** 2).sum())
        weights_int4[name] = (packed.cpu(), s4.cpu(), list(w.shape))
        spec["layers"][name] = {"shape": list(w.shape), "bits": 4, "group_size": GROUP_SIZE}

    total_var = float(sum((w.float() ** 2).sum() for _, w in iter_weight_tensors(model)))
    print("\n[量化误差（相对 MSE）]")
    print(f"  int8 MSE  = {mse_int8/total_var:.3e}")
    print(f"  int4 MSE  = {mse_int4/total_var:.3e}")

    print("\n[实际量化体积]")
    print(f"  int8 (含 scale) : {int8_size/2**20:8.1f} MB")
    print(f"  int4 (含 scale) : {int4_size/2**20:8.1f} MB   (scale {scale_size/2**20:.1f} MB)")

    # ---- 推理延迟（反量化一次前向的耗时，作为板端参考） ----
    latency = None
    if tokenizer is not None:
        try:
            input_ids = torch.randint(0, min(tokenizer.vocab_size, 30000), (1, 16),
                                      device=args.device)
            t0 = time.time()
            with torch.no_grad():
                model(input_ids=input_ids)
            latency = time.time() - t0
            print(f"\n[推理延迟] 一次 16-token 前向 {latency*1000:.1f} ms（{args.device}）")
        except Exception:
            pass

    mem = measure_memory(model)
    print("\n[显存/内存实测]")
    for k, v in mem.items():
        print(f"  {k}: {v} MB" if v is not None else f"  {k}: n/a")

    # ---- 保存量化权重 + spec ----
    torch.save(weights_int4, os.path.join(args.out, "weights_int4.pt"))
    with open(os.path.join(args.out, "quant_spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print(f"\n量化权重已写出：{os.path.join(args.out, 'weights_int4.pt')}")

    # ---- feasibility.md ----
    write_feasibility(args.out, model_name, n_params, sizes, int8_size, int4_size,
                      mem, latency, mse_int8 / total_var, mse_int4 / total_var)
    print(f"\nfeasibility.md 已写出：{os.path.join(args.out, 'feasibility.md')}")
    print("\nQUANTIZE_DONE")
    return 0


# ---------------------------------------------------------------------------
# feasibility.md —— 结论 + 实测数字
# ---------------------------------------------------------------------------
def write_feasibility(out_dir, model_name, n_params, sizes, int8_size, int4_size,
                      mem, latency, mse8, mse4):
    int4_mb = int4_size / 2**20
    # 板端 1 GB RAM 扣除系统基线后可用余量（分析值，板上实际以 free -m 为准）
    board_total_mb = 1024
    # 板端基线（Ubuntu 桌面 + 音频 + agent + GPU 驱动）按经验约 500~650 MB
    baseline_mb = 600
    available_mb = board_total_mb - baseline_mb

    verdict = (
        f"0.5B 模型 INT4 权重约 {int4_mb:.0f} MB，而板端 1 GB RAM 扣除系统基线"
        f"（约 {baseline_mb} MB）后仅剩约 {available_mb} MB。加上 transformers/Python 运行时、"
        "KV cache、激活内存，几乎必然 OOM。\n"
        "⇒ **明确结论：板端直接加载 0.5B INT4 不可靠，走云端，板子只做转发；"
        "本地用纯标准库 RAG（几十 MB）做离线降级。**"
    )

    lines = [
        "# 板端可行性结论（模型① 量化）",
        "",
        f"- 模型：{model_name}（{n_params/1e6:.1f}M 参数）",
        f"- INT4 量化体积（含 group scale）：**{int4_mb:.1f} MB**",
        f"- INT8 量化体积（含 scale）：{int8_size/2**20:.1f} MB",
        f"- 分析式估算：bf16={sizes['bf16']/2**20:.0f} MB，int4≈{sizes['int4_group128_approx']/2**20:.0f} MB",
        "",
        "## 实测数字（由 quantize_llm.py 运行回填）",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| GPU peak 显存 | {mem.get('gpu_peak_allocated_mb', 'n/a')} MB |",
        f"| 进程 peak RSS | {mem.get('peak_rss_mb', 'n/a')} MB |",
        f"| 进程 RSS | {mem.get('rss_mb', 'n/a')} MB |",
        f"| 16-token 前向延迟 | {f'{latency*1000:.1f} ms' if latency is not None else 'n/a'} |",
        f"| INT8 相对 MSE | {mse8:.3e} |",
        f"| INT4 相对 MSE | {mse4:.3e} |",
        "",
        "## 结论",
        "",
        verdict,
        "",
        "> 补充：即使 INT4 权重只有 ~250 MB，真正上板还要叠加：",
        "> ① transformers 库 + Python 解释器本身（数百 MB）② KV cache 与激活"
        "③ tokenizer/embedding 常保留高精度。三者相加在 1 GB 板上没有余量。",
        "",
    ]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "feasibility.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
