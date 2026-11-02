# 02 · 任务 A：云端 GPU 训练环境（Lab415）

> 验收标准（任务书）：**能从零复现出一个模型（有完整脚本 + 数据 + 超参记录）**
> 本文记录环境事实、搭建过程、踩到的坑，以及**怎么从零重建**。

---

## 1. 机器事实（实测，2026-10-01）

| 项 | 值 |
|---|---|
| 主机名 | `lab415new-PR4904P` |
| SSH | `ssh lab415` → 配置在 `~/.ssh/config`（`HostName 100.123.113.20`, `User pengyc_fzu`, 密钥登录） |
| 系统 | Ubuntu 18.04.6 LTS，内核 5.4.0-152-generic |
| CPU / 内存 | **80 核** / **62 GB** |
| GPU | **4 × NVIDIA GeForce RTX 2080 Ti（11 GB 显存/卡）** |
| 驱动 | 470.223.02（⇒ **最高 CUDA 11.4**，见 §4） |
| 磁盘 | `/`（sda6）**432 G 已 100% 满，只剩 ~300 MB**；`/data`（sdb1）3.6 T，**约 980 G 可用** |
| 现有环境 | 实验室既有 venv `/data/pengyc_fzu/envs/dl`（别人在用，**不动它**） |

> ★★ **第一件必须知道的事：根分区 `/` 已经 100% 满。**
> 任何往 `$HOME` / `/tmp` / pip 默认缓存写的操作都会失败或挤爆别人的环境。
> 本项目的**所有** cache/tmp/env/数据/权重都重定向到 `/data/pengyc_fzu/fpga2026_ai/`。

---

## 2. 交付的环境

```
解释器：/data/pengyc_fzu/envs/fpga2026/bin/python   (Python 3.10.20)
框架  ：torch 2.5.1+cu118   （CUDA 11.8，4 卡全部可用）
工程根：/data/pengyc_fzu/fpga2026_ai
冻结  ：/data/pengyc_fzu/fpga2026_ai/requirements_lock.txt
```

自检（`scripts/_env_check.sh` 的实测输出）：

```
TORCH 2.5.1+cu118 True 4        # cuda.is_available()=True, device_count()=4
GPU0 NVIDIA GeForce RTX 2080 Ti
GPU1 NVIDIA GeForce RTX 2080 Ti
GPU2 NVIDIA GeForce RTX 2080 Ti
GPU3 NVIDIA GeForce RTX 2080 Ti
```

---

## 3. ★ 网络坑（这一节能省后面的人半天）

实测结论（`curl -o /dev/null -w "%{http_code}"`）：

| URL | 结果 | 说明 |
|---|---|---|
| `https://pypi.org/simple/` | **200** | 索引可达 |
| `https://files.pythonhosted.org/...` | **不可达**（Errno 101 Network is unreachable） | ★ **真正的坑**：索引通、文件 CDN 不通 |
| `https://mirrors.aliyun.com/pypi/simple/` | **200** | ✅ 可用（推荐） |
| `https://mirrors.cloud.tencent.com/pypi/simple/` | **200** | ✅ 可用（备用） |
| `https://pypi.tuna.tsinghua.edu.cn/simple/` | **403** | ✗ 不可用 |
| `https://download.pytorch.org/whl/cu118` | **200** | ✅ torch 官方源可用 |
| `https://mirror.sjtu.edu.cn/pytorch-wheels/cu118/` | **200** | 备用 |

**踩坑经过**：第一次用默认 PyPI 装 torch，`torch`/`nvidia-*` 从
`download.pytorch.org` 下完了，但 `sympy/jinja2/networkx` 之类解析到
`files.pythonhosted.org`，**永远下不下来**，pip 一直重试 → 卡死 30 分钟。

**另一个坑**：即使换成镜像，一次性安装十几个包时，阿里云 CDN 的一条连接会
**半关闭（CLOSE-WAIT）**，pip 卡在 `pipe_wait` 不动、CPU 计数完全不涨。
⇒ `scripts/_install_extras.sh` 改成**逐包安装 + 两个镜像回退 + 显式 `timeout`**，
彻底规避。**以后在 lab415 上装包都建议这么干。**

---

## 4. ★ 为什么必须是 cu118（而不是更新的 cu12x）

