' start_remote_hidden.vbs -- 登录后静默启动「手机远程入口」的两件套
'   1) dsh_proxy.py   反向代理（把手机请求改写成"来自本机"再转给 DSH）
'   2) tunnel.py      cloudflared 公网隧道（用流量也能访问）
'
' 注意：
'   * pythonw / cloudflared 都必须给全路径，bare name 在 WScript 里找不到，
'     进程会静默死掉、没有任何提示。
'   * 用户目录含中文，所以用 %LOCALAPPDATA% 运行时展开，保持本文件纯 ASCII。
'   * 隧道用的是 cloudflared 的"快速隧道"，**网址每次重启都会变**。
'     新网址会写到 D:\ubuntu_iso\tunnel_url.txt，也可以双击 show_url.bat 查看。

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\ubuntu_iso"

py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & _
     "\Programs\Python\Python313\pythonw.exe"

' 1) 反向代理（固定端口 3081、固定口令）
sh.Run """" & py & """ dsh_proxy.py --port 3081 --token xb7k2m9q", 0, False

' 等 3 秒让代理先起来，再开隧道
WScript.Sleep 3000

' 2) 公网隧道（挂到本地代理上；口令门依然生效）
sh.Run """" & py & """ tunnel.py", 0, False
