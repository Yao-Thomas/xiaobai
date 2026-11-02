"""
preprocess.py —— 采集缓冲 → 28×28 STFT 时频图（★ 主机与板端必须逐点一致）

=============================================================================
★ 这是接口 ②（数据集格式）里最关键的"输入形态"实现，属于【冻结契约】。
   板端 / 主机 / 示波器负责人三方的实现必须与本文件输出逐点相同。
=============================================================================

背景约束（来自交接包）：
  · 示波器一次采集 = 4096 个 8 位样本（0~255），见 09_板子与工具链.md 第五节
  · 上一轮 PL 侧 CNN 加速器的输入几何是 **28×28×1 int8**（不是 32×32）：
        输入 28×28 → Conv3×3 1→8 → Pool2 → 13×13
                   → Conv3×3 8→16 → Pool2 → 5×5×16=400 → FC(400→N)
    见 交接文档/05_M4b_CNN方案.md 与 源码/hls/cnn_conv_pool_q.cpp
    该文件里 OH=(IH-KH+1)/P，28→13→5，FC 输入恰好 400。
  · ⇒ 数据集格式文档里写的 "如 32×32" 是示意值；**为复用既有 IP 不改硬件，
    本项目锁定 28×28**。这一条已写进 docs/00_接口冻结单.md，需主线融合负责人确认。

上游接口：
    samples_u8 : 长度 4096 的 uint8 序列（示波器 capture_once() 返回的 samples）
下游接口：
    28×28 uint8 图像；送加速器时统一按 int8 = u8 - 128 转换
=============================================================================
"""
from __future__ import annotations

CAP_LEN = 4096          # 一次采集的样本数（固定）
IMG = 28                # 输出图像边长（与 PL 加速器几何对齐）
NFFT = 512              # STFT 窗长
HOP = 132               # 帧移：(4096-512)//27 = 132 → 帧起点 0,132,...,3564，末帧右对齐
NROWS = 28              # 频率轴行数（对数分箱）
DB_RANGE = 60.0         # 相对本样本峰值的固定动态范围 (dB)
EPS = 1e-6

# ---------------------------------------------------------------------------
# ★ 频率轴分箱表：扫频 bin 1..256 按几何（对数）间隔分 28 行。
#   纯 Python 计算、无 numpy 依赖，保证主机/板端/任何人重算得到同一张表。
#   每个 bin 范围取【最大值】（保留谐波峰，比取均值更利于识别）。
# ---------------------------------------------------------------------------
def _bin_ranges():
    """频率轴分箱表：低频段线性、高频段对数（"半对数"混合轴）

    纯对数轴在低频端会退化：bin 1..256 分成 28 行时，相邻行边界落在整数 bin
    之间，导致前 3~4 行都只能取到 bin 1（信息冗余）。
    这里用 edge[r] = max(r+1, 1·ratio^r) 修掉：
      · 低端每行至少独享 1 个 bin（bin 1,2,3,...）
      · 高端仍是几何（对数）间距 —— 倍频程 = 固定行距，谐波梳变成等间距条纹
    """
    n_bins = NFFT // 2 + 1              # 257 个唯一频点 0..256
    lo_bin, hi_bin = 1, n_bins - 1      # 丢掉 DC(0)，最高到 256 (=fs/2)
    ratio = (float(hi_bin) / float(lo_bin)) ** (1.0 / float(NROWS))

    edges = []
    for r in range(NROWS + 1):
        e = lo_bin * (ratio ** r)
        if e < lo_bin + r:              # 低频端至少每行 1 个 bin
            e = float(lo_bin + r)
        edges.append(e)
    edges[NROWS] = float(n_bins)        # 末行一定覆盖到最高频点

    out = []
    for r in range(NROWS):
        i0 = int(edges[r])
        i1 = int(edges[r + 1])
        if i1 <= i0:
            i1 = i0 + 1
        i0 = max(lo_bin, min(i0, hi_bin))
        i1 = max(i0 + 1, min(i1, n_bins))
        out.append((i0, i1))
    return tuple(out)


BIN_RANGES = _bin_ranges()      # 长度 28 的 (start, end) 半开区间表


def _hann(n: int):
    """周期 Hann 窗：w[i] = 0.5 - 0.5*cos(2*pi*i/n)（不含 numpy 的写法见 pure 分支）"""
    import math
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / n) for i in range(n)]


HANN = _hann(NFFT)


def _frame_starts():
    """28 帧的起始下标。★ 首帧从 0、末帧右对齐到 CAP_LEN-NFFT，保证覆盖整段缓冲。"""
    starts = []
    for i in range(IMG):
        if i == IMG - 1:
            s = CAP_LEN - NFFT            # 末帧右对齐：尾部样本不被丢掉
        else:
            s = min(i * HOP, CAP_LEN - NFFT)
        starts.append(s)
    return starts


