"""ppo.py —— 从零实现的 PPO（Proximal Policy Optimization）

=============================================================================
★ 为什么不依赖 stable-baselines3（没装）：这里手写 PPO，含 GAE、clip、熵正则、
  学习率退火、优势归一化、checkpoint。

★ 策略网络（actor）= 浮点 MLP，激活用 HardTanh（clamp[-1,1]）
  为什么用 HardTanh 而不是 tanh/ReLU：
    · 本项目量化方案（红线，沿用波形识别模型）是
        acc = Σ x_q · w_q              （int8 × int8 -> int32）
        out = sat((acc × MFQ) >> 16)   （算术右移=floor，饱和到 [-128,127]）
      "sat" 即硬饱和。HardTanh 的输出正是 [-1,1] 的硬饱和，
      => 浮点前向与整数前向【逐位同构】（量化零损失，见 quantize_policy.py）。
    · 无偏置（bias=False）：HLS 的 cnn_fc_q 不读偏置，与波形识别模型一致。
    · 实测比 tanh / QAT 收敛更快（见 README §算法）。

★ 动作空间：因子化离散（factorized categorical）
  actor 输出多个独立的 Categorical 头（每个因子一个），log_prob = 各头之和。
  示波器 = 16(触发电平) + 16(DEC) + 5(增益) = 37 个 logits（而非 1280 笛卡尔积）；
  EQ = 8 段 × 9 档 = 72 个 logits（而非 9^8≈4300 万）。
=============================================================================
"""
from __future__ import annotations

import json
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical


# ---------------------------------------------------------------------------
# 随机种子（可复现）
# ---------------------------------------------------------------------------
def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ---------------------------------------------------------------------------
# 策略网络（actor，部署对象；float + HardTanh，量化零损失）
# ---------------------------------------------------------------------------
class PolicyMLP(nn.Module):
    """因子化离散动作的策略网络。

    obs ∈ [-1,1] -> Linear(bias=False) + HardTanh 若干层 -> 每因子一个 Linear 头
    输出 logits。HardTanh(clamp[-1,1]) 与量化方案的 sat[-128,127] 逐位同构。
    """

    def __init__(self, obs_dim: int, action_nvec, hidden=(64, 64)):
        super().__init__()
        self.obs_dim = int(obs_dim)
        self.action_nvec = tuple(int(n) for n in action_nvec)
        dims = [self.obs_dim] + list(hidden)
        seq = []
        for i in range(len(dims) - 1):
            seq.append(nn.Linear(dims[i], dims[i + 1], bias=False))
            seq.append(nn.Hardtanh())            # clamp[-1,1]，等价 sat
        self.body = nn.Sequential(*seq)
        self.heads = nn.ModuleList(
            [nn.Linear(dims[-1], n, bias=False) for n in self.action_nvec])
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=np.sqrt(2.0))

    def forward(self, obs):
        h = self.body(obs)
        return [head(h) for head in self.heads]

    def act(self, obs, deterministic: bool = False):
        """返回 (actions:list[(B,)], log_prob:(B,), entropy:(B,))。"""
        logits = self.forward(obs)
        dists = [Categorical(logits=l) for l in logits]
        actions, logps, ents = [], [], []
        for d in dists:
            a = d.logits.argmax(-1) if deterministic else d.sample()
            actions.append(a)
            logps.append(d.log_prob(a))
            ents.append(d.entropy())
        return actions, sum(logps), sum(ents)


# ---------------------------------------------------------------------------
# 价值网络（critic，浮点，不部署）
# ---------------------------------------------------------------------------
class ValueMLP(nn.Module):
    def __init__(self, obs_dim: int, hidden=(64, 64)):
        super().__init__()
        dims = [obs_dim] + list(hidden)
        seq = []
        for i in range(len(dims) - 1):
            seq.append(nn.Linear(dims[i], dims[i + 1]))
            seq.append(nn.Tanh())
        seq.append(nn.Linear(dims[-1], 1))
        self.net = nn.Sequential(*seq)
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=np.sqrt(2.0))
                nn.init.zeros_(m.bias)

    def forward(self, obs):
        return self.net(obs).squeeze(-1)


