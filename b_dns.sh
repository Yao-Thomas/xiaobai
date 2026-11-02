echo "--- 当前 DNS 配置 ---"
cat /etc/resolv.conf
echo
echo "--- DHCP 拿到的 DNS ---"
networkctl status wlx688fc92bd646 2>/dev/null | grep -E "DNS|Gateway|Address"
echo
echo "--- 实际解析测试 ---"
for h in www.baidu.com github.com api.deepseek.com; do
  r=$(getent hosts $h 2>/dev/null | head -1)
  printf "  %-20s %s\n" "$h" "${r:-✗ 解析失败}"
done
echo
echo "--- 连通性 ---"
ping -c 1 -W 3 223.5.5.5 >/dev/null 2>&1 && echo "  ✓ 223.5.5.5 可达" || echo "  ✗ 223.5.5.5 不通"
ping -c 1 -W 3 192.168.110.1 >/dev/null 2>&1 && echo "  ✓ 网关可达" || echo "  ✗ 网关不通"