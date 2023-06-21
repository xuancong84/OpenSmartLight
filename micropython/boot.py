import uos, machine, gc, network, socket, select

sta_if = network.WLAN(network.STA_IF)
sta_if.active(False)
ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)

gc.collect()

def connect_wifi():
	if sta_if.active():
		print(f'Already exist: {sta_if.ifconfig()}')
		return
	import secret as cred
	sta_if.active(True)
	sta_if.ifconfig((cred.WIFI_IP,cred.WIFI_SUBNET,cred.WIFI_GATEWAY,cred.WIFI_DNS))
	sta_if.connect(cred.WIFI_SSID,cred.WIFI_PASSWD)
	print(sta_if.ifconfig())

def create_hotspot():
	if ap_if.active():
		print(f'Already exist: {ap_if.ifconfig()}')
		return
	ap_if.active(True)
	ap_if.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))
	ap_if.config(ssid='ESP-AP', authmode=network.AUTH_OPEN)
	print(ap_if.ifconfig())


import uasyncio as asyncio
from microdot_asyncio import Microdot

app = Microdot()
N=0
@app.route('/')
async def hello(request):
	global N
	N += 1
	return f'Hello world = {N}'

def start_server():
	print('Starting microdot app')
	try:
		app.run(port=80)
	except:
		app.shutdown()

def start():
	create_hotspot()
	import captiveDNS
	cd=captiveDNS.CaptiveDNS('192.168.4.1')
	start_server()

# class WebServer:
# 	def __init__(self, host='0.0.0.0', captivePortal=False, port=80, max_conn=8):
# 		self.sock_web = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# 		self.sock_web.bind(('', port))
# 		self.sock_web.listen(max_conn)
# 		self.poll = select.poll()
# 		self.poll.register(self.sock_web, select.POLLIN)

# 		if captivePortal:
# 			self.sock_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# 			self.sock_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# 			self.sock_dns.bind((host, port))
# 			self.poll.register(self.sock_dns, select.POLLIN)
# 		else:
# 			self.sock_dns = None

# 	def run(self, dur=None):
# 		while True:
# 			self.poll.poll(dur)
# 			conn, addr = self.sock_web.accept()
# 			print('Got a connection from %s' % str(addr))
# 			request = conn.recv(1024)
# 			print('Content = %s' % str(request))
# 			conn.send("""<html><head><meta name="viewport" content="width=device-width, initial-scale=1"</head><body><h1>Hello, World!</h1></body></html>""")
# 			conn.close()
