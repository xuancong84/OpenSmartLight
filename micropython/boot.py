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


from microdot import Microdot

app = Microdot()
N=0
@app.route('/')
def hello(request):
	global N
	N += 1
	return f'Hello world = {N}'

class WebServer:
	def __init__(self, app: Microdot, host='0.0.0.0', captivePortalIP='', port=80, max_conn=8):
		self.app = app
		self.sock_web = app.run(host=host, port=port, loop_forever=False, max_conn=max_conn)
		self.poll = select.poll()
		self.poll.register(self.sock_web, select.POLLIN)
		self.sock_map = {id(self.sock_web): self.app.run_once}
		self.cpIP = captivePortalIP

		if captivePortalIP:
			self.sock_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.sock_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.sock_dns.bind((captivePortalIP, 53))
			self.poll.register(self.sock_dns, select.POLLIN)
			self.sock_map[id(self.sock_dns)] = self.handleDNS
		else:
			self.sock_dns = None

	def handleDNS(self):
		data, sender = self.sock_dns.recvfrom(512)
		packet = data[:2] + b"\x81\x80" + data[4:6] + data[4:6] + b"\x00\x00\x00\x00"
		packet += data[12:] + b"\xC0\x0C\x00\x01\x00\x01\x00\x00\x00\x3C\x00\x04"
		packet += bytes(map(int, self.cpIP.split(".")))
		self.sock_dns.sendto(packet, sender)

	def run(self):
		while True:
			for tp in self.poll.poll():
				self.sock_map[id(tp[0])]()
				gc.collect()


def start_server_hotspot():
	create_hotspot()
	server = WebServer(app, host='192.168.4.1', captivePortalIP='192.168.4.1')
	server.run()

def start_server_wifi():
	connect_wifi()
	print('Starting microdot app')
	try:
		app.run(port=80)
	except:
		app.shutdown()

print('BOOT OK')
gc.collect()