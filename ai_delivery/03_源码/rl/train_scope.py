"""train_scope.py —— 训练示波器自动设置策略 + 自动验收

流程：
  [1] 训练 PPO（actor=量化 MLP，QAT，训练前向即整数前向）
  [2] 保存 checkpoint + 超参 json（可复现）
  [3] 验收：对 正弦/方波/三角/锯齿/噪声 五种输入各测 N 次随机初值，
      报告成功率与平均回报（用确定性 argmax 策略）

用法：
  python train_scope.py --smoke                       # 冒烟（小规模）
  python train_scope.py --total-steps 300000 --out runs/scope_v1
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import torch

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 保证 Windows 控制台也能打印中文（远端 Linux 本身是 UTF-8，此调用为 no-op）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from scope_env import (ScopeEnv, WAVE_NAMES, OBS_DIM, DEFAULT_WEIGHTS,      # noqa: E402
                       N_TRIG, N_DEC, N_VGAIN)
from ppo import PolicyMLP, ValueMLP, PPO, set_seed                          # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--total-steps", type=int, default=300000)
    ap.add_argument("--num-envs", type=int, default=16)
    ap.add_argument("--num-steps", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--ent-coef", type=float, default=0.01)
    ap.add_argument("--hidden", type=int, nargs="+", default=[64, 64])
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--out", type=str, default="runs/scope_policy_v1")
    ap.add_argument("--device", type=str, default="auto")
    ap.add_argument("--n-accept", type=int, default=50)
    ap.add_argument("--success-bonus", type=float, default=60.0,
                    help="成功的一次性奖励。★ 必须足够大：整局回报约 25，"
                         "给 3.0 时策略会忽略成功（实测成功率 0.03~0.24）；"
                         "给 60 才压得住每步的加权和。")
    ap.add_argument("--success-threshold", type=float, nargs=3,
                    default=[0.9, 0.8, 0.9])
    ap.add_argument("--smoke", action="store_true", help="冒烟：小规模快速跑通")
    ap.add_argument("--init", type=str, default="",
                    help="从已有 checkpoint 继续训练（形如 runs/xxx/model_final.pt）；"
                         "只加载 actor+critic 权重，超参仍按本次命令行给的来")
    return ap


@torch.no_grad()
def acceptance(actor, device, n: int, max_steps: int, seed: int,
               success_bonus: float = 60.0, success_threshold=(0.9, 0.8, 0.9)):
    """五种输入各测 n 次随机初值，报告成功率/平均回报/平均步数。"""
    results = []
    for wave in range(5):
        succ = 0
        tot_reward = 0.0
        tot_steps = 0
        for i in range(n):
            env = ScopeEnv(fixed_wave=wave, seed=seed * 100003 + wave * 10007 + i,
                           max_steps=max_steps, success_bonus=success_bonus,
                           success_threshold=success_threshold)
            obs = env.reset()
            done = False
            ep_reward = 0.0
            while not done:
                obs_t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
                actions, _, _ = actor.act(obs_t, deterministic=True)
                act = torch.stack(actions, dim=1).cpu().numpy()[0]
                obs, r, done, info = env.step(act)
                ep_reward += r
            if info["success"]:
                succ += 1
            tot_reward += ep_reward
            tot_steps += info["steps"]
        results.append(dict(wave=WAVE_NAMES[wave], wave_idx=wave,
                            success_rate=succ / n, mean_reward=tot_reward / n,
                            mean_steps=tot_steps / n, n=n))
    return results


def main():
    args = build_parser().parse_args()
    if args.smoke:
        args.total_steps = min(args.total_steps, 4096)
        args.num_envs = 4
        args.num_steps = 32
        args.n_accept = 10

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    set_seed(args.seed)
    print("torch=%s device=%s" % (torch.__version__, device))
    print("obs_dim=%d action_nvec=%s" % (OBS_DIM, (N_TRIG, N_DEC, N_VGAIN)))

    actor = PolicyMLP(OBS_DIM, (N_TRIG, N_DEC, N_VGAIN), hidden=tuple(args.hidden))
    critic = ValueMLP(OBS_DIM, hidden=tuple(args.hidden))

    _counter = [0]

    def make_env():
        _counter[0] += 1
        return ScopeEnv(seed=args.seed + _counter[0] * 1009, max_steps=args.max_steps,
                    success_bonus=args.success_bonus,
                    success_threshold=tuple(args.success_threshold))

    # ★ 续训：从已有 checkpoint 加载 actor+critic
    if args.init:
        ck = torch.load(args.init, map_location=device)
        actor.load_state_dict(ck["actor"])
        try:
            critic.load_state_dict(ck["critic"])
        except Exception as e:
            print("  [warn] critic 未加载:", e)
        print("### 已从 %s 续训（actor+critic）" % args.init)

    ppo = PPO(actor, critic, lr=args.lr, ent_coef=args.ent_coef, device=device)
    print("### 开始训练 PPO ...")
    ppo.train(make_env, args.total_steps, args.num_envs, args.num_steps,
              args.out, args.seed, log_interval=1)

    # ---- 保存超参（供 quantize_policy.py 重建网络）----
    hyper = dict(
        task="scope_autoset",
        obs_dim=OBS_DIM,
        action_nvec=[N_TRIG, N_DEC, N_VGAIN],
        hidden=list(args.hidden),
        seed=args.seed,
        lr=args.lr,
        ent_coef=args.ent_coef,
        total_steps=args.total_steps,
        num_envs=args.num_envs,
        num_steps=args.num_steps,
        max_steps=args.max_steps,
        success_bonus=args.success_bonus,
        success_threshold=list(args.success_threshold),
        init_from=(args.init or None),
        weights=list(DEFAULT_WEIGHTS),
        device=device,
        torch_version=torch.__version__,
    )
    with open(os.path.join(args.out, "hyperparams.json"), "w", encoding="utf-8") as f:
        json.dump(hyper, f, ensure_ascii=False, indent=2)

    # ---- 验收 ----
    actor.eval()
    print("\n### 验收：五种输入 × %d 次随机初值（确定性策略）" % args.n_accept)
    res = acceptance(actor, device, args.n_accept, args.max_steps, args.seed,
                     success_bonus=args.success_bonus,
                     success_threshold=tuple(args.success_threshold))
    for r in res:
        print("  %-8s 成功率=%5.1f%%  平均回报=%+.3f  平均步数=%.2f"
              % (r["wave"], 100.0 * r["success_rate"], r["mean_reward"], r["mean_steps"]))
    overall = float(np.mean([r["success_rate"] for r in res]))
    print("  整体成功率 = %.1f%%" % (100.0 * overall))
    with open(os.path.join(args.out, "acceptance.json"), "w", encoding="utf-8") as f:
        json.dump(dict(results=res, overall_success_rate=overall), f,
                  ensure_ascii=False, indent=2)
    print("checkpoint -> %s" % args.out)


if __name__ == "__main__":
    main()
