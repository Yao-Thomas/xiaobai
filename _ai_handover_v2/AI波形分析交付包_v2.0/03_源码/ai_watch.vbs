' ============================================================
'  ai_watch.vbs -- keep wave_ai multi-modal service (port 8000) alive
'
'  Why this instead of a .bat in Startup:
'    1) .bat is parsed by cmd with GBK codepage -> any non-ASCII char
'       (Chinese comment, Chinese path) breaks parsing silently.
'       This file is pure ASCII and paths are ASCII junctions:
'         D:\ubuntu_iso\ai_src   -> ...\03_\u6e90\u7801
'         D:\ubuntu_iso\ai_deliv -> ...\01_\u4ea4\u4ed8\u7269
'    2) A one-shot launcher cannot recover if the service dies later.
'       This script stays resident and re-checks every 60 s.
'
'  Log: D:\ubuntu_iso\_ai_boot.log
' ============================================================
Option Explicit

Dim sh, fso, py, src, deliv, logf, cmd, ok, tries, http, f

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

py    = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\python.exe"
src   = "D:\ubuntu_iso\ai_src"
deliv = "D:\ubuntu_iso\ai_deliv"
logf  = "D:\ubuntu_iso\_ai_boot.log"

cmd = """" & py & """ -m wave_ai.serve" _
    & " --model """ & deliv & "\model_bundle.pt""" _
    & " --anomaly """ & deliv & "\anomaly_stats.npz""" _
    & " --host 0.0.0.0 --port 8000"

Sub LogLine(msg)
    Dim g
    On Error Resume Next
    Set g = fso.OpenTextFile(logf, 8, True)
    If Err.Number = 0 Then
        g.WriteLine Now & "  " & msg
        g.Close
    End If
    Err.Clear
    On Error GoTo 0
End Sub

Function ServiceOk()
    Dim h
    ServiceOk = False
    On Error Resume Next
    Set h = CreateObject("MSXML2.XMLHTTP")
    h.Open "GET", "http://127.0.0.1:8000/health", False
    h.Send
    If Err.Number = 0 Then
        If h.Status = 200 Then ServiceOk = True
    End If
    Err.Clear
    On Error GoTo 0
End Function

LogLine "watchdog start (pid " & sh.ExpandEnvironmentStrings("%PROCESSID%") & ")"

If Not fso.FileExists(py) Then
    LogLine "ERROR python not found: " & py
End If
If Not fso.FolderExists(src) Then
    LogLine "ERROR src not found: " & src
End If

tries = 0
Do
    If Not ServiceOk() Then
        tries = tries + 1
        LogLine "port 8000 down -> start attempt #" & tries
        On Error Resume Next
        sh.CurrentDirectory = src
        sh.Run cmd, 0, False          ' 0 = hidden window, don't wait
        If Err.Number <> 0 Then
            LogLine "ERROR launching: " & Err.Description
            Err.Clear
        End If
        On Error GoTo 0
        ' give the server time to bind
        WScript.Sleep 15000
        If ServiceOk() Then
            LogLine "service OK after start"
        Else
            LogLine "still not OK after start (sleep 45s and retry)"
            WScript.Sleep 45000
        End If
    Else
        tries = 0
    End If
    WScript.Sleep 60000
Loop
