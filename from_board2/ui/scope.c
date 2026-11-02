/*=====================================================================
 *  scope.c  ——  自研示波器采集器的用户态驱动 (编成 libscope.so)
 *---------------------------------------------------------------------
 *  寄存器映射 (base = 0x43CC0000, 窗口 64K)
 *    0x00 CTRL     W[0]=start W[1]=stop  R[0]=done R[1]=busy R[2]=trig R[3]=bank
 *    0x04 SRC      [0]=src_sel(0 DDS / 1 外部ADC)  [2:1]=wave
 *    0x08 DIV      基础分频 (5 -> 20 MSPS)
 *    0x0C DEC      抽取
 *    0x10 FREQ     DDS 频率字
 *    0x14 TRIGLEV  触发电平
 *    0x18 TRIGCFG  [0]=边沿(0升1降) [2:1]=模式(0Auto 1Normal 2Single)
 *    0x1C PRE      预触发点数
 *    0x20 START    R 最老样本地址
 *    0x24 RDPTR    W/R
 *    0x28 RDATA    R 返回 4 个样本, 读完自动 +4
 *    0x2C WRTOTAL  R
 *    0x30 STATUS   R[0]=err W[0]=清
 *    0x34 VERSION  R = 0x53434F50 ("SCOP")
 *
 *  ---- 为什么读缓冲要放在 C 里 ----
 *  一帧 4096 个样本 = 1024 次 AXI-Lite 读。在 Python 里做就是
 *  1024 次 ctypes 调用(每次 ~2µs) => 2ms 起步; 在 C 里是一个紧凑
 *  循环, 每次读只摊到几百纳秒。跟 libgpubatch 是同一个理由。
 *
 *  编译: gcc -O2 -shared -fPIC -o libscope.so scope.c
 *=====================================================================*/
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>

#define MAP_SIZE 0x10000

#define R_CTRL     0x00
#define R_SRC      0x04
#define R_DIV      0x08
#define R_DEC      0x0C
#define R_FREQ     0x10
#define R_TRIGLEV  0x14
#define R_TRIGCFG  0x18
#define R_PRE      0x1C
#define R_START    0x20
#define R_RDPTR    0x24
#define R_RDATA    0x28
#define R_WRTOTAL  0x2C
#define R_STATUS   0x30
#define R_VERSION  0x34

#define VERSION_MAGIC 0x53434F50u   /* "SCOP" */

static volatile uint32_t *REG = (volatile uint32_t *)0;
static int MEMFD = -1;
static unsigned int G_BASE = 0;

int sc_open(unsigned int base)
{
    void *m;
    if (REG) return 0;
    MEMFD = open("/dev/mem", O_RDWR | O_SYNC);
    if (MEMFD < 0) return -1;
    m = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, MEMFD, (off_t)base);
    if (m == MAP_FAILED) {
        close(MEMFD);
        MEMFD = -1;
        return -2;
    }
    REG = (volatile uint32_t *)m;
    G_BASE = base;
    return 0;
}

void sc_close(void)
{
    if (REG) {
        munmap((void *)REG, MAP_SIZE);
        REG = (volatile uint32_t *)0;
    }
    if (MEMFD >= 0) {
        close(MEMFD);
        MEMFD = -1;
    }
}

unsigned int sc_rd(int off)          { return REG ? REG[off / 4] : 0u; }
void         sc_wr(int off, unsigned int v) { if (REG) REG[off / 4] = v; }

unsigned int sc_version(void)        { return sc_rd(R_VERSION); }
unsigned int sc_base(void)           { return G_BASE; }

/* 探测: 读 VERSION 看是不是我们的 IP。
   ⚠️ 只有确认该地址在当前 bitstream 里被解码才敢调用, 否则 SIGBUS。 */
int sc_probe(void)
{
    return (REG && sc_rd(R_VERSION) == VERSION_MAGIC) ? 1 : 0;
}

