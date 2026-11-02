echo "=== 1) webfetch.norm_url 里的搜索引擎判定 ==="
grep -nE "SEARCH|duckduckgo|bing|search\?q|def norm_url" -A2 -B2 /home/zynq/ui/webfetch.py | head -40
echo
echo "=== 2) apps_browser 里的 SEARCH 用在哪 ==="
grep -nE "SEARCH|duckduckgo|bing" /home/zynq/ui/apps_browser.py | head -10
echo
echo "=== 3) 实测哪个搜索引擎能通 ==="
for u in "https://www.bing.com/search?q=zynq&format=rss" "https://lite.duckduckgo.com/lite/?q=zynq" "https://www.baidu.com/s?wd=zynq" "https://www.sogou.com/web?query=zynq"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$u" 2>/dev/null)
  printf "  %-52s HTTP %s\n" "$(echo $u | cut -c1-52)" "$code"
done