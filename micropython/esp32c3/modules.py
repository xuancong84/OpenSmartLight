import socket

PORT = 1883

def dysonFanAdj(IP, serial, adj):
	try:
		ser = serial.encode()
		msg1 = b'\x82\x99\x01\x00\x01\x00"438/{SER}/status/current\x01\x00#438/{SER}/status/software\x01\x00%438/{SER}/status/connection\x01\x00!438/{SER}/status/faults\x01'.replace(b'{SER}', ser)
		msg2 = b'2\xa4\x01\x00\x1b438/{SER}/command\x00\x02{\n  "g": "438/{SER}/command",\n  "mode-reason": "LAPP",\n  "msg": "REQUEST-CURRENT-STATE",\n  "time": "2024-01-01T13:25:18Z"\n}'.replace(b'{SER}', ser)
		msg3 = b'2\xbc\x01\x00\x1b438/{SER}/command\x00\x04{\n  "data": {\n    "fnsp": "%04d"\n  },\n  "h": "438/{SER}/command",\n  "mode-reason": "LAPP",\n  "msg": "STATE-SET",\n  "time": "2023-12-20T10:26:49Z"\n}'.replace(b'{SER}', ser)
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.settimeout(5)
		s.connect((IP, PORT))
		s.sendall(msg1)
		s.recv(256)
		s.sendall(msg2)
		while True:
			data = s.recv(1024)
			if b'"fnsp"' in data:
				p = data.find(b'"fnsp"')
				speed = int(b''.join([data[p+i:p+i+1] for i in range(6,13) if data[p+i:p+i+1].isdigit()]))
				break
		msg = msg3 % (speed + adj)
		s.sendall(msg)
		s.close()
		return f'Sent {len(msg)} bytes'
	except Exception as e:
		return str(e)