/* ---------------- 配置 ---------------- */
void sc_set_src(int src, int wave)
{
    sc_wr(R_SRC, (unsigned)((src & 1) | ((wave & 3) << 1)));
}
void sc_set_div(unsigned int div)    { sc_wr(R_DIV, div); }
void sc_set_dec(unsigned int dec)    { sc_wr(R_DEC, dec); }
void sc_set_freq(unsigned int f)     { sc_wr(R_FREQ, f); }
void sc_set_triglev(unsigned int l)  { sc_wr(R_TRIGLEV, l & 0xFF); }
void sc_set_trigcfg(int edge, int mode)
{
    sc_wr(R_TRIGCFG, (unsigned)((edge & 1) | ((mode & 3) << 1)));
}
void sc_set_pre(unsigned int pre)    { sc_wr(R_PRE, pre & 0xFFF); }

void sc_start(void)                  { sc_wr(R_CTRL, 1); }
void sc_stop(void)                   { sc_wr(R_CTRL, 2); }
unsigned int sc_ctrl(void)           { return sc_rd(R_CTRL); }
int sc_busy(void)                    { return (int)(sc_rd(R_CTRL) & 2u); }
int sc_done(void)                    { return (int)(sc_rd(R_CTRL) & 1u); }
int sc_triggered(void)               { return (int)((sc_rd(R_CTRL) >> 2) & 1u); }
int sc_bank(void)                    { return (int)((sc_rd(R_CTRL) >> 3) & 1u); }
unsigned int sc_start_addr(void)     { return sc_rd(R_START) & 0xFFFu; }
unsigned int sc_wr_total(void)       { return sc_rd(R_WRTOTAL); }
unsigned int sc_status(void)         { return sc_rd(R_STATUS); }
void sc_clear_status(void)           { sc_wr(R_STATUS, 1); }

/* 等一帧采完; 返回 1 成功, 0 超时 */
int sc_wait(int timeout_us)
{
    int i;
    for (i = 0; i < timeout_us; i++) {
        if (sc_done() || !sc_busy()) return 1;
        usleep(20);
    }
    return 0;
}

/* 触发一次并等结果 (最常用的一条龙) */
int sc_capture(void)
{
    sc_start();
    return sc_wait(200000);          /* 最多等 4 秒 */
}

/*---------------------------------------------------------------------
 *  读一整帧。
 *  上层拿到的是【按时间顺序】的样本: out[0] 最老, out[n-1] 最新。
 *  实现: 先把 RDPTR 设到 start_addr (= 最老样本的地址), 然后连读
 *        RDATA; 硬件每次返回 4 个样本并自动 +4, 地址 12 位自动回绕,
 *        所以不需要任何分段/搬运逻辑。
 *  返回写入的样本数, 失败返回负数。
 *-------------------------------------------------------------------*/
int sc_read_frame(unsigned char *out, int nsamp)
{
    unsigned int sa;
    int i, j, words;

    if (!REG || !out || nsamp <= 0) return -1;
    if (nsamp > 4096) nsamp = 4096;

    sa = sc_start_addr();
    REG[R_RDPTR / 4] = sa;
    (void)REG[R_RDPTR / 4];          /* 吸收一次往返, 让后台预取跟上 */

    words = nsamp / 4;
    for (i = 0; i < words; i++) {
        uint32_t w = REG[R_RDATA / 4];
        out[i * 4 + 0] = (unsigned char)(w & 0xFF);
        out[i * 4 + 1] = (unsigned char)((w >> 8) & 0xFF);
        out[i * 4 + 2] = (unsigned char)((w >> 16) & 0xFF);
        out[i * 4 + 3] = (unsigned char)((w >> 24) & 0xFF);
    }
    return words * 4;
}

/* 只读前 n 个样本 (给"先看一眼"用, 不常用) */
int sc_read_n(unsigned char *out, int n)
{
    return sc_read_frame(out, n);
}

