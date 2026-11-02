# FPGA2026 项目 · Git 版本控制工作流

## 为什么用 Git

之前靠 `cp -r xxx _xxx_bk_时间戳/` 做备份，问题：
- 只有文件级备份，没有整体状态
- 无法知道哪次改动导致问题
- 回滚只能回单个文件
- 备份目录越堆越多，磁盘占用大

Git 能解决这些：**每次改动可追溯、可整体回滚、可对比差异**。

---

## 仓库结构

```
D:\ubuntu_iso\          ← Git 仓库根目录
├── .gitignore          ← 排除规则（构建产物 / 二进制 / 大文件）
├── README_GIT.md       ← 本文件
├── board.py            ← PC ↔ 板子通信
├── xb_chat.py          ← 系统管家小白 PC 端
├── scope_panel.py      ← 云协同示波器
├── from_board2/        ← PS 侧完整源码
├── ai_delivery/        ← AI 交付物（文档 + 源码）
├── handover*/          ← 交接文档
├── _baseline/          ← 基线笔记
├── agent/              ← Agent 源码
├── cnn_hls_2026/       ← HLS 源码（不含 work/ 构建产物）
├── atk2026/            ← 正点原子原版 FPGA 工程（只跟踪 .xpr/.xdc/.bd）
├── scope_merge/        ← 我们的合并 FPGA 工程（同样只跟踪关键文件）
└── board_snapshot/     ← ★ 板端文件快照（由 sync_board.sh 生成）
```

---

## 日常操作

### 1. 改代码前 —— 确认工作区干净

```powershell
cd D:\ubuntu_iso
git status
```

如果显示有未提交改动，先提交或暂存：

```powershell
git stash        # 暂存（稍后 git stash pop 恢复）
# 或
git add -A && git commit -m "wip: 说明改了什么"
```

### 2. 改代码 —— 正常编辑

### 3. 改完 —— 看差异再提交

```powershell
git diff                    # 看所有改动
git diff 路径/文件.py        # 看单个文件
git add -A
git commit -m "类型: 简短说明"
```

**commit message 约定（方便以后查）：**
```
feat: 新功能
fix:  修 bug
refactor: 重构
docs: 文档
test: 测试
chore: 杂项
```

示例：
```powershell
git commit -m "fix: 修复触摸翻页误触发（TAP_SLOP 位移门限）"
git commit -m "feat: 示波器增加双引擎分析（本地CNN + 云端LLM）"
```

### 4. 出了问题 —— 回滚

**回滚某个文件到上次提交：**
```powershell
git checkout -- 路径/文件.py
```

**回滚到某个 commit（看历史）：**
```powershell
git log --oneline -20            # 看历史
git revert <commit-id>           # 撤销某次提交（保留历史，安全）
# 或
git reset --hard <commit-id>     # 强制回到某个状态（危险，会丢未提交改动）
```

**对比两个版本：**
```powershell
git diff <commit1> <commit2> -- 路径/文件.py
```

---

## 板端文件同步（关键）

板子上的文件（`/home/zynq/ui/*.py`、`/mnt/boot/system.bit` 等）不在 PC 仓库里，需要用脚本拉下来纳入 Git。

### 用法

```powershell
# 1. 先查板子 IP（可能会变）
#    常见：192.168.10.14 / .17 / .18 / .19

# 2. 同步
$env:BOARD_IP = "192.168.10.18"
python sync_board.py

# 3. 看差异
git diff board_snapshot/

# 4. 提交
git add board_snapshot/
git commit -m "board: 快照 <说明>"
```

### 会同步什么

```
board_snapshot/
├── ui/
│   ├── desktop.py
│   ├── fbui.py
│   ├── apps_scope_dual.py
│   ├── apps_notes.py
│   └── ... 所有 apps_*.py
├── cloud_api.py
├── agent/          ← agent 服务的 py 文件
├── boot/
│   ├── system.bit.sha256     ← 只存 md5，不存 3.8MB 的 bit 本体
│   ├── system.dtb.sha256
│   └── BOOT.BIN.sha256
├── etc/
│   └── xiaobai-cloud.json    ← 配置（含 token，注意不要公开仓库）
└── MANIFEST.txt              ← 所有文件的 md5 清单
```

---

## 禁止事项

```
❌ 不要 git add 大文件（>10MB）
❌ 不要提交 .bit / .exe / *.bin / *.npy
❌ 不要把 board_snapshot 里的 EEPROM 配置当唯一备份（那是硬件状态）
❌ 不要 git push 到公开仓库（含 token 和项目资料）
```

---

## 紧急恢复流程

**如果改坏了想回到"已知好状态"：**

```powershell
# 1. 看历史找到好的 commit
git log --oneline -30

# 2. 创建一个恢复分支（不破坏现有历史）
git checkout -b recover-20261023

# 3. 回到那个 commit
git reset --hard <好的commit-id>

# 4. 验证没问题后，合并回 master
git checkout master
git merge recover-20261023
```

**如果只是某个文件改坏了：**
```powershell
git checkout -- 那个文件
```

---

## 重要：板子的"硬件状态"Git 管不了

Git 只能管 **文件**。以下状态 Git 无法备份/恢复：

```
· PL 里实际加载的 bitstream（文件回滚了但可能需要断电重启才生效）
· GT911 触摸芯片内部 EEPROM 的配置
· LCD / 触摸的物理连接状态
· DDR 内容、运行中的进程状态
```

**所以每次重大操作前，除了 Git 提交，还要：**
```
1. 记录板子当前的 md5 状态（sync_board.py 会做）
2. 记录 touch / LCD / 音频 是否正常（跑一遍自检）
3. 才动手改
```
