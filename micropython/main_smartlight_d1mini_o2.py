import os, sys, gc, machine, network, socket, select, time, random, ntptime
import urequests as url
from array import array
from time import ticks_us, ticks_diff
from math import sqrt
from microWebSrv import MicroWebSrv as MWS
from machine import Pin, UART, PWM, ADC
gc.collect()

# namespace for global variable
class dummy:pass
g = dummy()

PIN_RF_IN = None
PIN_RF_OUT = None
PIN_IR_IN = None
PIN_IR_OUT = None
PIN_EXT_IN = None
A0 = ADC(0)
DEBUG = False
SAVELOG = False
RCFILE = 'rc-codes.txt'
LOGFILE = 'static/log.txt'
timezone = 8

if DEBUG:
	Pin(2, Pin.OUT)(0)

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

def build_rc():
	g.rc_set = set([L.split('\t')[0] for L in open(RCFILE)])
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
			( "/exec", "GET", lambda clie, resp: Exec(clie.GetRequestQueryString()) ),
			( "/eval", "GET", lambda clie, resp: Eval(clie.GetRequestQueryString()) ),
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
		if PIN_EXT_IN == 13:
			UART(0, 115200, tx=Pin(15), rx=Pin(13))	# swap UART0 to alternative ports to avoid interference from CH340
		self.sock_map = {id(self.sock_web): self.app.run_once}
		if PIN_EXT_IN != None:
			self.poll.register(sys.stdin, select.POLLIN)
			self.sock_map[id(sys.stdin)] = self.handleRC
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
build_rc()
if '__init__' in g.rc_set:
	execRC('__init__')

if PIN_RF_IN!=None or PIN_RF_OUT!=None or PIN_IR_IN!=None or PIN_IR_OUT!=None:
	from lib_RC import *
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
		if DEBUG:
			Pin(2, Pin.OUT)(1)
		server.run()
	except Exception as e:
		if PIN_EXT_IN==13:
			UART(0, 115200, tx=Pin(1), rx=Pin(3))
		prt(e)