/*---------------------------------------------------------------------
 *  把一帧采样【直接渲染】成显存字节。
 *
 *  为什么要在 C 里做:
 *    用 PIL 画 1024 条竖线 (d.line) 实测要 90 ms/帧, 整机只有 8 FPS。
 *    在 C 里就是把每列的 min/max 算出来填几列字节, 实测 ~1 ms。
 *
 *  dst  : 紧密排布的 w*h*3 缓冲, 字节序 B,G,R
 *         (和 fbui.to_raw 的输出一致, 可以直接喂给 fbui.blit_raw)
 *  color: 0xRRGGBB
 *  每列取该列覆盖区间的 min/max 画一条竖线 —— 示波器的标准画法,
 *  快信号也不会因为抽点而丢毛刺。
 *-------------------------------------------------------------------*/
void sc_render(unsigned char *dst, int w, int h,
               const unsigned char *smp, int n, unsigned int color)
{
    unsigned char cb = (unsigned char)(color & 0xFF);
    unsigned char cg = (unsigned char)((color >> 8) & 0xFF);
    unsigned char cr = (unsigned char)((color >> 16) & 0xFF);
    int px;

    if (!dst || !smp || w <= 0 || h <= 0 || n <= 0) return;

    for (px = 0; px < w; px++) {
        long a = (long)px * n / w;
        long e = (long)(px + 1) * n / w;
        int lo = 255, hi = 0;
        long i;
        int y0, y1, y;

        if (e <= a) e = a + 1;
        if (e > n) e = n;
        if (a >= n) break;

        /* ★ 到 e 为止【含边界样本】, 让相邻两列共用这一个样本。
           第一版写的是 i < e, 于是单调上升/下降的段落里,
           第 k 列的值域是 [s(4k), s(4k+3)], 第 k+1 列是 [s(4k+4), s(4k+7)],
           中间差一个采样间隔 —— 画出来就是一段一段的虚线 (放大看非常明显)。
           共用边界样本后两列的值域必然相接, 曲线才连得起来。 */
        for (i = a; i <= e && i < n; i++) {
            unsigned char v = smp[i];
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        y0 = (h - 1) - (int)((long)hi * (h - 1) / 255);
        y1 = (h - 1) - (int)((long)lo * (h - 1) / 255);
        if (y1 <= y0) y1 = y0 + 1;
        if (y0 < 0) y0 = 0;
        if (y1 > h - 1) y1 = h - 1;

        for (y = y0; y <= y1; y++) {
            unsigned char *p = dst + ((size_t)y * (size_t)w + (size_t)px) * 3;
            p[0] = cb;
            p[1] = cg;
            p[2] = cr;
        }
    }
}

/*---------------------------------------------------------------------
 *  一帧的测量, 全部在 C 里算 (Python 循环 4096 次要 9 ms)
 *  out[0]=min out[1]=max out[2]=mid out[3]=上升沿数
 *  out[4]=首尾上升沿距离(样本) out[5]=高电平点数 out[6]=n
 *-------------------------------------------------------------------*/
void sc_measure(const unsigned char *smp, int n, int *out)
{
    int i, mn = 255, mx = 0, mid, edges = 0, first = -1, last = -1, hi = 0;

    if (!out) return;
    for (i = 0; i < 7; i++) out[i] = 0;
    if (!smp || n < 8) return;

    for (i = 0; i < n; i++) {
        unsigned char v = smp[i];
        if (v < mn) mn = v;
        if (v > mx) mx = v;
    }
    mid = (mn + mx) / 2;
    for (i = 1; i < n; i++) {
        if (smp[i - 1] < mid && smp[i] >= mid) {
            edges++;
            if (first < 0) first = i;
            last = i;
        }
        if (smp[i] > mid) hi++;
    }
    out[0] = mn;
    out[1] = mx;
    out[2] = mid;
    out[3] = edges;
    out[4] = (first >= 0 && edges >= 2) ? (last - first) : 0;
    out[5] = hi;
    out[6] = n;
}

const char *sc_version_str(void)
{
    static char buf[64];
    snprintf(buf, sizeof(buf), "libscope 1.0 (magic 0x%08X @0x%08X)",
             sc_version(), G_BASE);
    return buf;
}

