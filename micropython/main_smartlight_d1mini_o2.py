import os, sys, gc, machine, network, socket, select, time, random, ntptime
import urequests as url
from array import array
from time import ticks_us, ticks_diff
from math import sqrt
from microWebSrv import MicroWebSrv as MWS
from machine import Pin, UART
gc.collect()

PIN_RF_IN = None
PIN_RF_OUT = None
PIN_IR_IN = None
PIN_IR_OUT = None
DEBUG = False
SAVELOG = False
RCFILE = 'rc-codes.txt'
LOGFILE = 'static/log.txt'
timezone = 8

LED = Pin(2, Pin.OUT)
LED(0)

class dummy:pass
g = dummy()
g.DL = g.SL = g.PL = g.ML = 0

def flashLED(intv=0.25):
	for i in range(3):
		LED(0)
		time.sleep(intv)
		LED(1)
		time.sleep(intv)

wifi = {}

def getTimeString(tm=None):
	tm = tm or time.localtime(time.time()+3600*timezone)
	return '%02d:%02d:%02d'%(tm[3],tm[4],tm[5])

def getDateString(tm, showDay=True):
	ds = "%04d-%02d-%02d"%(tm[0],tm[1],tm[2])
	return ds if showDay else ds[:-3]

weekDays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
def getWeekdayString(tm):
	return weekDays[tm[6]]

def getFullDateTime():
	tm = time.localtime(time.time()+3600*timezone)
	return getDateString(tm)+" ("+getWeekdayString(tm)+") "+getTimeString(tm)

def prt(*args, **kwarg):
	if DEBUG:
		print(getFullDateTime(), end=' ')
		print(*args, **kwarg)
	if SAVELOG and LOGFILE:
		try:
			if os.stat(LOGFILE)[6]>1000000:
				os.remove(LOGFILE)
		except:
			pass
		with open(LOGFILE, 'a') as fp:
			print(getFullDateTime(), end=' ', file=fp)
			print(*args, **kwarg, file=fp)

def connect_wifi():
	global wifi
	sta_if = network.WLAN(network.STA_IF)
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
	ap_if = network.WLAN(network.AP_IF)
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
	ntptime.settime()
	return ''


