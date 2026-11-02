# tts_gen.ps1 —— 用 Windows 自带 TTS 生成一段中文语音 WAV
#
# ★ 用途：自测语音识别链路。
#   语音识别没法"自己说话"来测（要真人对麦克风讲），
#   但可以让 Windows 的 TTS 说一句、存成 WAV，
#   再把它喂给识别器（SetInputToWaveFile）——
#   这样整条链路就能【全自动】验证，不用等人。
#
# 用法:
#   powershell -File tts_gen.ps1 -Text "现在多少度" -Out D:\ubuntu_iso\_tts_test.wav

param(
    [string]$Text = "现在多少度",
    [string]$Out = "D:\ubuntu_iso\_tts_test.wav"
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

# 挑一个中文音色（有就用，没有就用默认）
$zh = $null
foreach ($v in $synth.GetInstalledVoices()) {
    if ($v.VoiceInfo.Culture.Name -like "zh*") { $zh = $v.VoiceInfo.Name; break }
}
if ($zh) {
    $synth.SelectVoice($zh)
    Write-Host "  用音色: $zh"
} else {
    Write-Host "  [警告] 没有中文音色，用默认的（识别结果可能不准）"
}

$synth.Rate = 0
$synth.Volume = 100
$synth.SetOutputToWaveFile($Out)
$synth.Speak($Text)
$synth.SetOutputToNull()
$synth.Dispose()

Write-Host "  已写 $Out"
