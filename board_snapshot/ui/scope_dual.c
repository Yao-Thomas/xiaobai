/*=====================================================================
 *  scope_dual.c —— 双通道示波器采集器 的 C 驱动
 *
 *  对应 PL 里的 dsh:user:scope_dual_axi:1.0（VERSION = "SCP2"）
 *  AXI 基地址 0x43CC0000，64K。
 *
 *  和老的 scope.c 的区别：
 *    · VERSION 魔数是 0x53435032（"SCP2"），不是 0x53434F50（"SCOP"）
 *    · RDATA 一次读回【两个通道】：CH1 在 bit[9:0]，CH2 在 bit[25:16]
 *      每次读自动 +1（老的是 +4，一次打包 4 个 8 位样本）
 *    · 采样是 10 位（0..1023），不是 8 位
 *    · 触发电平/预触发/抽取的位宽都变大了
 *    · 多了 CAPS / RATE / FRAMESEQ 三个只读寄存器
 *
 *  编译（在板子上直接编，不需要交叉工具链）：
 *      gcc -O2 -shared -fPIC -o libscopedual.so scope_dual.c
 *====================================================================*/
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sys/mman.h>

#define MAP_SIZE 0x10000

/* 寄存器字节偏移（word = off/4） */
#define R_CTRL      0x00
#define R_SOURCE    0x04
#define R_DIV       0x08
#define R_DEC       0x0C
#define R_RESERVED  0x10
#define R_TRIGLEV   0x14
#define R_TRIGCFG   0x18
#define R_PRE       0x1C
#define R_START     0x20
#define R_RDPTR     0x24
#define R_RDATA     0x28
#define R_WRTOTAL   0x2C
#define R_STATUS    0x30
#define R_VERSION   0x34
#define R_CAPS      0x38
#define R_RATE      0x3C
#define R_FRAMESEQ  0x40
/* ---- 帧描述符 + Bank 锁定（步骤1）---- */
#define R_DESC0     0x44   /* {bank(1), start_addr[11:0]} */
#define R_DESC1     0x48   /* sample_count */
#define R_TRIGIDX   0x4C   /* 触发点在帧内位置 */
#define R_LOST      0x50   /* 丢帧计数 */
#define R_LOCK      0x54   /* 写: bit0=锁 bit1=bank bit2=应答 */
#define R_FLAGS     0x58   /* bit0=triggered bit1=locked bit2=busy */
#define R_FRAMEDEC  0x5C   /* 本帧实际抽取倍率 */
/* ---- 步骤2：迟滞宽度 + 采集模式 ---- */
#define R_HYS       0x60   /* 迟滞宽度（LSB）*/
#define R_ACQMODE   0x64   /* 0=Auto 1=Normal 2=Single 3=Roll */
#define R_ROLLPTR   0x68   /* {fill, roll_ptr[11:0]} */
/* ---- 阶段4：PL 列包络（复用遗留寄存器地址）---- */
#define R_ENV_PTR   0x10   /* = old R_RESERVED(0x04*4)：写起始列, bit10=通道 */
#define R_ENV_DATA  0x04   /* = old R_SOURCE(0x01*4)：读一列并自动+1 */
/* ---- 阶段4：帧统计结果寄存器 ---- */
#define R_ST_MM1    0x80   /* {max1, min1} */
#define R_ST_MM2    0x84   /* {max2, min2} */
#define R_ST_SUM1   0x88   /* 累加和 */
#define R_ST_SUM2   0x8C
#define R_ST_CLIP1  0x90   /* {贴1023数, 贴0数} */
#define R_ST_CLIP2  0x94
#define R_ST_EDG1   0x98   /* {首末边沿间隔, 边沿数} */
#define R_ST_EDG2   0x9C
#define R_ST_N      0xA0   /* {valid, 统计点数} */
#define R_WIN_START 0xA4   /* 显示窗口起点（相对触发点，采样点） */
#define R_WIN_LEN   0xA8   /* 显示窗口长度 = Timebase.span */
#define R_COL_STEP  0xAC   /* 列号步进（DDA），PS 算好下发，PL 里没有除法器 */
/* SCP4: per-frame statistics computed in PL */
#define R_STATS1    0x70   /* {clip_hi,clip_lo,2'b0,max[9:0],min[9:0]} */
#define R_STATS2    0x74
#define R_EDGE1     0x78   /* {edge_count[7:0], edge_span_ticks[23:0]} */
#define R_EDGE2     0x7C

#define VERSION_MAGIC 0x53435032u    /* "SCP2" */
#define VERSION_MAGIC_3 0x53435033u  /* "SCP3" —— 加了诊断寄存器那一版 */
#define DEPTH         4096
#define SAMPLE_MAX    1023           /* 10 位 */

static volatile uint32_t *REG = (volatile uint32_t *)0;
static int MEMFD = -1;
static unsigned int G_BASE = 0;

int sd_open(unsigned int base)
{
    void *m;
    if (REG) return 0;
    MEMFD = open("/dev/mem", O_RDWR | O_SYNC);
    if (MEMFD < 0) return -1;
    m = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, MEMFD,
             (off_t)base);
    if (m == MAP_FAILED) {
        close(MEMFD);
        MEMFD = -1;
        return -2;
    }
    REG = (volatile uint32_t *)m;
    G_BASE = base;
    return 0;
}

void sd_close(void)
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

unsigned int sd_rd(int off)          { return REG ? REG[off / 4] : 0u; }
void         sd_wr(int off, unsigned int v) { if (REG) REG[off / 4] = v; }

unsigned int sd_version(void)        { return sd_rd(R_VERSION); }
unsigned int sd_caps(void)           { return sd_rd(R_CAPS); }
unsigned int sd_rate(void)           { return sd_rd(R_RATE); }
unsigned int sd_frameseq(void)       { return sd_rd(R_FRAMESEQ); }

/* ---------------- 帧描述符 / Bank 锁定（步骤1）----------------
 * 读一帧的正确姿势：
 *     锁 bank -> 读 DESC0/DESC1/TRIGIDX -> 搬数据 -> 发 ACK
 * 核在 ACK 之前绝不覆盖这个 bank，所以拿到的永远是同一个不可变帧，
 * 不会出现由两个 bank 拼成的帧。
 *-------------------------------------------------------------*/
unsigned int sd_desc0(void)    { return sd_rd(R_DESC0); }
unsigned int sd_desc1(void)    { return sd_rd(R_DESC1); }
unsigned int sd_trigidx(void)  { return sd_rd(R_TRIGIDX); }
unsigned int sd_lost(void)     { return sd_rd(R_LOST); }
unsigned int sd_flags(void)    { return sd_rd(R_FLAGS); }
unsigned int sd_framedec(void) { return sd_rd(R_FRAMEDEC); }
unsigned int sd_stats1(void)   { return sd_rd(R_STATS1); }
unsigned int sd_stats2(void)   { return sd_rd(R_STATS2); }
unsigned int sd_edge1(void)    { return sd_rd(R_EDGE1); }
unsigned int sd_edge2(void)    { return sd_rd(R_EDGE2); }

