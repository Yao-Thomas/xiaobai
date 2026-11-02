#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_wifi.py —— WiFi 网络选择器 (像电脑一样选网络、输密码、连接)

功能:
  - 扫描周围 WiFi, 显示 SSID / 信号强度条 / 是否加密
  - 点一下就连接; 加密的弹软键盘输密码
  - 显示当前连接状态, 可一键断开
  - 记住连接过的网络 (wpa_cli save_config)
"""
import os, re, time, subprocess

#=========================================================
#  底层: 找无线网卡 / 执行 wpa_cli
#=========================================================
def wlan_name():
    try:
        for n in sorted(os.listdir("/sys/class/net")):
            if n.startswith("wl"):
                return n
    except Exception:
        pass
    return "wlan0"


WLAN = None


def iface():
    global WLAN
    if WLAN is None:
        WLAN = wlan_name()
    return WLAN


def sh(cmd, t=15):
    """执行命令, 返回 (ok, 输出)"""
    try:
        out = subprocess.check_output(cmd, shell=True,
                                      stderr=subprocess.STDOUT,
                                      timeout=t).decode(errors="replace")
        return True, out
    except subprocess.CalledProcessError as e:
        return False, (e.output or b"").decode(errors="replace")
    except Exception as e:
        return False, str(e)


def have(tool):
    return subprocess.call("command -v %s >/dev/null 2>&1" % tool, shell=True) == 0


def wpa(args, t=15):
    """调用 wpa_cli, 自动尝试 sudo -n"""
    i = iface()
    base = "wpa_cli -i %s %s" % (i, args)
    ok, out = sh(base, t)
    if not ok and "Failed to connect" in out:
        ok, out = sh("sudo -n " + base, t)
    return ok, out


def is_root():
    return os.geteuid() == 0


def wpa_state():
    """读 wpa_cli status -> dict (wpa_state / ssid / ip_address ...)"""
    st = {}
    ok, out = wpa("status", 5)
    if not ok:
        return st
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            st[k.strip()] = v.strip()
    return st


def flush_ip():
    """丢掉网卡上现有的 IPv4 地址

    ★ 切换 AP 时必须做这一步: 旧网络(比如手机热点 192.168.43.x)分到的 IP
    在新网络(192.168.10.x)里是无效的, 不清掉的话 has_ip() 会一直返回
    那个旧 IP, 程序以为"连上了", 实际根本不可达 —— 板子就这么"掉线"的。
    """
    i = iface()
    sh("ip -4 addr flush dev %s" % i, 8)


def set_power_save(off=True):
    """关掉/打开 WiFi 省电模式

    ★ 2026-10-01 新增：省电模式开着时，网卡空闲就休眠，AP 会认为它掉线
      （journal 里 "Lost carrier"），表现为网络时有时无、IP 一会儿有一会儿没。
      实测开机 13 分钟内掉了 40 次。这是嵌入式 USB WiFi 的经典毛病。
    """
    i = iface()
    if have("iw"):
        sh("sudo -n iw dev %s set power_save %s" % (i, "off" if off else "on"), 8)


def run_dhcp():
    """主动续一次 DHCP

    切换 AP 之后不一定有人帮我们重新跑 DHCP, 干等是等不到 IP 的 ——
    这是"连上了却没有 IP / 留着旧 IP"的根因。

    ★ 2026-10-01 修复（重要）:
      板子上根本没装 udhcpc / dhclient / dhcpcd —— 三个都是
      "command not found"。原来的实现三个都 have()==False，直接
      return ""，**什么也没做**。这就是"换了网络就拿不到 IP、
      界面只显示 '-'"的直接原因（只有 systemd-networkd 自己
      碰巧续上租约时才正常）。

      而 systemd-networkd 是活的，它自带 DHCP 客户端 ——
      用 networkctl reconfigure 就能立刻让它重新要一次 IP。
      所以把它放在第一位；传统客户端作为退路保留（哪天装了自动生效）。
    """
    i = iface()

    # ① 首选：systemd-networkd（板上唯一实际存在的 DHCP 实现）
    if have("networkctl"):
        sh("networkctl reconfigure %s" % i, 20)
        for _ in range(12):          # 等它真拿到 IP，最多约 12 秒
            if has_ip():
                return "systemd-networkd"
            time.sleep(1)

    # ② 退路：传统 DHCP 客户端
    for cmd in ("udhcpc -i %s -n -q -t 5" % i,
                "dhclient -1 %s" % i,
                "dhcpcd -1 %s" % i):
        tool = cmd.split()[0]
        if have(tool):
            sh(cmd, 30)
            return tool
    return ""


# wpa_supplicant 配置文件可能的位置(板子上是第一个)
CONF_PATHS = [
    "/etc/wpa_supplicant/wpa_supplicant.conf",
    "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf",
    "/etc/wpa_supplicant.conf",
]


def conf_has(ssid):
    """直接读配置文件确认这个网络真的写盘了

    只查 wpa_cli 的内存列表是不够的: 内存里有、盘上没有, 一重启就没了。
    """
    for p in CONF_PATHS:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                if ssid in f.read():
                    return p
        except Exception:
            pass
    return None


#=========================================================
#  扫描
#=========================================================
def parse_flags(flags):
    """判断加密类型"""
    f = flags.upper()
    if "EAP" in f:
        return "企业"          # 需要账号密码, 本选择器不支持
    if "WPA3" in f:
        return "WPA3"
    if "WPA2" in f:
        return "WPA2"
    if "WPA" in f:
        return "WPA"
    if "WEP" in f:
        return "WEP"
    if "ESS" in f:
        return "开放"
    return "?"


def scan_wpa():
    """用 wpa_cli 扫描, 返回 [(ssid, signal_dbm, sec, bssid), ...]"""
    wpa("scan")
    # 等扫描完成 (最多 6 秒)
    for _ in range(12):
        time.sleep(0.5)
        ok, out = wpa("scan_results", 5)
        if ok and out.count("\n") > 1:
            break
    ok, out = wpa("scan_results", 5)
    if not ok or not out:
        return None
    res = []
    for line in out.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 5:
            p = line.split()
            if len(p) < 5:
                continue
        bssid, freq, sig, flags, ssid = p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else ""
        ssid = ssid.strip()
        if not ssid:
            continue
        try:
            sig = int(sig)
        except Exception:
            sig = -100
        res.append((ssid, sig, parse_flags(flags), bssid))
    return res


def scan_iwlist():
    """用 iwlist 扫描 (备用)"""
    i = iface()
    ok, out = sh("iwlist %s scan" % i, 20)
    if not ok:
        ok, out = sh("sudo -n iwlist %s scan" % i, 20)
    if not ok:
        return None
    res = []
    cur = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Cell "):
            if cur.get("ssid"):
                res.append((cur["ssid"], cur.get("sig", -100), cur.get("sec", "?"),
                            cur.get("bssid", "")))
            cur = {}
            m = re.search(r"Address:\s*(\S+)", line)
            if m:
                cur["bssid"] = m.group(1)
        elif "ESSID:" in line:
            s = line.split("ESSID:", 1)[1].strip()
            if s.startswith('"'):
                cur["ssid"] = s[1:].split('"', 1)[0]
        elif "Signal level=" in line:
            m = re.search(r"Signal level=(-?\d+)", line)
            if m:
                cur["sig"] = int(m.group(1))
        elif "Encryption key:on" in line:
            cur["sec"] = "加密"
        elif "Encryption key:off" in line:
            cur["sec"] = "开放"
    if cur.get("ssid"):
        res.append((cur["ssid"], cur.get("sig", -100), cur.get("sec", "?"),
                    cur.get("bssid", "")))
    return res or None


def scan_nmcli():
    ok, out = sh("nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list", 20)
    if not ok:
        return None
    res = []
    for line in out.splitlines():
        p = line.split(":")
        if len(p) >= 3 and p[0].strip():
            try:
                sig = int(p[1])
            except Exception:
                sig = 0
            res.append((p[0].strip(), -100 + sig // 2, p[2].strip() or "开放", ""))
    return res or None


def dedup(nets):
    """同一 SSID 只留信号最强的那条, 并按信号从强到弱排序"""
    best = {}
    for ssid, sig, sec, bssid in nets:
        k = ssid
        if k not in best or sig > best[k][1]:
            best[k] = (ssid, sig, sec, bssid)
    return sorted(best.values(), key=lambda t: -t[1])


def scan_all():
    for fn in (scan_wpa, scan_iwlist, scan_nmcli):
        try:
            r = fn()
            if r:
                return dedup(r)
        except Exception:
            pass
    return []


#=========================================================
#  当前连接状态
#=========================================================
def current_ssid():
    i = iface()
    ok, out = sh("iwconfig %s" % i, 5)
    for line in out.splitlines():
        if "ESSID:" in line:
            r = line.split("ESSID:", 1)[1].strip()
            if r.startswith('"'):
                return r[1:].split('"', 1)[0]
            return r.split()[0] if r.split() else ""
    return ""


def current_signal():
    i = iface()
    ok, out = sh("iwconfig %s" % i, 5)
    for line in out.splitlines():
        if "Signal level=" in line:
            m = re.search(r"Signal level=(-?\d+)", line)
            if m:
                return int(m.group(1))
    return None


def has_ip():
    i = iface()
    ok, out = sh("ip -4 addr show %s" % i, 5)
    for tok in out.replace("/", " ").split():
        if tok.count(".") == 3 and not tok.startswith("255"):
            return tok
    return ""


#=========================================================
#  连接
#=========================================================
def connect(ssid, psk=None):
    """连接指定网络, 返回 (ok, 提示文字)

    重要: 只有【连成功】才 save_config 保存下来。
          失败就把刚加的那条配置删掉, 免得列表里留下一堆连不上的"已保存"。
    """
    i = iface()
    if not is_root() and not have("wpa_cli"):
        return False, "缺少 wpa_cli"

    old_ssid = current_ssid()      # 记下现在连的是谁, 判断要不要重做 DHCP

    ok, out = wpa("add_network", 8)
    if not ok or not out.strip():
        return False, "wpa_cli 不可用: " + out.strip()[:40]
    nid = out.strip().splitlines()[-1].strip()
    if not nid.isdigit():
        return False, "拿不到 network id"

    def cleanup():
        """失败时把临时加的配置删掉 (没 save 过, 删内存里的就够了)"""
        wpa("disable_network %s" % nid, 8)
        wpa("remove_network %s" % nid, 8)

    def drop_old():
        """删掉其他所有同名旧条目, 避免列表里堆一堆重复的"""
        for snid, sname, _fl in list_networks_all():
            if sname == ssid and str(snid) != nid:
                wpa("remove_network %d" % snid, 8)

    wpa('set_network %s ssid \'"%s"\'' % (nid, ssid), 8)
    if psk:
        wpa('set_network %s psk \'"%s"\'' % (nid, psk), 8)
    else:
        wpa("set_network %s key_mgmt NONE" % nid, 8)
    # 给个中等优先级, 这样多网可用时它也会被考虑
    wpa("set_network %s priority 2" % nid, 8)

    wpa("enable_network %s" % nid, 8)
    wpa("select_network %s" % nid, 8)

    # 等关联 + DHCP (最多 30 秒)
    got_ip = ""
    bad_key = 0
    for step in range(30):
        time.sleep(1)
        st = wpa_state()
        ws = st.get("wpa_state", "")
        if ws == "4WAY_HANDSHAKE":
            bad_key += 1
            if bad_key >= 3:
                break                      # 反复握手失败 = 密码不对
        if ws == "COMPLETED" and (st.get("ssid") or current_ssid()) == ssid:
            # ★ 换了网络 -> 旧 IP 是上一个网段的, 必须丢掉重新 DHCP
            if old_ssid != ssid:
                flush_ip()
                old_ssid = ssid
            got_ip = has_ip()
            if not got_ip:
                run_dhcp()                 # ★ 主动续租, 别干等
                got_ip = has_ip()
            if got_ip:
                break
        if ws in ("INACTIVE", "DISCONNECTED") and step > 18:
            break

    if current_ssid() == ssid and (got_ip or has_ip()):
        got_ip = got_ip or has_ip()
        drop_old()
        enable_all()                       # ★ 别把其他网络留在禁用状态
        wpa("save_config", 8)              # ★ 只有成功才保存
        time.sleep(0.3)
        persisted = conf_has(ssid)         # ★ 回读配置文件确认真写盘
        note = "" if persisted else " (注意: 好像没写进配置文件)"
        return True, "已连接, IP " + got_ip + note

    # 失败: 清掉刚加的
    cleanup()
    if psk is not None:
        return False, "连接失败(密码可能不对), 未保存"
    return False, "连接失败, 未保存"


def disconnect():
    wpa("disconnect", 8)
    wpa("save_config", 8)
    return True, "已断开"


#=========================================================
#  已保存的网络 (连过的就不用再输密码)
#=========================================================
def list_networks_all():
    """读 wpa_cli list_networks -> [(network_id, ssid, flags), ...]

    wpa_cli 输出格式:
        network id / ssid / bssid / flags
        0   001    any    [CURRENT]
        1   Home   any    [DISABLED]
    (最前面可能还有一行 "Selected interface 'wlan0'")

    这里逐行过滤而不是简单地 [1:], 免得某一行格式不同就整体错位。
    """
    rows = []
    ok, out = wpa("list_networks", 8)
    if not ok or not out:
        return rows
    for line in out.splitlines():
        line = line.rstrip()
        if not line or line.startswith("network id") or line.startswith("Selected"):
            continue
        p = line.split("\t")
        if len(p) < 2:
            p = line.split()
        if len(p) < 2:
            continue
        nid, ssid = p[0].strip(), p[1].strip()
        flags = p[3].strip() if len(p) > 3 else ""
        if nid.isdigit() and ssid:
            rows.append((int(nid), ssid, flags))
    return rows


def list_networks():
    """已保存的网络 -> {ssid: network_id}

    同一个 SSID 有多条时, 优先选"没被禁用 + id 最大(最新)"的那条。
    否则可能挑到一条早就失效的旧条目, 一连就失败, 反过来把保存删掉。
    """
    saved = {}
    best = {}
    for nid, ssid, flags in list_networks_all():
        score = (0 if "DISABLED" in flags.upper() else 1, nid)
        if ssid not in best or score > best[ssid]:
            best[ssid] = score
            saved[ssid] = nid
    return saved


def connect_saved(ssid, nid, wait=40):
    """连接一个已保存的网络 (密码已在配置里, 不用重新输入)

    ★★ 关键修复: 【超时绝不删保存】★★

    之前这里是"连不上就 remove_network + save_config", 结果:
      * 切换 AP 要重新关联 + 重新 DHCP, 经常超过 20 秒 -> 超时 -> 把
        用户保存得好好的密码自己删掉了
      * wpa_supplicant 刚 select_network 时会短暂报 DISCONNECTED,
        旧代码据此提前退出 -> 又一次删掉保存
    用户看到的现象就是"根本没保存, 每次都要重输密码"。

    现在只有 wpa_supplicant 明确【反复握手失败】(密码真的不对)
    才删掉这条配置让用户重输; 超时一律保留。
    """
    old_ssid = current_ssid()

    wpa("enable_network %d" % nid, 8)
    wpa("select_network %d" % nid, 8)

    bad_key = 0
    dhcp_done = False
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(1.5)
        st = wpa_state()
        ws = st.get("wpa_state", "")

        if ws == "4WAY_HANDSHAKE":
            bad_key += 1
            # 反复握手失败 且 已经试了够久 -> 密码确实不对
            if bad_key >= 3 and time.time() - t0 > 12:
                wpa("remove_network %d" % nid, 8)
                wpa("save_config", 8)
                return False, "保存的密码已失效(已忘记), 请重新输入"
        elif ws == "COMPLETED" and (st.get("ssid") or current_ssid()) == ssid:
            # ★ 换了网络 -> 旧 IP 是上一个网段的, 必须丢掉重新 DHCP
            if old_ssid != ssid:
                flush_ip()
                old_ssid = ssid
                dhcp_done = False
            ip = has_ip()
            if not ip and not dhcp_done:
                run_dhcp()                 # ★ 主动续租, 别干等
                dhcp_done = True
                ip = has_ip()
            if ip:
                return True, "已连接, IP " + ip
            if dhcp_done:
                # 关联成功但 DHCP 还没回来 —— 不算失败, 更不能删保存
                return True, "已关联 %s, 正在获取 IP" % ssid

    # 超时: 【保留保存】, 只报告
    return False, "连接超时(保存的密码还在, 可以再点一次)"


def forget_network(ssid):
    """忘记一个已保存的网络"""
    saved = list_networks()
    nid = saved.get(ssid)
    if nid is None:
        return False, "没有保存过这个网络"
    wpa("remove_network %d" % nid, 8)
    wpa("save_config", 8)
    return True, "已忘记 " + ssid


def enable_all():
    """把所有被禁用的已保存网络重新启用

    ★★★ 这是板子"失联"的根因, 必须堵死 ★★★

    `select_network` 会【禁用其他所有网络】。如果紧接着 save_config,
    那些 disabled=1 就被永久写进 /etc/wpa_supplicant/wpa_supplicant.conf。
    用户来回切几次网络之后, 所有网络全变成 disabled=1, 板子再也连不上
    任何 WiFi —— 表面上"WiFi 是开的", 实际一个 AP 都不连, 直接失联。
    (这个坑已经真实踩过, 只能用串口登进去手工修配置才救回来。)

    所以每次保存配置之前, 都要把其他网络重新启用。
    """
    n = 0
    for nid, _ssid, flags in list_networks_all():
        if "DISABLED" in flags.upper():
            wpa("enable_network %d" % nid, 8)
            n += 1
    return n


def heal_disabled():
    """自愈: 如果所有已保存的网络都被禁用了, 全部重新启用

    万一配置文件已经处于"全禁用"的坏状态, 进 WiFi 应用就自动救回来。
    """
    rows = list_networks_all()
    if not rows:
        return 0
    if all("DISABLED" in f.upper() for _, _, f in rows):
        n = 0
        for nid, _ssid, _f in rows:
            wpa("enable_network %d" % nid, 8)
            n += 1
        wpa("save_config", 8)
        return n
    return 0


#=========================================================
#  UI
#=========================================================
def bars(dbm):
    """信号强度 -> 格数 (1..5)"""
    if dbm is None:
        return 0
    if dbm >= -50:
        return 5
    if dbm >= -60:
        return 4
    if dbm >= -70:
        return 3
    if dbm >= -80:
        return 2
    return 1


def draw_signal(scr, x, y, n, color=(120, 220, 150), bg=(70, 90, 110)):
    """画信号强度条 (5 格)"""
    for k in range(5):
        h = 6 + k * 5
        c = color if k < n else bg
        scr.rect([x + k * 9, y - h, x + k * 9 + 6, y], fill=c)


def draw_list(scr, nets, cur_ssid, msg, scanning, saved=None, forget_confirm=""):
    saved = saved or {}
    scr.clear((12, 20, 30))
    # 顶栏
    scr.rect([0, 0, scr.w, 60], fill=(22, 40, 52))
    scr.rect([0, 58, scr.w, 62], fill=(60, 160, 190))
    scr.rrect([10, 8, 130, 52], 10, fill=(46, 70, 88))
    scr.text((70, 30), "< 返回", 22, (255, 255, 255), cn=True, anchor="mm")
    scr.text((150, 30), "WiFi 网络", 26, (220, 245, 255), cn=True, anchor="lm")

    # 当前状态 + 按钮
    y = 72
    scr.rrect([20, y, scr.w - 20, y + 56], 10,
              fill=(24, 62, 46) if cur_ssid else (54, 40, 30))
    if cur_ssid:
        sig = current_signal()
        ip = has_ip()
        txt = "已连接: %s" % cur_ssid
        if ip:
            txt += "   " + ip
        scr.text((40, y + 28), txt, 21, (150, 245, 190), cn=True, anchor="lm")
        draw_signal(scr, scr.w - 130, y + 40, bars(sig))
    else:
        scr.text((40, y + 28), "未连接 — 点下面的网络连接", 21,
                 (245, 200, 140), cn=True, anchor="lm")

    # 按钮行
    y += 64
    scr.rrect([20, y, 230, y + 52], 10, fill=(40, 120, 190))
    scr.text((125, y + 26), "重新扫描" if not scanning else "扫描中...", 22,
             (255, 255, 255), cn=True, anchor="mm")
    scr.rrect([246, y, 456, y + 52], 10, fill=(150, 60, 60))
    scr.text((351, y + 26), "断开连接", 22, (255, 255, 255), cn=True, anchor="mm")
    if msg:
        scr.text((480, y + 26), msg[:34], 19, (200, 230, 255), cn=True, anchor="lm")

    # 列表
    y += 62
    row_h = 56
    maxrows = (scr.h - y - 30) // row_h
    if not nets:
        tip = "正在扫描..." if scanning else "没扫到网络, 点上面「重新扫描」"
        scr.text((scr.w // 2, y + 60), tip, 22, (150, 180, 200), cn=True, anchor="mm")
    for i, (ssid, sig, sec, bssid) in enumerate(nets[:maxrows]):
        ry = y + i * row_h
        is_cur = (ssid == cur_ssid)
        is_saved = ssid in saved
        scr.rrect([20, ry, scr.w - 20, ry + row_h - 6], 10,
                  fill=(30, 58, 78) if is_cur else (22, 36, 50))
        draw_signal(scr, 40, ry + 36, bars(sig))
        name = ssid if len(ssid) <= 22 else ssid[:21] + "…"
        scr.text((140, ry + 24), name, 22,
                 (170, 250, 200) if is_cur else (235, 245, 255), cn=True, anchor="lm")

        # 右侧: 加密方式 + 信号
        scr.text((scr.w - 40, ry + 20), "%s  %ddBm" % (sec, sig), 19,
                 (160, 190, 210), anchor="rm")

        # 左下角标记: 已保存 / 已连接 (用画点代替特殊符号, 避免字体缺字)
        if is_cur:
            scr.rect([140, ry + 38, 148, ry + 46], fill=(120, 240, 160))
            scr.text((154, ry + 42), "已连接", 16, (120, 240, 160),
                     cn=True, anchor="lm")
        elif is_saved:
            scr.rect([140, ry + 38, 148, ry + 46], fill=(150, 230, 150))
            scr.text((154, ry + 42), "已保存 — 点一下免密码连接", 16,
                     (150, 230, 150), cn=True, anchor="lm")

        # 已保存的显示「忘记」按钮 (大一点, 好点)
        #
        # ★ 2026-10-01 修复：原来的条件是 `if is_saved and not is_cur`，
        #   把"当前正连着的那条"排除掉了 —— 用户想删掉当前网络时，
        #   界面上完全找不到入口。而其他已保存的网络又常常不在扫描
        #   范围内（比如换了地方），于是整个界面一个「忘记」都看不到。
        #   现在：所有已保存的都显示按钮；删当前那条会先自动断开。
        #   两次点击确认，避免误删（和音乐 App 的删除按钮一致）。
        if is_saved:
            bg = (220, 70, 70) if forget_confirm == ssid else (120, 56, 56)
            scr.rrect([scr.w - 130, ry + 26, scr.w - 26, ry + 52], 9, fill=bg)
            scr.text((scr.w - 78, ry + 39),
                     "确认?" if forget_confirm == ssid else "忘记",
                     18, (255, 215, 215), cn=True, anchor="mm")
    return y


def draw_psk(scr, ssid, psk, msg):
    scr.clear((12, 20, 30))
    scr.rect([0, 0, scr.w, 60], fill=(22, 40, 52))
    scr.rect([0, 58, scr.w, 62], fill=(60, 160, 190))
    scr.rrect([10, 8, 130, 52], 10, fill=(46, 70, 88))
    scr.text((70, 30), "< 返回", 22, (255, 255, 255), cn=True, anchor="mm")
    scr.text((150, 30), "输入密码", 26, (220, 245, 255), cn=True, anchor="lm")

    scr.text((30, 88), "网络:", 21, (160, 200, 230), cn=True, anchor="lm")
    scr.text((96, 88), ssid[:30], 21, (255, 255, 255), anchor="lm")

    # 密码框
    scr.rrect([30, 108, scr.w - 30, 158], 10, fill=(18, 30, 44))
    shown = psk if psk else "点下面键盘输入密码"
    col = (255, 255, 255) if psk else (110, 130, 150)
    scr.text((48, 133), shown[:44], 24, col, anchor="lm", mono=True)
    if psk:
        cx = 48 + min(len(psk), 44) * 13
        scr.rect([cx, 114, cx + 2, 152], fill=(120, 220, 160))

    # ★★★ 醒目的操作按钮 ★★★
    scr.rrect([30, 168, 300, 226], 12, fill=(150, 60, 60))
    scr.text((165, 197), "取消", 26, (255, 255, 255), cn=True, anchor="mm")

    scr.rrect([316, 168, scr.w - 30, 226], 12, fill=(40, 150, 90))
    scr.text(((316 + scr.w - 30) // 2, 197), "连接", 28, (255, 255, 255),
             cn=True, anchor="mm", bold=True)

    if msg:
        scr.text((scr.w // 2, 240), msg[:56], 19, (250, 200, 130), cn=True, anchor="mm")

    from fbui import MiniKeyboard
    kb = MiniKeyboard(y0=252)
    kb.draw(scr)
    return kb


def draw_connecting(scr, ssid, psk, msg):
    scr.clear((12, 20, 30))
    scr.rect([0, 0, scr.w, 60], fill=(22, 40, 52))
    scr.rect([0, 58, scr.w, 62], fill=(60, 160, 190))
    scr.text((150, 30), "正在连接...", 26, (220, 245, 255), cn=True, anchor="lm")
    scr.text((scr.w // 2, 200), ssid[:30], 30, (255, 255, 255), cn=True, anchor="mm")
    scr.text((scr.w // 2, 250), msg or "请稍候, 最多等 20 秒", 22,
             (170, 210, 240), cn=True, anchor="mm")
    # 简易转圈提示
    scr.rrect([312, 320, 712, 370], 12, fill=(24, 46, 62))
    scr.text((512, 345), "连接中, 请稍候...", 22, (140, 220, 255), cn=True, anchor="mm")


def do_connect(scr, ssid, psk):
    """执行连接, 过程中显示"正在连接"界面"""
    draw_connecting(scr, ssid, psk, "")
    scr.flush()
    ok, m = connect(ssid, psk if psk else None)
    return ok, m


def run(scr, touch):
    from fbui import MiniKeyboard

    nets = []
    saved = {}              # {ssid: network_id} 已保存的网络
    cur = current_ssid()
    msg = ""
    scanning = False
    top_y = 0
    state = "list"          # list | psk | connecting
    forget_confirm = ""     # ★ 2026-10-01: 待确认删除的 SSID（两次点击才真删）
    psk_ssid = ""
    psk = ""
    kb = None
    dirty = True
    last_refresh = 0

    # 自愈: 万一配置里所有网络都被禁用了(会导致板子完全失联), 先救回来
    try:
        n = heal_disabled()
        if n:
            msg = "发现 %d 个网络被禁用, 已全部重新启用" % n
    except Exception:
        pass

    # 进入时自动扫一次
    scanning = True
    draw_list(scr, nets, cur, "正在扫描...", True, saved)
    scr.flush()
    nets = scan_all()
    saved = list_networks()
    scanning = False
    cur = current_ssid()
    last_refresh = time.time()
    msg = "找到 %d 个网络, 其中 %d 个已保存" % (len(nets), len(saved))
    dirty = True

    while True:
        if dirty:
            if state == "list":
                top_y = draw_list(scr, nets, cur, msg, scanning, saved,
                                  forget_confirm)
            elif state == "psk":
                kb = draw_psk(scr, psk_ssid, psk, msg)
            else:                                   # connecting
                draw_connecting(scr, psk_ssid or "网络", psk, msg)
            scr.flush()
            dirty = False

        ev = touch.poll()
        if ev:
            kind, x, y = ev
            # ★ 2026-10-01: 任何一次点击先清掉"待确认删除"。
            #   否则点了「忘记」却没点第二次，状态会一直留着 ——
            #   下次不小心再点一下就真删了。只有点到忘记按钮才会重新置上。
            _pending_forget = forget_confirm
            forget_confirm = ""

            # ---------------- 返回 ----------------
            if 0 <= x <= 140 and 0 <= y <= 62:
                if state == "list":
                    return
                state = "list"
                psk = ""
                msg = ""
                dirty = True
                continue

            # ---------------- 密码界面 ----------------
            if state == "psk":
                if y >= 252:
                    ch = kb.press(x, y) if kb else None
                    if ch:
                        if ch in ("<BS>", "\b"):
                            psk = psk[:-1]
                        elif ch in ("<ENTER>", "\n"):
                            state = "connecting"
                            draw_connecting(scr, psk_ssid, psk, "")
                            scr.flush()
                            ok, m = connect(psk_ssid, psk if psk else None)
                            msg = m
                            saved = list_networks()
                            cur = current_ssid()
                            state = "list"
                            psk = ""
                        elif len(ch) == 1 and len(psk) < 63:
                            psk += ch
                        dirty = True
                    continue
                # ★ 可见按钮: 取消 / 连接
                if 168 <= y <= 226:
                    if 30 <= x <= 300:
                        state = "list"
                        psk = ""
                        msg = ""
                        dirty = True
                        continue
                    if 316 <= x <= scr.w - 30:
                        state = "connecting"
                        draw_connecting(scr, psk_ssid, psk, "")
                        scr.flush()
                        ok, m = connect(psk_ssid, psk if psk else None)
                        msg = m
                        saved = list_networks()
                        cur = current_ssid()
                        state = "list"
                        psk = ""
                        dirty = True
                        continue
                continue

            if state == "connecting":
                continue

            # ---------------- 列表界面 ----------------
            y_btn = 72 + 64
            if y_btn <= y <= y_btn + 52:
                if 20 <= x <= 230:                  # 重新扫描
                    scanning = True
                    draw_list(scr, nets, cur, "正在扫描...", True, saved)
                    scr.flush()
                    nets = scan_all()
                    saved = list_networks()
                    scanning = False
                    cur = current_ssid()
                    msg = "找到 %d 个网络, 其中 %d 个已保存" % (len(nets), len(saved))
                    last_refresh = time.time()
                    dirty = True
                    continue
                if 246 <= x <= 456:                 # 断开
                    disconnect()
                    time.sleep(2)
                    cur = current_ssid()
                    msg = "已断开" if not cur else "断开失败"
                    dirty = True
                    continue

            # 点网络
            li = (y - top_y) // 56
            if 0 <= li < len(nets) and y >= top_y:
                ssid, sig, sec, bssid = nets[li]
                ry = top_y + li * 56

                # 「忘记」按钮
                # ★ 2026-10-01 修复：不再要求 `ssid != cur` ——
                #   当前连接的网络也能删（会先自动断开）。
                #   两次点击确认，第一次只是高亮提示。
                if (ssid in saved and
                        scr.w - 130 <= x <= scr.w - 26 and
                        ry + 26 <= y <= ry + 52):
                    if _pending_forget != ssid:
                        forget_confirm = ssid
                        msg = "⚠ 再点一次「忘记」确认删除: %s" % ssid
                        dirty = True
                        continue
                    # 第二次点击 -> 真删
                    if ssid == cur:
                        disconnect()
                        time.sleep(2.5)
                    ok, m = forget_network(ssid)
                    forget_confirm = ""
                    msg = m
                    saved = list_networks()
                    cur = current_ssid()
                    dirty = True
                    continue

                if ssid == cur:
                    msg = "已经连着这个了"
                    dirty = True
                    continue
                if sec == "企业":
                    msg = "企业网需要账号密码, 暂不支持"
                    dirty = True
                    continue

                # ★ 已保存 -> 免密码直接连
                if ssid in saved:
                    psk_ssid = ssid
                    state = "connecting"
                    draw_connecting(scr, ssid, "", "已保存过, 免密码连接中...")
                    scr.flush()
                    ok, m = connect_saved(ssid, saved[ssid])
                    if not ok and "已失效" in m:
                        # 只有密码确实不对, 才让用户重新输
                        psk = ""
                        state = "psk"
                        msg = m + " — 请重新输入密码"
                        kb = MiniKeyboard(y0=252)
                    else:
                        # 成功, 或者只是超时 -> 都回列表(保存没被删)
                        msg = m
                        state = "list"
                    saved = list_networks()
                    cur = current_ssid()
                    dirty = True
                    continue

                if sec == "开放":
                    psk_ssid = ssid
                    psk = ""
                    state = "connecting"
                    draw_connecting(scr, ssid, "", "开放网络, 无需密码")
                    scr.flush()
                    ok, m = connect(ssid, None)
                    msg = m
                    saved = list_networks()
                    cur = current_ssid()
                    state = "list"
                    dirty = True
                else:
                    psk_ssid = ssid
                    psk = ""
                    msg = "输密码后点绿色「连接」按钮"
                    kb = MiniKeyboard(y0=252)
                    state = "psk"
                    dirty = True
                continue

        # 每 12 秒刷新一次状态
        if state == "list" and time.time() - last_refresh > 12:
            cur = current_ssid()
            last_refresh = time.time()
            dirty = True

        time.sleep(0.05)
