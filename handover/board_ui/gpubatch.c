/*
 * gpubatch.c —— 自研 FPGA GPU (gpu2d_axi) 的【批量驱动】
 *
 * 为什么必须要有这个:
 *   Python 驱动画一个矩形要 6 次寄存器写 + 一次 wait()。
 *   而 wait() 里有 time.sleep(0.0002) —— 一个操作至少 0.2 ms。
 *   俄罗斯方块一帧几百个方块 -> 光 Python 开销就 40~80 ms, GPU 再快也没用。
 *   把【一整批操作】丢进 C, 紧凑地写寄存器 + 紧轮询 PIXCNT,
 *   每个操作降到几微秒 —— 这才是能真正用起来的关键。
 *
 * 硬件寄存器 (偏移, 见 03_自研GPU/rtl/gpu2d_axi.v):
 *   0x00 CTRL   写1=start  读 bit0=done(只有1拍!) bit1=busy
 *   0x04 OP     0=FILL 1=LINE
 *   0x08 BASE   显存基址(物理地址)
 *   0x0C STRIDE 行跨距(字节)
 *   0x10 XY0    [31:16]=x0 [15:0]=y0
 *   0x14 XY1    [31:16]=x1 [15:0]=y1
 *   0x18 COLOR  0xRRGGBB
 *   0x1C PIXCNT 已写像素数(锁存, ★判完成就看这个)
 *   0x20 STATUS bit0=出错, 写1清
 *
 * 完成判定【必须】用 PIXCNT: 核心的 done 只有 1 个时钟周期(10ns),
 * 软件轮询(微秒级)永远抓不到。
 *
 * ops 数组格式: 每个操作 6 个 int32
 *     [0] op     0=FILL 1=LINE
 *     [1] x0
 *     [2] y0
 *     [3] x1
 *     [4] y1
 *     [5] color  0xRRGGBB
 * 矩形是【闭区间】: 宽 = x1-x0+1, 高 = y1-y0+1
 *
 * 编译: gcc -O3 -shared -fPIC -o libgpubatch.so gpubatch.c -lm
 */
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define PAGE 4096

#define R_CTRL    0x00
#define R_OP      0x04
#define R_BASE    0x08
#define R_STRIDE  0x0C
#define R_XY0     0x10
#define R_XY1     0x14
#define R_COLOR   0x18
#define R_PIXCNT  0x1C
#define R_STATUS  0x20

static int  fd = -1;
static volatile uint32_t *REG = 0;
static uint32_t GB_BASE = 0x43CB0000;
static uint32_t FB_PHYS = 0x3F100000;
static int      FB_STRIDE = 3072;
static int      READY = 0;

/* 统计 */
static unsigned char *FB_BASE_PTR = 0;   /* 显存映射起点(CPU 填充用) */
static double CPU_MS = 0.0;
static long   CPU_PX = 0;

static long   ST_OPS = 0;
static long   ST_PIXELS = 0;      /* 硬件累计写入的像素(含重绘) */
static double ST_MS = 0.0;
static double ST_MS_MAX = 0.0;

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1000000.0;
}

int gb_open(unsigned int base, unsigned int fb, int stride)
{
    if (REG) return 0;
    GB_BASE = base ? base : 0x43CB0000;
    FB_PHYS = fb ? fb : 0x3F100000;
    FB_STRIDE = stride > 0 ? stride : 3072;
    fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return -1; }
    REG = (volatile uint32_t *)mmap(NULL, PAGE, PROT_READ | PROT_WRITE,
                                    MAP_SHARED, fd, (off_t)GB_BASE);
    if (REG == MAP_FAILED) { REG = 0; close(fd); fd = -1; return -2; }
    READY = 1;
    /* 顺便把显存也映射进来, 给 CPU 版填充器(cb_rects)用 */
    if (!FB_BASE_PTR) {
        void *m = mmap(NULL, (size_t)FB_STRIDE * 1200, PROT_READ | PROT_WRITE,
                       MAP_SHARED, fd, (off_t)FB_PHYS);
        if (m != MAP_FAILED) FB_BASE_PTR = (unsigned char *)m;
    }
    return 0;
}