class RC():
	def __init__(self, rx_pin, tx_pin, nedges, nrepeat, min_nframes, gap_tol, recv_dur, proto={}):  # Typically ~15 frames
		self.rx_pin = None if rx_pin==None else Pin(rx_pin, Pin.IN, Pin.PULL_UP)
		self.tx_pin = None if tx_pin==None else Pin(tx_pin, Pin.OUT)
		if self.tx_pin != None:
			self.tx_pin(0)	# turn off radio
		self.nedges = nedges
		self.nrepeat = nrepeat
		self.min_nframes = min_nframes
		self.gap_tol = gap_tol
		self.recv_dur = recv_dur
		self.proto = proto
		gc.collect()

	def recv(self):
		prt('Receiving RC data ...')
		gc.collect()
		nedges = self.nedges
		p = self.rx_pin
		arr = array('I',  [0]*nedges)

		# ** Time critical **
		cur_freq = machine.freq()
		machine.freq(160000000)
		st_irq = machine.disable_irq()
		tm_til = ticks_us()+self.recv_dur
		init_level = v = p()
		for x in range(nedges):
			while v == p() and ticks_us()<tm_til: pass
			arr[x] = ticks_us()
			if arr[x]>tm_til: break
			v = p()
		machine.enable_irq(st_irq)
		machine.freq(cur_freq)
		# ** End of time critical **

		if x <= self.min_nframes*2:
			return 'No signal received'
		nedges = x
		arr = arr[:nedges]
		gc.collect()

        # Compute diffs
		for x in range(nedges-1, 0, -1):
			arr[x] = ticks_diff(arr[x], arr[x-1])
		arr[0] = 0
		arr[0] = max(arr)

		# Extract segments
		gap = round(arr[0]*self.gap_tol)
		gap_pos = [0]+[i for i,v in enumerate(arr) if v>=gap]+[nedges]
		if len(gap_pos) < self.min_nframes:
			return f'Too few frames {len(gap_pos)}'
		segs = [arr[gap_pos[i-1]:gap_pos[i]] for i in range(1, len(gap_pos))]
		del arr

		lengths = [len(x) for x in segs]
		prt(f'Received data size = {nedges}, segment lengths: {lengths}') #DEBUG

		# Select segments with most common frame length
		cnter = {x:lengths.count(x) for x in set(lengths)}
		cnt_max = max(cnter.values())
		len_most = [i for i,j in cnter.items() if j==cnt_max][0]
		N_old = len(segs)
		seg0id = [ii for ii,seg in enumerate(segs) if len(seg)==len_most][0]
		segs = [seg for seg in segs if len(seg)==len_most]
		init_level = 1-init_level if (gap_pos[seg0id]&1) else init_level
		N_new = len(segs)

		if N_new < self.min_nframes:
			return f'Too few selected frames: {N_new}'
		
		if N_old != N_new:
			prt('Deleted {} frames of different length'.format(N_old - N_new))

		prt(f'Averaging {N_new} frames')
		m = [sum(x)/N_new for x in zip(*segs)]	# compute mean
		for seg in segs:	# ignore STD due to gaps difference, clam gap duration to 0.2 sec
			m[0] = seg[0] = min(m[0], 100000)
		std = [sqrt(sum([(y - m[i])**2 for y in x])/N_new) for i, x in enumerate(zip(*segs))]
		del segs
		prt('Capture quality {:5.1f} (0: perfect)'.format(sum(std)/len(std)))
		ret = {'init_level':init_level, 'data':list(map(round, m))}
		ret.update(self.proto)
	
		return ret

	def send(self, obj):
		if 'fPWM' in obj:
			return self.sendPWM(obj)
		
		gc.collect()

		try:
			init_level, arr = obj['init_level'], obj['data']
		except Exception as e:
			prt(e)
			return str(e)
		
		prt('Sending RC data ...')
		p = self.tx_pin

		# ** Time critical **
		st_irq = machine.disable_irq()
		for i in range(self.nrepeat):
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
		return 'OK'

	def sendPWM(self, obj):
		gc.collect()

		try:
			init_level, arr, fPWM = obj['init_level'], obj['data'], int(obj['fPWM'])
		except Exception as e:
			prt(e)
			return str(e)
		
		prt('Sending PWM data ...')
		cur_freq = machine.freq()
		machine.freq(160000000)
		p = machine.PWM(self.tx_pin, fPWM, 0)

		# ** Time critical **
		for i in range(self.nrepeat):
			level = init_level<<9
			p.duty(level)
			while not self.tx_pin():pass
			tm_til = ticks_us()
			for dt in arr:
				tm_til += dt
				level = 512-level
				while ticks_us()<tm_til: pass
				p.duty(level)
		# ** End of time critical **

		p.duty(0)	# turn off signal
		p.deinit()
		machine.freq(cur_freq)
		return 'OK'


# For RF 433MHz remote controller
class RF433RC(RC):
	def __init__(self, rx_pin=None, tx_pin=None, nedges=800, nrepeat=5, min_nframes=5, recv_dur=3000000, gap_tol=0.8):
		super().__init__(rx_pin, tx_pin, nedges, nrepeat, min_nframes, gap_tol, recv_dur, proto={'protocol':'RF433'})

# For infrared remote controller
class IRRC(RC):
	def __init__(self, rx_pin=None, tx_pin=None, nedges=600, nrepeat=1, min_nframes=2, recv_dur=5000000, gap_tol=0.5):
		super().__init__(rx_pin, tx_pin, nedges, nrepeat, min_nframes, gap_tol, recv_dur, proto={'protocol':'IRRC', 'fPWM':43000})