FRAME_STARTS = _frame_starts()       # 长度 28


# ===========================================================================
# 主实现（numpy）
# ===========================================================================
def capture_to_image_u8_np(samples_u8, fs_hz=None):
    """4096 样本 → 28×28 uint8 时频图。fs_hz 仅作元信息记录，不参与计算。"""
    import numpy as np

    s = np.asarray(samples_u8)
    if s.shape != (CAP_LEN,):
        raise ValueError("capture must have exactly %d samples, got %s" % (CAP_LEN, s.shape))
    s = s.astype(np.float64)

    # 1) 归一化到 [-1, 1)（8 位 ADC 的满量程）
    x = (s - 128.0) / 128.0

    # 2) 分帧 + 加窗
    win = np.asarray(HANN, dtype=np.float64)
    frames = np.empty((IMG, NFFT), dtype=np.float64)
    for i, st in enumerate(FRAME_STARTS):
        frames[i] = x[st:st + NFFT] * win

    # 3) 幅度谱
    spec = np.abs(np.fft.rfft(frames, n=NFFT, axis=1))       # (28, 257)

    # 4) 对数频率分箱（每行取该频段的最大值）
    rows = np.empty((NROWS, IMG), dtype=np.float64)
    for r, (i0, i1) in enumerate(BIN_RANGES):
        rows[r] = spec[:, i0:i1].max(axis=1)

    # 5) dB，并以本样本峰值为基准固定 60 dB 动态范围
    db = 20.0 * np.log10(rows + EPS)
    peak = float(db.max())
    v = (db - (peak - DB_RANGE)) / DB_RANGE
    np.clip(v, 0.0, 1.0, out=v)

    # 6) 量化到 uint8（四舍五入）
    u8 = np.rint(v * 255.0).astype(np.uint8)
    return u8


def capture_to_image_u8_batch(samples_2d):
    """批量版（用于数据集生成）。★ 与单样本版逐点一致，已在 tests 里断言。"""
    import numpy as np

    s = np.asarray(samples_2d)
    if s.ndim != 2 or s.shape[1] != CAP_LEN:
        raise ValueError("expect (N,%d), got %s" % (CAP_LEN, s.shape))
    x = (s.astype(np.float64) - 128.0) / 128.0
    win = np.asarray(HANN, dtype=np.float64)

    frames = np.empty((s.shape[0], IMG, NFFT), dtype=np.float64)
    for i, st in enumerate(FRAME_STARTS):
        frames[:, i, :] = x[:, st:st + NFFT] * win

    spec = np.abs(np.fft.rfft(frames, n=NFFT, axis=2))        # (N,28,257)
    rows = np.empty((s.shape[0], NROWS, IMG), dtype=np.float64)
    for r, (i0, i1) in enumerate(BIN_RANGES):
        rows[:, r, :] = spec[:, :, i0:i1].max(axis=2)

    db = 20.0 * np.log10(rows + EPS)
    peak = db.max(axis=(1, 2), keepdims=True)
    v = (db - (peak - DB_RANGE)) / DB_RANGE
    np.clip(v, 0.0, 1.0, out=v)
    return np.rint(v * 255.0).astype(np.uint8)


# ===========================================================================
# ★ 第二种输入形态：时间×幅度【密度图】(wdens)
#
# 为什么必须准备它（这是本项目一个必须说清的技术判断）：
#   接口②建议用 STFT。但 STFT 的分辨率要求「一个窗内至少 2 个周期」：
#       窗口内周期数 = K × NFFT / 4096
#   而示波器为了"屏幕上看 2~5 个周期"（自动设置目标的回报项之一），
#   缓冲区内只有 K = 2~5 个周期 ⇒ 窗内 0.25~0.6 个周期 ⇒ **谐波根本分不开**。
#   即使 K=16（窗内 2 周期）也只是勉强。
#   ⇒ 少周期工况下，能用的 2D 表示只有【时间-幅度】域。
#
# 密度图的优势：
#   · 稠密、无栅格化空洞（这正是接口②反对"折线图"的理由，密度图没有这个缺点）
#   · 每个采样点都被计入（画折线会丢点）
#   · 少周期时直接呈现波形形状；多周期时每个时间列内退化为【幅度分布】，
#     而正弦/三角/锯齿/方波的幅度分布**本来就各不相同**
#     （正弦是反正弦分布、三角是均匀分布、方波是双尖峰、噪声是高斯）
#   · 四类异常在密度图上都极其直观：
#       毛刺→孤立亮点；削顶→顶端整片截断；丢信号→窄带平线；占空比异常→上下轨亮度不对称
#
# 结论：两种形态都实现、都用同一份原始数据训练、用验证集比出赢家再交付。
#       原始缓冲已经全量落盘（dataset/raw/），换表示不用重采数据。
# ===========================================================================
NCOLS = 28          # 时间列
NROWS_D = 28        # 幅度行