驱动是 **470.223.02**，对应 CUDA 11.4。CUDA 12 的运行时要求驱动 ≥ 525。
但 **CUDA 11.x 内部有「次版本兼容」保证**：任何 11.x 的运行时都能跑在
驱动 ≥ 450.80.02 上。所以 **cu118 的 wheel 在 470 驱动上可用**（已实测）。
⇒ 环境锁定 `torch==2.5.1+cu118`。

---

## 5. 从零重建（换一台机器时照这个做）

```bash
# 方式一：常规路径（网络通的话）
bash scripts/bootstrap_env_lab415.sh
#   它会：建 conda env(py3.10) → 装 torch cu118 → 装其余依赖 → 冻结 requirements_lock.txt
#   已验证：PYPI_MIRROR 默认 mirrors.aliyun.com

# 方式二（本项目实际采用的、更快的路径）
bash scripts/_build_env_from_dl.sh
#   复制实验室已有 venv /data/pengyc_fzu/envs/dl（里面 torch+nvidia 全套已就绪）
#   再补装本项目需要的包。约 3 分钟，且完全不影响原环境。
```

两种方式得到的环境都用同一个 `requirements_lock.txt` 冻结，**可复现性由此保证**。

### 可复现性三件套（任务 A 验收要求）

| 要求 | 实现 |
|---|---|
| 固定随机种子 | `train_waveform.py --seed`（默认 20261001）同时固定 `numpy` / `torch` / `torch.cuda`，并开 `cudnn.deterministic=True`、`benchmark=False` |
| 记录超参 | 每个 run 目录下 `train_report.json` 里 `args` 段完整记录命令行超参 |
| 保存 checkpoint | `ckpt_p1_float.pt`（浮点预训练）/ `ckpt_p2_calib.pt`（校准后）/ `ckpt_best.pt`（验证集最优）/ `ckpt_final.pt` / `model_final.pt` |

**"从零复现"的完整命令**：

```bash
cd /data/pengyc_fzu/fpga2026_ai
bash scripts/run_pipeline.sh          # 数据集 + 训练 + 导出，一条命令到底
```

---

## 6. 远端操作辅助（Windows 侧）

| 脚本 | 用途 |
|---|---|
| `scripts/rsh.ps1` | 把本地 `.sh` 通过 stdin 送到远端执行（避开 Windows 引号/CRLF 地狱） |
| `scripts/sync_to_lab415.ps1` | `scp -r` 推送 `src/ scripts/ docs/ tests/` 到远端 |
| `scripts/run_pipeline.sh` | 任务 B/C/F 端到端 |
| `scripts/compare_pp.sh` | 输入表示选型实验 |
| `scripts/run_rl.sh` / `run_agent.sh` / `run_serve.sh` | 任务 E / D / G |

```powershell
# 典型用法
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\sync_to_lab415.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\rsh.ps1 -Script scripts\_status.sh
```

> ★ 两个 Windows 侧的坑（已修）：
> 1. **脚本执行策略**：本机 `Restricted`，必须用 `powershell.exe -ExecutionPolicy Bypass -File`。
>    （`pwsh` 不在 PATH 上；`& .\x.ps1` 会被拒绝。）
> 2. **Windows bsdtar 会崩**（exit `0xC0000005`）在本项目的目录树上，
>    所以同步改用 `scp -r`；另外 **PowerShell 5.1 没有 `ProcessStartInfo.ArgumentList`**，
>    `rsh.ps1` 里用 `Arguments` 拼字符串代替。
> 3. `.ps1` 文件在 **PowerShell 5.1 下按 ANSI 读**，所以 `rsh.ps1` / `sync_to_lab415.ps1`
>    里刻意**只用 ASCII**（中文会乱码导致语法错误）。

---

## 7. 数据与产物的落盘位置（全在 /data）

```
/data/pengyc_fzu/fpga2026_ai/
├─ src/ scripts/ docs/ tests/      ← 与本地仓库同步
├─ data/
│  ├─ scope_ds_v1/                 数据集（wdens，规范格式）
│  ├─ scope_ds_stft/               数据集（stft，选型对比用）
│  └─ scope_ds_smoke/              冒烟数据集
├─ runs/                           每次训练的 checkpoint 与报告
├─ deliverables/                   ★ 交付物（quantized_model/ …）
├─ logs/                           所有日志
├─ .cache/{pip,tmp,hf}             缓存与临时目录（★ 绝不写到 / 或 $HOME）
└─ requirements_lock.txt
```