int  sd_desc_bank(void)        { return (int)(sd_rd(R_DESC0) >> 12) & 1; }
int  sd_desc_start(void)       { return (int)(sd_rd(R_DESC0) & 0xFFF); }
int  sd_locked(void)           { return (sd_rd(R_FLAGS) >> 1) & 1; }
int  sd_frame_triggered(void)  { return sd_rd(R_FLAGS) & 1; }

/* 锁定某个 bank（PS 开始读之前调用） */
void sd_bank_lock(int bank)    { sd_wr(R_LOCK, 1u | ((unsigned)(bank & 1) << 1)); }
/* 读完释放（应答）；核收到后才会覆盖这个 bank */
void sd_bank_ack(void)         { sd_wr(R_LOCK, 4u); }
/* 释放锁定但不发 ACK（极少用） */
void sd_bank_unlock(void)      { sd_wr(R_LOCK, 0u); }

/* ---------------- 步骤2：迟滞 + 采集模式 ----------------
 * 触发检测跑在 PL 的 20MHz 原始数据上，这里只把迟滞宽度和采集模式写下去。
 * 采集模式：0=Auto 1=Normal 2=Single 3=Roll
 *   注意 Roll 是【采集模式】，不再是触发源
 *-------------------------------------------------------*/
void sd_set_hys(unsigned int lsb)  { sd_wr(R_HYS, lsb & 0x3FF); }
unsigned int sd_get_hys(void)      { return sd_rd(R_HYS) & 0x3FF; }
void sd_set_acqmode(unsigned int m){ sd_wr(R_ACQMODE, m & 3); }

/* ---------------- 阶段4：读 PL 列包络 ----------------
 * PL 在采集过程中流式生成包络，每条目 20 位 {max[9:0], min[9:0]}。
 * PS 只写一次起始列，然后连读 COLS 次即可；硬件每读一次自动 +1，
 * 读完第 COLS-1 列会自动翻到另一个通道。
 *
 * 相比旧路径（逐点写 RDPTR + 读 RDATA，8192 次事务），
 * 现在只要 2*COLS = 2016 次事务，且每次只有一次读，不再有写。
 *-----------------------------------------------------*/
/* ---------------- 阶段4：读取 PL 流式帧统计 ----------------
 * PL 在采集过程中就把 min/max/累加和/过载计数/迟滞边沿算好了，
 * PS 只需读 9 个寄存器，再自己做一次除法就得到均值与周期。
 * 这样 PS 完全不必遍历原始帧。
 *
 *   out[0]=min1 out[1]=max1 out[2]=min2 out[3]=max2
 *   out[4]=sum1 out[5]=sum2
 *   out[6]=贴0_1 out[7]=贴1023_1 out[8]=贴0_2 out[9]=贴1023_2
 *   out[10]=边沿数1 out[11]=首末间隔1 out[12]=边沿数2 out[13]=首末间隔2
 *   out[14]=统计点数 out[15]=valid
 * 返回 1 表示 valid，0 表示还没准备好。
 *-------------------------------------------------------------*/
/* 设置 PL 的显示窗口：包络只在这段采样点上算，横轴才与 Time/div 一致 */
void sd_set_window(unsigned int start, unsigned int len)
{
    unsigned long long step;
    if (len == 0) len = 4096;
    if (len > 4096) len = 4096;
    sd_wr(R_WIN_START, start & 0xFFFu);
    sd_wr(R_WIN_LEN,   len   & 0x1FFFu);
    /* ★ 列号步进 = COLS*65536/len。除法放在 PS 做（免费），
       PL 只做增量累加，避免综合出除法器把设计撑爆。*/
    step = (1008ULL * 65536ULL) / (unsigned long long)len;
    sd_wr(R_COL_STEP, (unsigned int)(step & 0xFFFFFFu));
}

unsigned int sd_get_win_start(void) { return sd_rd(R_WIN_START) & 0xFFFu; }
unsigned int sd_get_win_len(void)   { return sd_rd(R_WIN_LEN)   & 0x1FFFu; }

int sd_read_stats(unsigned int *out)
{
    unsigned int a, b, c, d, e, f, g, h, i;
    if (!out) return 0;
    a = sd_rd(R_ST_MM1);  b = sd_rd(R_ST_MM2);
    c = sd_rd(R_ST_SUM1); d = sd_rd(R_ST_SUM2);
    e = sd_rd(R_ST_CLIP1); f = sd_rd(R_ST_CLIP2);
    g = sd_rd(R_ST_EDG1); h = sd_rd(R_ST_EDG2);
    i = sd_rd(R_ST_N);
    out[0]  = a & 0x3FF;         out[1]  = (a >> 10) & 0x3FF;
    out[2]  = b & 0x3FF;         out[3]  = (b >> 10) & 0x3FF;
    out[4]  = c;                 out[5]  = d;
    out[6]  = e & 0xFFFF;        out[7]  = (e >> 16) & 0xFFFF;
    out[8]  = f & 0xFFFF;        out[9]  = (f >> 16) & 0xFFFF;
    out[10] = g & 0xFFFF;        out[11] = (g >> 16) & 0xFFFF;
    out[12] = h & 0xFFFF;        out[13] = (h >> 16) & 0xFFFF;
    out[14] = i & 0x7FFF;        out[15] = (i >> 15) & 1;
    return (int)out[15];
}

int sd_read_envelope(unsigned short *mn1, unsigned short *mx1,
                     unsigned short *mn2, unsigned short *mx2, int cols)
{
    int i, w;
    if (cols <= 0) return -1;
    sd_wr(R_ENV_PTR, 0u);                 /* 从 CH1 第 0 列开始 */
    for (i = 0; i < cols; i++) {
        w = (int)sd_rd(R_ENV_DATA);
        if (mn1) mn1[i] = (unsigned short)(w & 0x3FF);
        if (mx1) mx1[i] = (unsigned short)((w >> 10) & 0x3FF);
    }
    for (i = 0; i < cols; i++) {          /* 指针已自动翻到 CH2 */
        w = (int)sd_rd(R_ENV_DATA);
        if (mn2) mn2[i] = (unsigned short)(w & 0x3FF);
        if (mx2) mx2[i] = (unsigned short)((w >> 10) & 0x3FF);
    }
    return cols;
}

/* ---------------- 步骤3：Roll 连续读取 ----------------
 * Roll 模式下 PL 的 write_ptr 环形回绕、采样连续不停。
 * 这里每次取【最新 n 个连续点】：从 (roll_ptr - n) 开始按环形顺序读到 roll_ptr-1。
 * n 建议 64~256。
 *-----------------------------------------------------*/
