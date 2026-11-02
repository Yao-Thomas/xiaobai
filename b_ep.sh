echo "=== 1) 8767 上是谁 ==="
sudo ss -tlnp 2>/dev/null | grep -E "8767|8768|8765" || netstat -tlnp 2>/dev/null | grep -E "8767|8768|8765"
echo
echo "=== 2) 探端点 ==="
for ep in /state /record /play /selftest /stop; do
  printf "  %-12s " "$ep"
  if [ "$ep" = "/record" ]; then
    curl -s -o /dev/null -w "POST->%{http_code}\n" -X POST -H "Content-Type: application/json" -d '{"secs":1,"rate":16000,"mono":true}' --max-time 20 http://127.0.0.1:8767$ep
  else
    curl -s -o /dev/null -w "GET->%{http_code} " --max-time 5 http://127.0.0.1:8767$ep
    curl -s -o /dev/null -w "POST->%{http_code}\n" -X POST -H "Content-Type: application/json" -d '{}' --max-time 5 http://127.0.0.1:8767$ep
  fi
done
echo
echo "=== 3) audio_svc.py 的端口和端点 ==="
grep -nE "^PORT|PORT =|AUDIO_SVC_PORT" /home/zynq/ui/audio_svc.py | head -3
grep -nE '"/record"|"/play"|"/selftest"|"/state"|self\.path ==' /home/zynq/ui/audio_svc.py | head -10
echo
echo "=== 4) 两个服务文件对比 ==="
ls -la /home/zynq/ui/audio_alsa_svc.py /home/zynq/ui/audio_svc.py