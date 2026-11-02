#!/bin/bash
# =============================================================================
#  板端部署.sh —— 「系统管家小白」Zynq-7020 一键部署脚本
# -----------------------------------------------------------------------------
#  目标板: 正点原子 领航者 Zynq-7020 (xc7z020), Ubuntu 20.04 / Linux 4.19 xlnx
#  用法  : 把本脚本和交接包目录放在同一目录, 然后
#              sudo bash 板端部署.sh
#          可选参数:
#              sudo bash 板端部署.sh --skip-audio     不跑 ES8388 初始化
#              sudo bash 板端部署.sh --no-enable      只装文件, 不 enable 服务
#              sudo bash 板端部署.sh --dry-run        只检查环境, 不写任何文件
#
#  特性  : · 幂等 —— 重复跑不会炸, 已存在的配置会先备份成 .bak_<时间戳>
#          · 每步都有 [n/N] 进度输出, 失败会明确告诉你是哪一步
#          · 不写死任何 IP (需要本机地址时一律用 127.0.0.1)
#          · ★ 不拷贝 / 不生成 / 不删除任何对话记录(见文末说明)
#
#  依赖的包内目录(与脚本同目录):
#      board_ui/  board_agent/  board_root/  board_units/
#      board_etc/ board_bin/    board_lib/   board_boot/
#      详见《板端文件清单.md》§0.1
# =============================================================================

set -u
# 注意: 故意不用 set -e —— 我们想自己控制每一步的失败处理, 并继续往下走完
#       (比如音频初始化失败不该阻止 systemd unit 安装)

# ---------------------------------------------------------------------------
# 全局
# ---------------------------------------------------------------------------
HERE=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%Y%m%d_%H%M%S)

ZYNQ_USER=zynq
ZYNQ_HOME=/home/zynq
UI_DIR=$ZYNQ_HOME/ui
AGENT_DIR=$ZYNQ_HOME/agent
HWCHANGE_DIR=/var/lib/hwchange
FW_DIR=/lib/firmware
BOOT_DIR=/mnt/boot

SKIP_AUDIO=0
NO_ENABLE=0
DRY_RUN=0

STEP_NO=0
STEP_TOTAL=9
WARN_COUNT=0
FAIL_COUNT=0

# 颜色(不支持就自动退化)
if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_HD=$'\033[1;36m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_WARN=""; C_ERR=""; C_HD=""; C_OFF=""
fi

ok()   { echo "    ${C_OK}✔${C_OFF} $*"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); echo "    ${C_WARN}⚠${C_OFF} $*"; }
err()  { FAIL_COUNT=$((FAIL_COUNT + 1));  echo "    ${C_ERR}✘${C_OFF} $*"; }
hd()   { echo ""; echo "${C_HD}$*${C_OFF}"; }

step() {
    STEP_NO=$((STEP_NO + 1))
    echo ""
    echo "${C_HD}=== [$STEP_NO/$STEP_TOTAL] $* ===${C_OFF}"
}

# 记录失败但不中断整个脚本(某些步骤失败是允许的)
try() {
    if "$@"; then
        return 0
    else
        warn "「$*」返回非 0(继续执行)"
        return 1
    fi
}

run() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "      [dry-run] $*"
        return 0
    fi
    "$@"
}