int sd_roll_ptr(void)  { return (int)(sd_rd(R_ROLLPTR) & 0xFFF); }
int sd_roll_fill(void) { return (int)((sd_rd(R_ROLLPTR) >> 12) & 0x1FFF); }

int sd_read_roll(unsigned short *ch1, unsigned short *ch2, int n)
{
    int ptr, i, idx;
    if (n <= 0 || n > DEPTH) return -1;
    /* ★ Roll 模式下核必须处于运行态，否则 write_ptr 不前进、BRAM 全是 0。
       首次调用补一次 start（静态标志，避免每帧重启导致采样断流）。*/
    {
        static int roll_started = 0;
        if (!roll_started) { sd_start(); roll_started = 1; }
    }
    ptr = sd_roll_ptr();
    if (ptr < 0 || ptr >= DEPTH) ptr = 0;
    for (i = 0; i < n; i++) {
        unsigned int raw;
        idx = (ptr - n + i) % DEPTH;         /* 环形：最新 n 点的起点 */
        if (idx < 0) idx += DEPTH;
        sd_wr(R_RDPTR, (unsigned int)idx);
        raw = sd_rd(R_RDATA);
        if (ch1) ch1[i] = (unsigned short)(raw & 0x3FF);
        if (ch2) ch2[i] = (unsigned short)((raw >> 16) & 0x3FF);
    }
    return n;
}
unsigned int sd_get_acqmode(void)  { return sd_rd(R_ACQMODE) & 3; }

unsigned int sd_base(void)           { return G_BASE; }

/* 探测：读 VERSION 看是不是这个 IP。
   ⚠️ 只有确认该地址在当前 bitstream 里被解码才敢调用，否则 SIGBUS。 */
int sd_probe(void)
{
    unsigned int v;
    if (!REG) return 0;
    v = sd_rd(R_VERSION);
    return (v == VERSION_MAGIC || v == VERSION_MAGIC_3) ? 1 : 0;
}

/* ---------------- 配置 ---------------- */
void sd_set_src(int channel)         { sd_wr(R_SOURCE, (unsigned)(channel & 1)); }
void sd_set_div(unsigned int div)    { sd_wr(R_DIV, div); }
void sd_set_dec(unsigned int dec)    { sd_wr(R_DEC, dec & 0xFFFF); }
void sd_set_triglev(unsigned int l)  { sd_wr(R_TRIGLEV, l & 0x3FF); }
void sd_set_pre(unsigned int pre)    { sd_wr(R_PRE, pre & 0xFFF); }

/* edge: 0=上升 1=下降；mode: 0=Auto 1=Normal 2=Single；channel: 0=CH1 1=CH2 */
void sd_set_trigcfg(int edge, int mode, int channel)
{
    unsigned int v = (unsigned)(edge & 1)
                   | ((unsigned)(mode & 3) << 1)
                   | ((unsigned)(channel & 1) << 3);
    sd_wr(R_TRIGCFG, v);
}

/* 新版：带 4 种触发源
 *   edge  : 0=上升 1=下降
 *   mode  : 0=Auto 1=Normal 2=Single
 *   source: 0=CH1  1=CH2  2=CH1&CH2 同时  3=不触发(自由运行，用于滚动)
 * TRIGCFG 位域：bit0=edge, [2:1]=mode, [4:3]=source, bit3 兼容旧 channel
 */
void sd_set_trigcfg2(int edge, int mode, int source)
{
    unsigned int v = (unsigned)(edge & 1)
                   | ((unsigned)(mode & 3) << 1)
                   | ((unsigned)(source & 3) << 3);
    sd_wr(R_TRIGCFG, v);
}

/* ---------------- 采集控制 ----------------
 * CTRL 的 bit0 是"翻转启动"，bit1 是"翻转停止"（上升沿翻转，不是电平）。
 * 所以必须写 1 再写 0，否则第二次写同样的值不会触发。 */
void sd_start(void) { sd_wr(R_CTRL, 1); sd_wr(R_CTRL, 0); }
void sd_stop(void)  { sd_wr(R_CTRL, 2); sd_wr(R_CTRL, 0); }
void sd_clear(void) { sd_wr(R_STATUS, 1); }

static int rd_bit(int bit)
{
    return REG ? (int)((REG[R_CTRL / 4] >> bit) & 1u) : 0;
}

int sd_busy(void)      { return rd_bit(1); }
int sd_done(void)      { return rd_bit(0); }
int sd_triggered(void) { return rd_bit(2); }
int sd_bank(void)      { return rd_bit(3); }

unsigned int sd_start_addr(void) { return sd_rd(R_START) & 0xFFF; }
unsigned int sd_wr_total(void)   { return sd_rd(R_WRTOTAL) & 0x1FFF; }
unsigned int sd_status(void)     { return sd_rd(R_STATUS); }

/* ---------------------------------------------------------------
 * sd_wait_us —— 真正的【微秒】超时等待
 *
 * 旧实现把参数当"循环次数"用（每次 usleep(20)），传 200000 实际等
 * 了 4 秒，Normal 无触发时会把整个 UI 卡死。这里改成用单调时钟
 * 真正按微秒计时，并且把默认等待缩短到可接受的范围。
 * ---------------------------------------------------------------*/
int sd_wait_us(int us)
{
    struct timespec t0, t1;
    long el;
    if (us <= 0) us = 1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (;;) {
        if (sd_done() || !sd_busy()) return 1;
        usleep(20);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        el = (t1.tv_sec - t0.tv_sec) * 1000000L
           + (t1.tv_nsec - t0.tv_nsec) / 1000L;
        if (el >= (long)us) return 0;
    }
}

/* 兼容旧名字：参数现在是真正的微秒 */
int sd_wait(int timeout_us) { return sd_wait_us(timeout_us); }

/* 默认只等 20ms —— 一帧在 20MSPS/dec=1 下才 0.2ms，20ms 足够宽松 */
int sd_capture(void)
{
    sd_start();
    return sd_wait_us(20000);
}

/* 非阻塞：没准备好立刻返回 0，绝不阻塞 UI */
int sd_poll_frame(void)
{
    if (sd_done() || !sd_busy()) return 1;
    return 0;
}

/*---------------------------------------------------------------------
 *  读一整帧的原始 32 位字。
 *  out[i] = {6'd0, CH2[9:0], 6'd0, CH1[9:0]}  —— 和 RTL 里 RDATA 的排布一致
 *  上层拿到的是【按时间顺序】：out[0] 最老，out[n-1] 最新。
 *  实现：先把 RDPTR 设到 start_addr（最老样本），然后连读 RDATA；
 *        硬件每次自动 +1，12 位地址自动回绕，不需要分段。
 *-------------------------------------------------------------------*/
