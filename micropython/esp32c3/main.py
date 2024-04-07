import os, sys, gc, machine, network, socket, select, time, random, esp
import urequests as url
from array import array
from time import ticks_us, ticks_diff
from math import sqrt
from microWebSrv import MicroWebSrv as MWS
from machine import Pin, UART, PWM, ADC, reset, reset_cause
gc.collect()


# Global variables
RCFILE = 'rc-codes.txt'

PIN_RF_IN = ''	# GPIO5 tested working
PIN_RF_OUT = ''	# GPIO4 tested working
PIN_IR_IN = ''	# GPIO14 tested working
PIN_IR_OUT = ''	# GPIO12 tested working
PIN_ASR_IN = ''	# GPIO 13 or 3: generic ASR chip sending UART output upon voice commands
PIN_LD1115H = ''	# GPIO 13 or 3: HLK-LD1115H motion sensor
PIN_DEBUG_LED = ''	# only GPIO 2 or None: for debug blinking
use_BLE = False

# Namespace for global variable
import lib_common as g
from lib_common import *

wifi = {}

read_py_obj = lambda f: Try(lambda: eval(open('secret.py').read()), '')

def connect_wifi():
	global wifi, sta_if
	if sta_if.active():
		sta_if.disconnect()
		sta_if.active(False)
		time.sleep(1)
	try:
		cred = read_py_obj('secret.py')
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
	global wifi, ap_if
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
	syncNTP()
	return ''

def build_rc():
	if not isFile(RCFILE):
		open(RCFILE, 'w').close()
	fp = open(RCFILE)
	g.rc_set = ' '
	while True:
		L = fp.readline()
		if not L:break
		g.rc_set += L.split('\t')[0]+' '
		del L
	fp.close()

def get_rc_code(key):
	if f' {key} ' not in g.rc_set:
		return None
	try:
		fp = open(RCFILE)
		for L in fp:
			gc.collect()
			its = L.split('\t')
			if key == its[0]:
				fp.close()
				return eval(its[-1])
		fp.close()
	except Exception as e:
		prt(e)
	return None

def save_file(fn, gen):
	try:
		fp = open(fn, 'wb')
		for L in gen:
			fp.write(L)
			gc.collect()
		fp.close()
		del fp
		if fn==RCFILE:
			build_rc()
		gc.collect()
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
	
def isFile(fn):
	try:
		open(fn).close()
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

def run_python(obj):
	try:
		exec(open(obj['filename']).read(), globals(), globals())
		gc.collect()
		return 'OK'
	except Exception as e:
		return str(e)

def run_module(obj):
	try:
		mod_name = obj['filename'].split('.')[0]
		env = {}
		exec(f'from {mod_name} import *', env, env)
		res = eval(obj['cmd'], env, env)
		del env, mod_name
		gc.collect()
		return res
	except Exception as e:
		return str(e)

def execRC(s):
	if type(s)==bytes:
		s = s.decode()
	prt(f'execRC:{str(s)}')
	if s is None: return 'OK'
	try:
		if type(s) == list:
			res = []
			for i in s:
				res += [execRC(i)]
				gc.collect()
			return '\r\n'.join(res)
		elif type(s)==str:
			if s.startswith('http'):
				url.get(url_encode(s),timeout=5).close()
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
			elif p=='BLE':
				return ble_task(s)
			elif p=='PY':
				return run_python(s)
			elif p=='MOD':
				return run_module(s)

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

asr_write = lambda t: Try(lambda: f'{g.server.uart_ASR_out.write(bytes.fromhex(t))} bytes sent')
asr_print = lambda t: Try(lambda: [print(t, file=g.server.uart_ASR_out), 'message sent'][-1])

