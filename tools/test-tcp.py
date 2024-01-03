#!/usr/bin/env python3

import os, sys, socket
from select import select

IP='192.168.50.11'
PORT=1883

data1='''
10 8a 01 00 04 4d 51 54  54 04 c2 00 3c 00 13 70  .....MQTT...<..p
61 68 6f 35 37 39 32 32  32 35 30 34 38 38 36 31  aho5792225048861
33 37 00 0f 45 31 47 2d  53 47 2d 4e 47 41 30 33  37..E1G-SG-NGA03
30 31 41 00 58 77 66 73  77 30 65 54 4f 4b 36 46  01A.Xwfsw0eTOK6F
2b 38 71 31 67 30 6e 39  57 33 68 70 47 47 4f 79  +8q1g0n9W3hpGGOy
67 65 32 4f 76 46 6b 4d  41 46 51 42 67 71 55 4f  ge2OvFkMAFQBgqUO
6b 5a 77 61 65 71 43 4e  63 7a 61 42 6c 52 7a 42  kZwaeqCNczaBlRzB
74 6a 56 47 4d 79 42 72  37 37 70 62 52 6d 33 55  tjVGMyBr77pbRm3U
47 39 34 72 66 6c 4a 73  76 53 51 3d 3d           G94rflJsvSQ==
'''

data2='''
82 99 01 00 01 00 22 34  33 38 2f 45 31 47 2d 53  ......"438/E1G-S
47 2d 4e 47 41 30 33 30  31 41 2f 73 74 61 74 75  G-NGA0301A/statu
73 2f 63 75 72 72 65 6e  74 01 00 23 34 33 38 2f  s/current..#438/
45 31 47 2d 53 47 2d 4e  47 41 30 33 30 31 41 2f  E1G-SG-NGA0301A/
73 74 61 74 75 73 2f 73  6f 66 74 77 61 72 65 01  status/software.
00 25 34 33 38 2f 45 31  47 2d 53 47 2d 4e 47 41  .%438/E1G-SG-NGA
30 33 30 31 41 2f 73 74  61 74 75 73 2f 63 6f 6e  0301A/status/con
6e 65 63 74 69 6f 6e 01  00 21 34 33 38 2f 45 31  nection..!438/E1
47 2d 53 47 2d 4e 47 41  30 33 30 31 41 2f 73 74  G-SG-NGA0301A/st
61 74 75 73 2f 66 61 75  6c 74 73 01              atus/faults.
'''

data3='''
32 a4 01 00 1b 34 33 38  2f 45 31 47 2d 53 47 2d  2....438/E1G-SG-
4e 47 41 30 33 30 31 41  2f 63 6f 6d 6d 61 6e 64  NGA0301A/command
00 02 7b 0a 20 20 22 67  22 3a 20 22 34 33 38 2f  ..{.  "g": "438/
45 31 47 2d 53 47 2d 4e  47 41 30 33 30 31 41 2f  E1G-SG-NGA0301A/
63 6f 6d 6d 61 6e 64 22  2c 0a 20 20 22 6d 6f 64  command",.  "mod
65 2d 72 65 61 73 6f 6e  22 3a 20 22 4c 41 50 50  e-reason": "LAPP
22 2c 0a 20 20 22 6d 73  67 22 3a 20 22 52 45 51  ",.  "msg": "REQ
55 45 53 54 2d 43 55 52  52 45 4e 54 2d 53 54 41  UEST-CURRENT-STA
54 45 22 2c 0a 20 20 22  74 69 6d 65 22 3a 20 22  TE",.  "time": "
32 30 32 34 2d 30 31 2d  30 31 54 31 33 3a 32 35  2024-01-01T13:25
3a 31 38 5a 22 0a 7d                              :18Z".}
'''

data = [data2, data3]

def parse_data(data_cap):
	data = [L[:50].split() for L in data_cap.splitlines() if L.strip()]
	return bytes.fromhex(''.join([i for its in data for i in its]))

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
	s.connect((IP, PORT))
	for d1 in data:
		data_raw = parse_data(d1)
		n=len(data_raw)
		print(f'Data: {data_raw}')
		s.sendall(data_raw)
		print(f'Sent {n} bytes')
		print('RECV:', s.recv(1024))

	while True:
		select([s], [], [])
		print(s.recv(1024))
