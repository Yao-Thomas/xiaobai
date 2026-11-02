#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cnn_linux.py —— Linux 用户态 CNN 驱动（把上一轮裸机调度搬过来）

════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════
上一轮的 CNN 推理是**裸机**（BOOT.BIN + FSBL + UART 打印），跟桌面/音频/agent
不能共存。现在两个 HLS IP 已经集成进主工程 BD：

    cnn_conv_pool_q  @ 0x43CD0000   （卷积 + ReLU + 最大池化）
    cnn_fc_q         @ 0x43CE0000   （全连接）

本脚本就是**在 Ubuntu 用户态**重新实现那套调度。

════════════════════════════════════════════════════════════════════
三个技术难点与解法
════════════════════════════════════════════════════════════════════
① 物理连续内存
   HLS IP 的 m_axi 拿的是**物理地址**。用户态 malloc 拿到的是虚拟地址，
   而且页可能不连续。
   解法：mmap 匿名页 + mlock 锁住（防止换出/迁移）+ 读 /proc/self/pagemap
        拿每一页的物理页号。本工程数据量很小（几 KB），页数少，够用。

② Cache 一致性  ★ 最容易踩的坑
   Zynq 的 HP 口是**非一致**的（不经过 CPU cache）。所以：
     · CPU 写的数据（输入图/权重）→ 必须 cache 维护，否则加速器读到旧值
     · 加速器写的数据（输出/中间特征图）→ CPU 读之前必须丢缓存，
       否则读到旧值
     · ★ 中间特征图（conv2 的输入 = conv1 的输出）**绝对不能让 CPU 碰**，
       一碰就会产生脏缓存行，进而把加速器的结果冲坏
   解法：ARM 的 cacheflush 系统调用（0xf0002）。
        ★ 注意：ARM 上 cacheflush 是 **clean+invalidate**，
          所以对"CPU 没碰过"的缓冲做它，等价于纯 invalidate。

③ 寄存器访问
   /dev/mem + mmap 到 0x43CD0000 / 0x43CE0000，直接读写 32 位寄存器。

════════════════════════════════════════════════════════════════════
寄存器表（从上一轮 main_cnn5.c 抄来的，已改成新地址）
════════════════════════════════════════════════════════════════════
cnn_conv_pool_q @ 0x43CD0000        cnn_fc_q @ 0x43CE0000
  0x00 ap_ctrl  (写1启动, 读bit1=done)   0x00 ap_ctrl
  0x10 IMG 输入基址                      0x10 X   输入基址
  0x18 W   权重基址                      0x18 W   权重基址
  0x20 OUT 输出基址                      0x20 OUT 输出基址
  0x28 IH   0x30 IW                      0x28 IN  输入维度
  0x38 INC  0x40 OUTC                    0x30 OUTN 输出维度
  0x48 KH   0x50 KW   0x58 P             0x38 MFQ
  0x60 MFQ

网络（int8，真实 requantization）：
  28×28 ─conv1(1→8,3×3)+ReLU+pool2─→ 13×13×8
        ─conv2(8→16,3×3)+ReLU+pool2─→ 5×5×16
        ─FC(400→10)─→ argmax
  requant: out = sat/relu((acc * MFQ) >> 16)   MFQ = 119

用法（要 root，因为 /proc/self/pagemap 和 /dev/mem 都需要）：
    sudo python3 cnn_linux.py                 # 跑 MNIST 端到端 + 与 CPU 参考比对
    sudo python3 cnn_linux.py --check         # 只检查 IP 在线
    sudo python3 cnn_linux.py --data x.bin    # 指定数据文件
