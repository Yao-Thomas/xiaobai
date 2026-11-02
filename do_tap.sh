#!/bin/bash
sudo chmod 666 /dev/input/event1 2>/dev/null
sudo python3 /tmp/tap.py 300 290 2>&1
sleep 3