def _col_bounds():
    """28 列均分 4096 个采样点（最后一列吃掉余数）"""
    base = CAP_LEN // NCOLS
    out = []
    for c in range(NCOLS):
        a = c * base
        b = CAP_LEN if c == NCOLS - 1 else (c + 1) * base
        out.append((a, b))
    return tuple(out)


COL_BOUNDS = _col_bounds()

# 行 0 = 顶部 = 高电平（和示波器屏幕方向一致）
ROW_CODE_EDGES = tuple(255.0 - (r * 256.0 / NROWS_D) for r in range(NROWS_D + 1))


def _row_of(code: int) -> int:
    """8 位码值 → 行号（0 = 顶部/高电平，27 = 底部/低电平）"""
    r = int((255 - code) * NROWS_D / 256.0)
    if r < 0:
        r = 0
    if r > NROWS_D - 1:
        r = NROWS_D - 1
    return r


def capture_to_wdens_u8_np(samples_u8, fs_hz=None):
    """4096 样本 → 28×28 密度图（uint8）。行=幅度（0 顶=高电平），列=时间。"""
    import numpy as np

    s = np.asarray(samples_u8)
    if s.shape != (CAP_LEN,):
        raise ValueError("capture must have exactly %d samples, got %s" % (CAP_LEN, s.shape))

    rows = (255 - s.astype(np.int32)) * NROWS_D // 256
    np.clip(rows, 0, NROWS_D - 1, out=rows)

    img = np.zeros((NROWS_D, NCOLS), dtype=np.float64)
    for c, (a, b) in enumerate(COL_BOUNDS):
        rr = rows[a:b]
        cnt = np.bincount(rr, minlength=NROWS_D).astype(np.float64)
        n = float(b - a)
        # 列内密度 → sqrt 压缩（方差稳定化，且让弱轨迹也看得见）
        img[:, c] = np.sqrt(cnt / n)

    mx = float(img.max())
    if mx <= 0:
        return np.zeros((NROWS_D, NCOLS), dtype=np.uint8)
    v = img / mx
    return np.rint(v * 255.0).astype(np.uint8)


def capture_to_wdens_u8_batch(samples_2d):
    """批量版密度图（数据集生成用）"""
    import numpy as np

    s = np.asarray(samples_2d)
    if s.ndim != 2 or s.shape[1] != CAP_LEN:
        raise ValueError("expect (N,%d), got %s" % (CAP_LEN, s.shape))
    rows = (255 - s.astype(np.int32)) * NROWS_D // 256
    np.clip(rows, 0, NROWS_D - 1, out=rows)

    N = s.shape[0]
    img = np.zeros((N, NROWS_D, NCOLS), dtype=np.float64)
    for c, (a, b) in enumerate(COL_BOUNDS):
        rr = rows[:, a:b]                                   # (N, w)
        idx = rr + (np.arange(N)[:, None] * NROWS_D)        # 展平索引
        flat = np.bincount(idx.ravel(), minlength=N * NROWS_D)
        img[:, :, c] = np.sqrt(flat.reshape(N, NROWS_D) / float(b - a))

    mx = img.max(axis=(1, 2), keepdims=True)
    mx[mx <= 0] = 1.0
    return np.rint((img / mx) * 255.0).astype(np.uint8)


def capture_to_wdens_u8_pure(samples_u8, fs_hz=None):
    import math

    if len(samples_u8) != CAP_LEN:
        raise ValueError("capture must have exactly %d samples" % CAP_LEN)
    img = [[0.0] * NCOLS for _ in range(NROWS_D)]
    for c, (a, b) in enumerate(COL_BOUNDS):
        cnt = [0] * NROWS_D
        for i in range(a, b):
            cnt[_row_of(int(samples_u8[i]))] += 1
        n = float(b - a)
        for r in range(NROWS_D):
            img[r][c] = math.sqrt(cnt[r] / n)
    mx = max(max(row) for row in img)
    if mx <= 0:
        return [[0] * NCOLS for _ in range(NROWS_D)]
    return [[int(math.floor(img[r][c] / mx * 255.0 + 0.5)) for c in range(NCOLS)]
            for r in range(NROWS_D)]


# ===========================================================================
# 统一入口
# ===========================================================================
PP_MODES = ("stft", "wdens")


def capture_to_image(samples, mode: str = "stft"):
    if mode == "stft":
        return capture_to_image_u8(samples)
    if mode == "wdens":
        return capture_to_wdens_u8(samples)
    raise ValueError("unknown preprocessing mode %r (expect %s)" % (mode, PP_MODES))


