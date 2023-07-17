import os, sys, machine, gc, network, socket, select, time, random, json
import urequests as url
from array import array
from time import ticks_us, ticks_diff
from math import sqrt
from microWebSrv import MicroWebSrv as MWS
gc.collect()

PIN_RC_IN = 5
PIN_RC_OUT = 4
DEBUG = True

LED = machine.Pin(2, machine.Pin.OUT)
LED(0)
time.sleep(1)
LED(1)

def flashLED(intv=0.25):
	for i in range(3):
		LED(0)
		time.sleep(intv)
		LED(1)
		time.sleep(intv)

pino = machine.Pin(PIN_RC_OUT, machine.Pin.OUT)
pino(0)

sta_if = network.WLAN(network.STA_IF)
ap_if = network.WLAN(network.AP_IF)
wifi = {}

def prt(*args, **kwarg):
	if DEBUG: print(*args, **kwarg)

def connect_wifi():
	global wifi
	if sta_if.isconnected():
		sta_if.disconnect()
		time.sleep(1)
	try:
		cred = eval(open('secret.py').read())
		sta_if.active(True)
		WIFI_IP, WIFI_SUBNET, WIFI_GATEWAY, WIFI_DNS = [cred.get(v, '') for v in ['WIFI_IP', 'WIFI_SUBNET', 'WIFI_GATEWAY', 'WIFI_DNS']]
		if WIFI_IP and WIFI_SUBNET and WIFI_GATEWAY and WIFI_DNS:
			sta_if.ifconfig((WIFI_IP, WIFI_SUBNET, WIFI_GATEWAY, WIFI_DNS))
		sta_if.connect(cred['WIFI_SSID'], cred['WIFI_PASSWD'])
		x = 0
		while x<30 and not sta_if.isconnected():
			time.sleep(2)
			prt('.', end='')
			x += 1
		wifi.update({'mode':'wifi', 'config':sta_if.ifconfig()})
		return sta_if.isconnected()
	except Exception as e:
		prt(e)
		return False

def create_hotspot():
	global wifi
	if ap_if.active():
		wifi.update({'mode':'hotspot', 'config':ap_if.ifconfig()})
		return
	ap_if.active(True)
	IP = f'192.168.{min(250, random.getrandbits(8))}.1'
	ap_if.ifconfig((IP, '255.255.255.0', IP, IP))
	ap_if.config(ssid='ESP-AP', authmode=network.AUTH_OPEN)
	wifi.update({'mode':'hotspot', 'config':ap_if.ifconfig()})

def start_wifi():
	if not connect_wifi():
		create_hotspot()
		return wifi['config'][0]
	return ''


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
			return 'No signal received'

        # Compute diffs
		for x in range(nedges-1, 0, -1):
			arr[x] = ticks_diff(arr[x], arr[x-1])
		arr[0] = 0

		# Extract segments
		gap = round(max(arr)*0.8)
		gap_pos = [i for i,v in enumerate(arr) if v>=gap]
		if len(gap_pos) < 6:
			return 'Too few frames'
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
			return 'Too few selected frames'
		
		if N_old != N_new:
			prt('Deleted {} frames of wrong length'.format(N_old - N_new))

		prt(f'Averaging {N_new} frames')
		m = [sum(x)/N_new for x in zip(*segs)]	# mean
		std = [sqrt(sum([(y - m[i])**2 for y in x])/N_new) for i, x in enumerate(zip(*segs))]
		del segs
		prt('Capture quality {:5.1f} (0: perfect)'.format(sum(std)/len(std)))
		ret = {'init_level':init_level, 'data':list(map(round, m))}
	
		if key != None:
			self.data[key] = ret
			prt(f'Key "{key}" stored.')
		return ret


	def send(self, key, repeat=5):
		gc.collect()

		try:
			obj = key if type(key)==dict else self.data.get(key, eval(key if type(key)==str else key.decode()))
			init_level, arr = obj['init_level'], obj['data']
		except Exception as e:
			prt(f'key={key}')
			prt(e)
			return False
		
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
		return True


# Globals
g_reboot = False
g_restartWifi = False
rc = RC(PIN_RC_IN, PIN_RC_OUT)

def get_rc_code(key):
	try:
		with open('rc-codes.txt') as fp:
			for L in fp:
				its = L.split('\t')
				if key == its[0]:
					return eval(its[2])
	except Exception as e:
		prt(e)
	return None