def build_rc():
	g.rc_set = set()
	for L in open(RCFILE):
		its = L.split('\t')
		g.rc_set.add(its[0])
		gc.collect()

def get_rc_code(key):
	if key not in g.rc_set:
		return None
	try:
		with open(RCFILE) as fp:
			for L in fp:
				gc.collect()
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
		if fn==RCFILE:
			build_rc()
		return 'Save OK'
	except Exception as e:
		prt(e)
		return str(e)
	
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

@MWS.Route('/move_file', 'POST')
def move_file(clie, resp):
	try:
		src, dst = clie.ReadRequestContent().decode().split('\n')[:2]
		if isDir(dst):
			dst += src.rstrip('/').split('/')[-1]
		os.rename(src, dst)
		return f'OK, moved {src} to {dst}'
	except Exception as e:
		prt(e)
		return str(e)

def deleteFile(path):
	try:
		os.rmdir(path) if isDir(path) else os.remove(path)
		return 'Delete OK'
	except Exception as e:
		return str(e)

def send_tcp(obj):
	try:
		s = socket.socket()
		s.connect((obj['IP'], obj['PORT']))
		s.sendall(obj['data'])
		s.recv(obj.get('recv_size', 256))
		s.close()
		return f'OK, sent {len(obj["data"])} bytes'
	except Exception as e:
		prt(e)
		return str(e)

def send_udp(obj):
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		nsent = s.sendto(obj['data'], (obj['IP'], obj['PORT']))
		s.close()
		return f'OK, sent {nsent} bytes'
	except Exception as e:
		prt(e)
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
		prt(e)
		return str(e)

def send_cap(fn):
	s = None
	with open(fn, 'rb') as fp:
		for L in fp:
			L = L.strip()
			if L.startswith(b'{'):
				obj = eval(L)
				del L
				gc.collect()
				s = socket.socket()
				s.connect((obj['IP'], obj['PORT']))
				if 'data' in obj:
					s.sendall(obj['data'])
			elif L.startswith(b'b'):
				s.sendall(eval(L))
				del L
			elif L.isdigit():
				s.recv(int(L)*2)
			gc.collect()
	try:
		s.close()
	except Exception as e:
		return str(e)


def execRC(s):
	if type(s)==bytes:
		s = s.decode()
	prt(f'execRC:{str(s)}')
	if s is None: return 'OK'
	try:
		if type(s) in [list, tuple, set]:
			res = []
			for i in s:
				res += [execRC(i)]
				gc.collect()
			return '\r\n'.join(res)
		elif type(s)==str:
			if s.startswith('http'):
				url.get(s).close()
			else:
				code = get_rc_code(s)
				return execRC(eval(s) if code==None else code)
		elif type(s)==dict:
			p = s.get('protocol', 'RF433')
			prt(p, s)
			if p=='RF433':
				return rfc.send(s)
			elif p=='IRRC':
				return irc.send(s)
			elif p=='TCP':
				return send_tcp(s)
			elif p=='UDP':
				return send_udp(s)
			elif p=='WOL':
				return send_wol(s)
			elif p=='FILE':
				return send_cap(s['filename'])
			else:
				return 'Unknown protocol'
	except Exception as e:
		prt(e)
		return str(e)
	return f'Unknown command {str(s)}'

def Exec(cmd):
	try:
		exec(cmd, globals(), globals())
		return 'OK'
	except Exception as e:
		return str(e)
	
def Eval(cmd):
	try:
		return eval(cmd, globals(), globals())
	except Exception as e:
		return str(e)

