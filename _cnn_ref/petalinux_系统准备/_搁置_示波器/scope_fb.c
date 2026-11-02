// ============================================================================
// scope_fb.c —— 极简示波器（直接画 Linux framebuffer /dev/fb0，不依赖 Qt）
//   数据源二选一：
//     (1) UIO: /dev/uio0 的 mmap 缓冲里是 PL 采集的 8bit 采样(经 VDMA/采集FIFO)
//     (2) DEMO: 没接采集时用内部正弦/方波自测，先把界面跑起来
//   支持 16bpp(RGB565) 与 32bpp(XRGB8888) 两种 framebuffer。
//   交叉编译(PetaLinux sysroot):  $CROSS_COMPILE gcc scope_fb.c -O2 -o scope_fb
// ============================================================================
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <math.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/fb.h>

/* ------------------------- framebuffer ------------------------- */
typedef struct { int fd; uint8_t *mem; size_t size; int w,h,bpp,line; } fb_t;
static fb_t FB;

static int fb_open(const char *dev){
    struct fb_var_screeninfo v; struct fb_fix_screeninfo f;
    FB.fd = open(dev, O_RDWR);
    if (FB.fd < 0){ perror("open fb"); return -1; }
    if (ioctl(FB.fd, FBIOGET_VSCREENINFO, &v) || ioctl(FB.fd, FBIOGET_FSCREENINFO, &f)){ perror("ioctl fb"); return -1; }
    FB.w=v.xres; FB.h=v.yres; FB.bpp=v.bits_per_pixel; FB.line=f.line_length;
    FB.size = FB.line * FB.h;
    FB.mem = mmap(0, FB.size, PROT_READ|PROT_WRITE, MAP_SHARED, FB.fd, 0);
    if (FB.mem == MAP_FAILED){ perror("mmap fb"); return -1; }
    printf("[fb] %dx%d %dbpp line=%d\n", FB.w, FB.h, FB.bpp, FB.line);
    return 0;
}
static inline void px(int x,int y,uint32_t c){
    if(x<0||y<0||x>=FB.w||y>=FB.h) return;
    uint8_t *p = FB.mem + y*FB.line + x*(FB.bpp/8);
    if (FB.bpp==32){ *(uint32_t*)p = c; }
    else if (FB.bpp==16){ /* RGB565 */ *(uint16_t*)p = (uint16_t)(((c>>19)&0x1F)<<11 | ((c>>10)&0x3F)<<5 | ((c>>3)&0x1F)); }
    else if (FB.bpp==24){ p[0]=c&0xFF; p[1]=(c>>8)&0xFF; p[2]=(c>>16)&0xFF; }
}
static void hline(int x0,int x1,int y,uint32_t c){ int x; for(x=x0;x<=x1;x++) px(x,y,c); }
static void vline(int x,int y0,int y1,uint32_t c){ int y; for(y=y0;y<=y1;y++) px(x,y,c); }
static void clear(uint32_t c){ int y; for(y=0;y<FB.h;y++) hline(0,FB.w-1,y,c); }

/* ------------------------- 数据源 ------------------------- */
#define NSAMP 1024               /* 每屏显示的采样点数 */
static volatile uint8_t *UIO;    /* UIO mmap 指针(NULL=用 DEMO) */

static int uio_open(const char *dev){
    int fd = open(dev, O_RDWR|O_SYNC);
    if (fd < 0) return -1;
    /* UIO 一般: offset 0=寄存器, 4096=数据缓冲(按你的 PL 映射改) */
    void *p = mmap(0, 8192, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
    if (p==MAP_FAILED){ close(fd); return -1; }
    UIO = (volatile uint8_t*)((uint8_t*)p + 4096);
    printf("[uio] mapped %s\n", dev);
    return fd;
}
static float g_phase=0.0f;
static void get_samples(uint8_t *buf,int n){
    int i;
    if (UIO){ for(i=0;i<n;i++) buf[i]=UIO[i]; }
    else {   /* DEMO: 正弦 + 一点噪声，先把界面跑起来 */
        for(i=0;i<n;i++){ float v = 127.5f + 100.0f*sinf(g_phase + i*0.06f); buf[i]=(uint8_t)v; }
        g_phase += 0.9f;
    }
}

/* ------------------------- 绘制 ------------------------- */
#define COL_BG     0x00101820
#define COL_GRID   0x00304050
#define COL_WAVE   0x00FFE000
#define COL_AXIS   0x0080A0C0

static void draw_grid(void){
    int i;
    for(i=0;i<=10;i++){ int x=i*(FB.w-1)/10; vline(x, 20, FB.h-20, COL_GRID); }
    for(i=0;i<=8;i++){ int y=20+i*(FB.h-40)/8; hline(0, FB.w-1, y, COL_GRID); }
}
static void draw_wave(const uint8_t *s,int n){
    int x, y0, y1, prev=-1, H = FB.h-40;
    for(x=0;x<FB.w;x++){
        int idx = x*n/FB.w;
        int v = s[idx];                       /* 0..255 */
        int y = FB.h-20 - (v*H)/255;          /* 0 在底, 255 在顶 */
        if(prev>=0){ int a=prev<b?prev:y, b=prev<y?y:prev; vline(x, a, b, COL_WAVE); }
        prev=y;
    }
}
static void draw_text(const char *s,int x,int y,uint32_t c){
    /* 极简 8x8 假字: 用方块示意(真实项目可移植一个 8x8 font) */
    int i; for(i=0;s[i];i++){ int k; for(k=0;k<6;k++) px(x+i*8+k, y, c); }
}

int main(int argc,char**argv){
    const char *fbdev = "/dev/fb0";
    uint8_t s[NSAMP]; int i;
    if (argc>1) fbdev=argv[1];
    if (fb_open(fbdev)) return 1;
    int ufd = uio_open("/dev/uio0");      /* 没有就 DEMO 模式 */
    (void)ufd;
    clear(COL_BG);
    for(i=0;i<30;i++){                    /* 跑 30 帧后退出(演示); 真机可 while(1) */
        get_samples(s,NSAMP);
        clear(COL_BG); draw_grid(); draw_wave(s,NSAMP);
        draw_text("SCOPE 1V/div 1ms/div", 10, 4, COL_WAVE);
        usleep(100000);                   /* 10fps */
    }
    munmap(FB.mem, FB.size); close(FB.fd);
    printf("[scope] done\n");
    return 0;
}
