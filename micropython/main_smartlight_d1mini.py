import os, sys, esp, gc, uping, network, random
import machine, time, ntptime, select, socket
from microdot import *
gc.collect()

# Global objects
ap_if = network.WLAN(network.AP_IF)
sta_if = network.WLAN(network.STA_IF)

# Load credentials if present
try:
	import secret as cred
except:
	class dummy: pass
	cred = dummy()

# constant definitions
PIN_LED_BUILTIN = machine.Pin(2, machine.Pin.OUT)
PIN_CONTROL_OUTPUT = machine.Pin(4, machine.Pin.OUT)
PIN_MOTION_SENSOR = machine.Pin(0, machine.Pin.OUT)
PIN_LED_MASTER = machine.Pin(5, machine.Pin.OUT)
PIN_LED_ADJ = machine.Pin(14, machine.Pin.OUT)
PIN_AMBIENT_PULLUP = machine.Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)
PIN_AMBIENT_INPUT = machine.ADC(0)
SENSOR_LOG_MAX = 120
LOGFILE_MAX_SIZE = 200000
LOGFILE_MAX_NUM = 8
WIFI_NAME = "OpenSmartLight"
UDP_PORT = 18888      # for LAN broadcast and inform own existence
TEST_ALIVE = 1000000

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

def hotspot():
	rand_ip = f'{random.getrandbits(16)%240+10}.0.0.1'
	ap_if.active(True)
	ap_if.ifconfig((rand_ip, '255.255.255.0', rand_ip, rand_ip))
	ap_if.config(ssid='ESP-AP', authmode=network.AUTH_OPEN)
	return False

def initWifi():
	g_nodeList.clear()

	if not saved['wifi_ssid']:
		return hotspot()

	print("Connecting to WiFi ...", end='', flush=True)

	# Configure static IP address
	sta_if.active(True)
	sta_if.ifconfig([saved['wifi_'+i] for i in ['IP','subnet','gateway','DNS']])
	sta_if.connect(saved['wifi_ssid'],saved['wifi_password'])

	for i in range(60):
		if sta_if.isconnected():
			break
		time.sleep(1)
		print(".", end='', flush=True)
	
	if sta_if.isconnected():
		ap_if.active(False)
		log_event(f"Connected to WIFI, SSID={saved['wifi_ssid']}, IP={sta_if.ifconfig()[0]}")
	else:
		sta_if.active(False)
		log_event("Failed to connect to WIFI, SSID="+saved['wifi_ssid'])
		return hotspot()
	
	return True

def deleteALL():
	for fn in os.listdir():
		if fn.endswith(".log"):
			os.remove(fn)

app = Microdot()

@app.route('/')
def index(request):
	return send_file('/static/server_html.h')


class WebServer:
	def __init__(self, app: Microdot, host='0.0.0.0', captivePortalIP='', port=80, max_conn=8):
		self.app = app
		self.sock_web = app.run(host=host, port=port, loop_forever=False, max_conn=max_conn)
		self.poll = select.poll()
		self.poll.register(self.sock_web, select.POLLIN)
		self.sock_map = {self.sock_web: self.app.run_once}
		self.cpIP = captivePortalIP

		if captivePortalIP:
			self.sock_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.sock_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.sock_dns.bind((captivePortalIP, 53))
			self.poll.register(self.sock_dns, select.POLLIN)
			self.sock_map[self.sock_dns] = self.handleDNS
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
				self.sock_map[tp[0]]()
				gc.collect()


# SETUP
PIN_LED_BUILTIN.off()
open_logfile_auto_rotate()
config_loaded = load_config()
log_event("Config file loaded" if config_loaded else "Config file NOT loaded")
initWifi()
PIN_LED_BUILTIN.on()
if ap_if.active():
	server = WebServer(app, host=ap_if.ifconfig()[0], captivePortalIP=ap_if.ifconfig()[0])
else:
	server = WebServer(app, host=sta_if.ifconfig()[0], captivePortalIP='')

# LOOP
print('Starting main server ...')
server.run()