void gb_close(void)
{
    if (REG) { munmap((void *)REG, PAGE); REG = 0; }
    if (FB_BASE_PTR) { munmap(FB_BASE_PTR, (size_t)FB_STRIDE * 1200);
                       FB_BASE_PTR = 0; }
    if (fd >= 0) { close(fd); fd = -1; }
    READY = 0;
}

int gb_ready(void) { return READY; }
void gb_set_fb(unsigned int fb, int stride)
{
    if (fb) FB_PHYS = fb;
    if (stride > 0) FB_STRIDE = stride;
}
void gb_set_base(unsigned int base) { if (base) GB_BASE = base; }
unsigned int gb_get_base(void) { return GB_BASE; }

/* 探测: 写 COLOR 再读回 (和 Python 版 probe 一样) */
int gb_probe(void)
{
    uint32_t v;
    if (!READY) return 0;
    REG[R_COLOR / 4] = 0x5A5A5A;
    v = REG[R_COLOR / 4];
    return (v == 0x5A5A5A) ? 1 : 0;
}

void gb_stats_reset(void)
{
    ST_OPS = 0; ST_PIXELS = 0; ST_MS = 0.0; ST_MS_MAX = 0.0;
}
void gb_stats(long *ops, long *pixels, double *ms, double *ms_max)
{
    if (ops) *ops = ST_OPS;
    if (pixels) *pixels = ST_PIXELS;
    if (ms) *ms = ST_MS;
    if (ms_max) *ms_max = ST_MS_MAX;
}

/*=====================================================================
 *  批量提交: 一次把 n 个操作全画完
 *  返回实际执行的操作数; <0 表示没准备好
 *===================================================================*/
int gb_batch(const int *ops, int n)
{
    int i, done = 0;
    double t0, t1;
    long px = 0;
    if (!READY || !ops || n <= 0) return READY ? 0 : -1;

    t0 = now_ms();
    /* ★ BASE/STRIDE 整批只需要写一次 —— 以前每个操作都重写,
       在 AXI-Lite 上一次寄存器访问约 1µs, 白白多花两成时间 */
    REG[R_BASE / 4]   = FB_PHYS;
    REG[R_STRIDE / 4] = (uint32_t)FB_STRIDE;
    for (i = 0; i < n; i++) {
        const int *o = ops + i * 6;
        int op  = o[0];
        int x0  = o[1], y0 = o[2], x1 = o[3], y1 = o[4];
        uint32_t col = ((uint32_t)o[5]) & 0xFFFFFFu;
        long expect;
        int guard;

        /* ★ 这里原来是一句无条件的 `if (x1 < x0 || y1 < y0) continue;`
           —— 那是【矩形】的规范化检查 (矩形必须 x1>=x0, y1>=y0),
           却被套用到了【直线】上。结果: 任何向左 (x1<x0) 或向上 (y1<y0)
           的线都被静默丢掉, 一个像素都不画。
           实测: 6 条斜线里朝上的 3 条全没画出来 (起点像素只对上 3/6)。 */
        if (op == 0) {
            if (x1 < x0 || y1 < y0) continue;      /* 矩形: 必须规范化 */
            if (x0 < 0) x0 = 0;
            if (y0 < 0) y0 = 0;
        } else {
            /* 直线: 端点朝任意方向都合法, 只把负坐标夹到 0 */
            if (x0 < 0) x0 = 0;
            if (y0 < 0) y0 = 0;
            if (x1 < 0) x1 = 0;
            if (y1 < 0) y1 = 0;
        }

        REG[R_XY0 / 4]    = ((uint32_t)(x0 & 0xFFFF) << 16) | (uint32_t)(y0 & 0xFFFF);
        REG[R_XY1 / 4]    = ((uint32_t)(x1 & 0xFFFF) << 16) | (uint32_t)(y1 & 0xFFFF);
        REG[R_COLOR / 4]  = col;
        REG[R_OP / 4]     = (uint32_t)(op & 1);
        REG[R_CTRL / 4]   = 1;                 /* start (start 是脉冲, 硬件自动清) */

        if (op == 0) {
            expect = (long)(x1 - x0 + 1) * (long)(y1 - y0 + 1);
        } else {
            int ax = abs(x1 - x0), ay = abs(y1 - y0);
            expect = (ax > ay ? ax : ay) + 1;
        }
        /* ★ 紧轮询 PIXCNT (done 只有 1 拍, 抓不到) */
        guard = 0;
        while ((long)REG[R_PIXCNT / 4] < expect) {
            if (++guard > 40000000) break;          /* 死等保护 */
        }
        /* 出错才需要清 STATUS —— 放在循环外做, 省掉每个操作一次写 */
        px += expect;
        done++;
    }
    if (REG[R_STATUS / 4] & 1u) REG[R_STATUS / 4] = 1;
    t1 = now_ms();
    ST_OPS += done;
    ST_PIXELS += px;
    ST_MS += (t1 - t0);
    if ((t1 - t0) > ST_MS_MAX) ST_MS_MAX = (t1 - t0);
    return done;
}

