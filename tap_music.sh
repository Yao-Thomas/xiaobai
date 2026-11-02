#!/bin/bash
sudo chmod 666 /dev/input/event1 2>/dev/null
sudo python3 /tmp/tap.py 378 550
sleep 2
sudo python3 /tmp/tap.py 300 290
sleep 3