int sd_read_raw(unsigned int *out, int n)
{
    unsigned int sa;
    int i;

    if (!REG || !out || n <= 0) return -1;
    if (n > DEPTH) n = DEPTH;

    sa = sd_start_addr();
    REG[R_RDPTR / 4] = sa & 0xFFF;
    (void)REG[R_RDPTR / 4];       /* 吸收一次往返，让预取跟上 */

    for (i = 0; i < n; i++)
        out[i] = REG[R_RDATA / 4];
    return n;
}

/* 拆成两个通道（10 位） */
int sd_read_ch(unsigned short *ch1, unsigned short *ch2, int n)
{
    unsigned int *raw;
    int i, got;

    if (n <= 0 || n > DEPTH) return -1;
    raw = (unsigned int *)malloc(sizeof(unsigned int) * (size_t)n);
    if (!raw) return -2;
    got = sd_read_raw(raw, n);
    if (got < 0) { free(raw); return got; }
    for (i = 0; i < got; i++) {
        if (ch1) ch1[i] = (unsigned short)(raw[i] & 0x3FF);
        if (ch2) ch2[i] = (unsigned short)((raw[i] >> 16) & 0x3FF);
    }
    free(raw);
    return got;
}

/*---------------------------------------------------------------------
 * sd_read_frame_locked —— 原子读一帧（步骤1 的核心）
 *
 *   info[0] = 帧序号 sequence
 *   info[1] = bank
 *   info[2] = start_address
 *   info[3] = sample_count
 *   info[4] = trigger_index
 *   info[5] = lost_frames
 *   info[6] = frame_decimation
 *   info[7] = triggered
 *
 * 流程：等帧完成 -> 读描述符 -> 【锁 bank】-> 从 start 环绕读 n 点
 *       -> 【发 ACK】。核在 ACK 前绝不覆盖该 bank，所以拿到的必然是
 *       同一个不可变帧，不会出现两个 bank 拼接。
 *-------------------------------------------------------------------*/
int sd_read_frame_locked(unsigned short *ch1, unsigned short *ch2,
                         int n, unsigned int *info)
{
    unsigned int desc0, count, seq0, seq1;
    int bank, start, i, got;
    unsigned int *raw;

    if (n <= 0) return -1;

    /* 等一帧完成（Auto 模式下核会自动重装） */
    if (sd_capture() != 1) {
        /* 超时也尽量把当前描述符读出来，让 UI 能显示"未锁定" */
    }

    seq0  = sd_rd(R_FRAMESEQ);
    desc0 = sd_rd(R_DESC0);
    count = sd_rd(R_DESC1) & 0x1FFF;
    bank  = (int)((desc0 >> 12) & 1);
    start = (int)(desc0 & 0xFFF);
    if (count == 0) count = (unsigned int)n;
    if (start >= DEPTH) start = 0;

    /* 锁住这个 bank */
    sd_bank_lock(bank);

    raw = (unsigned int *)malloc(sizeof(unsigned int) * (size_t)n);
    if (!raw) { sd_bank_ack(); return -2; }

    for (i = 0; i < n; i++) {
        int idx = (start + i) % DEPTH;          /* 在 bank 内环绕 */
        sd_wr(R_RDPTR, (unsigned int)idx);
        raw[i] = sd_rd(R_RDATA);
    }

    got = n;
    if (ch1) for (i = 0; i < got; i++) ch1[i] = (unsigned short)(raw[i] & 0x3FF);
    if (ch2) for (i = 0; i < got; i++) ch2[i] = (unsigned short)((raw[i] >> 16) & 0x3FF);
    free(raw);

    seq1 = sd_rd(R_FRAMESEQ);

    /* 读完，应答；核收到后才允许覆盖这个 bank */
    sd_bank_ack();

    if (info) {
        info[0] = seq0;
        info[1] = (unsigned int)bank;
        info[2] = (unsigned int)start;
        info[3] = count;
        info[4] = sd_rd(R_TRIGIDX) & 0xFFF;
        info[5] = sd_rd(R_LOST);
        info[6] = sd_rd(R_FRAMEDEC) & 0xFFFF;
        info[7] = sd_rd(R_FLAGS) & 1;
        /* 读期间帧号又变了 -> 说明这帧可能不是最新的，标记出来 */
        if (seq1 != seq0) info[7] |= 0x80000000u;
    }
    return got;
}

/*---------------------------------------------------------------------
 *  把一路采样渲染成显存字节（每列 min/max 竖线 —— 示波器标准画法）
 *
 *  dst  : 紧密排布 w*h*3，字节序 B,G,R（和 fbui.to_raw 一致）
 *  color: 0xRRGGBB
 *  vlo/vhi : 映射到整幅高度的数值范围（10 位，默认 0..1023）
 *  yoff : 整条波形垂直偏移（像素，正数向下）—— 双通道上下分开用
 *-------------------------------------------------------------------*/