class WebServer:
	def __init__(self, host='0.0.0.0', captivePortalIP='', port=80, max_conn=0):
		self.cmd = ''
		routeHandlers = [
			( "/", "GET", lambda clie, resp: resp.WriteResponseFile('/static/hub.html', "text/html") ),
			( "/status", "GET", lambda clie, resp: resp.WriteResponseJSONOk({
				'datetime': getFullDateTime(),
				'heap_free': gc.mem_free(),
				'stack_free': Try(lambda: esp.freemem()),
				'flash_size': esp.flash_size(),
				'g.timezone': g.timezone,
				'g.DEBUG': g.DEBUG,
				'g.SAVELOG': g.SAVELOG,
				'g.LOGFILE': g.LOGFILE,
				'g.SMART_CTRL': g.SMART_CTRL,
				'LD1115H': g.LD1115H.status() if hasattr(g, 'LD1115H') else None,
				'PIN_RF_IN': PIN_RF_IN,
				'PIN_RF_OUT': PIN_RF_OUT,
				'PIN_IR_IN': PIN_IR_IN,
				'PIN_IR_OUT': PIN_IR_OUT,
				'PIN_ASR_IN': PIN_ASR_IN,
				'PIN_LD1115H': PIN_LD1115H,
				'PIN_DEBUG_LED': PIN_DEBUG_LED,
				}) ),
			( "/hello", "GET", lambda *_: f'Hello world!' ),
			( "/exec", "GET", lambda clie, resp: Exec(clie.GetRequestQueryString(True)) ),
			( "/eval", "GET", lambda clie, resp: Eval(clie.GetRequestQueryString(True)) ),
			( "/wifi_restart", "GET", lambda *_: self.set_cmd('restartWifi') ),
			( "/wifi_save", "POST", lambda clie, resp: save_file('secret.py', clie.YieldRequestContent()) ),
			( "/wifi_load", "GET", lambda clie, resp: resp.WriteResponseJSONOk(read_py_obj('secret.py')) ),
			( "/reboot", "GET", lambda *_: self.set_cmd('reboot') ),
			( "/rf_record", "GET", lambda clie, resp: resp.WriteResponseJSONOk(rfc.recv()) ),
			( "/ir_record", "GET", lambda clie, resp: resp.WriteResponseJSONOk(irc.recv()) ),
			( "/rc_run", "GET", lambda cli, *arg: execRC(cli.GetRequestQueryString(True))),
			( "/rc_exec", "POST", lambda cli, *arg: execRC(cli.ReadRequestContent())),
			( "/rc_save", "POST", lambda clie, resp: save_file(RCFILE, clie.YieldRequestContent()) ),
			( "/rc_load", "GET", lambda clie, resp: resp.WriteResponseFile(RCFILE) ),
			( "/list_files", "GET", lambda clie, resp: resp.WriteResponseYield(list_files()) ),
			( "/delete_files", "GET", lambda clie, resp: deleteFile(clie.GetRequestQueryString(True)) ),
			( "/mkdir", "GET", lambda clie, resp: mkdir(clie.GetRequestQueryString(True)) ),
			( "/get_file", "GET", lambda clie, resp: resp.WriteResponseFileAttachment(clie.GetRequestQueryString(True)) ),
			( "/upload_file", "POST", lambda clie, resp: save_file(clie.GetRequestQueryString(True), clie.YieldRequestContent()) ),
			( "/asr_write", "GET", lambda clie, resp: asr_write(clie.GetRequestQueryString(True)) ),
			( "/asr_print", "GET", lambda clie, resp: asr_print(clie.GetRequestQueryString(True)) ),
		]
		self.mws = MWS(routeHandlers=routeHandlers, port=port, bindIP='0.0.0.0', webPath="/static")
		self.sock_web = self.mws.run(max_conn=max_conn, loop_forever=False)
		self.poll = select.poll()
		self.poll.register(self.sock_web, select.POLLIN)
		self.poll_tmout = -1
		set_uart = lambda p: (sys.stdin, sys.stdout) if p==20 else (UART(1, 115200, tx=0, rx=1) if p==1 else None,)*2
		self.uart_ASR, self.uart_ASR_out = set_uart(PIN_ASR_IN)
		self.uart_LD1115H, self.uart_LD1115H_out = set_uart(PIN_LD1115H)
		self.sock_map = {self.sock_web: self.mws.run_once}
		self.cpIP = captivePortalIP
		if captivePortalIP:
			self.sock_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.sock_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.sock_dns.bind((captivePortalIP, 53))
			self.poll.register(self.sock_dns, select.POLLIN)
			self.sock_map[self.sock_dns] = self.handleDNS
		else:
			self.sock_dns = None

		if not g.SMART_CTRL:
			return
		if self.uart_ASR != None:
			self.poll.register(self.uart_ASR, select.POLLIN)
			self.sock_map[self.uart_ASR] = self.handleASR
		if self.uart_LD1115H != None:
			g.LD1115H = LD1115H(self.mws, self.uart_LD1115H)
			self.poll_tmout = 1
			self.poll.register(self.uart_LD1115H, select.POLLIN)
			self.sock_map[self.uart_LD1115H] = g.LD1115H.handleUART

	def handleASR(self):
		key = self.uart_ASR.readline().strip()
		key = key.decode() if type(key)==bytes else key
		prt(f'RX-ASR received {key}')
		code = get_rc_code(key)
		execRC(code)
		flashLED()

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
			now = time.time()
			dlist = []
			poll_tmout = self.poll_tmout
			for tn,tm in g.Timers.items():
				diff = now-tm[0]-tm[1]
				if diff>=0:
					try:
						tm[3]()
					except Exception as e:
						prt(e)
					if tm[2]:
						tm[0] = now
					else:
						dlist += [tn]
					poll_tmout = tm[1] if poll_tmout<0 else min(poll_tmout, tm[1])
				else:
					poll_tmout = abs(diff) if poll_tmout<0 else min(poll_tmout, abs(diff))
			for tn in dlist:
				del g.Timers[tn]
			tps = self.poll.poll(poll_tmout*1000)
			for tp in tps:
				self.sock_map[tp[0]]()
				gc.collect()
				time.sleep(0.1)
				if self.cmd=='reboot':
					machine.reset()
				elif self.cmd=='restartWifi':
					start_wifi()
				elif self.cmd:
					execRC(self.cmd)
				self.cmd = ''
			if type(PIN_LD1115H)==int:
				g.LD1115H.run1()

