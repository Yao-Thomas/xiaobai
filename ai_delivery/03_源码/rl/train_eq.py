"""train_eq.py —— 训练音频 EQ 调优策略 + 平坦度报告

流程：
  [1] 训练 PPO（actor=量化 MLP，QAT）
  [2] 保存 checkpoint + 超参 json
  [3] 报告：初始频响 vs 调完后频响的 RMS 误差（dB），要"明显改善"
        · 标称房间（固定工况，可复现）：初始 RMS vs 调完 RMS
        · N 个随机房间：平均初始 RMS vs 平均调完 RMS

用法：
  python train_eq.py --smoke
  python train_eq.py --total-steps 300000 --out runs/eq_v1
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

from audio_eq_env import (AudioEqEnv, OBS_DIM_EQ, N_BANDS, N_GAIN,           # noqa: E402
                          DEFAULT_ROOM, rms_db_error)
from ppo import PolicyMLP, ValueMLP, PPO, set_seed                          # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--total-steps", type=int, default=200000)
    ap.add_argument("--num-envs", type=int, default=16)
    ap.add_argument("--num-steps", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--ent-coef", type=float, default=0.02)
    ap.add_argument("--w-gain", type=float, default=0.02)
    ap.add_argument("--hidden", type=int, nargs="+", default=[64, 64])
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--out", type=str, default="runs/eq_policy_v1")
    ap.add_argument("--device", type=str, default="auto")
    ap.add_argument("--n-rooms", type=int, default=20)
    ap.add_argument("--smoke", action="store_true", help="冒烟：小规模快速跑通")
    return ap


def _run_policy_once(actor, device, env, max_steps):
    """在给定 env 上跑确定性策略，返回 (最终 rms_err, 最终 gains_db, 回报)。"""
    obs = env.reset()
    done = False
    ep_reward = 0.0
    while not done:
        obs_t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
        actions, _, _ = actor.act(obs_t, deterministic=True)
        act = torch.stack(actions, dim=1).cpu().numpy()[0]
        obs, r, done, info = env.step(act)
        ep_reward += r
    return info["rms_err"], info["gains_db"], ep_reward


@torch.no_grad()
def report(actor, device, n_rooms, max_steps, seed):
    actor.eval()
    # 标称房间（固定，可复现）
    nom_env = AudioEqEnv(randomize_room=False, seed=seed, max_steps=max_steps)
    initial_resp = nom_env._measure()[0]
    initial_rms = rms_db_error(initial_resp)
    final_rms, final_gains, _ = _run_policy_once(actor, device, nom_env, max_steps)

    # N 个随机房间
    init_list, final_list = [], []
    for i in range(n_rooms):
        env = AudioEqEnv(randomize_room=True, seed=seed * 100003 + i,
                         max_steps=max_steps)
        init_rms = rms_db_error(env._measure()[0])
        f_rms, _, _ = _run_policy_once(actor, device, env, max_steps)
        init_list.append(init_rms)
        final_list.append(f_rms)

    return dict(
        nominal=dict(initial_rms=initial_rms, final_rms=final_rms,
                     improvement=initial_rms - final_rms, gains_db=final_gains.tolist()),
        random_rooms=dict(
            mean_initial_rms=float(np.mean(init_list)),
            mean_final_rms=float(np.mean(final_list)),
            mean_improvement=float(np.mean(init_list) - np.mean(final_list)),
            n=n_rooms),
    )


def main():
    args = build_parser().parse_args()
    if args.smoke:
        args.total_steps = min(args.total_steps, 4096)
        args.num_envs = 4
        args.num_steps = 32
        args.n_rooms = 4

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    set_seed(args.seed)
    print("torch=%s device=%s" % (torch.__version__, device))
    print("obs_dim=%d action_nvec=%s" % (OBS_DIM_EQ, (N_GAIN,) * N_BANDS))

    actor = PolicyMLP(OBS_DIM_EQ, (N_GAIN,) * N_BANDS, hidden=tuple(args.hidden))
    critic = ValueMLP(OBS_DIM_EQ, hidden=tuple(args.hidden))

    _counter = [0]

    def make_env():
        _counter[0] += 1
        return AudioEqEnv(seed=args.seed + _counter[0] * 1013,
                          max_steps=args.max_steps, w_gain=args.w_gain)

    ppo = PPO(actor, critic, lr=args.lr, ent_coef=args.ent_coef, device=device)
    print("### 开始训练 PPO ...")
    ppo.train(make_env, args.total_steps, args.num_envs, args.num_steps,
              args.out, args.seed, log_interval=1)

    hyper = dict(
        task="audio_eq",
        obs_dim=OBS_DIM_EQ,
        action_nvec=[N_GAIN] * N_BANDS,
        hidden=list(args.hidden),
        seed=args.seed,
        lr=args.lr,
        ent_coef=args.ent_coef,
        w_gain=args.w_gain,
        total_steps=args.total_steps,
        num_envs=args.num_envs,
        num_steps=args.num_steps,
        max_steps=args.max_steps,
        device=device,
        torch_version=torch.__version__,
    )
    with open(os.path.join(args.out, "hyperparams.json"), "w", encoding="utf-8") as f:
        json.dump(hyper, f, ensure_ascii=False, indent=2)

    print("\n### 验收：初始频响 vs 调完后频响（平坦度）")
    rep = report(actor, device, args.n_rooms, args.max_steps, args.seed)
    nom = rep["nominal"]
    rr = rep["random_rooms"]
    print("  标称房间  : 初始 RMS=%.2f dB -> 调完 RMS=%.2f dB （改善 %.2f dB）"
          % (nom["initial_rms"], nom["final_rms"], nom["improvement"]))
    print("  随机房间  : 平均初始 RMS=%.2f dB -> 平均调完 RMS=%.2f dB （改善 %.2f dB, n=%d）"
          % (rr["mean_initial_rms"], rr["mean_final_rms"], rr["mean_improvement"], rr["n"]))
    with open(os.path.join(args.out, "acceptance.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print("checkpoint -> %s" % args.out)


if __name__ == "__main__":
    main()
