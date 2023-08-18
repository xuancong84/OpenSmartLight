import os, sys, gc, machine, network, socket, select, time, random
import urequests as url
from array import array
from time import ticks_us, ticks_diff
from math import sqrt
from microWebSrv import MicroWebSrv as MWS
from machine import Pin, UART, PWM, ADC
gc.collect()


# Global variables
PIN_RF_IN = None
PIN_RF_OUT = None
PIN_IR_IN = None
PIN_IR_OUT = None
PIN_ASR_IN = None	# generic ASR chip sending UART output upon voice commands
PIN_LD1115H = None	# HLK-LD1115H motion sensor
RCFILE = 'rc-codes.txt'

# For analog sensors
PIN_COMMON_PULLUP = None
PIN_PHOTORES_GND = None
PIN_THERMAL_GND = None
A0 = ADC(0)

# Namespace for global variable
import lib_common as g
from lib_common import *

if DEBUG:
	Pin(2, Pin.OUT)(0)

wifi = {}


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
	setNTP()
	return ''

def build_rc():
	g.rc_set = ' '+' '.join([L.split('\t')[0] for L in open(RCFILE)])+' '
	gc.collect()

def get_rc_code(key):
	if f' {key} ' not in g.rc_set:
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

def mkdir(path):
	try:
		os.mkdir(path)
		return 'OK'
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
			elif p=='CAP':
				return send_cap(s)
	except Exception as e:
		prt(e)
		return str(e)
	return str(s)

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
			( "/mkdir", "GET", lambda clie, resp: mkdir(clie.GetRequestQueryString()) ),
			( "/get_file", "GET", lambda clie, resp: resp.WriteResponseFileAttachment(clie.GetRequestQueryString()) ),
			( "/upload_file", "POST", lambda clie, resp: save_file(clie.GetRequestQueryString(), clie.YieldRequestContent()) ),
		]
		self.app = MWS(routeHandlers=routeHandlers, port=port, bindIP='0.0.0.0', webPath="/static")
		self.sock_web = self.app.run(max_conn=max_conn, loop_forever=False)
		self.poll = select.poll()
		self.poll.register(self.sock_web, select.POLLIN)
		self.poll_tmout = -1
		if PIN_ASR_IN == 13 or PIN_LD1115H == 13:
			UART(0, 115200, tx=Pin(15), rx=Pin(13))	# swap UART0 to alternative ports to avoid interference from CH340
		self.sock_map = {id(self.sock_web): self.app.run_once}
		if PIN_ASR_IN != None:
			self.poll.register(sys.stdin, select.POLLIN)
			self.sock_map[id(sys.stdin)] = self.handleASR
		elif PIN_LD1115H != None:
			self.ld1115h = LD1115H(PIN_LD1115H)
			self.poll_tmout = 1000
			self.poll.register(sys.stdin, select.POLLIN)
			self.sock_map[id(sys.stdin)] = self.ld1115h.handleUART
		self.cpIP = captivePortalIP

		if captivePortalIP:
			self.sock_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.sock_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.sock_dns.bind((captivePortalIP, 53))
			self.poll.register(self.sock_dns, select.POLLIN)
			self.sock_map[id(self.sock_dns)] = self.handleDNS
		else:
			self.sock_dns = None

	def handleASR(self):
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
			tps = self.poll.poll(self.poll_tmout)
			if not tps:
				self.ld1115h.run1()
			for tp in tps:
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
if ' __init__ ' in g.rc_set:
	execRC('__init__')

if PIN_ASR_IN != None:
	from lib_TCPIP import *
if PIN_LD1115H != None:
	from lib_LD1115H import *
if [PIN_RF_IN, PIN_RF_OUT, PIN_IR_IN, PIN_IR_OUT].count(None) != 4:
	from lib_RC import *
if PIN_RF_IN!=None or PIN_RF_OUT!=None:
	rfc = RF433RC(PIN_RF_IN, PIN_RF_OUT)
if PIN_IR_IN!=None or PIN_IR_OUT!=None:
	irc = IRRC(PIN_IR_IN, PIN_IR_OUT)
if PIN_COMMON_PULLUP != None:
	Pin(PIN_COMMON_PULLUP, Pin.IN, Pin.PULL_UP)
if PIN_PHOTORES_GND != None:
	Pin(PIN_PHOTORES_GND, Pin.IN)
if PIN_THERMAL_GND != None:
	Pin(PIN_THERMAL_GND, Pin.IN)
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
		if PIN_ASR_IN==13:
			UART(0, 115200, tx=Pin(1), rx=Pin(3))
		prt(e)