# Globals
build_rc()
gc.collect()
if '__init__' in g.rc_set:
	execRC('__init__')

MWS.DEBUG = g.DEBUG
if type(PIN_DEBUG_LED) != int:
	flashLED=lambda **kw:None
else:
	digitalWrite(PIN_DEBUG_LED, 1)
	def flashLED(intv=0.1, N=3):
		for i in range(N):
			digitalWrite(PIN_DEBUG_LED, 1)
			time.sleep(intv)
			digitalWrite(PIN_DEBUG_LED, 0)
			time.sleep(intv)

gc.collect()

if use_BLE:
	from lib_BLE import *
if type(PIN_ASR_IN) == int:
	from lib_TCPIP import *
if type(PIN_LD1115H) == int:
	from lib_LD1115H import *
if int in [type(i) for i in [PIN_RF_IN, PIN_RF_OUT, PIN_IR_IN, PIN_IR_OUT]]:
	from lib_RC import *
if type(PIN_RF_IN)==int or type(PIN_RF_OUT)==int:
	rfc = RF433RC(PIN_RF_IN, PIN_RF_OUT)
if type(PIN_IR_IN)==int or type(PIN_IR_OUT)==int:
	irc = IRRC(PIN_IR_IN, PIN_IR_OUT)

### MAIN function
def run():
	cpIP = start_wifi()
	prt(wifi)
	g.server = WebServer(captivePortalIP=cpIP)
	if '__postinit__' in g.rc_set:
		execRC('__postinit__')
	if type(PIN_DEBUG_LED) == int:
		digitalWrite(PIN_DEBUG_LED, 0)
	SetTimer('syncNTP', 12*3600, True, syncNTP)
	g.server.run()

gc.collect()

if not isFile('debug') or reset_cause()==1:
	run()
	reset()