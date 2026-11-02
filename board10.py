import sys
sys.argv = ['board.py', 'echo 板子活着; hostname; date; echo -n \"WiFi: \"; iwconfig wlx688fc92bd646 2>/dev/null | grep -oP \"ESSID:\S+\"; echo -n \"IP: \"; hostname -I']
exec(open(r'D:\ubuntu_iso\board.py').read().replace('HOST = \"192.168.43.210\"', 'HOST = \"192.168.10.13\"'))