# ---------------------------------------------------------------------------
# PPO
# ---------------------------------------------------------------------------
class PPO:
    def __init__(self, actor, critic, lr: float = 3e-4, gamma: float = 0.99,
                 gae_lambda: float = 0.95, clip: float = 0.2, ent_coef: float = 0.01,
                 vf_coef: float = 0.5, max_grad_norm: float = 0.5, epochs: int = 4,
                 minibatch: int = 256, lr_anneal: bool = True, device: str = "cpu"):
        self.device = device
        self.actor = actor.to(device)
        self.critic = critic.to(device)
        self.lr = lr
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip = clip
        self.ent_coef = ent_coef
        self.vf_coef = vf_coef
        self.max_grad_norm = max_grad_norm
        self.epochs = epochs
        self.minibatch = minibatch
        self.lr_anneal = lr_anneal
        self.opt = torch.optim.Adam(
            list(actor.parameters()) + list(critic.parameters()), lr=lr, eps=1e-5)

    def _set_lr(self, lr):
        for g in self.opt.param_groups:
            g["lr"] = lr

    def _obs_tensor(self, obs):
        return torch.as_tensor(obs, dtype=torch.float32, device=self.device)

    def collect_rollout(self, envs, num_steps: int) -> dict:
        num_envs = len(envs)
        obs_dim = envs[0].obs_dim
        n_heads = len(envs[0].action_nvec)
        obs_buf = np.zeros((num_steps, num_envs, obs_dim), dtype=np.float32)
        act_buf = np.zeros((num_steps, num_envs, n_heads), dtype=np.int64)
        logp_buf = np.zeros((num_steps, num_envs), dtype=np.float32)
        rew_buf = np.zeros((num_steps, num_envs), dtype=np.float32)
        done_buf = np.zeros((num_steps, num_envs), dtype=np.bool_)
        val_buf = np.zeros((num_steps, num_envs), dtype=np.float32)

        obs = np.stack([env.reset() for env in envs]).astype(np.float32)
        for t in range(num_steps):
            obs_t = self._obs_tensor(obs)
            with torch.no_grad():
                actions, logp, _ = self.actor.act(obs_t)
                values = self.critic(obs_t)
            act = torch.stack(actions, dim=1).cpu().numpy()
            obs_buf[t] = obs
            act_buf[t] = act
            logp_buf[t] = logp.cpu().numpy()
            val_buf[t] = values.cpu().numpy()
            for i, env in enumerate(envs):
                o, r, d, _info = env.step(act[i])
                rew_buf[t, i] = r
                done_buf[t, i] = d
                obs[i] = o if not d else env.reset()
        with torch.no_grad():
            last_val = self.critic(self._obs_tensor(obs)).cpu().numpy()
        return dict(obs=obs_buf, act=act_buf, logp=logp_buf, rew=rew_buf,
                    done=done_buf, val=val_buf, last_val=last_val)

    def compute_gae(self, rew, val, done, last_val):
        num_steps, num_envs = rew.shape
        adv = np.zeros((num_steps, num_envs), dtype=np.float32)
        lastgaelam = np.zeros(num_envs, dtype=np.float32)
        for t in reversed(range(num_steps)):
            next_val = last_val if t == num_steps - 1 else val[t + 1]
            next_nonterm = 1.0 - done[t].astype(np.float32)
            delta = rew[t] + self.gamma * next_val * next_nonterm - val[t]
            lastgaelam = delta + self.gamma * self.gae_lambda * next_nonterm * lastgaelam
            adv[t] = lastgaelam
        return adv, adv + val

    def update(self, batch: dict):
        num_steps, num_envs = batch["rew"].shape
        b_obs = batch["obs"].reshape(-1, batch["obs"].shape[-1])
        b_act = batch["act"].reshape(-1, batch["act"].shape[-1])
        b_logp = batch["logp"].reshape(-1)
        b_ret = batch["ret"].reshape(-1)
        b_adv = batch["adv"].reshape(-1)
        adv = (b_adv - b_adv.mean()) / (b_adv.std() + 1e-8)

        n = len(b_obs)
        idxs = np.arange(n)
        agg = dict(pg_loss=0.0, vf_loss=0.0, entropy=0.0, approx_kl=0.0,
                   clipfrac=0.0, n_updates=0)
        for _ in range(self.epochs):
            np.random.shuffle(idxs)
            for start in range(0, n, self.minibatch):
                mb = idxs[start:start + self.minibatch]
                obs_t = self._obs_tensor(b_obs[mb])
                act_t = torch.as_tensor(b_act[mb], dtype=torch.long, device=self.device)
                adv_t = torch.as_tensor(adv[mb], dtype=torch.float32, device=self.device)
                ret_t = torch.as_tensor(b_ret[mb], dtype=torch.float32, device=self.device)
                old_logp = torch.as_tensor(b_logp[mb], dtype=torch.float32, device=self.device)

                logits = self.actor(obs_t)
                dists = [Categorical(logits=l) for l in logits]
                new_logp = sum(d.log_prob(act_t[:, i]) for i, d in enumerate(dists))
                entropy = sum(d.entropy().mean() for d in dists)

                ratio = torch.exp(new_logp - old_logp)
                pg_loss1 = -adv_t * ratio
                pg_loss2 = -adv_t * torch.clamp(ratio, 1.0 - self.clip, 1.0 + self.clip)
                pg_loss = torch.max(pg_loss1, pg_loss2).mean()

                values = self.critic(obs_t)
                vf_loss = F.mse_loss(values, ret_t)

                loss = pg_loss + self.vf_coef * vf_loss - self.ent_coef * entropy
                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(
                    list(self.actor.parameters()) + list(self.critic.parameters()),
                    self.max_grad_norm)
                self.opt.step()

                with torch.no_grad():
                    approx_kl = ((new_logp - old_logp) ** 2).mean().item()
                    clipfrac = ((ratio - 1.0).abs() > self.clip).float().mean().item()
                agg["pg_loss"] += float(pg_loss.item())
                agg["vf_loss"] += float(vf_loss.item())
                agg["entropy"] += float(entropy.item())
                agg["approx_kl"] += float(approx_kl)
                agg["clipfrac"] += float(clipfrac)
                agg["n_updates"] += 1
        for k in ("pg_loss", "vf_loss", "entropy", "approx_kl", "clipfrac"):
            agg[k] /= max(1, agg["n_updates"])
        return agg

    def train(self, make_env, total_steps: int, num_envs: int, num_steps: int,
              out_dir: str, seed: int, log_interval: int = 1) -> list:
        set_seed(seed)
        envs = [make_env() for _ in range(num_envs)]
        steps_done = 0
        iteration = 0
        log = []
        while steps_done < total_steps:
            if self.lr_anneal:
                frac = min(1.0, steps_done / float(total_steps))
                self._set_lr(self.lr * (1.0 - frac))
            batch = self.collect_rollout(envs, num_steps)
            adv, ret = self.compute_gae(batch["rew"], batch["val"], batch["done"],
                                        batch["last_val"])
            batch["adv"], batch["ret"] = adv, ret
            stats = self.update(batch)
            steps_done += num_steps * num_envs
            iteration += 1
            log.append(dict(iteration=iteration, steps=steps_done,
                            mean_reward=float(batch["rew"].mean()),
                            entropy=stats["entropy"], approx_kl=stats["approx_kl"],
                            clipfrac=stats["clipfrac"]))
            if iteration % log_interval == 0:
                print("[iter %4d] steps=%d mean_reward=%+.3f entropy=%.3f kl=%.4f" %
                      (iteration, steps_done, log[-1]["mean_reward"],
                       log[-1]["entropy"], log[-1]["approx_kl"]),
                      flush=True)

        os.makedirs(out_dir, exist_ok=True)
        torch.save(dict(actor=self.actor.state_dict(),
                        critic=self.critic.state_dict()),
                   os.path.join(out_dir, "model_final.pt"))
        with open(os.path.join(out_dir, "train_report.json"), "w", encoding="utf-8") as f:
            json.dump(dict(seed=seed, log=log,
                           final_mean_reward=log[-1]["mean_reward"] if log else None),
                      f, ensure_ascii=False, indent=2)
        return log
