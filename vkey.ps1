# vkey.ps1 -- VirtualBox VM key injection helper (ASCII only)  [v3: 前缀键, 彻底解决大小写]
# usage:  . D:\ubuntu_iso\vkey.ps1 ;  VMKeys "1c 9c" | VMType "text" | VMLine "long text" | VMShot "x.png"

$script:VBM   = "D:\VirualBox\VBoxManage.exe"
$script:VNAME = "zynq-peta"

$script:MK = @{}
function Brk([string]$code){ (([Convert]::ToInt32($code,16)) -bor 0x80).ToString('x2') }

# 字母: 小写 key="L<c>", 大写 key="U<c>" (Shift+字母)
foreach($p in 'a1e b30 c2e d20 e12 f21 g22 h23 i17 j24 k25 l26 m32 n31 o18 p19 q10 r13 s1f t14 u16 v2f w11 x2d y15 z2c'.Split(' ')){
    $ch=$p[0]; $code=$p.Substring(1); $b=Brk $code
    $script:MK["L$ch"] = @($code,$b)
    $script:MK["U$ch"] = @('2a',$code,$b,'aa')
}
# 数字: key="S<d>"
foreach($p in '1 02|2 03|3 04|4 05|5 06|6 07|7 08|8 09|9 0a|0 0b'.Split('|')){
    $q=$p.Split(' '); $code=$q[1]
    $script:MK["S$($q[0])"] = @($code,(Brk $code))
}
# 普通符号: key="S<c>"
$sym = @{ ' '='39';'-'='0c';'='='0d';'['='1a';']'='1b';';'='27';"'"='28';'`'='29';'\'='2b';','='33';'.'='34';'/'='35' }
foreach($k in $sym.Keys){ $code=$sym[$k]; $script:MK["S$k"] = @($code,(Brk $code)) }
# 需 Shift 的符号: key="S<c>"
$shifted = @{ ':'='27';'_'='0c';'!'='02';'@'='03';'#'='04';'$'='05';'%'='06';'^'='07';'&'='08';'*'='09';'('='0a';')'='0b';'+'='0d';'{'='1a';'}'='1b';'|'='2b';'"'='28';'~'='29';'<'='33';'>'='34';'?'='35' }
foreach($k in $shifted.Keys){ $code=$shifted[$k]; $script:MK["S$k"] = @('2a',$code,(Brk $code),'aa') }

$script:MISSED = New-Object System.Collections.Generic.List[string]
$script:LASTERR = ""

function VMKeys([string]$codes){
    & $script:VBM controlvm $script:VNAME keyboardputscancode @($codes.Split(' '))
    Start-Sleep -Milliseconds 280
}

function KeyFor([string]$c){
    if($c -cmatch '^[a-z]$'){ return "L$c" }
    if($c -cmatch '^[A-Z]$'){ return "U$c" }
    return "S$c"
}

function VMType([string]$text){
    $out = New-Object System.Collections.Generic.List[string]
    foreach($ch in $text.ToCharArray()){
        $k = KeyFor ([string]$ch)
        if($script:MK.ContainsKey($k)){ foreach($x in [string[]]$script:MK[$k]){ $out.Add($x) } }
        else { $script:MISSED.Add($ch) }
    }
    if($out.Count -gt 0){ & $script:VBM controlvm $script:VNAME keyboardputscancode @($out) }
    Start-Sleep -Milliseconds 400
}

function VMLine([string]$text){
    for($i=0; $i -lt $text.Length; $i+=16){
        VMType $text.Substring($i, [Math]::Min(16, $text.Length-$i))
        Start-Sleep -Milliseconds 350
    }
}

function VMShot([string]$path){
    & $script:VBM controlvm $script:VNAME screenshotpng $path 2>&1 | Out-Null
}
