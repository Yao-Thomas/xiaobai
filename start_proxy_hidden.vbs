' start_proxy_hidden.vbs -- run the DSH phone-entry proxy silently at logon.
'
' Notes (learned the hard way):
'   * pythonw must be given by FULL path: a bare "pythonw" is not found from
'     the WScript environment, and the process dies with no output at all.
'   * The user profile path contains non-ASCII characters, so we expand
'     %LOCALAPPDATA% at runtime instead of hard-coding it -- that keeps this
'     file pure ASCII and avoids codepage mangling.
'   * Working directory D:\ubuntu_iso is ASCII, safe to hard-code.
'
' Phone URL: http://192.168.10.17:3081/?k=xb7k2m9q

Set sh = CreateObject("WScript.Shell")
py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & _
     "\Programs\Python\Python313\pythonw.exe"
sh.CurrentDirectory = "D:\ubuntu_iso"
sh.Run """" & py & """ dsh_proxy.py --port 3081 --token xb7k2m9q", 0, False