void sd_render(unsigned char *dst, int w, int h,
               const unsigned short *smp, int n, unsigned int color,
               int vlo, int vhi, int yoff)
{
    unsigned char cb = (unsigned char)(color & 0xFF);
    unsigned char cg = (unsigned char)((color >> 8) & 0xFF);
    unsigned char cr = (unsigned char)((color >> 16) & 0xFF);
    long span;
    int px;

    if (!dst || !smp || w <= 0 || h <= 0 || n <= 0) return;
    if (vhi <= vlo) { vlo = 0; vhi = SAMPLE_MAX; }
    span = vhi - vlo;

    for (px = 0; px < w; px++) {
        long a = (long)px * n / w;
        long e = (long)(px + 1) * n / w;
        int lo = 0x7FFF, hi = -1;
        long i;
        int y0, y1, y;

        if (e <= a) e = a + 1;
        if (e > n) e = n;
        if (a >= n) break;

        /* 到 e 为止【含边界样本】，相邻两列共用，曲线才接得上 */
        for (i = a; i <= e && i < n; i++) {
            int v = (int)smp[i];
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        if (hi < 0) continue;

        y0 = (h - 1) - (int)(((long)hi - vlo) * (h - 1) / span) + yoff;
        y1 = (h - 1) - (int)(((long)lo - vlo) * (h - 1) / span) + yoff;
        if (y1 <= y0) y1 = y0 + 1;
        if (y0 < 0) y0 = 0;
        if (y1 > h - 1) y1 = h - 1;
        if (y0 > h - 1) continue;

        for (y = y0; y <= y1; y++) {
            unsigned char *p = dst + ((size_t)y * (size_t)w + (size_t)px) * 3;
            p[0] = cr;
            p[1] = cg;
            p[2] = cb;
        }
    }
}

/* 画一条水平参考线（0V 基线 / 触发电平） */
void sd_hline(unsigned char *dst, int w, int h, int y, unsigned int color)
{
    int x;
    unsigned char cb = (unsigned char)(color & 0xFF);
    unsigned char cg = (unsigned char)((color >> 8) & 0xFF);
    unsigned char cr = (unsigned char)((color >> 16) & 0xFF);
    if (!dst || w <= 0 || h <= 0 || y < 0 || y >= h) return;
    for (x = 0; x < w; x++) {
        unsigned char *p = dst + ((size_t)y * (size_t)w + (size_t)x) * 3;
        p[0] = cr; p[1] = cg; p[2] = cb;
    }
}

/*---------------------------------------------------------------------
 *  一帧的测量（全在 C 里算，Python 循环 4096 次要 9ms）
 *  out[0]=min out[1]=max out[2]=mid out[3]=上升沿数
 *  out[4]=首尾上升沿距离(样本) out[5]=高电平点数 out[6]=n
 *-------------------------------------------------------------------*/
/* --------------------------------------------------------------------
 * sd_measure —— 帧测量（给 UI 用的整型接口）
 *
 * ★★ 2026-10-10 修掉两个测不准的根因：
 *
 * (1) 频率乱跳：原来用【零迟滞】的中点比较
 *         mid = (mn+mx)/2;  if (smp[i-1] < mid && smp[i] >= mid) edges++;
 *     只要有一个 LSB 跨过中点就计一个边沿。实测在只有 7 LSB 噪声的通道上
 *     数出 1010 个假边沿 -> 频率 4.93MHz（真实值接近 0），CH2 也一样
 *     （56 个假边沿 -> 3~5MHz 乱跳）。
 *     改成和 PL 里一致的【迟滞（施密特）】判据：
 *         先回到 mid-hys 以下武装，再升到 mid+hys 以上才计一个上升沿。
 *
 * (2) Vmax/Vmin 不准：原来用原始极值，孤立毛刺会把它拉偏。
 *     改成用直方图的 1% / 99% 分位（稳健极值），并在其基础上算中点与迟滞。
 *
 * 迟滞取稳健峰峰值的 12.5%（下限 3 LSB，上限 200 LSB）。
 * -------------------------------------------------------------------- */
void sd_measure(const unsigned short *smp, int n, int *out)
{
    int i, mid, edges = 0, first = -1, last = -1, hi = 0;
    int hist[1024];
    int acc, p1 = 0, p99 = 1023, hys, hi_th, lo_th, armed = 0;
    int half = 0, period_pk = 0, jump_kind = 0;

    if (!out) return;
    for (i = 0; i < 7; i++) out[i] = 0;
    if (!smp || n < 8) return;

    for (i = 0; i < 1024; i++) hist[i] = 0;
    for (i = 0; i < n; i++) {
        int v = (int)(smp[i] & 0x3FF);
        hist[v]++;
    }

    /* 1% 分位 */
    acc = 0;
    for (i = 0; i < 1024; i++) {
        acc += hist[i];
        if (acc >= (n + 99) / 100) { p1 = i; break; }
    }
    /* 99% 分位 */
    acc = 0;
    for (i = 0; i < 1024; i++) {
        acc += hist[i];
        if (acc >= (n * 99 + 99) / 100) { p99 = i; break; }
    }
    if (p99 < p1) p99 = p1;

    mid = (p1 + p99) / 2;
    hys = (p99 - p1) / 8;               /* 稳健峰峰的 12.5% */
    if (hys < 3)   hys = 3;
    if (hys > 200) hys = 200;
    hi_th = mid + hys;
    lo_th = mid - hys;

    /* ---- 迟滞穿越计数：上升沿和下降沿都算 ----
     *
     * ★ 为什么两个方向都算：实测用户的锯齿波周期约 204.8us，
     *   而显示窗口只有几十~几百个采样点，整帧 4096 点里也常常只有 1 个周期。
     *   只数上升沿的话需要 >=2 个上升沿才能算周期 -> 单周期信号永远测不出来
     *   （UI 只能显示 "--"）。
     *   把上升沿+下降沿都算，1 个完整周期就有 2 次穿越 -> 仍然能算出频率。
     *   兼容做法：out[3] 保持"边沿个数"的语义（穿越次数），
     *   周期 = 2*span/trans，调用方按 freq = fs * trans / (2*span) 计算。
     */
    {
        int armed_lo = 1;               /* 允许识别上升沿 */
        int prev = -1, ng = 0;
        int gaps[512];
        for (i = 0; i < n; i++) {
            int v = (int)smp[i];
            int crossed = 0;
            if (v >= hi_th && armed_lo) { crossed = 1; armed_lo = 0; }
            else if (v <= lo_th && !armed_lo) { crossed = 1; armed_lo = 1; }
            if (crossed) {
                edges++;
                if (first < 0) first = i;
                last = i;
                if (prev >= 0 && ng < 512) gaps[ng++] = i - prev;
                prev = i;
            }
            if (v > mid) hi++;
        }
        /* ★ 用【相邻穿越间隔的中位数】当半个周期。
         *   原来用 (last-first)/(edges-1) 会被个别离群穿越带偏：
         *   实测真实 1kHz（周期 2000 点）时，4 次穿越里有噪声穿越，
         *   首末间隔 2758 -> 算出 1.45kHz（偏 45%）。
         *   取中位数就能把离群值挡掉。 */
        /* ---- 周期估计：优先用"大幅度跳变"（回扫沿）----
         *
         * ★ 为什么放弃单纯数穿越：实测用户的锯齿波，回扫沿太陡，
         *   迟滞状态机被带乱 -> 间隔序列出现 [72, 2361] 这种
         *   （72 是噪声、2361 说明漏了一次穿越），中位数/四分位/最大值
         *   分别给出 1311 / 808 / 813 Hz，全都偏离真实的 1000 Hz。
         *
         *   改成：找相邻两点跳变幅度 > 稳健峰峰 / 2 的位置（也就是回扫沿），
         *   相邻两次回扫的间隔就是【一个完整周期】。对锯齿波是精确的。
         *   如果找不到这种跳变（正弦/方波），再退回穿越法。
         */
        {
            int j, last_jump = -1, nj = 0, alt = 0, last_sign = 0;
            int jg[512];
            int thr = (p99 - p1) / 2;
            if (thr < 8) thr = 8;
            for (j = 1; j < n; j++) {
                int d = (int)smp[j] - (int)smp[j - 1];
                if (d > thr || d < -thr) {       /* 上升跳变或回扫跳变都算 */
                    int sg = (d > 0) ? 1 : -1;
                    if (last_sign != 0 && sg != last_sign) alt++;
                    last_sign = sg;
                    if (last_jump >= 0 && nj < 512) jg[nj++] = j - last_jump;
                    last_jump = j;
                }
            }
            if (nj > 0) {
                int a, b, tmp;
                for (a = 1; a < nj; a++) {
                    tmp = jg[a];
                    for (b = a - 1; b >= 0 && jg[b] > tmp; b--) jg[b + 1] = jg[b];
                    jg[b + 1] = tmp;
                }
                /* 中位数间隔：
                 *   锯齿波 -> 跳变只有回扫一种符号（alt==0）-> 间隔就是【整周期】
                 *   方波   -> 跳变正负交替（alt 大）-> 间隔是【半周期】-> 乘 2
                 */
                period_pk = jg[nj / 2];
                /* ★ 只有【至少 2 个间隔】时才谈得上"符号交替"。
                 *   原来写 alt >= nj/2，nj=1 时 nj/2=0 而 alt=0 -> 0>=0 成立，
                 *   于是把锯齿波的整周期又乘了 2（实测 1kHz 读成 500Hz）。
                 *   改成必须 nj>=2，并且交替次数要过半。 */
                if (nj >= 2 && alt * 2 >= nj) period_pk *= 2;
                jump_kind = nj;
            }
        }

    if (0) { }
        if (ng > 0) {
            int a, b, tmp;
            for (a = 1; a < ng; a++) {          /* 插入排序，ng 很小 */
                tmp = gaps[a];
                for (b = a - 1; b >= 0 && gaps[b] > tmp; b--) gaps[b + 1] = gaps[b];
                gaps[b + 1] = tmp;
            }
            half = gaps[ng - 1];
            if (half <= 0) half = gaps[ng / 2];
        }
    }

    out[0] = p1;                        /* ★ Vmin = 1% 分位（稳健） */
    out[1] = p99;                       /* ★ Vmax = 99% 分位（稳健） */
    out[2] = mid;
    out[3] = edges;                     /* 穿越次数（上升+下降），诊断用 */
    /* ★ out[4] = 【整周期】的点数。
     *   优先用跳变法（对锯齿波/方波/脉冲都准）；找不到跳变时退回穿越法
     *   （2 x 半周期）。0 表示测不到周期。 */
    if (period_pk > 2)      out[4] = period_pk;
    else if (half > 2)      out[4] = 2 * half;
    else                    out[4] = 0;
    out[5] = hi;
    out[6] = n;
}

/*-------------------------------------------------------------------
 * sd_vdash -- 画一条竖虚线（水平位置的指示线用）
 *   dst/w/h : 目标缓冲（RGB 紧密排布）
 *   x       : 列号； on/off = 实/虚长度（像素）
 *   ★ 和 sd_hdash 对称，横线用 hdash、竖线用 vdash。
 *-------------------------------------------------------------------*/
void sd_vdash(unsigned char *dst, int w, int h, int x,
              unsigned int color, int on, int off)
{
    unsigned char cb = (unsigned char)(color & 0xFF);
    unsigned char cg = (unsigned char)((color >> 8) & 0xFF);
    unsigned char cr = (unsigned char)((color >> 16) & 0xFF);
    int y, k;
    if (!dst || w <= 0 || h <= 0 || x < 0 || x >= w) return;
    if (on <= 0) on = 6;
    if (off <= 0) off = 6;
    for (y = 0; y < h; y++) {
        if ((y % (on + off)) >= on) continue;
        for (k = 0; k < 2 && (x + k) < w; k++) {
            unsigned char *p = dst + ((size_t)y * (size_t)w + (size_t)(x + k)) * 3;
            p[0] = cr; p[1] = cg; p[2] = cb;
        }
    }
}

static int cmp_int(const void *a, const void *b)
{
    int aa = *(const int *)a, bb = *(const int *)b;
    return (aa > bb) - (aa < bb);
}

/* Robust live measurement. Keeping the hot loop here removes roughly 45 ms
 * of Python work per frame on the Zynq ARM. The FPGA v4 statistics registers
 * provide clipping/min/max/edge-span first; this routine is the compatible
 * fallback and also supplies percentile-based voltage measurements. */
void sd_measure_ex(const unsigned short *smp, int n, int requested_hys,
                   double *out)
{
    int hist[1024] = {0};
    int rise[512], fall[512], events[1024], gaps[1023];
    int i, nr = 0, nf = 0, ne = 0, ng = 0;
    int raw_min = 1023, raw_max = 0, lo = 0, hi = 1023;
    int center, hys, armed_r = 0, armed_f = 0;
    int low_count = 0, high_count = 0, acc;
    long long sum = 0;
    double period = 0.0, spread = 1.0, duty = -1.0;

    if (!out) return;
    for (i = 0; i < 16; i++) out[i] = 0.0;
    if (!smp || n < 8) return;
    for (i = 0; i < n; i++) {
        int v = smp[i] & 0x3FF;
        hist[v]++; sum += v;
        if (v < raw_min) raw_min = v;
        if (v > raw_max) raw_max = v;
        if (v <= 2) low_count++;
        if (v >= 1021) high_count++;
    }
    acc = 0;
    for (i = 0; i < 1024; i++) {
        acc += hist[i];
        if (acc >= (n + 99) / 100) { lo = i; break; }
    }
    acc = 0;
    for (i = 0; i < 1024; i++) {
        acc += hist[i];
        if (acc >= (n * 99 + 99) / 100) { hi = i; break; }
    }
    center = (lo + hi) / 2;
    hys = requested_hys > 0 ? requested_hys : (hi - lo) / 32;
    if (hys < 2) hys = 2;
    if (hi > lo && hys > (hi - lo) / 2) hys = (hi - lo) / 2;
    if (hys < 2) hys = 2;

    if (hi - lo >= 8) {
        int low = center - hys, high = center + hys;
        if (low < 0) low = 0;
        if (high > 1023) high = 1023;
        for (i = 0; i < n; i++) {
            int v = smp[i];
            if (v <= low) armed_r = 1;
            else if (v >= high && armed_r) {
                if (nr < 512) rise[nr++] = i;
                armed_r = 0;
            }
            if (v >= high) armed_f = 1;
            else if (v <= low && armed_f) {
                if (nf < 512) fall[nf++] = i;
                armed_f = 0;
            }
        }
        if (nr >= 2) {
            for (i = 1; i < nr; i++) gaps[ng++] = rise[i] - rise[i - 1];
            ne = nr;
        } else if (nf >= 2) {
            for (i = 1; i < nf; i++) gaps[ng++] = fall[i] - fall[i - 1];
            ne = nf;
        } else {
            int a = 0, b = 0;
            while (a < nr || b < nf) {
                if (b >= nf || (a < nr && rise[a] <= fall[b])) events[ne++] = rise[a++];
                else events[ne++] = fall[b++];
            }
            for (i = 1; i < ne; i++) gaps[ng++] = 2 * (events[i] - events[i - 1]);
        }
        if (ng > 0) {
            int median, good = 0, gmin = 0x7FFFFFFF, gmax = 0;
            long long gsum = 0;
            qsort(gaps, (size_t)ng, sizeof(gaps[0]), cmp_int);
            median = gaps[ng / 2];
            for (i = 0; i < ng; i++) {
                int g = gaps[i];
                if (g * 2 < median || g > median * 2) continue;
                gsum += g; good++;
                if (g < gmin) gmin = g;
                if (g > gmax) gmax = g;
            }
            if (good) {
                period = (double)gsum / good;
                spread = median > 0 ? (double)(gmax - gmin) / median : 1.0;
            }
        }
        if (period > 0.0 && nr >= 2) {
            long long total = 0, high_total = 0;
            int high_thr = center + hys;
            for (i = 1; i < nr; i++) {
                int j, a = rise[i - 1], b = rise[i];
                if (b - a < 4) continue;
                total += b - a;
                for (j = a; j < b; j++) if (smp[j] >= high_thr) high_total++;
            }
            if (total) duty = 100.0 * high_total / total;
        } else if (period > 0.0 && nr && nf) {
            int widths[512], nw = 0;
            for (i = 0; i < nr && nw < 512; i++) {
                int j;
                for (j = 0; j < nf; j++) if (fall[j] > rise[i]) {
                    widths[nw++] = fall[j] - rise[i]; break;
                }
            }
            if (nw) {
                qsort(widths, (size_t)nw, sizeof(widths[0]), cmp_int);
                duty = 100.0 * widths[nw / 2] / period;
            }
        }
    }
    out[0] = raw_min; out[1] = raw_max; out[2] = lo; out[3] = hi;
    out[4] = (double)sum / n; out[5] = 0.0; out[6] = center; out[7] = hys;
    out[8] = ne; out[9] = period; out[10] = spread; out[11] = duty;
    out[12] = (period > 0.0 && spread < 0.25) ? 1.0 : 0.0;
    out[13] = low_count; out[14] = high_count; out[15] = 1.0;
}

const char *sd_version_str(void)
{
    static char buf[80];
    snprintf(buf, sizeof(buf),
             "libscopedual 1.0 (magic 0x%08X caps 0x%08X @0x%08X)",
             sd_version(), sd_caps(), G_BASE);
    return buf;
}


/*-------------------------------------------------------------------
 * sd_saturation —— ADC 过载检测
 *
 *   out[0] = 贴低端(<=4)  的点数
 *   out[1] = 贴高端(>=1019)的点数
 *   out[2] = 最长低端连续段
 *   out[3] = 最长高端连续段
 *   out[4] = 1 表示判定为【输入过量程】
 *
 * 3PA1030 前端 VO = VI/5 + 1，输入范围 -5V..+5V。超出范围时 ADC 会
 * 顶在 0 或 1023 上出现平顶，此时必须明确告诉用户，而不是假装波形正常。
 * 判据：两端合计 >= n/64 点，或任一端有 >= 16 点的连续停留。
 *-------------------------------------------------------------------*/
int sd_saturation(const unsigned short *smp, int n, int *out)
{
    int i, nlo = 0, nhi = 0, rlo = 0, rhi = 0, mlo = 0, mhi = 0;
    if (!out) return -1;
    for (i = 0; i < 5; i++) out[i] = 0;
    if (!smp || n <= 0) return -1;
    for (i = 0; i < n; i++) {
        int v = (int)smp[i];
        if (v <= 4) { nlo++; rlo++; if (rlo > mlo) mlo = rlo; } else rlo = 0;
        if (v >= 1019) { nhi++; rhi++; if (rhi > mhi) mhi = rhi; } else rhi = 0;
    }
    out[0] = nlo; out[1] = nhi; out[2] = mlo; out[3] = mhi;
    out[4] = ((nlo + nhi) >= (n / 64)) || (mlo >= 16) || (mhi >= 16);
    return out[4];
}

/*-------------------------------------------------------------------
 * sd_envelope —— 把一帧采样压成屏幕列包络（在【C 里】做，不在 Python 里）
 *
 *   dst_min / dst_max : 各 cols 个 unsigned short
 *   每列取该列覆盖的采样点区间的 min / max —— 窄脉冲不会漏
 *   offset            : 水平偏移（采样点）
 *
 * 这一版先放在 C（原生代码，比 Python 循环快两个数量级）；
 * 下一步会把同样的运算搬进 PL（scope_env.v 已经写好），
 * 那样 PS 连这 8KB 都不用读。
 *-------------------------------------------------------------------*/
void sd_envelope(const unsigned short *smp, int n,
                 unsigned short *dst_min, unsigned short *dst_max,
                 int cols, int offset)
{
    int x;
    if (!smp || !dst_min || !dst_max || n <= 0 || cols <= 0) return;
    for (x = 0; x < cols; x++) {
        long long a = ((long long)(x + offset) * n) / cols;
        long long e = ((long long)(x + offset + 1) * n) / cols;
        int lo = 0x7FFF, hi = -1;
        long long i;
        if (e <= a) e = a + 1;
        a = ((a % n) + n) % n;
        e = ((e % n) + n) % n;
        if (e <= a) e += n;
        /* half-open [a,e): adjacent columns do not duplicate samples */
        for (i = a; i < e; i++) {
            int v = (int)smp[(int)(i % n)];
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        if (hi < 0) { lo = 0; hi = 0; }
        dst_min[x] = (unsigned short)lo;
        dst_max[x] = (unsigned short)hi;
    }
}


/*-------------------------------------------------------------------
 * sd_draw_env —— 把列包络按「每格 lsb_per_div 个 LSB」映射到像素并上色
 *
 *   cy         : 绘图区中心的像素 y（含上下位置）
 *   lsb_per_px : 每个像素代表多少 LSB
 *   每列从 min 到 max 画一整条竖线（包络），波形不会断
 *-------------------------------------------------------------------*/
void sd_draw_env(unsigned char *dst, int w, int h,
                 const unsigned short *emin, const unsigned short *emax,
                 int cols, unsigned int color,
                 double cy, double lsb_per_px)
{
    /* ENV_POLYLINE_V2
     *
     * 为什么重写：
     *   旧实现每列只画一根【竖线】（emin[y1] .. emax[y0]）。
     *   对正弦/三角这类连续变化的波形没问题，
     *   但对【方波】这种「陡跳变 + 长平台」的波形：
     *     · 平台段 emin~emax 只差 1~3 LSB => 竖线只有 2 像素高
     *     · 相邻列因为量化误差，竖线的 y 位置会跳 1~2 像素
     *     => 竖线之间有空隙 => 平台段看起来「断成一节一节」
     *
     * 新做法（包络折线）：
     *   把包络看成两条连续曲线：
     *     上边界 (x, y_of_emax[x])   下边界 (x, y_of_emin[x])
     *   相邻列之间用 Bresenham 把上边界连起来、下边界连起来，
     *   再把上边界到下边界之间填满（平台段就成了一条连续的横线）。
     *   · 平台段：边界水平 => 连成横线，连续无断
     *   · 陡跳变：边界陡变 => 连成竖线/斜线，正确
     *   · 不需要任何阈值判断
     */
    unsigned char cb = (unsigned char)(color & 0xFF);
    unsigned char cg = (unsigned char)((color >> 8) & 0xFF);
    unsigned char cr = (unsigned char)((color >> 16) & 0xFF);
    int x;
    int prev_x = -1, prev_top = 0, prev_bot = 0;

    if (!dst || !emin || !emax || w <= 0 || h <= 0 || cols <= 0) return;
    if (lsb_per_px <= 0.0) lsb_per_px = 1.0;

    for (x = 0; x < w; x++) {
        int c = (int)((long long)x * cols / w);
        double ytop_d, ybot_d;
        int ytop, ybot, y;

        if (c < 0) c = 0;
        if (c >= cols) c = cols - 1;

        /* emax 是最大码值 -> 屏幕上方（y 小）；emin 是最小码值 -> 下方（y 大） */
        ytop_d = cy - ((double)emax[c] - 511.5) / lsb_per_px;
        ybot_d = cy - ((double)emin[c] - 511.5) / lsb_per_px;
        ytop = (int)(ytop_d + 0.5);
        ybot = (int)(ybot_d + 0.5);

        /* 至少 1 像素高，避免细线消失 */
        if (ybot < ytop) { int t = ytop; ytop = ybot; ybot = t; }
        if (ybot == ytop) ybot = ytop + 1;

        /* 夹到画布内 */
        if (ytop < 0) ytop = 0;
        if (ybot > h - 1) ybot = h - 1;
        if (ytop > h - 1) { prev_x = -1; continue; }
        if (ybot < ytop) ybot = ytop;

        if (prev_x < 0) {
            /* 第一列：直接画竖线 */
            for (y = ytop; y <= ybot; y++) {
                unsigned char *p = dst + ((size_t)y * (size_t)w + (size_t)x) * 3;
                p[0] = cr; p[1] = cg; p[2] = cb;
            }
        } else {
            /* 从上一列到当前列：上下边界各画一条 Bresenham 线，
               再把两条线之间沿 x 方向填满 */
            int dx = x - prev_x;
            int y;
            /* 上边界线 */
            {
                int x0 = prev_x, y0 = prev_top, x1 = x, y1 = ytop;
                int ddx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
                int ddy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
                int err = ddx + ddy;
                for (;;) {
                    if (x0 >= 0 && x0 < w && y0 >= 0 && y0 < h) {
                        unsigned char *p = dst + ((size_t)y0 * (size_t)w + (size_t)x0) * 3;
                        p[0] = cr; p[1] = cg; p[2] = cb;
                    }
                    if (x0 == x1 && y0 == y1) break;
                    { int e2 = 2 * err;
                      if (e2 >= ddy) { err += ddy; x0 += sx; }
                      if (e2 <= ddx) { err += ddx; y0 += sy; } }
                }
            }
            /* 下边界线 */
            {
                int x0 = prev_x, y0 = prev_bot, x1 = x, y1 = ybot;
                int ddx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
                int ddy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
                int err = ddx + ddy;
                for (;;) {
                    if (x0 >= 0 && x0 < w && y0 >= 0 && y0 < h) {
                        unsigned char *p = dst + ((size_t)y0 * (size_t)w + (size_t)x0) * 3;
                        p[0] = cr; p[1] = cg; p[2] = cb;
                    }
                    if (x0 == x1 && y0 == y1) break;
                    { int e2 = 2 * err;
                      if (e2 >= ddy) { err += ddy; x0 += sx; }
                      if (e2 <= ddx) { err += ddx; y0 += sy; } }
                }
            }
            /* 当前列竖线：把上下边界之间填满 */
            for (y = ytop; y <= ybot; y++) {
                unsigned char *p = dst + ((size_t)y * (size_t)w + (size_t)x) * 3;
                p[0] = cr; p[1] = cg; p[2] = cb;
            }
        }

        prev_x = x;
        prev_top = ytop;
        prev_bot = ybot;
    }
}

/* Vector path for zoomed-in timebases. It avoids the thick min/max bars that
 * make a sparse waveform look flat or blocky. */
void sd_draw_trace(unsigned char *dst, int w, int h,
                   const unsigned short *smp, int n, unsigned int color,
                   double cy, double lsb_per_px)
{
    unsigned char r = (unsigned char)((color >> 16) & 0xFF);
    unsigned char g = (unsigned char)((color >> 8) & 0xFF);
    unsigned char b = (unsigned char)(color & 0xFF);
    int i;
    if (!dst || !smp || w <= 0 || h <= 0 || n < 2) return;
    if (lsb_per_px <= 0.0) lsb_per_px = 1.0;
    for (i = 1; i < n; i++) {
        int x0 = (int)((long long)(i - 1) * (w - 1) / (n - 1));
        int x1 = (int)((long long)i * (w - 1) / (n - 1));
        int y0 = (int)(cy - ((double)smp[i - 1] - 511.5) / lsb_per_px + 0.5);
        int y1 = (int)(cy - ((double)smp[i] - 511.5) / lsb_per_px + 0.5);
        int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
        int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
        int err = dx + dy;
        for (;;) {
            if (x0 >= 0 && x0 < w && y0 >= 0 && y0 < h) {
                unsigned char *p = dst + ((size_t)y0 * w + x0) * 3;
                p[0] = r; p[1] = g; p[2] = b;
            }
            if (x0 == x1 && y0 == y1) break;
            { int e2 = 2 * err;
              if (e2 >= dy) { err += dy; x0 += sx; }
              if (e2 <= dx) { err += dx; y0 += sy; } }
        }
    }
}

/*-------------------------------------------------------------------
 * sd_hdash —— 画一条水平虚线（触发电平线用）
 *   dst/w/h : 目标缓冲（RGB 紧密排布）
 *   y       : 行号； on/off = 实/虚长度（像素）
 *-------------------------------------------------------------------*/
void sd_hdash(unsigned char *dst, int w, int h, int y,
              unsigned int color, int on, int off)
{
    unsigned char cb = (unsigned char)(color & 0xFF);
    unsigned char cg = (unsigned char)((color >> 8) & 0xFF);
    unsigned char cr = (unsigned char)((color >> 16) & 0xFF);
    int x, k;
    if (!dst || w <= 0 || y < 0 || y >= h) return;
    if (on <= 0) on = 6;
    if (off <= 0) off = 6;
    for (x = 0; x < w; x++) {
        if ((x % (on + off)) >= on) continue;
        for (k = 0; k < 2 && (y + k) < h; k++) {
            unsigned char *p = dst + ((size_t)(y + k) * (size_t)w + (size_t)x) * 3;
            p[0] = cr; p[1] = cg; p[2] = cb;
        }
    }
}
