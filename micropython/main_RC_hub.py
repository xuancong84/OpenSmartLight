import machine, gc, network, socket, select, time, random
from array import array
from time import ticks_us, ticks_diff
from math import sqrt
from microWebSrv import MicroWebSrv
gc.collect()

PIN_RC_IN = 5
PIN_RC_OUT = 4
DEBUG = True

pino = machine.Pin(PIN_RC_OUT, machine.Pin.OUT)
pino(0)

sta_if = network.WLAN(network.STA_IF)
sta_if.active(False)
ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)
wifi = {}

def prt(*args, **kwarg):
	if DEBUG: print(*args, **kwarg)

def connect_wifi():
	global wifi
	if sta_if.isconnected():
		prt(f'Already exist: {sta_if.ifconfig()}')
		return True
	try:
		import secret as cred
		sta_if.active(True)
		sta_if.ifconfig((cred.WIFI_IP, cred.WIFI_SUBNET, cred.WIFI_GATEWAY, cred.WIFI_DNS))
		sta_if.connect(cred.WIFI_SSID, cred.WIFI_PASSWD)
		x = 0
		while x<30 and not sta_if.isconnected():
			time.sleep(2)
			prt('.', end='')
			x += 1
		wifi.update({'mode':'wifi', 'config':sta_if.ifconfig()})
		return sta_if.isconnected()
	except:
		return False

def create_hotspot():
	global wifi
	if ap_if.isconnected():
		prt(f'Already exist: {ap_if.ifconfig()}')
		return
	ap_if.active(True)
	IP = f'192.168.{min(250, random.getrandbits(8))}.1'
	ap_if.ifconfig((IP, '255.255.255.0', IP, IP))
	ap_if.config(ssid='ESP-AP', authmode=network.AUTH_OPEN)
	wifi.update({'mode':'hotspot', 'config':ap_if.ifconfig()})

g_N = 0
@MicroWebSrv.Route('/global')
def hello(*req):
	global g_N
	g_N += 1
	return f'Hello global = {g_N}'

class MWebServer:
	def __init__(self, host='0.0.0.0', captivePortalIP='', port=80, max_conn=8):
		self.N = 0
		routeHandlers = [( "/", "GET", lambda *_: f'Hello world!' )]
		self.app = MicroWebSrv(routeHandlers=routeHandlers, port=port, bindIP='0.0.0.0', webPath="/static")
		self.sock_web = self.app.run(max_conn=max_conn, loop_forever=False)
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

		@self.app.route('/local')
		def hello(*req):
			self.N += 1
			return f'Hello local = {self.N}'

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


class RC():
	def __init__(self, rx_pin, tx_pin=None):  # Typically ~15 frames
		self.rx_pin = machine.Pin(rx_pin, machine.Pin.IN, machine.Pin.PULL_UP)
		self.tx_pin = self.rx_pin if tx_pin is None else machine.Pin(tx_pin, machine.Pin.OUT)
		self.tx_pin(0)
		self.data = {}
		gc.collect()

	# View list of pulse lengths: prt(receiver['on'])
	def __getitem__(self, key):
		return self.data.get(key, (None, None))

	def __delitem__(self, key):  # Key deletion: del receiver['on']
		del self.data[key]

	def keys(self):
		return self.data.keys()

	def recv(self, key=None, nedges=800):
		gc.collect()
		prt('Receiving radio data ...')
		p = self.rx_pin
		arr = array('I',  [0]*nedges)

		# ** Time critical **
		st_irq = machine.disable_irq()
		tm_til = ticks_us()+3000000
		init_level = v = p()
		for x in range(nedges):
			while v == p() and ticks_us()<tm_til: pass
			arr[x] = ticks_us()
			if arr[x]>tm_til: break
			v = p()
		machine.enable_irq(st_irq)
		# ** End of time critical **

		if x < nedges-1:
			return 'No signal received', None

        # Compute diffs
		for x in range(nedges-1, 0, -1):
			arr[x] = ticks_diff(arr[x], arr[x-1])
		arr[0] = 0

		# Extract segments
		gap = round(max(arr)*0.8)
		gap_pos = [i for i,v in enumerate(arr) if v>=gap]
		if len(gap_pos) < 6:
			return 'Too few frames', None
		segs = [arr[gap_pos[i-1]:gap_pos[i]] for i in range(1, len(gap_pos))]
		prt(f'init level={init_level}')
		init_level = 1-init_level if (gap_pos[0]&1) else init_level
		del arr

		lengths = [len(x) for x in segs]

		# Select segments with most common frame length
		cnter = {x:lengths.count(x) for x in set(lengths)}
		cnt_max = max(cnter.values())
		len_most = [i for i,j in cnter.items() if j==cnt_max][0]
		N_old = len(segs)
		segs = [seg for seg in segs if len(seg)==len_most]
		N_new = len(segs)

		if N_new < 5:
			return 'Too few selected frames', None
		
		if N_old != N_new:
			prt('Deleted {} frames of wrong length'.format(N_old - N_new))

		prt(f'Averaging {N_new} frames')
		m = [sum(x)/N_new for x in zip(*segs)]	# mean
		std = [sqrt(sum([(y - m[i])**2 for y in x])/N_new) for i, x in enumerate(zip(*segs))]
		del segs
		prt('Capture quality {:5.1f} (0: perfect)'.format(sum(std)/len(std)))
		res = list(map(round, m))
	
		if key != None:
			self.data[key] = init_level, res
			prt(f'Key "{key}" stored.')
		return init_level, res


	def send(self, key, repeat=5):
		gc.collect()
		init_level, arr = self[key] if type(key)==str else key
		if arr == None:
			prt('No valid data found')
			return
		
		prt('Sending radio data ...')
		p = self.tx_pin

		# ** Time critical **
		st_irq = machine.disable_irq()
		for i in range(repeat):
			level = init_level
			p(level)
			tm_til = ticks_us()
			for dt in arr:
				tm_til += dt
				level = 1-level
				while ticks_us()<tm_til: pass
				p(level)
		machine.enable_irq(st_irq)
		# ** End of time critical **

		p(0)	# turn off radio

rc = RC(PIN_RC_IN, PIN_RC_OUT)

gc.collect()

### MAIN function
def run():
	cpIP = ''
	if not connect_wifi():
		create_hotspot()
		cpIP = wifi['config'][0]
	prt(wifi)
	server = MWebServer(captivePortalIP=cpIP)
	server.run()