def save_file(fn, gen):
	try:
		with open(fn, 'wb') as fp:
			for L in gen:
				fp.write(L)
				gc.collect()
		return True
	except:
		return False
	
def list_files(path=''):
	yield f'{path}/\t\n'
	for f in os.listdir(path):
		ff = path+'/'+f
		try:
			os.listdir(ff)
			yield from list_files(ff)
		except:
			yield f'{ff}\t{os.stat(ff)[6]}\n'

def isDir(path):
	try:
		os.listdir(path)
		return True
	except:
		return False

def deleteFile(path):
	try:
		os.rmdir(path) if isDir(path) else os.remove(path)
		return 'OK'
	except Exception as e:
		return str(e)

def set_true(vn):
	exec(f'{vn}=True')
	return 'OK'

class MWebServer:
	def __init__(self, host='0.0.0.0', captivePortalIP='', port=80, max_conn=8):
		self.N = 0
		routeHandlers = [
			( "/", "GET", lambda *_: f'Hello world!' ),
			( "/wifi_restart", "GET", lambda *_: set_true('g_restartWifi') ),
			( "/wifi_save", "POST", lambda clie, resp: 'Save OK' if save_file('secret.py', clie.YieldRequestContent()) else 'Save failed' ),
			( "/wifi_load", "GET", lambda clie, resp: resp.WriteResponseFile('secret.py')),
			( "/reboot", "GET", lambda *_: set_true('g_reboot') ),
			( "/rc_record", "GET", lambda *_: str(rc.recv()) ),
			( "/rc_emit", "POST", lambda cli, *arg: str(rc.send(cli.ReadRequestContent())) ),
			( "/rc_save", "POST", lambda clie, resp: 'Save OK' if save_file('rc-codes.txt', clie.YieldRequestContent()) else 'Save failed' ),
			( "/rc_load", "GET", lambda clie, resp: resp.WriteResponseFile('rc-codes.txt') ),
			( "/list_files", "GET", lambda clie, resp: resp.WriteResponseFile(list_files()) ),
			( "/delete_files", "GET", lambda clie, resp: deleteFile(clie.GetRequestQueryString()) ),
			( "/get_file", "GET", lambda clie, resp: resp.WriteResponseFileAttachment(clie.GetRequestQueryString()) ),
		]
		self.app = MWS(routeHandlers=routeHandlers, port=port, bindIP='0.0.0.0', webPath="/static")
		self.sock_web = self.app.run(max_conn=max_conn, loop_forever=False)
		self.poll = select.poll()
		self.poll.register(self.sock_web, select.POLLIN)
		self.uart = machine.UART(0, 115200, tx=machine.Pin(15), rx=machine.Pin(13))	# swap UART0 to alternative ports to avoid interference from CH340
		self.poll.register(sys.stdin, select.POLLIN)
		self.poll.register(self.uart, select.POLLIN)
		self.sock_map = {id(self.sock_web): self.app.run_once, id(sys.stdin): self.handleRC_stdin, id(self.uart): self.handleRC}
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

	def execRC(self, s):
		prt(f'execRC:{s}')
		if s is None: return
		try:
			if type(s)==list:
				for i in s:
					self.execRC(i)
					gc.collect()
			elif type(s)==str:
				if s.startswith('http'):
					url.get(s).close()
				else:
					code = get_rc_code(s)
					if code is not None:
						self.execRC(code)
			elif type(s)==dict:
				rc.send(s)
		except:
			pass

	def handleRC(self):
		key = self.uart.readline().strip()
		prt(f'RX received {key}')
		code = get_rc_code(key)
		self.execRC(code)
		flashLED(0.1)

	def handleRC_stdin(self):
		key = sys.stdin.readline().strip()
		prt(f'RX received {key}')
		code = get_rc_code(key)
		self.execRC(code)
		flashLED(0.1)

	def run(self):
		global g_reboot, g_restartWifi
		while True:
			for tp in self.poll.poll():
				self.sock_map[id(tp[0])]()
				gc.collect()
			if g_reboot:
				machine.reset()
			if g_restartWifi:
				g_restartWifi = False
				sta_if.disconnect()
				sta_if.active(False)
				ap_if.active(False)
				time.sleep(1)
				start_wifi()


gc.collect()

### MAIN function
def run():
	try:
		cpIP = start_wifi()
		prt(wifi)
		server = MWebServer(captivePortalIP=cpIP)
		server.run()
	except:
		machine.UART(0, 115200, tx=machine.Pin(1), rx=machine.Pin(3))