def captures_to_images(samples_2d, mode: str = "stft"):
    if mode == "stft":
        return capture_to_image_u8_batch(samples_2d)
    if mode == "wdens":
        return capture_to_wdens_u8_batch(samples_2d)
    raise ValueError("unknown preprocessing mode %r" % (mode,))


# ===========================================================================
# 纯 Python 后备实现（板端 armv7l 若无 numpy 时使用；输出与上面逐点一致）
# ===========================================================================
def _fft(re, im):
    """迭代 radix-2 FFT（原地，长度必须是 2 的幂）"""
    import math
    n = len(re)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wl_re, wl_im = math.cos(ang), math.sin(ang)
        half = length >> 1
        for i in range(0, n, length):
            wr, wi = 1.0, 0.0
            for k in range(half):
                ur, ui = re[i + k], im[i + k]
                vr = re[i + k + half] * wr - im[i + k + half] * wi
                vi = re[i + k + half] * wi + im[i + k + half] * wr
                re[i + k], im[i + k] = ur + vr, ui + vi
                re[i + k + half], im[i + k + half] = ur - vr, ui - vi
                wr, wi = wr * wl_re - wi * wl_im, wr * wl_im + wi * wl_re
        length <<= 1


def capture_to_image_u8_pure(samples_u8, fs_hz=None):
    import math

    if len(samples_u8) != CAP_LEN:
        raise ValueError("capture must have exactly %d samples" % CAP_LEN)
    x = [(float(v) - 128.0) / 128.0 for v in samples_u8]

    spec = []
    for st in FRAME_STARTS:
        re = [x[st + i] * HANN[i] for i in range(NFFT)]
        im = [0.0] * NFFT
        _fft(re, im)
        spec.append([math.hypot(re[k], im[k]) for k in range(NFFT // 2 + 1)])

    rows = []
    for (i0, i1) in BIN_RANGES:
        rows.append([max(spec[f][i0:i1]) for f in range(IMG)])

    db = [[20.0 * math.log10(v + EPS) for v in row] for row in rows]
    peak = max(max(r) for r in db)
    img = []
    for r in range(NROWS):
        line = []
        for f in range(IMG):
            v = (db[r][f] - (peak - DB_RANGE)) / DB_RANGE
            v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
            line.append(int(math.floor(v * 255.0 + 0.5)))
        img.append(line)
    return img


# ===========================================================================
# 自动选择实现
# ===========================================================================
try:
    import numpy as _np        # noqa: F401
    capture_to_image_u8 = capture_to_image_u8_np
    capture_to_wdens_u8 = capture_to_wdens_u8_np
    IMPL = "numpy"
except Exception:              # pragma: no cover
    capture_to_image_u8 = capture_to_image_u8_pure
    capture_to_wdens_u8 = capture_to_wdens_u8_pure
    IMPL = "pure-python"


def image_u8_to_int8(img_u8):
    """★ 送加速器前的唯一转换：int8 = uint8 - 128（8 位 ADC 满量程的中心化）"""
    import numpy as np
    a = np.asarray(img_u8, dtype=np.int16) - 128
    return a.astype(np.int8)


# ===========================================================================
# 自检
# ===========================================================================
if __name__ == "__main__":
    import numpy as np
    rng = np.random.default_rng(0)
    s = (127.5 + 100 * np.sin(2 * np.pi * 0.03 * np.arange(CAP_LEN))).astype(np.uint8)
    a = capture_to_image_u8_np(s)
    b = np.asarray(capture_to_image_u8_pure(s.tolist()), dtype=np.uint8)
    print("impl           :", IMPL)
    print("[stft] shape/dtype:", a.shape, a.dtype, "range", a.min(), a.max())
    print("[stft] numpy vs pure:", "IDENTICAL" if np.array_equal(a, b)
          else "MISMATCH maxdiff=%d" % np.abs(a.astype(int) - b.astype(int)).max())
    print("bin ranges[0:4]:", BIN_RANGES[:4], "...", BIN_RANGES[-2:])
    print("frame starts   :", FRAME_STARTS[:3], "...", FRAME_STARTS[-2:])

    w = capture_to_wdens_u8_np(s)
    w2 = np.asarray(capture_to_wdens_u8_pure(s.tolist()), dtype=np.uint8)
    print("[wdens] shape/dtype:", w.shape, w.dtype, "range", w.min(), w.max())
    print("[wdens] numpy vs pure:", "IDENTICAL" if np.array_equal(w, w2)
          else "MISMATCH maxdiff=%d" % np.abs(w.astype(int) - w2.astype(int)).max())
    print("[wdens] col bounds:", COL_BOUNDS[:3], "...", COL_BOUNDS[-1])

    print("\nstft 前 8 行 x 10 列:\n", a[:8, :10])
    print("\nwdens 前 12 行 x 10 列:\n", w[:12, :10])