class MWebServer:
	def __init__(self, host='0.0.0.0', captivePortalIP='', port=80, max_conn=8):
		self.cmd = ''
		routeHandlers = [
			( "/", "GET", lambda clie, resp: resp.WriteResponseFile('/static/hub.html', "text/html") ),
			( "/hello", "GET", lambda *_: f'Hello world!' ),
			( "/setv", "GET", lambda clie, resp: Exec(clie.GetRequestQueryString()) ),
			( "/getv", "GET", lambda clie, resp: Eval(clie.GetRequestQueryString()) ),
			( "/wifi_restart", "GET", lambda *_: self.set_cmd('restartWifi') ),
			( "/wifi_save", "POST", lambda clie, resp: save_file('secret.py', clie.YieldRequestContent()) ),
			( "/wifi_load", "GET", lambda clie, resp: resp.WriteResponseFile('secret.py')),
			( "/reboot", "GET", lambda *_: self.set_cmd('reboot') ),
			( "/rf_record", "GET", lambda *_: str(rfc.recv()) ),
			( "/ir_record", "GET", lambda *_: str(irc.recv()) ),
			( "/rc_run", "GET", lambda cli, *arg: execRC(cli.GetRequestQueryString())),
			( "/rc_exec", "POST", lambda cli, *arg: execRC(cli.ReadRequestContent())),
			( "/rc_save", "POST", lambda clie, resp: save_file(RCFILE, clie.YieldRequestContent()) ),
			( "/rc_load", "GET", lambda clie, resp: resp.WriteResponseFile(RCFILE) ),
			( "/list_files", "GET", lambda clie, resp: resp.WriteResponseFile(list_files()) ),
			( "/delete_files", "GET", lambda clie, resp: deleteFile(clie.GetRequestQueryString()) ),
			( "/get_file", "GET", lambda clie, resp: resp.WriteResponseFileAttachment(clie.GetRequestQueryString()) ),
			( "/upload_file", "POST", lambda clie, resp: save_file(clie.GetRequestQueryString(), clie.YieldRequestContent()) ),
		]
		self.app = MWS(routeHandlers=routeHandlers, port=port, bindIP='0.0.0.0', webPath="/static")
		self.sock_web = self.app.run(max_conn=max_conn, loop_forever=False)
		self.poll = select.poll()
		self.poll.register(self.sock_web, select.POLLIN)
		UART(0, 115200, tx=Pin(15), rx=Pin(13))	# swap UART0 to alternative ports to avoid interference from CH340
		self.poll.register(sys.stdin, select.POLLIN)
		self.sock_map = {
			id(self.sock_web): self.app.run_once, 
			id(sys.stdin): self.handleRC,
		}
		self.cpIP = captivePortalIP

		if captivePortalIP:
			self.sock_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.sock_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.sock_dns.bind((captivePortalIP, 53))
			self.poll.register(self.sock_dns, select.POLLIN)
			self.sock_map[id(self.sock_dns)] = self.handleDNS
		else:
			self.sock_dns = None

	def handleRC(self):
		key = sys.stdin.readline().strip()
		prt(f'RX received {key}')
		code = get_rc_code(key)
		execRC(code)
		flashLED(0.1)

	def set_cmd(self, vn):
		prt(f'Setting cmd to :{vn}')
		self.cmd = vn
		return 'OK'

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
				time.sleep(0.1)
				if self.cmd=='reboot':
					machine.reset()
				elif self.cmd=='restartWifi':
					start_wifi()
				elif self.cmd:
					execRC(self.cmd)
				self.cmd = ''

# Globals
if PIN_RF_IN!=None or PIN_RF_OUT!=None:
	rfc = RF433RC(PIN_RF_IN, PIN_RF_OUT)
if PIN_IR_IN!=None or PIN_IR_OUT!=None:
	irc = IRRC(PIN_IR_IN, PIN_IR_OUT)
gc.collect()

### MAIN function
def run():
	try:
		cpIP = start_wifi()
		prt(wifi)
		server = MWebServer(captivePortalIP=cpIP)
		build_rc()
		LED(1)
		server.run()
	except Exception as e:
		UART(0, 115200, tx=Pin(1), rx=Pin(3))
		prt(e)
