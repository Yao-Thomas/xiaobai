#!/bin/bash
echo "--- 不带口令（应看到口令页 403）---"
curl -s -o /dev/null -w "  HTTP %{http_code}\n" --max-time 8 http://192.168.10.17:3081/
echo "--- 带口令 ?k=test1234（应 303 + Set-Cookie）---"
curl -s -i --max-time 8 "http://192.168.10.17:3081/?k=test1234" | head -8
echo "--- 完整流程：带口令拿 cookie，再用 cookie 请求 ---"
rm -f /tmp/ck.txt
curl -s -c /tmp/ck.txt -o /dev/null --max-time 8 "http://192.168.10.17:3081/?k=test1234"
echo "  拿到的 cookie:"
cat /tmp/ck.txt | grep -v '^#' | awk '{print "    " $6 " = " substr($7,1,24) "..."}'
echo "  用 cookie 请求首页:"
curl -s -b /tmp/ck.txt -o /tmp/pg.html -w "    HTTP %{http_code}  大小 %{size_download} 字节\n" --max-time 10 http://192.168.10.17:3081/
head -c 100 /tmp/pg.html; echo