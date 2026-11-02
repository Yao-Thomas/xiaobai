#!/bin/bash
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"v":30}' \
  http://127.0.0.1:8767/volume; echo
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo "--- 服务 ---"
systemctl is-active zynq-audio zynq-agent zynq-desktop