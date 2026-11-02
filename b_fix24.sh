cd /home/zynq/ui
TS=$(date +%Y%m%d_%H%M%S)
cp audio_alsa_svc.py audio_alsa_svc.py.bak_s24fix_$TS
echo "  备份: audio_alsa_svc.py.bak_s24fix_$TS"
sudo cp /tmp/aas_new.py audio_alsa_svc.py
sudo chown zynq:zynq audio_alsa_svc.py
md5sum audio_alsa_svc.py
python3 -c "import ast,io; ast.parse(io.open('audio_alsa_svc.py',encoding='utf-8').read()); print('syntax OK')"
sudo systemctl restart zynq-audio
sleep 5
echo "  服务: $(systemctl is-active zynq-audio)"