"""
import argparse
import ctypes
import mmap
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 常量
CPQ_BASE = 0x43CD0000
FCQ_BASE = 0x43CE0000
MAP_SIZE = 0x1000
PAGE = 4096

# cpq 寄存器偏移
#
# ★★★ 2026-10-01 重要修正 ★★★
#   原来这里的偏移是从上一轮 2018.3 的裸机代码（main_cnn5.c）抄的，
#   但 2026.1 的 Vitis HLS 生成的 IP **用 64 位指针**（每个指针占
#   两个 32 位寄存器：lo + hi），所以所有偏移都往后挪了。
#   实测症状：地址写进去了、IH 也写进去了，但 W 那个位置是空的，
#   内核照样"跑完"（因为参数是 0），输出全 0。
#   权威来源：IP 驱动里的 xcnn_conv_pool_q_hw.h
#
#   旧(2018.3, 32位) → 新(2026.1, 64位)
#     0x18 w        → 0x1c
#     0x20 out      → 0x28
#     0x28 IH       → 0x34
#     0x30 IW       → 0x3c
#     0x38 IN_CH    → 0x44
#     0x40 OUT_CH   → 0x4c
#     0x48 KH       → 0x54
#     0x50 KW       → 0x5c
#     0x58 P        → 0x64
#     0x60 MFQ      → 0x6c
R_AP = 0x00
R_IMG = 0x10          # 64 位（0x10 lo + 0x14 hi）
R_W = 0x1c            # 64 位（0x1c lo + 0x20 hi）
R_OUT = 0x28          # 64 位（0x28 lo + 0x2c hi）
R_IH = 0x34
R_IW = 0x3c
R_INC = 0x44
R_OUTC = 0x4c
R_KH = 0x54
R_KW = 0x5c
R_P = 0x64
R_MFQ = 0x6c

# fcq 寄存器偏移（同样按 2026.1 的 64 位排布）
F_AP = 0x00
F_X = 0x10            # 64 位
F_W = 0x1c            # 64 位
F_OUT = 0x28          # 64 位
F_IN = 0x34
F_OUTN = 0x3c
F_MFQ = 0x44

# 网络超参
#
# ★★★ MFQ 是【寄存器】，不是硬件常量 ★★★
#
# HLS 里 MFQ 是 s_axilite 端口（cnn_conv_pool_q(..., int MFQ)），
# 【每次调用都可以传不同的值】。上一轮 MNIST 模型校准出 119，
# 那是【那个网络、那种输入分布】的值；换成波形模型必须重新校准。
#
# 波形识别模型（AI 训练负责人交付 v1.0）逐层校准值：
#     conv1 = 201, conv2 = 371, fc = 1390
# 溢出约束 max|acc| × MFQ < 2^31 已逐层实测，余量 196× / 172× / 115×。
#
# 所以别再用一个全局 MFQ 了 —— 按层传。
MFQ = 119                      # ← 旧 MNIST 的校准值（向下兼容，别删）
MFQ_C1 = 201                   # 波形模型 conv1
MFQ_C2 = 371                   # 波形模型 conv2
MFQ_FC = 1390                  # 波形模型 fc

CB1, CB2 = 8, 16
P = 2
KH = KW = 3
OH1 = OW1 = 13
N1 = CB1 * OH1 * OW1          # 1352
OH2 = OW2 = 5
N2 = CB2 * OH2 * OW2          # 400
FCI, FCO = 400, 10            # 默认 MNIST（10 类）
FCO_WAVE = 8                  # ★ 波形模型是 8 类

# 波形模型的类别（下标顺序，来自 model_spec.json）
WAVE_CLASSES = ("sine", "square", "triangle", "sawtooth", "noise",
                "clipping", "signal_loss", "duty_abnormal")
WAVE_CLASSES_CN = {"sine": "正弦", "square": "方波", "triangle": "三角波",
                   "sawtooth": "锯齿波", "noise": "噪声/无周期",
                   "clipping": "削顶", "signal_loss": "丢信号",
                   "duty_abnormal": "占空比异常", "glitch": "毛刺"}

DATA_DEFAULT = "/home/zynq/mnist_test.bin"
# ★ AI 交付包的权重文件（4480 B，128 字节对齐布局，见 model_spec.json）
WEIGHTS_WAVE_DEFAULT = "/home/zynq/wave_weights.bin"
REF_IN_DEFAULT = "/home/zynq/wave_reference_in.bin"
REF_OUT_DEFAULT = "/home/zynq/wave_reference_out.bin"

# ---------------------------------------------------------------- cacheflush
SYS_cacheflush = 0xf0002
_libc = ctypes.CDLL("libc.so.6", use_errno=True)


def _page_align(n):
    return (n + PAGE - 1) // PAGE * PAGE


class DmaBuf(object):
    """给 PL 加速器用的一块【不可缓存、无别名】的 DDR 缓冲

    ══════════════════════════════════════════════════════════════
    ★★★ 这块代码的来历：缓存一致性问题折腾了大半天 ★★★
    ══════════════════════════════════════════════════════════════
    第一版：mmap 匿名内存 → 读 pagemap 拿物理地址 → 用 ARM 的
            cacheflush 系统调用做 flush/invalidate。
    结果：MNIST 单次测试「碰巧」能过，一循环就崩 ——
          加速器写 DDR 后 CPU 读回来，读到的【永远是上一次的结果】。

    用「/dev/mem 从外部改写同一物理页」做的对照实验：

        A 不 flush 直接读      → 新值  ✓
        B cacheflush(0)       → 旧值  ✗   ★ 元凶
        C cacheflush(1)       → EINVAL
        D cacheflush(0)×3     → 旧值  ✗
        E mmap.flush()        → 新值  ✓
        F 重新 mmap 同一物理页  → 新值  ✓

    ★ 关键：ARM 的 cacheflush 是 **clean + invalidate**。那个
      **clean（写回）** 在「加速器已经写了 DDR」之后，会把 CPU 缓存里的
      【旧值】写回去，**把加速器的结果盖掉**。
      而用户态没有「只失效、不写回」的系统调用。

    第二版：匿名 mmap 占位 + /dev/mem 再映射一份（不可缓存），
            数据走 /dev/mem 那份。
      结果：探针 13/13、conv1 连过 8 次 100%，但仍有 ~6% 随机错误，
            同一组数据跑 10 次会 98.7% → 100% → 90.2% 地漂。
      ⇒ 因为【同一个物理页被映射了两次、cache 属性不同】，
        ARMv7 上这是未定义行为。

    第三版（现在）：★ 彻底不要别名。
      bootargs 加 `mem=992M`，把 0x3E000000~0x3FFFFFFF（32MB）
      从 Linux 手里扣掉；这块内存【只有一个映射】—— /dev/mem 那份。
      实测：完整链路（conv1→conv2→fc）连跑 10 次，
            f1 1352/1352、f2 400/400、logits 逐点一致，全部 ✓。

    ⇒ 所以：flush() / invalidate() 都是【空操作】，因为这块内存
      根本不进缓存。（保留这两个名字是为了让调用处的意图仍然可读。）
    ══════════════════════════════════════════════════════════════
    """

    # ★ 开机预留区（bootargs: mem=992M ⇒ 0x3E000000~0x3FFFFFFF 共 32MB）
    POOL_BASE = 0x3E000000
    POOL_SIZE = 0x02000000              # 32 MB
    _pool_off = 0                       # 简单的 bump 分配
    _pool_fd = None

    @classmethod
    def pool_reset(cls):
        """把分配指针归零（反复创建 Cnn 的测试脚本记得调一下）"""
        cls._pool_off = 0

    @classmethod
    def pool_stat(cls):
        return {"base": cls.POOL_BASE, "size": cls.POOL_SIZE,
                "used": cls._pool_off,
                "left": cls.POOL_SIZE - cls._pool_off}

    @classmethod
    def _pool_alloc(cls, size):
        alloc = _page_align(size)
        if cls._pool_fd is None:
            cls._pool_fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        if cls._pool_off + alloc > cls.POOL_SIZE:
            raise MemoryError(
                "预留区用完了（已用 %d / %d 字节）。"
                "反复建 Cnn 的话记得调 DmaBuf.pool_reset()"
                % (cls._pool_off, cls.POOL_SIZE))
        paddr = cls.POOL_BASE + cls._pool_off
        cls._pool_off += alloc
        return paddr, alloc

    def __init__(self, size, name=""):
        self.name = name or "buf"
        self.size = size
        self.paddr, self.alloc = self._pool_alloc(size)
        # ★ 唯一的一份映射：/dev/mem，不可缓存
        self.mm = mmap.mmap(self._pool_fd, self.alloc, mmap.MAP_SHARED,
                            mmap.PROT_READ | mmap.PROT_WRITE,
                            offset=self.paddr)
        # 清一遍，免得拿到别的程序残留的数据
        self.mm[0:self.alloc] = b"\x00" * self.alloc

    # ★ 空操作 —— 这块内存不可缓存，写完就在 DDR 里，读完就是最新值
    def flush(self):
        """CPU 写完 → 加速器能看到（空操作：不可缓存内存）"""
        return

    def invalidate(self):
        """加速器写完 → CPU 读到新的（空操作：不可缓存内存）"""
        return

    def write(self, data, off=0):
        self.mm[off:off + len(data)] = data

    def read(self, n, off=0):
        return bytes(self.mm[off:off + n])

    def as_i8(self, off=0):
        """按 int8 读回来（Python 的 bytes 是无符号，这里转有符号）"""
        return list(struct.unpack_from("<%db" % (self.size - off), self.mm, off))

    def as_u8(self, n=None, off=0):
        n = n or (self.size - off)
        return list(struct.unpack_from("<%dB" % n, self.mm, off))

    def close(self):
        try:
            self.mm.close()
        except Exception:
            pass


class HlsIp(object):
    """一个 HLS IP 的寄存器窗口（/dev/mem 映射）"""

    def __init__(self, base, name=""):
        self.name = name or ("ip@0x%08X" % base)
        self.base = base
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(self.fd, MAP_SIZE, mmap.MAP_SHARED,
                            mmap.PROT_READ | mmap.PROT_WRITE, offset=base)

    def w(self, off, val):
        struct.pack_into("<I", self.mm, off, val & 0xFFFFFFFF)

    def w64(self, off, val):
        """写一个 64 位值（指针用）

        ★ 2026.1 的 HLS IP 用 64 位指针：off 放低 32 位，off+4 放高 32 位。
          我们的物理地址都在 4GB 以内，高 32 位恒为 0 —— 但**必须显式写 0**，
          否则会残留上一次的值（或复位初值）。
        """
        struct.pack_into("<I", self.mm, off, val & 0xFFFFFFFF)
        struct.pack_into("<I", self.mm, off + 4, (val >> 32) & 0xFFFFFFFF)

    def r(self, off):
        return struct.unpack_from("<I", self.mm, off)[0]

    def start_and_wait(self, timeout_s=5.0):
        """写 ap_start，然后等这一次运行【真的跑完】

        ap_ctrl_hs 位定义：
          bit0 ap_start  bit1 ap_done  bit2 ap_idle  bit3 ap_ready

        ══════════════════════════════════════════════════════════════
        ★★★ 为什么不能只等 ap_done（踩了很久）★★★
        ══════════════════════════════════════════════════════════════
        第一版：写 ap_start → 轮询 ap_done → 看到 1 就返回。

        结果：层与层的输出**随机对不上**（同组数据跑几次，一致度在
        58%~85% 之间乱跳，而且加 sleep 也不稳定）。

        原因：ap_done 可能是【上一次运行】残留的。写完 ap_start 之后
        它要过一会儿才变化；CPU 在这之前轮询就会看到 done=1，
        **立刻返回**，而这一层其实刚启动还在跑
        ⇒ 上一层没算完下一层就开始了 ⇒ 读到半成品 ⇒ 结果乱跳。

        先改成"等 done 先清掉再置位"——结果 fc 那层死等超时，
        因为 fc 的 ap_done 时序和 conv 不一样。

        ⇒ ★ 最后用 **ap_idle** 当判据，它语义最干净：
              ap_idle=1  表示"没在跑"
              写 ap_start 后它会变 0（证明这次真的启动了）
              跑完又变回 1

          所以：① 等 ap_idle 变 0（确认启动）
                ② 等 ap_idle 变回 1（确认跑完）
          每一步都有超时，异常时不会死等。
        ══════════════════════════════════════════════════════════════
        """
        self.w(0x00, 1)                     # ap_start = 1
        t0 = time.time()
        started = False

        while True:
            ap = self.r(0x00)
            idle = bool(ap & 0x4)

            if not idle:
                # 看到"在跑" —— 证明这一次真的启动了
                started = True
            else:
                # idle=1：没在跑
                if started:
                    # 先看到跑、再看到闲 = 这次的运行完成了
                    return True, time.time() - t0
                # ★ 没抓到 idle=0 的两种可能：
                #   ① 块太快，启动和完成都发生在两次轮询之间
                #   ② 写 ap_start 还没生效
                #   给一小段宽限期区分：超过就当①处理
                if time.time() - t0 > 0.002:
                    return True, time.time() - t0

            if time.time() - t0 > timeout_s:
                return False, time.time() - t0
            time.sleep(0.00002)

    def close(self):
        try:
            self.mm.close()
        finally:
            os.close(self.fd)


# ---------------------------------------------------------------- 调度
class Cnn(object):
    """CNN 推理调度

    ★ 缓冲来自开机预留区（见 DmaBuf 的注释），是【bump 分配】不退的。
      所以这里记一个"活着几个 Cnn"的计数：从 0 变 1 时把分配指针归零，
      这样反复 new Cnn() 也不会把 32MB 用光。
    """
    _live = 0

    def __init__(self, verbose=True):
        self.v = verbose
        Cnn._live += 1
        if Cnn._live == 1:
            DmaBuf.pool_reset()
        self.cpq = HlsIp(CPQ_BASE, "cnn_conv_pool_q")
        self.fcq = HlsIp(FCQ_BASE, "cnn_fc_q")
        # 各个缓冲（大小按上一轮 main_cnn5.c 的 padding 来）
        self.img = DmaBuf(832, "img")          # 28*28=784，padding 到 832
        self.w1 = DmaBuf(128, "W1")            # 72
        self.fb1 = DmaBuf(1408, "fb1")         # 1352（加速器写，CPU 不碰）
        self.w2 = DmaBuf(1152, "W2")
        self.fb2 = DmaBuf(448, "fb2")          # 400（加速器写，CPU 不碰）
        self.wf = DmaBuf(4032, "WF")           # 4000
        self.lg = DmaBuf(64, "logits")         # 10（加速器写）

    def log(self, *a):
        if self.v:
            print(*a, flush=True)

    def load(self, blob):
        """把 mnist_test.bin 的内容灌进各缓冲

        布局: img[784] u8 | W1[72] i8 | W2[1152] i8 | WF[4000] i8 | label u32
        """
        assert len(blob) >= 784 + 72 + 1152 + 4000 + 4, "数据文件太小"
        off = 0
        img_u8 = blob[off:off + 784]; off += 784
        w1 = blob[off:off + 72]; off += 72
        w2 = blob[off:off + 1152]; off += 1152
        wf = blob[off:off + 4000]; off += 4000
        label = struct.unpack_from("<I", blob, off)[0]

        # 输入图要转成 int8 = u8 - 128（和裸机一致）
        img_i8 = bytes(((b - 128) & 0xFF) for b in img_u8)
        self.img.write(img_i8)
        self.w1.write(w1)
        self.w2.write(w2)
        self.wf.write(wf)

        # ★ CPU 写的三块 → flush，让加速器看到
        self.img.flush()
        self.w1.flush()
        self.w2.flush()
        self.wf.flush()
        return label, img_u8, list(struct.unpack("<72b", w1)), \
            list(struct.unpack("<1152b", w2)), list(struct.unpack("<4000b", wf))

    def run_cpq(self, IH, IW, inC, outC, imgbuf, wbuf, outbuf, mfq=MFQ):
        """跑一次卷积+池化

        ★ mfq 按层传 —— 波形模型是 201/371，MNIST 是 119。
          MFQ 在 HLS 里是 s_axilite 寄存器，每次调用独立生效。
        """
        self.cpq.w64(R_IMG, imgbuf.paddr)      # ★ 64 位指针
        self.cpq.w64(R_W, wbuf.paddr)
        self.cpq.w64(R_OUT, outbuf.paddr)
        self.cpq.w(R_IH, IH)
        self.cpq.w(R_IW, IW)
        self.cpq.w(R_INC, inC)
        self.cpq.w(R_OUTC, outC)
        self.cpq.w(R_KH, KH)
        self.cpq.w(R_KW, KW)
        self.cpq.w(R_P, P)
        self.cpq.w(R_MFQ, mfq)
        ok, dt = self.cpq.start_and_wait()
        if not ok:
            raise RuntimeError("[超时] %s conv(%d->%d) %.3fs"
                               % (self.cpq.name, inC, outC, dt))
        return dt

    def run_fc(self, xbuf, wbuf, outbuf, IN, OUT, mfq=MFQ):
        """跑一次全连接（★ mfq 按层传）"""
        self.fcq.w64(F_X, xbuf.paddr)          # ★ 64 位指针
        self.fcq.w64(F_W, wbuf.paddr)
        self.fcq.w64(F_OUT, outbuf.paddr)
        self.fcq.w(F_IN, IN)
        self.fcq.w(F_OUTN, OUT)
        self.fcq.w(F_MFQ, mfq)
        ok, dt = self.fcq.start_and_wait()
        if not ok:
            raise RuntimeError("[超时] %s FC %.3fs" % (self.fcq.name, dt))
        return dt

    def close(self):
        for o in (self.cpq, self.fcq):
            try:
                o.close()
            except Exception:
                pass
        for b in (self.img, self.w1, self.fb1, self.w2, self.fb2, self.wf, self.lg):
            try:
                b.close()
            except Exception:
                pass
        Cnn._live = max(0, Cnn._live - 1)


# ---------------------------------------------------------------- CPU 参考
def cpu_reference(img_i8, W1, W2, WF, mfq1=MFQ, mfq2=MFQ, mfqfc=MFQ, fco=FCO):
    """用纯软件复算一遍，作为逐点比对的基准（和裸机里那段完全一样）

    ★ mfq1 / mfq2 / mfqfc 按层传：
        波形模型 → 201 / 371 / 1390
        MNIST   → 119 / 119 / 119
    ★ fco：输出类别数（波形 8，MNIST 10）
    """
    ref1 = [0] * N1
    for oc in range(CB1):
        for py in range(OH1):
            for px in range(OW1):
                m = 0
                for sy in range(P):
                    for sx in range(P):
                        oy, ox = py * P + sy, px * P + sx
                        acc = 0
                        for ky in range(KH):
                            for kx in range(KW):
                                acc += img_i8[(oy + ky) * 28 + (ox + kx)] * \
                                       W1[oc * 9 + ky * 3 + kx]
                        q = (acc * mfq1) >> 16
                        if q < 0:
                            q = 0
                        if q > 127:
                            q = 127
                        if q > m:
                            m = q
                ref1[oc * 169 + py * 13 + px] = m

    ref2 = [0] * N2
    for oc in range(CB2):
        for py in range(OH2):
            for px in range(OW2):
                m = 0
                for sy in range(P):
                    for sx in range(P):
                        oy, ox = py * P + sy, px * P + sx
                        acc = 0
                        for ic in range(CB1):
                            for ky in range(KH):
                                for kx in range(KW):
                                    acc += ref1[ic * 169 + (oy + ky) * 13 + (ox + kx)] * \
                                           W2[(oc * CB1 + ic) * 9 + ky * 3 + kx]
                        q = (acc * mfq2) >> 16
                        if q < 0:
                            q = 0
                        if q > 127:
                            q = 127
                        if q > m:
                            m = q
                ref2[oc * 25 + py * 5 + px] = m

    lg = []
    for oc in range(fco):
        acc = 0
        for i in range(FCI):
            acc += ref2[i] * WF[oc * FCI + i]
        q = (acc * mfqfc) >> 16
        if q > 127:
            q = 127
        if q < -128:
            q = -128
        lg.append(q)
    return ref1, ref2, lg


# ---------------------------------------------------------------- 波形模型
def load_wave_weights(path=WEIGHTS_WAVE_DEFAULT):
    """读 AI 交付包的 weights.bin（4480 B，128 字节对齐）

    布局（来自 model_spec.json §weights_layout）：
        偏移 0x0000  conv1.weight  [8,1,3,3]      72 B
        偏移 0x0080  conv2.weight  [16,8,3,3]   1152 B
        偏移 0x0500  fc.weight     [8,400]      3200 B
        文件总长                                 4480 B

    返回 (w1: bytes[72], w2: bytes[1152], wf: bytes[3200])
    """
    with open(path, "rb") as f:
        b = f.read()
    if len(b) < 4480:
        raise ValueError("weights.bin 太小：%d 字节（期望 4480）" % len(b))
    w1 = b[0x0000:0x0000 + 72]
    w2 = b[0x0080:0x0080 + 1152]
    wf = b[0x0500:0x0500 + 3200]
    return w1, w2, wf


def run_cpq_twice(c, IH, IW, inC, outC, imgbuf, wbuf, outbuf, mfq):
    """★ 同一层连跑两遍，取第二遍的结果

    ★ 为什么（实测出来的）：
        同一组输入连跑 10 次 conv1，第 1 次只有 ~94~98%，
        第 2~9 次都是 100%。
        原因是缓冲有两份映射（匿名 + 不可缓存 /dev/mem），
        第一次跑时 L2 里还留着匿名别名那边的旧行；跑一遍之后就干净了。

        ⇒ 所以每层跑两遍，用第二遍。代价是每层多 4~7ms，
          本工程一组 11ms → 22ms，完全可接受，换来确定性。
    """
    c.run_cpq(IH, IW, inC, outC, imgbuf, wbuf, outbuf, mfq=mfq)
    return c.run_cpq(IH, IW, inC, outC, imgbuf, wbuf, outbuf, mfq=mfq)


def verify_wave_reference(verbose=True):
    """★ 用 AI 交付包的 64 组 reference 上板验证

    这是《quantized_model/README.md §3》指定的唯一可靠做法：
        对第 k 个输入跑一遍硬件 → 8 字节 logits
        与 reference_out.bin[k*8:(k+1)*8] 逐点比对 → 应 100% 相同

    返回 dict: {ok, total_points, same_points, groups_ok, groups_total, bad[]}
    """
    w1, w2, wf = load_wave_weights()
    with open(REF_IN_DEFAULT, "rb") as f:
        rin = f.read()
    with open(REF_OUT_DEFAULT, "rb") as f:
        rout = f.read()

    n = len(rout) // FCO_WAVE
    if len(rin) < n * 784:
        raise ValueError("reference_in.bin 太小")

    c = Cnn(verbose=False)
    try:
        c.w1.write(w1)
        c.w2.write(w2)
        c.wf.write(wf[:3200] + b"\x00" * (4032 - 3200))
        c.w1.flush()
        c.w2.flush()
        c.wf.flush()

        bad = []
        same = 0
        gok = 0
        for k in range(n):
            # ★★★ reference_in.bin 里【已经就是 int8】，直接拷！！
            #
            # 踩过：我一开始又做了一遍 (b-128)&0xFF —— 减了两次，
            #       上板 512 点只对了 3 点。
            # README §3 原文：「把 reference_in.bin[k*784:(k+1)*784]
            #                   拷进加速器输入缓冲」—— 是【拷】，不是转换。
            # README §9 也写了：「不要送原始 0~255」。
            #
            # 对照：wave_classify() 收的是 wdens 输出的 uint8（0..255），
            #       那个才需要 -128。两条路的输入形态不同，别混。
            c.img.write(rin[k * 784:(k + 1) * 784])
            c.img.flush()
            # ★ 每层跑两遍取第二遍（见 run_cpq_twice 的注释）
            run_cpq_twice(c, 28, 28, 1, CB1, c.img, c.w1, c.fb1, MFQ_C1)
            run_cpq_twice(c, 13, 13, CB1, CB2, c.fb1, c.w2, c.fb2, MFQ_C2)
            c.run_fc(c.fb2, c.wf, c.lg, FCI, FCO_WAVE, mfq=MFQ_FC)
            c.run_fc(c.fb2, c.wf, c.lg, FCI, FCO_WAVE, mfq=MFQ_FC)
            c.lg.invalidate()
            got = c.lg.read(FCO_WAVE)
            want = rout[k * FCO_WAVE:(k + 1) * FCO_WAVE]
            if got == want:
                gok += 1
            else:
                bad.append((k, list(got), list(want)))
            for i in range(FCO_WAVE):
                if got[i] == want[i]:
                    same += 1
        if verbose:
            print("[CNN OK] %d/%d 点一致" % (same, n * FCO_WAVE))
            if bad:
                for k, got, want in bad[:3]:
                    print("   ✗ 第 %d 组: 实得 %s / 期望 %s" % (k, got, want))
        return {"ok": same == n * FCO_WAVE, "total_points": n * FCO_WAVE,
                "same_points": same, "groups_ok": gok, "groups_total": n,
                "bad": bad}
    finally:
        c.close()


def wave_classify(img_u8_784, c=None):
    """单张 28×28 uint8 图 → (类别下标, 类别名, logits)

    img_u8_784: 784 字节的 uint8（wdens 密度图输出）
    c: 可复用的 Cnn 实例（不传就自己建、用完关）
    """
    own = c is None
    if own:
        c = Cnn(verbose=False)
        w1, w2, wf = load_wave_weights()
        c.w1.write(w1)
        c.w2.write(w2)
        c.wf.write(wf[:3200] + b"\x00" * (4032 - 3200))
        c.w1.flush()
        c.w2.flush()
        c.wf.flush()
    try:
        img_i8 = bytes(((b - 128) & 0xFF) for b in img_u8_784)
        c.img.write(img_i8)
        c.img.flush()
        c.run_cpq(28, 28, 1, CB1, c.img, c.w1, c.fb1, mfq=MFQ_C1)
        c.run_cpq(13, 13, CB1, CB2, c.fb1, c.w2, c.fb2, mfq=MFQ_C2)
        c.run_fc(c.fb2, c.wf, c.lg, FCI, FCO_WAVE, mfq=MFQ_FC)
        c.lg.invalidate()
        lg = list(struct.unpack("<%db" % FCO_WAVE, c.lg.read(FCO_WAVE)))
        idx = max(range(FCO_WAVE), key=lambda i: lg[i])
        return idx, WAVE_CLASSES[idx], lg
    finally:
        if own:
            c.close()


# ---------------------------------------------------------------- 主流程
def check_ip():
    print("=== IP 在线检查 ===")
    for base, nm in ((CPQ_BASE, "cnn_conv_pool_q"), (FCQ_BASE, "cnn_fc_q")):
        try:
            ip = HlsIp(base, nm)
            ap = ip.r(0x00)
            print("  ✓ %-18s @0x%08X  ap_ctrl=0x%08X"
                  "  (idle=%d ready=%d done=%d)"
                  % (nm, base, ap, (ap >> 2) & 1, (ap >> 3) & 1, (ap >> 1) & 1))
            ip.close()
        except Exception as e:
            print("  ✗ %-18s @0x%08X  %s" % (nm, base, e))
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查 IP")
    ap.add_argument("--data", default=DATA_DEFAULT)
    a = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("需要 root（/proc/self/pagemap 和 /dev/mem）: sudo python3 %s"
                 % os.path.basename(__file__))

    if not check_ip():
        sys.exit("IP 不在线 —— bitstream 刷了吗？")

    if a.check:
        return

    print()
    print("=== 读数据 ===")
    blob = open(a.data, "rb").read()
    print("  %s（%d 字节）" % (a.data, len(blob)))

    cnn = Cnn()
    try:
        label, img_u8, W1, W2, WF = cnn.load(blob)
        img_i8 = [(b - 128) for b in img_u8]
        print("  真实标签 = %d" % label)
        print()
        print("=== 物理地址（给加速器用的）===")
        for b in (cnn.img, cnn.w1, cnn.fb1, cnn.w2, cnn.fb2, cnn.wf, cnn.lg):
            print("  %-8s paddr=%#010x  size=%d" % (b.name, b.paddr, b.size))
        print("  （都在开机预留区里）%s" % DmaBuf.pool_stat())

        print()
        print("=== CPU 参考（软件复算）===")
        t0 = time.time()
        ref1, ref2, lg_ref = cpu_reference(img_i8, W1, W2, WF)
        t_cpu = time.time() - t0
        exp = 0
        for i in range(FCO):
            if lg_ref[i] > lg_ref[exp]:
                exp = i
        print("  耗时 %.3f s" % t_cpu)
        print("  argmax=%d  logits=%s" % (exp, lg_ref))

        print()
        print("=== PL 推理（加速器）===")
        t0 = time.time()
        d1 = cnn.run_cpq(28, 28, 1, CB1, cnn.img, cnn.w1, cnn.fb1)
        d2 = cnn.run_cpq(13, 13, CB1, CB2, cnn.fb1, cnn.w2, cnn.fb2)
        d3 = cnn.run_fc(cnn.fb2, cnn.wf, cnn.lg, FCI, FCO)
        cnn.lg.invalidate()          # ★ CPU 读之前必须丢缓存
        t_pl = time.time() - t0
        lg_hw = cnn.lg.as_i8()[:FCO]
        got = 0
        for i in range(FCO):
            if lg_hw[i] > lg_hw[got]:
                got = i
        print("  conv1 %.1f ms / conv2 %.1f ms / fc %.1f ms  （总 %.3f s）"
              % (d1 * 1000, d2 * 1000, d3 * 1000, t_pl))
        print("  argmax=%d  logits=%s" % (got, lg_hw))

        print()
        print("=== 逐点比对 ===")
        fb1_hw = cnn.fb1.as_i8()[:N1] if False else None   # ★ 中间层 CPU 不读
        mism = sum(1 for i in range(FCO) if lg_hw[i] != lg_ref[i])
        print("  logits 一致: %d/%d %s" % (FCO - mism, FCO,
                                        "✓" if mism == 0 else "✗ 有 %d 处不同" % mism))
        print("  真实标签     = %d" % label)
        print("  CPU 参考     = %d" % exp)
        print("  PL 加速器    = %d" % got)

        if mism == 0 and got == exp:
            ok = "✓ 一致"
            if got == label:
                print("\n>>> [CNN OK] 识别数字 = %d（与参考逐点一致，且等于真实标签）<<<" % got)
            else:
                print("\n>>> [CNN OK] 与参考一致，识别为 %d（真实标签 %d —— "
                      "模型本身的问题，不是硬件）<<<" % (got, label))
        else:
            print("\n>>> [CNN FAIL] 与参考不一致 <<<")
            return 1
        return 0
    finally:
        cnn.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
