import os, time, ntptime, network
from machine import Timer, ADC, Pin, PWM

DEBUG = False
SMART_CTRL = True
SAVELOG = False
LOGFILE = 'static/log.txt'
RL_MAX_DELAY = 10
Timers = {}	# {'timer-name': [last-stamp-sec, period-in-sec, True (is periodic or oneshot), callback_func]}
timezone = 8
A0, A1, A2, A3, A4 = [ADC(i) for i in range(5)]

url_string = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~/?'
digitalWrite = lambda pin, val: Pin(abs(pin), Pin.OUT)(1-val if pin<0 else val) if type(pin)==int else None
digitalRead = lambda pin: (1-Pin(abs(pin), Pin.OUT)()) if pin<0 else Pin(abs(pin), Pin.OUT)() if type(pin)==int else None
analogWrite = lambda pin, val: PWM(abs(pin), freq=1000, duty=(1023-val if pin<0 else val)) if type(pin)==int else None
analogRead = lambda pin: (1023-PWM(abs(pin)).duty()) if pin<0 else PWM(abs(pin)).duty() if type(pin)==int else None

getDateTime = lambda: time.localtime(time.time()+3600*timezone)

sta_if = network.WLAN(network.STA_IF)
ap_if = network.WLAN(network.AP_IF)
getActiveNIF = lambda: sta_if if sta_if.active(True) else ap_if
read_py_obj = lambda f: Try(lambda: eval(open(f).read()), '')

def getTimeString(tm=None):
	tm = tm or getDateTime()
	return '%02d:%02d:%02d'%(tm[3],tm[4],tm[5])

def getDateString(tm=None, showDay=True):
	tm = tm or getDateTime()
	ds = "%04d-%02d-%02d"%(tm[0],tm[1],tm[2])
	return ds if showDay else ds[:-3]

weekDays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
def getWeekdayNum(tm=None):
	tm = tm or getDateTime()
	return tm[6]

def getWeekdayString(tm):
	return weekDays[tm[6]]

def getFullDateTime():
	tm = getDateTime()
	return getDateString(tm)+" ("+getWeekdayString(tm)+") "+getTimeString(tm)

def syncNTP():
	t = time.time()
	for i in range(3):
		try:
			ntptime.settime()
			break
		except:
			pass
	t = time.time()-t
	for k, v in Timers.items():
		v[0] += t

# Compare time string, whether dt is in between dt1 and dt2
# If dt1==dt2 => range=0, always false
# If dt1='00:00*' && dt2='24:00*' => range=24hrs, always true
def isTimeInBetween(dt, dt1, dt2):
	if not dt1 or not dt2 or dt1==dt2:
		return False
	return (dt>=dt1 and dt<=dt2) if dt2 > dt1 else (dt>=dt1 or dt<=dt2)

# On ESP8266, virtual timers with large periods (> a few seconds) will cause system crash upon receiving HTTP request
def FastTimer(period, F, keep=False):
	assert period<2000
	tmr = Timer(-1)
	tmr.init(period=period, mode=Timer.PERIODIC, callback=F)
	if keep:
		return tmr
	else:
		del tmr

def SetTimer(name, period, repeat, F):
	Timers[name] = [time.time(), period, repeat, F]

def DelTimer(name):
	Timers.pop(name, None)

def prt(*args, **kwarg):
	if DEBUG:
		print(getFullDateTime(), end=' ')
		print(*args, **kwarg)
	if SAVELOG and LOGFILE:
		try:
			if os.stat(LOGFILE)[6]>1000000:
				os.rename(LOGFILE, LOGFILE+'.old')
		except:
			pass
		with open(LOGFILE, 'a') as fp:
			print(getFullDateTime(), end=' ', file=fp)
			print(*args, **kwarg, file=fp)

def Try(*args):
	exc = ''
	for arg in args:
		try:
			if callable(arg):
				return arg()
		except Exception as e:
			exc = e
	return str(exc)

def parse_data(s):
	if type(s)==int:
		h = hex(s)[2:]
		return bytes.fromhex(('0'+h) if len(h)&1 else h)
	if type(s)==str:
		return Try(lambda: bytes.fromhex(s), s.encode())
	return s

def url_encode(s):
	try:
		p = s.find('/', s.find('//')+2)
		return s[:p] + ''.join([(c if c in url_string else f'%{ord(c):x}') for c in s[p:]])
	except:
		return s

def load_params(ns):
	ret = Try(lambda: [P.update(eval(open('params.conf').read())), 'OK'][1], 'Load default OK')
	auto_makepins(ns, P)
	return ret

def save_params():
	try:
		with open('params.conf', 'w') as fp:
			fp.write(str(P))
		return 'OK'
	except Exception as e:
		return str(e)