/* 单矩形快捷方式 */
int gb_fill(int x0, int y0, int x1, int y1, unsigned int color)
{
    int o[6];
    o[0] = 0; o[1] = x0; o[2] = y0; o[3] = x1; o[4] = y1; o[5] = (int)color;
    return gb_batch(o, 1);
}
int gb_line(int x0, int y0, int x1, int y1, unsigned int color)
{
    int o[6];
    o[0] = 1; o[1] = x0; o[2] = y0; o[3] = x1; o[4] = y1; o[5] = (int)color;
    return gb_batch(o, 1);
}

/*=====================================================================
 *  ★ 异步接口 —— 让 CPU 的计算和 GPU 的绘图真正重叠
 *
 *  为什么需要: gb_batch() 提交完就死等 PIXCNT, 等于把 CPU 和 GPU 串成
 *  一条线。GPU 的唯一价值不是"比 CPU 填得快"(实测填整屏 GPU 20.2ms,
 *  CPU 只要 3.6ms, CPU 快 5.6 倍), 而是【不占 CPU】。
 *  所以必须能: 提交 -> 立刻返回 -> CPU 去干别的 -> 再回来收。
 *
 *  注意: 硬件只有一个操作槽, 寄存器是复用的, 所以【提交下一个之前必须
 *  等上一个完成】。真正能和 CPU 重叠的是"最后提交的那一个操作"。
 *  想要彻底并行得在 RTL 里加命令 FIFO。
 *===================================================================*/
static long PEND_EXPECT = 0;
static int  PEND = 0;

static long op_expect(int op, int x0, int y0, int x1, int y1)
{
    if (op == 0) return (long)(x1 - x0 + 1) * (long)(y1 - y0 + 1);
    {
        int ax = abs(x1 - x0), ay = abs(y1 - y0);
        return (ax > ay ? ax : ay) + 1;
    }
}

/* GPU 是否空闲 (非阻塞) */
int gb_idle(void)
{
    if (!READY || !PEND) return 1;
    if ((long)REG[R_PIXCNT / 4] >= PEND_EXPECT) { PEND = 0; return 1; }
    return 0;
}

/* 等 GPU 空闲 (阻塞) */
void gb_sync(void)
{
    int guard = 0;
    while (!gb_idle()) {
        if (++guard > 40000000) break;
    }
}

/* 提交一个操作但【不等待】。返回预期像素数。 */
long gb_post(int op, int x0, int y0, int x1, int y1, unsigned color)
{
    long expect;
    if (!READY) return 0;
    gb_sync();                        /* 寄存器复用, 必须先等上一个 */
    if (x1 < x0 || y1 < y0) return 0;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    expect = op_expect(op, x0, y0, x1, y1);
    REG[R_BASE / 4]   = FB_PHYS;
    REG[R_STRIDE / 4] = (uint32_t)FB_STRIDE;
    REG[R_XY0 / 4]    = ((uint32_t)(x0 & 0xFFFF) << 16) | (uint32_t)(y0 & 0xFFFF);
    REG[R_XY1 / 4]    = ((uint32_t)(x1 & 0xFFFF) << 16) | (uint32_t)(y1 & 0xFFFF);
    REG[R_COLOR / 4]  = color & 0xFFFFFFu;
    REG[R_OP / 4]     = (uint32_t)(op & 1);
    REG[R_CTRL / 4]   = 1;
    PEND_EXPECT = expect;
    PEND = 1;
    return expect;
}

