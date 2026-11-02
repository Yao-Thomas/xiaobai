# 🔧 Vivado 2018.3 "2026 年份" bug 补丁说明

## 症状
用 Vivado 2018.3 生成某些 **HLS 类 IP**（如 `v_frmbuf_rd` / `v_frmbuf_wr`）时失败：

```
source run_ippack.tcl -notrace
bad lexical cast: source type value could not be interpreted as target
    while executing
"rdi::set_property core_revision 2609191539 {component component_1}"
ERROR: [IMPL 213-28] Failed to generate IP.
```

## 根因
HLS 打包 IP 时，把 **`core_revision` 设成 `YYMMDDHHMM` 格式的当前时间**。

- 2020 年：`2012312359` —— 小于 32 位有符号上限 `2147483647` ✅ 正常
- **2026 年：`2609191539` —— 超过上限** ❌ → TCL 无法把字符串转成 32 位整数 → IP 打包失败

**这是一个"到 2026 年才会暴露"的 Xilinx 老 bug**，与正点原子工程无关。

## 补丁
**文件**：`D:\Xilinx\Vivado\2018.3\scripts\ip\ipxhls.tcl`
**备份**：`ipxhls.tcl.bak_before_y2026fix`

**原代码（第 202~204 行）**：
```tcl
if { $IpxRevision ne "" } {
    set_property core_revision $IpxRevision [ipx::current_core]
}
```

**改成**：
```tcl
if { $IpxRevision ne "" } {
    # ---- DSH FIX (2026): 压回 32 位有符号范围, 避免 bad lexical cast ----
    if {[catch {expr {$IpxRevision > 2147483647}} _big] && $_big} {
        set IpxRevision [expr {$IpxRevision - 2000000000}]
    }
    set_property core_revision $IpxRevision [ipx::current_core]
}
```

## 恢复方法
```powershell
Copy-Item "D:\Xilinx\Vivado\2018.3\scripts\ip\ipxhls.tcl.bak_before_y2026fix" `
          "D:\Xilinx\Vivado\2018.3\scripts\ip\ipxhls.tcl" -Force
```

## 备注
- 该补丁只影响 IP 打包时的"修订号"字段（一个元数据数字），**不影响生成的硬件功能**。
- 如果以后升级到 Vivado 2020.2+，不需要这个补丁。
