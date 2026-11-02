#!/usr/bin/env python3
"""
bc_warmstart.py —— ★ 用 ORACLE 做行为克隆预热（warm start），再用同样的 PPO 目标微调

为什么需要它（实测依据）：
  · ORACLE（穷举 1280 个动作）成功率 **0.983** ⇒ 任务可达
  · 但从零 PPO 在 30 万步只能到 58%（success_bonus=60/200 都 plateau）
  ⇒ 说明**探索**是瓶颈，不是任务难度、也不是回报公式。

做法（**完全不改任务书规定的回报公式**）：
  1. 用 oracle 在大量随机工况上算出"最优动作"，得到 (观测 → 动作) 监督数据；
     ★ oracle 在**采数据时**可以用特权信息（真实 f、amp），
       但**策略本身只看 74 维观测** —— 这就是标准的模仿学习设定；
  2. 用交叉熵把 actor 的三个头预训练到能复现 oracle 的决策；
  3. 存成 checkpoint，交给 train_scope.py 用**同一套 PPO 目标**继续微调。

用法：
  python bc_warmstart.py --n 30000 --out runs/scope_bc --gpu 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import scope_env as SE                                     # noqa: E402
from ppo import PolicyMLP, set_seed                        # noqa: E402


def oracle_best_action(env: SE.ScopeEnv, rng=None):
    """
    穷举全部 (dec, vgain, trig)，返回 (best_action, best_reward)

    ★ 注意：这里用到了 env.f_hz / env.wave_kind 等特权信息（算 K 需要）。
      这是"老师"的视角，只在造监督数据时使用。

    ★★ 平局处理很重要：满足成功判据的动作常常**有很多个**
      （例如 trig 取 119 或 136 都行）。如果永远取"遍历到的第一个"，
      监督标签就带有系统性偏置，BC 会去拟合一个并不唯一的目标。
      所以这里**在所有并列最优的动作里随机取一个**。
    """
    th0, th1, th2 = env.success_threshold
    dec0, vg0 = env.dec_idx, env.vgain_idx      # 保证不改变"当前设置"以外的状态
    best_key = None
    ties = []
    try:
        for di, dec in enumerate(SE.DEC_LEVELS):
            for vi, vg in enumerate(SE.VGAIN_LEVELS):
                env.dec_idx, env.vgain_idx = di, vi
                s = env._capture()
                for ti, trig in enumerate(SE.TRIG_LEVELS):
                    r = SE.compute_scope_reward(s, float(trig), dec,
                                                env.wave_kind, env.f_hz, env.weights)
                    succ = (r["t_occupy"] >= th0 and r["t_center"] >= th1
                            and r["t_cycles"] >= th2 and r["triggered"])
                    key = (1 if succ else 0, round(r["reward"], 6))
                    if best_key is None or key > best_key:
                        best_key = key
                        ties = [((ti, di, vi), r)]
                    elif key == best_key:
                        ties.append(((ti, di, vi), r))
    finally:
        env.dec_idx, env.vgain_idx = dec0, vg0
    pick = ties[0] if (rng is None or len(ties) == 1) else ties[int(rng.integers(len(ties)))]
    return pick[0], pick[1]


def collect(env: SE.ScopeEnv, n: int, log_every: int = 2000):
    """采样 n 条 (obs, 最优动作)"""
    obs_buf, act_buf, succ_buf = [], [], []
    t0 = time.time()
    for i in range(n):
        env.reset()
        # ★ 随机化"当前设置"，让策略学会从任意状态出发决策（不只是初始状态）
        env.dec_idx = int(env.rng.integers(0, SE.N_DEC))
        env.vgain_idx = int(env.rng.integers(0, SE.N_VGAIN))
        obs = env._obs()
        a, r = oracle_best_action(env, rng=env.rng)
        obs_buf.append(obs)
        act_buf.append(a)
        succ_buf.append(1.0 if (r["t_occupy"] >= env.success_threshold[0]
                                and r["t_center"] >= env.success_threshold[1]
                                and r["t_cycles"] >= env.success_threshold[2]
                                and r["triggered"]) else 0.0)
        if log_every and (i + 1) % log_every == 0:
            print("    采数据 %5d/%d  %.0fs  oracle 可行率 %.3f"
                  % (i + 1, n, time.time() - t0, float(np.mean(succ_buf))), flush=True)
    return (np.asarray(obs_buf, dtype=np.float32),
            np.asarray(act_buf, dtype=np.int64),
            np.asarray(succ_buf, dtype=np.float32))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--hidden", type=int, nargs="+", default=[64, 64])
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--out", type=str, default="runs/scope_bc")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--data", type=str, default="", help="已有 npz 就直接用，不重采")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    dev = "cuda:%d" % args.gpu if torch.cuda.is_available() else "cpu"
    set_seed(args.seed)

    npz = args.data or os.path.join(args.out, "bc_data.npz")
    if os.path.exists(npz):
        d = np.load(npz)
        X, Y, S = d["obs"], d["act"], d["succ"]
        print("复用已有监督数据:", npz, X.shape)
    else:
        env = SE.ScopeEnv(seed=args.seed)
        print("=== 用 oracle 采监督数据 %d 条 ===" % args.n)
        X, Y, S = collect(env, args.n)
        np.savez_compressed(npz, obs=X, act=Y, succ=S)
        print("已存:", npz)

    print("oracle 可达率 = %.4f（这就是模仿学习的上界）" % float(S.mean()))

    Xt = torch.as_tensor(X, device=dev)
    Yt = torch.as_tensor(Y, device=dev)
    ntr = int(len(Xt) * 0.9)
    tr = torch.arange(ntr)
    va = torch.arange(ntr, len(Xt))

    actor = PolicyMLP(SE.OBS_DIM, (SE.N_TRIG, SE.N_DEC, SE.N_VGAIN),
                      hidden=tuple(args.hidden)).to(dev)
    opt = torch.optim.AdamW(actor.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=args.lr,
        total_steps=max(1, args.epochs * max(1, ntr // args.batch)), pct_start=0.2)

    print("=== 行为克隆训练 ===")
    for ep in range(args.epochs):
        actor.train()
        perm = torch.randperm(ntr, device=dev)
        tot = cor = 0
        for i in range(0, ntr, args.batch):
            b = perm[i:i + args.batch]
            logits = actor(Xt[b])
            loss = sum(F.cross_entropy(logits[h], Yt[b, h]) for h in range(3))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(actor.parameters(), 5.0)
            opt.step()
            try:
                sched.step()
            except Exception:
                pass
            pred = torch.stack([logits[h].argmax(1) for h in range(3)], 1)
            cor += int((pred == Yt[b]).all(1).sum())
            tot += len(b)
        if (ep + 1) % 5 == 0 or ep == 0:
            actor.eval()
            with torch.no_grad():
                pv = torch.stack([actor(Xt[va])[h].argmax(1) for h in range(3)], 1)
                acc = float((pv == Yt[va]).all(1).float().mean())
                per = [float((pv[:, h] == Yt[va, h]).float().mean()) for h in range(3)]
            print("  ep%3d train=%.4f  val(三头全对)=%.4f  单头=%s"
                  % (ep + 1, cor / tot, acc, [round(x, 3) for x in per]), flush=True)

    ckpt = os.path.join(args.out, "bc_actor.pt")
    torch.save(actor.state_dict(), ckpt)
    json.dump({"n": int(args.n), "oracle_feasible": float(S.mean()),
               "val_all_head_acc": acc, "hidden": list(args.hidden),
               "obs_dim": SE.OBS_DIM, "seed": args.seed},
              open(os.path.join(args.out, "bc_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n预热模型 ->", ckpt)
    print("BC_V2_DONE")


if __name__ == "__main__":
    main()