/* 提交一批, 但每个之间等上一个 —— 只有最后一个能和后面的 CPU 活重叠 */
int gb_post_batch(const int *ops, int n)
{
    int i, done = 0;
    for (i = 0; i < n; i++) {
        const int *o = ops + i * 6;
        if (o[3] < o[1] || o[4] < o[2]) continue;
        gb_post(o[0], o[1], o[2], o[3], o[4], (uint32_t)o[5]);
        done++;
    }
    return done;
}

/*=====================================================================
 *  ★ CPU 版填充器 —— 只为了【公平对比】
 *
 *  不加上这个, "GPU vs CPU"就是假的: GPU 那边走的是 C 批量驱动, CPU 那边
 *  如果用 Python 的 fill_raw(每个矩形一个 Python 循环)会慢一个数量级,
 *  于是 GPU 白捡 2.8 倍。两边必须是同一份矩形表、同一种调用方式,
 *  区别只在"交给硬件"还是"CPU 自己写内存"。
 *===================================================================*/
int cb_rects(const int *ops, int n)
{
    int i, done = 0;
    double t0 = now_ms(), t1;
    long px = 0;
    if (!READY) return -1;
    for (i = 0; i < n; i++) {
        const int *o = ops + i * 6;
        int op = o[0];
        int x0 = o[1], y0 = o[2], x1 = o[3], y1 = o[4];
        unsigned char r = (unsigned char)((o[5] >> 16) & 255);
        unsigned char g = (unsigned char)((o[5] >> 8) & 255);
        unsigned char b = (unsigned char)(o[5] & 255);
        unsigned char *base = (unsigned char *)FB_BASE_PTR;
        int y;
        /* 同一个 bug 的另一份拷贝: 直线不能被矩形规则过滤掉 */
        if (op == 0) {
            if (x1 < x0 || y1 < y0) continue;
            if (x0 < 0) x0 = 0;
            if (y0 < 0) y0 = 0;
        } else {
            if (x0 < 0) x0 = 0;
            if (y0 < 0) y0 = 0;
            if (x1 < 0) x1 = 0;
            if (y1 < 0) y1 = 0;
        }
        if (op == 1) {
            /* 直线: Bresenham, 逐像素写 */
            int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
            int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
            int err = dx + dy;
            for (;;) {
                unsigned char *p = base + (size_t)y0 * FB_STRIDE + (size_t)x0 * 3;
                p[0] = b; p[1] = g; p[2] = r;
                px++;
                if (x0 == x1 && y0 == y1) break;
                {
                    int e2 = 2 * err;
                    if (e2 >= dy) { err += dy; x0 += sx; }
                    if (e2 <= dx) { err += dx; y0 += sy; }
                }
            }
            done++;
            continue;
        }
        for (y = y0; y <= y1; y++) {
            unsigned char *p = base + (size_t)y * FB_STRIDE + (size_t)x0 * 3;
            int k, w = x1 - x0 + 1;
            for (k = 0; k < w; k++) { p[0] = b; p[1] = g; p[2] = r; p += 3; }
        }
        px += (long)(x1 - x0 + 1) * (long)(y1 - y0 + 1);
        done++;
    }
    t1 = now_ms();
    CPU_MS += (t1 - t0);
    CPU_PX += px;
    return done;
}

double cb_stats(long *pixels)
{
    if (pixels) *pixels = CPU_PX;
    return CPU_MS;
}
void cb_stats_reset(void) { CPU_MS = 0.0; CPU_PX = 0; }

/* 版本, 方便确认板上加载的是哪一版 */
const char *gb_version(void) { return "gpubatch 1.0"; }
