import os, sys, esp, gc, uping, network, random
import machine, time, ntptime, select, socket
from microWebSrv import MicroWebSrv as MWS
from machine import Pin, UART

gc.collect()

# constant definitions
PIN_LED_BUILTIN = Pin(2, machine.Pin.OUT)
PIN_LED_BUILTIN(0)
PIN_CONTROL_OUTPUT = Pin(4, machine.Pin.OUT)
PIN_MOTION_SENSOR = Pin(0, machine.Pin.OUT)
PIN_LED_MASTER = Pin(5, machine.Pin.OUT)
PIN_LED_ADJ = Pin(14, machine.Pin.OUT)
PIN_AMBIENT_PULLUP = Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)
PIN_AMBIENT_INPUT = machine.ADC(0)
SENSOR_LOG_MAX = 120
LOGFILE_MAX_SIZE = 200000
LOGFILE_MAX_NUM = 8
WIFI_NAME = "OpenSmartLight"
UDP_PORT = 18888      # for LAN broadcast and inform own existence
TEST_ALIVE = 1000000
DEBUG = False
SAVELOG = False
RCFILE = 'rc-codes.txt'
LOGFILE = 'static/log.txt'
wifi = {}

# Saved parameters
saved = {
	'nodename': "SmartNode01",
	'timezone': 8,
	'DARK_TH_LOW': 960,
	'DARK_TH_HIGH': 990,
	'DELAY_ON_MOV': 30000,
	'DELAY_ON_OCC': 20000,
	'OCC_TRIG_TH': 65530,
	'OCC_CONT_TH': 600,
	'MOV_TRIG_TH': 400,
	'MOV_CONT_TH': 250,
	'LED_BEGIN': 100,
	'LED_END': 125,
	'GLIDE_TIME': 800,
	'wifi_IP': getattr(cred, 'WIFI_IP', ''),
	'wifi_subnet': getattr(cred, 'WIFI_SUBNET', ''),
	'wifi_gateway': getattr(cred, 'WIFI_GATEWAY', ''),
	'wifi_DNS': getattr(cred, 'WIFI_DNS', ''),
	'wifi_ssid': getattr(cred, 'WIFI_SSID', ''),
	'wifi_password': getattr(cred, 'WIFI_PASSWORD', ''),
	'midnight_starts': ["23:00", "23:00", "23:00", "23:00", "00:00", "00:00", "23:00"],
	'midnight_stops': ["07:00", "07:00", "07:00", "07:00", "07:00", "07:00", "07:00"]
}

# Unsaved state parameter
g_nodeList, g_nodeLastPing = {}, {}
ambient_level = 0
onboard_led_level = 0
is_dark_mode = False
is_smartlight_on = False
onboard_led = False
motion_sensor = False
control_output = False
DEBUG = True
SYSLED = False
sensor_log = svr_reply = params_hash = ''

fp_hist = None
do_glide = 0
reboot = False
restart_wifi = False
update_ntp = False
reset_wifi = False
tm_last_ambient = 0
tm_last_timesync = 0
tm_last_debugon = 0
tm_last_savehist = 0

def getTimeString(tm=None):
	tm = tm or time.localtime(time.time()+3600*saved['timezone'])
	return '%02d:%02d:%02d'%(tm[3],tm[4],tm[5])

def getDateString(tm, showDay=True):
	ds = "%04d-%02d-%02d"%(tm[0],tm[1],tm[2])
	return ds if showDay else ds[:-3]

weekDays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
def getWeekdayString(tm):
	return weekDays[tm[6]]

def getFullDateTime():
  tm = time.localtime(time.time()+3600*saved['timezone'])
  return getDateString(tm)+" ("+getWeekdayString(tm)+") "+getTimeString(tm)

def getBoardInfo():
	s = os.statvfs('/')
	return f"FreeHeap: {esp.freemem()}; FlashSize: {esp.flash_size()}; Speed: {machine.freq()}; File system size (bytes): {s[3]*s[0]}/{s[2]*s[0]}";

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

def open_logfile_auto_rotate():
	global fp_hist
	if fp_hist==None:
		fp_hist = open('0.log', "a")
	if os.stat('0.log')[6]>LOGFILE_MAX_SIZE:
		fp_hist.close()
		for x in range(LOGFILE_MAX_NUM, 0, -1):
			os.rename(f"{x-1}.log", f"{x}.log")
		os.remove(f"{LOGFILE_MAX_NUM}.log")
		fp_hist = open("/0.log", "a")

def log_event(msg):
	open_logfile_auto_rotate()
	fullDateTime = getFullDateTime()
	print(f"{getFullDateTime()} : {msg}", file=fp_hist, flush=True)
	if DEBUG:
		print(f"{getFullDateTime()} : {msg}", flush=True)

def save_config():
	with open('config.json', 'w') as fp:
		fp.write(str(saved))

def load_config():
	with open('config.json') as fp:
		saved_new = eval(fp.read())
	if set(saved.keys())==set(saved_new.keys()):
		saved = saved_new
		return True
	return False

hasInternet = lambda:bool(uping.ping('8.8.8.8',quiet=True)[1])

def initNTP():
	success=True
	try:
		ntptime.settime()
	except:
		success=False
	log_event(f"Synchronize time {'succeeded' if success else 'failed'} at {getFullDateTime()}")

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

def deleteALL():
	for fn in os.listdir():
		if fn.endswith(".log"):
			os.remove(fn)

def get_rc_code(key):
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

def Exec(cmd):
	try:
		exec(cmd, globals(), globals())
		return 'OK'
	except Exception as e:
		return str(e)

class MWebServer:
	def __init__(self, host='0.0.0.0', captivePortalIP='', port=80, max_conn=8):
		self.cmd = ''
		routeHandlers = [
			( "/", "GET", lambda clie, resp: resp.WriteResponseFile('/static/smartlight.html') ),
			( "/setv", "GET", lambda clie, resp: Exec(clie.GetRequestQueryString()) ),
			( "/getv", "GET", lambda clie, resp: eval(clie.GetRequestQueryString(), globals(), globals()) ),
			( "/wifi_restart", "GET", lambda *_: self.set_cmd('restartWifi') ),
			( "/wifi_save", "POST", lambda clie, resp: save_file('secret.py', clie.YieldRequestContent()) ),
			( "/wifi_load", "GET", lambda clie, resp: resp.WriteResponseFile('secret.py')),
			( "/reboot", "GET", lambda *_: self.set_cmd('reboot') ),
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
gc.collect()

### MAIN function
def run():
	try:
		cpIP = start_wifi()
		prt(wifi)
		server = MWebServer(captivePortalIP=cpIP)
		PIN_LED_BUILTIN(1)
		server.run()
	except Exception as e:
		UART(0, 115200, tx=Pin(1), rx=Pin(3))
		prt(e)