# ---------------------------------------------------------------------------
# ★ 隐私黑名单 —— 纵深防御
#   即使打包的人误把对话/用户数据放进了包, 本函数也会拦住, 绝不部署到新板子。
#   这是硬性要求, 不要为了"方便"删掉。
# ---------------------------------------------------------------------------
is_private() {
    case "$1" in
        *agent_chats*|*agent_sessions*|*agent_spill*|*agent_settings*|\
        *.bash_history*|*novel_marks*|*novel_pos*|*.weather.json|\
        */.ssh/*|*/.config/*|*/.cache/*|*/.minetest/*|\
        */Books/*|*/Music/*|*/Pictures/*|*/Documents/*|\
        */received/*|*/ai_delivery/*|*chats*|*history*|*session*.jsonl)
            return 0 ;;
    esac
    return 1
}

# 系统自带的 shell rc, 不属于本项目, 不要覆盖新板子的
is_sysfile() {
    case "$(basename "$1")" in
        .bashrc|.profile|.bash_logout|.sudo_as_admin_successful) return 0 ;;
    esac
    return 1
}

# 幂等拷贝: 目标已存在且内容相同则跳过
copy_file() {
    local src="$1" dst="$2" mode="${3:-}"
    if [ ! -f "$src" ]; then
        err "包内缺少文件: $src"
        return 1
    fi
    if is_private "$dst"; then
        warn "★ 隐私拦截: 拒绝部署 $dst (该路径属于对话/用户数据黑名单)"
        return 0
    fi
    if is_sysfile "$dst"; then
        warn "跳过系统文件: $dst (不属于本项目)"
        return 0
    fi
    if [ "$DRY_RUN" = "1" ]; then
        echo "      [dry-run] 拷贝 $src -> $dst"
        return 0
    fi
    mkdir -p "$(dirname "$dst")"
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        echo "      · 未变化: $dst"
    else
        cp -f "$src" "$dst" || { err "拷贝失败: $src -> $dst"; return 1; }
        echo "      + 已写入: $dst"
    fi
    [ -n "$mode" ] && chmod "$mode" "$dst"
    return 0
}

# 幂等安装配置文件: 已存在则备份
install_conf() {
    local src="$1" dst="$2" mode="${3:-0644}"
    if [ ! -f "$src" ]; then
        warn "包内没有 $src (跳过, 新板子需要自己准备)"
        return 0
    fi
    if is_private "$dst"; then
        warn "★ 隐私拦截: 拒绝安装 $dst (该路径属于对话/用户数据黑名单)"
        return 0
    fi
    if [ "$DRY_RUN" = "1" ]; then
        echo "      [dry-run] 安装配置 $src -> $dst"
        return 0
    fi
    mkdir -p "$(dirname "$dst")"
    if [ -f "$dst" ]; then
        if cmp -s "$src" "$dst"; then
            echo "      · 已存在且相同, 保留: $dst"
            return 0
        fi
        cp -f "$dst" "${dst}.bak_${STAMP}" \
            && echo "      · 已备份原文件 -> ${dst}.bak_${STAMP}"
    fi
    cp -f "$src" "$dst" || { err "安装失败: $src -> $dst"; return 1; }
    chmod "$mode" "$dst"
    echo "      + 已安装: $dst (权限 $mode)"
    return 0
}

# ===========================================================================
# 解析参数
# ===========================================================================
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-audio) SKIP_AUDIO=1 ;;
        --no-enable)  NO_ENABLE=1 ;;
        --dry-run)    DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "未知参数: $1  (用 --help 看用法)"
            exit 2
            ;;
    esac
    shift
done

echo "============================================================================="
echo " 「系统管家小白」板端部署 —— Zynq-7020 领航者"
echo " 时间      : $(date '+%Y-%m-%d %H:%M:%S')"
echo " 包目录    : $HERE"
echo " 模式      : $([ "$DRY_RUN" = 1 ] && echo '仅检查(dry-run)' || echo '实际部署')"
echo "============================================================================="

# ===========================================================================
step "环境检查 (root / 关键路径 / 包完整性)"
# ===========================================================================
if [ "$(id -u)" != "0" ]; then
    err "必须以 root 运行。请用:  sudo bash $(basename "$0")"
    echo ""
    echo "部署中止。"
    exit 1
fi
ok "当前身份: root"

# 关键系统路径
for d in /etc/systemd/system /usr/local/bin /lib/firmware; do
    if [ -d "$d" ]; then ok "存在: $d"; else err "缺少目录: $d"; fi
done

# 关键命令
for c in python3 systemctl amixer; do
    if command -v "$c" >/dev/null 2>&1; then
        ok "命令可用: $c ($(command -v "$c"))"
    else
        err "缺少命令: $c  —— 音频/systemd 相关步骤会失败"
    fi
done
for c in i2cget i2cset; do
    p="/usr/sbin/$c"
    if [ -x "$p" ]; then ok "命令可用: $p"; else warn "缺少 $p (ES8388 初始化会跳过, 用 apt install i2c-tools)"; fi
done

# 包目录完整性
MISSING_PKG=0
for d in board_ui board_agent board_root; do
    if [ -d "$HERE/$d" ]; then
        n=$(find "$HERE/$d" -type f 2>/dev/null | wc -l)
        ok "包目录 $d/ ($n 个文件)"
    else
        err "包目录缺失: $HERE/$d/"
        MISSING_PKG=1
    fi
done
for d in board_units board_etc board_bin; do
    if [ -d "$HERE/$d" ]; then
        n=$(find "$HERE/$d" -type f 2>/dev/null | wc -l)
        ok "包目录 $d/ ($n 个文件)"
    else
        warn "包目录缺失: $HERE/$d/ (对应步骤会跳过)"
    fi
done
for d in board_lib board_boot; do
    if [ -d "$HERE/$d" ]; then
        n=$(find "$HERE/$d" -type f 2>/dev/null | wc -l)
        ok "包目录 $d/ ($n 个文件)"
    else
        warn "包目录缺失: $HERE/$d/ (需要手工准备, 见清单 §7)"
    fi
done

if [ "$MISSING_PKG" = "1" ]; then
    err "核心包目录不完整, 部署中止。请确认交接包是完整解压的。"
    exit 1
fi

# Zynq 平台判定(不匹配只警告, 因为可能有人拿别的板子试)
if grep -qi "xilinx\|zynq\|armv7" /proc/cpuinfo 2>/dev/null; then
    ok "平台识别: Zynq / ARMv7"
else
    warn "没在 /proc/cpuinfo 里识别出 Zynq —— 如果不是 Zynq-7020, 后续 PL 相关功能肯定不可用"
fi

if [ -d "$ZYNQ_HOME" ]; then
    ok "用户目录存在: $ZYNQ_HOME"
else
    warn "$ZYNQ_HOME 不存在 —— 后续会创建, 但请确认板子上的用户名确实叫 $ZYNQ_USER"
fi

# ===========================================================================
step "创建目录结构"
# ===========================================================================
for d in "$UI_DIR" "$AGENT_DIR" "$AGENT_DIR/kb" "$HWCHANGE_DIR" "$ZYNQ_HOME/received"; do
    if [ -d "$d" ]; then
        ok "已存在: $d"
    else
        if run mkdir -p "$d"; then ok "已创建: $d"; else err "创建失败: $d"; fi
    fi
done

# 服务日志目录(systemd StandardOutput=append: 需要)
if [ -d /var/log ]; then ok "已存在: /var/log"; else err "缺少 /var/log"; fi

# 属主修正
if [ "$DRY_RUN" = "1" ]; then
    echo "      [dry-run] 会执行: chown -R $ZYNQ_USER:$ZYNQ_USER $UI_DIR $AGENT_DIR $ZYNQ_HOME/received"
elif id "$ZYNQ_USER" >/dev/null 2>&1; then
    chown -R "$ZYNQ_USER:$ZYNQ_USER" "$UI_DIR" "$AGENT_DIR" "$ZYNQ_HOME/received" 2>/dev/null \
        && ok "属主已设为 $ZYNQ_USER:$ZYNQ_USER ($UI_DIR / $AGENT_DIR / received)"
    chown -R root:root "$HWCHANGE_DIR" 2>/dev/null && ok "属主已设为 root:root ($HWCHANGE_DIR)"
else
    warn "用户 $ZYNQ_USER 不存在, 跳过 chown (请确认板子用户名)"
fi

# ===========================================================================
step "拷贝程序文件 (board_ui / board_agent / board_root)"
# ===========================================================================
if [ -d "$HERE/board_ui" ]; then
    n=0
    while IFS= read -r f; do
        rel="${f#$HERE/board_ui/}"
        copy_file "$f" "$UI_DIR/$rel" || true
        n=$((n + 1))
    done < <(find "$HERE/board_ui" -type f ! -name '.*' ! -name '*.bak*' 2>/dev/null)
    ok "board_ui/ -> $UI_DIR ($n 个文件)"
else
    err "缺少 board_ui/, 桌面 UI 无法部署"
fi

if [ -d "$HERE/board_agent" ]; then
    n=0
    while IFS= read -r f; do
        rel="${f#$HERE/board_agent/}"
        copy_file "$f" "$AGENT_DIR/$rel" || true
        n=$((n + 1))
    done < <(find "$HERE/board_agent" -type f ! -path '*__pycache__*' ! -name '*.bak*' 2>/dev/null)
    ok "board_agent/ -> $AGENT_DIR ($n 个文件, 含 kb/)"
else
    err "缺少 board_agent/, AI Agent 无法部署"
fi

if [ -d "$HERE/board_root" ]; then
    n=0
    while IFS= read -r f; do
        rel="${f#$HERE/board_root/}"
        # 只放到 /home/zynq 第一层(以及 board_root 内显式带的子目录)
        copy_file "$f" "$ZYNQ_HOME/$rel" || true
        n=$((n + 1))
    done < <(find "$HERE/board_root" -maxdepth 1 -type f ! -name '*.bak*' 2>/dev/null)
    ok "board_root/ -> $ZYNQ_HOME ($n 个文件, 点文件经隐私黑名单过滤)"
else
    err "缺少 board_root/, cloud_api / thermal_guard 等无法部署"
fi

# 可执行位
if [ "$DRY_RUN" != "1" ]; then
    chmod +x "$ZYNQ_HOME"/*.sh 2>/dev/null
    chmod +x "$UI_DIR"/*.sh 2>/dev/null
    ok "已补 .sh 可执行位"
fi

# 三个原生库需要可执行/可读
for so in libscope.so libmcrender.so libgpubatch.so; do
    if [ -f "$UI_DIR/$so" ]; then ok "原生库就位: $UI_DIR/$so"; else warn "缺少原生库 $UI_DIR/$so (示波器/我的世界/GPU 批量填充会失败)"; fi
done

# ===========================================================================
step "安装 /etc 配置文件 (已存在则备份)"
# ===========================================================================
if [ -d "$HERE/board_etc" ]; then
    n=0
    while IFS= read -r f; do
        rel="${f#$HERE/board_etc/}"
        # asound.conf 在下面单独装(它有从 board_root 兜底的逻辑), 这里跳过避免装两遍
        [ "$rel" = "asound.conf" ] && continue
        case "$rel" in
            zynq-baidu.env|zynq-baidu-ocr.env|zynq-agent.env) install_conf "$f" "/etc/$rel" 0600 ;;
            *)                                                install_conf "$f" "/etc/$rel" 0644 ;;
        esac
        n=$((n + 1))
    done < <(find "$HERE/board_etc" -maxdepth 1 -type f 2>/dev/null)
    ok "board_etc/ -> /etc ($n 个文件, asound.conf 单独处理)"
    echo "      ★ 提醒: 上面的密钥文件是【模板/占位】, 接手人必须换成自己的密钥,"
    echo "        否则 AI / 语音 / 文字识别全部调不通。来源见《板端文件清单.md》§6。"
else
    warn "缺少 board_etc/ —— 跳过。新板子需要手工创建:"
    echo "        /etc/zynq-baidu.env       (BAIDU_API_KEY / BAIDU_SECRET_KEY)"
    echo "        /etc/zynq-baidu-ocr.env   (文字识别专用应用, 与语音是两套)"
    echo "        /etc/zynq-agent.env       (AGENT_MODEL / DEEPSEEK_API_KEY)"
    echo "        /etc/xiaobai-cloud.json   (云协同 token / port 8768)"
fi

# asound.conf 是音频能不能打开设备的前提
if [ -f "$HERE/board_etc/asound.conf" ]; then
    install_conf "$HERE/board_etc/asound.conf" /etc/asound.conf 0644
elif [ -f "$ZYNQ_HOME/asound_es8388.conf" ]; then
    install_conf "$ZYNQ_HOME/asound_es8388.conf" /etc/asound.conf 0644
    ok "已用 $ZYNQ_HOME/asound_es8388.conf 生成 /etc/asound.conf"
else
    warn "没有 asound.conf —— 音频服务很可能起不来 (见清单 §6.3)"
fi

# ===========================================================================
step "安装 systemd unit 与 drop-in"
# ===========================================================================
UNITS_INSTALLED=""
if [ -d "$HERE/board_units" ]; then
    n=0
    while IFS= read -r f; do
        rel="${f#$HERE/board_units/}"
        install_conf "$f" "/etc/systemd/system/$rel" 0644
        n=$((n + 1))
    done < <(find "$HERE/board_units" -type f 2>/dev/null)
    ok "board_units/ -> /etc/systemd/system/ ($n 个文件, 含 .d/ drop-in)"
    UNITS_INSTALLED="yes"
else
    warn "缺少 board_units/ —— 跳过。请手工安装《板端文件清单.md》§4.2 里的 13 个 unit"
fi

if [ "$DRY_RUN" != "1" ] && [ -n "$UNITS_INSTALLED" ]; then
    if systemctl daemon-reload; then ok "systemctl daemon-reload 完成"; else err "daemon-reload 失败"; fi
fi

# 服务列表(与清单 §4 一致)
SERVICES="zynq-desktop zynq-agent zynq-audio cloud-api thermal-guard zynq-screen-guard thermal-cooldown zynq-gpu-loader"

if [ "$DRY_RUN" != "1" ] && [ -n "$UNITS_INSTALLED" ] && [ "$NO_ENABLE" = "0" ]; then
    for s in $SERVICES; do
        if [ ! -f "/etc/systemd/system/$s.service" ]; then
            warn "没有 $s.service (跳过 enable)"
            continue
        fi
        if systemctl is-enabled "$s" >/dev/null 2>&1; then
            ok "$s 已经是 enabled"
        else
            if systemctl enable "$s" >/dev/null 2>&1; then ok "$s 已 enable"; else warn "$s enable 失败"; fi
        fi
    done
elif [ "$NO_ENABLE" = "1" ]; then
    warn "--no-enable 指定, 跳过 enable"
fi

# ===========================================================================
step "部署落地文件 (firmware / boot / bin)"
# ===========================================================================
# 6a. /usr/local/bin
if [ -d "$HERE/board_bin" ]; then
    while IFS= read -r f; do
        rel="${f#$HERE/board_bin/}"
        copy_file "$f" "/usr/local/bin/$rel" 0755 || true
    done < <(find "$HERE/board_bin" -type f 2>/dev/null)
    ok "board_bin/ -> /usr/local/bin/"
else
    warn "缺少 board_bin/ —— zynq-gpu-loader 会因找不到 /usr/local/bin/gpu-load.sh 而失败"
fi

# 6b. /lib/firmware (PL bitstream 的字节交换 .bin)
if [ -d "$HERE/board_lib" ]; then
    while IFS= read -r f; do
        rel="${f#$HERE/board_lib/}"
        copy_file "$f" "$FW_DIR/$rel" 0644 || true
    done < <(find "$HERE/board_lib" -type f 2>/dev/null)
    ok "board_lib/ -> $FW_DIR/"
else
    warn "缺少 board_lib/ —— $FW_DIR/gpu.bin 需要手工准备"
    echo "        做法: python3 $ZYNQ_HOME/bit2bin.py <system.bit> $FW_DIR/gpu.bin"
fi

if [ -f "$FW_DIR/gpu.bin" ]; then
    ok "已就位: $FW_DIR/gpu.bin ($(stat -c %s "$FW_DIR/gpu.bin" 2>/dev/null) 字节)"
else
    warn "没有 $FW_DIR/gpu.bin —— 桌面会回退软件渲染(不崩, 但 GPU 演示不可用)"
fi

# 6c. /mnt/boot —— 这是启动分区, 默认【只报告不动手】, 避免把新板子搞到起不来
if [ -d "$HERE/board_boot" ] && [ -d "$BOOT_DIR" ]; then
    if mountpoint -q "$BOOT_DIR" 2>/dev/null; then
        ok "$BOOT_DIR 已挂载 (启动分区)"
        echo "      ★ 出于安全考虑, 本脚本【不自动覆盖】BOOT.BIN / zImage / system.dtb / system.bit。"
        echo "        这些东西刷错新板子会直接起不来。请接手人【手工】比对后拷贝:"
        echo "          源(包内)            ->  目标(板子)"
        for f in BOOT.BIN boot.scr zImage image.ub system.bit system.dtb board_config.gz use_ours.flag; do
            if [ -f "$HERE/board_boot/$f" ]; then
                printf "          %-20s ->  %s/%s\n" "$f" "$BOOT_DIR" "$f"
            fi
        done
        echo "        比 md5 的命令:  md5sum $HERE/board_boot/system.dtb $BOOT_DIR/system.dtb"
    else
        warn "$BOOT_DIR 没有挂载 —— 跳过"
        echo "        新板子要刷 bitstream 的话:  mount /dev/mmcblk0p1 /mnt/boot"
    fi
elif [ ! -d "$BOOT_DIR" ]; then
    warn "板子上没有 $BOOT_DIR 目录 —— 请确认启动分区路径"
else
    warn "缺少 board_boot/ —— 启动相关文件需要接手人自行准备(见清单 §7.1)"
fi

# ===========================================================================
step "初始化 ES8388 音频采集通路"
# ===========================================================================
if [ "$SKIP_AUDIO" = "1" ]; then
    warn "--skip-audio 指定, 跳过"
elif [ ! -f "$ZYNQ_HOME/audio_cap_init.py" ]; then
    err "找不到 $ZYNQ_HOME/audio_cap_init.py —— 麦克风会是近乎静音状态(见清单 §7.3)"
elif [ "$DRY_RUN" = "1" ]; then
    echo "      [dry-run] python3 $ZYNQ_HOME/audio_cap_init.py"
else
    echo "      · 作用: 把 ES8388 寄存器 0x0A 强制写成 0x00 (麦克风接 LIN1/RIN1)"
    echo "        内核驱动默认写 0x50 (LINE_IN 插孔), 会导致采集 -93 dBFS 近乎静音。"
    if python3 "$ZYNQ_HOME/audio_cap_init.py"; then
        ok "audio_cap_init.py 执行成功"
    else
        warn "audio_cap_init.py 返回非 0 —— 检查 I2C-1 上 0x10 是否在线 (i2cdetect -y 1)"
    fi

    # 顺带把增益拉到最大(与 volume-max.conf drop-in 一致, 幂等)
    if command -v amixer >/dev/null 2>&1; then
        try amixer -q -c 0 sset "Playback" 192  >/dev/null 2>&1
        try amixer -q -c 0 sset "Output 1" 33   >/dev/null 2>&1
        try amixer -q -c 0 sset "Output 2" 33   >/dev/null 2>&1
        ok "amixer 增益已拉到配置上限 (Playback 192 / Output 33)"
    fi
fi

# 音频依赖自检
if command -v aplay >/dev/null 2>&1; then
    if aplay -l 2>/dev/null | grep -qi "xlnxi2ssndcard"; then
        ok "声卡已识别: $(aplay -l 2>/dev/null | grep -i 'xlnxi2ssndcard' | head -1)"
    else
        warn "aplay -l 看不到 xlnxi2ssndcard —— dtb 里 es8388 节点可能没生效(见清单 §7.1)"
    fi
fi
if lsmod 2>/dev/null | grep -q "snd_soc_es8388"; then
    ok "驱动已加载: snd_soc_es8388"
else
    warn "snd_soc_es8388 未加载 —— 检查 /mnt/boot/system.dtb"
fi

# 离线语音模型
if [ -d "$ZYNQ_HOME/vosk-model-small-cn-0.22" ]; then
    ok "vosk 离线语音模型已就位 (68 MB)"
else
    warn "缺少 $ZYNQ_HOME/vosk-model-small-cn-0.22 —— agent 离线语音识别会退化到在线 ASR"
    echo "        下载后放到该路径即可"
fi

# ===========================================================================
step "重启服务并检查状态"
# ===========================================================================
echo "      ★ 部署脚本【不碰】任何对话记录文件(见脚本末尾说明)。"
echo ""

if [ "$DRY_RUN" = "1" ]; then
    echo "      [dry-run] 以下服务会被 restart:"
    for s in $SERVICES; do echo "        - $s"; done
else
    for s in $SERVICES; do
        if [ ! -f "/etc/systemd/system/$s.service" ]; then
            warn "$s.service 不存在, 跳过"
            continue
        fi
        if systemctl restart "$s" 2>/dev/null; then
            echo "      · $s 已 restart"
        else
            warn "$s restart 返回非 0"
        fi
    done
    echo ""
    echo "      · 等 6 秒让服务把端口/设备拿到手 ..."
    sleep 6
fi

echo ""
printf "      %-24s %-10s %s\n" "服务" "状态" "备注"
printf "      %-24s %-10s %s\n" "------------------------" "----------" "--------------------------------"
for s in $SERVICES; do
    if [ "$DRY_RUN" = "1" ]; then
        printf "      %-24s %-10s %s\n" "$s" "(dry)" "-"
        continue
    fi
    st=$(systemctl is-active "$s" 2>/dev/null)
    note=""
    case "$s:$st" in
        zynq-desktop:active)     note="桌面 UI" ;;
        zynq-agent:active)       note="AI Agent" ;;
        zynq-audio:active)       note="ES8388 音频" ;;
        cloud-api:active)        note="云协同 :8768" ;;
        thermal-guard:active)    note="温度守护" ;;
        zynq-screen-guard:active) note="黑屏看门狗" ;;
        thermal-cooldown:active) note="开机冷却(oneshot, active=已跑完)" ;;
        *:active)                note="" ;;
        *:inactive)              note="★ 没起来 —— journalctl -u $s -n 50" ;;
        *:failed)                note="★ 启动失败 —— journalctl -u $s -n 50" ;;
        *)                       note="" ;;
    esac
    if [ "$st" = "active" ]; then
        printf "      %-24s ${C_OK}%-10s${C_OFF} %s\n" "$s" "$st" "$note"
    else
        printf "      %-24s ${C_WARN}%-10s${C_OFF} %s\n" "$s" "$st" "$note"
        WARN_COUNT=$((WARN_COUNT + 1))
    fi
done

# 端口自检(不写死板子 IP, 一律用 127.0.0.1)
echo ""
if [ "$DRY_RUN" = "1" ]; then
    echo "      · 端口自检: [dry-run] 跳过 (会检查 127.0.0.1 的 8765 / 8767 / 8768)"
else
    echo "      · 端口自检 (127.0.0.1):"
    for port in 8765 8767 8768; do
        if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ":$port "; then
            ok "端口 $port 正在监听"
        else
            warn "端口 $port 没有监听"
        fi
    done
fi

# ===========================================================================
step "部署摘要"
# ===========================================================================
echo "      包目录      : $HERE"
echo "      备份后缀    : .bak_$STAMP"
echo "      警告数      : $WARN_COUNT"
echo "      失败数      : $FAIL_COUNT"
echo ""
if [ "$FAIL_COUNT" -eq 0 ] && [ "$WARN_COUNT" -eq 0 ]; then
    echo "  ${C_OK}全部步骤通过。${C_OFF}"
elif [ "$FAIL_COUNT" -eq 0 ]; then
    echo "  ${C_WARN}完成, 但有 $WARN_COUNT 处警告 —— 逐条看上面的 ⚠。${C_OFF}"
else
    echo "  ${C_ERR}有 $FAIL_COUNT 处失败 —— 逐条看上面的 ✘。${C_OFF}"
fi

echo ""
echo "  下一步(手工):"
echo "    1. 填自己的密钥:  /etc/zynq-baidu.env  /etc/zynq-baidu-ocr.env"
echo "                      /etc/zynq-agent.env  /etc/xiaobai-cloud.json"
echo "    2. 启动画面自检:  sudo systemctl restart zynq-desktop && sleep 8"
echo "                      tail -30 /var/log/zynq-desktop.log"
echo "    3. 看板子 IP:     ip -4 addr show | grep inet"
echo "    4. 云协同自测:    python3 $ZYNQ_HOME/test_cloud_api_http.py"
echo "    5. 麦克风自测:    python3 $ZYNQ_HOME/audio_verify.py"
echo ""
echo "  出问题看这里:  《板端文件清单.md》§4.3 服务依赖图 / §7 硬件一次性配置"
echo ""
echo "-----------------------------------------------------------------------------"
echo "  ★ 关于用户对话数据(重要)"
echo "  本脚本【不做】以下任何一件事:"
echo "    · 不拷贝 /home/zynq/.agent_chats.json 及 .lock"
echo "    · 不拷贝 /home/zynq/agent_sessions/ 与 agent_spill/ 里的会话记录"
echo "    · 不拷贝 /var/log/zynq-agent.log (该日志会把用户提问和回答整段打出来)"
echo "    · 不生成、不覆盖、不删除任何对话数据"
echo "  新板子上如果已经存在旧对话文件, 本脚本【保持原样不动】。"
echo "  如确认不需要旧对话, 接手人可自行放开下面这行(默认注释掉):"
echo ""
echo "    # rm -f /home/zynq/.agent_chats.json /home/zynq/.agent_chats.json.lock"
echo "    # rm -rf /home/zynq/agent_sessions/* /home/zynq/agent_spill/*"
echo "    # : > /var/log/zynq-agent.log"
echo "-----------------------------------------------------------------------------"
exit "$FAIL_COUNT"
