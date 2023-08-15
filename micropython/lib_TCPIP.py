import socket

def send_tcp(obj):
	try:
		s = socket.socket()
		s.settimeout(3)
		s.connect((obj['IP'], obj['PORT']))
		s.sendall(obj['data'])
		s.recv(obj.get('recv_size', 256))
		s.close()
		return f'OK, sent {len(obj["data"])} bytes'
	except Exception as e:
		#prt(e)
		return str(e)

def send_udp(obj):
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		nsent = s.sendto(obj['data'], (obj['IP'], obj['PORT']))
		s.close()
		return f'OK, sent {nsent} bytes'
	except Exception as e:
		#prt(e)
		return str(e)
	
def send_wol(obj):
	try:
		mac = obj['data']
		if len(mac) == 17:
			mac = mac.replace(mac[2], "")
		elif len(mac) != 12:
			return "Incorrect MAC address format"
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		nsent = s.sendto(bytes.fromhex("F"*12 + mac*16), (obj.get('IP', '255.255.255.255'), obj.get('PORT', 9)))
		s.close()
		return f'OK, sent {nsent} bytes'
	except Exception as e:
		#prt(e)
		return str(e)

def send_cap(obj):
	s = None
	for L in open(obj['filename'], 'rb'):
		try:
			L = L.strip()
			if L.startswith(b'{'):
				obj = eval(L)
				del L
				gc.collect()
				s = socket.socket()
				s.settimeout(3)
				s.connect((obj['IP'], obj['PORT']))
				if 'data' in obj:
					s.sendall(obj['data'])
			elif L.startswith(b'b'):
				s.sendall(eval(L))
				del L
			elif L.isdigit():
				s.recv(int(L)*2)
			gc.collect()
		except:
			pass
	try:
		s.close()
	except Exception as e:
		return str(e)
