import os, time, ntptime, network
from machine import Timer, ADC, Pin, PWM

LOGFILE = 'static/log.txt'
Timers = {}	# {'timer-name': [last-stamp-sec, period-in-sec, True (is periodic or oneshot), callback_func]}
A0 = ADC(0)

# global savable parameters
P = {
	'DEBUG': False,
	'SMART_CTRL': True,
	'SAVELOG': False,
	'timezone': 8,
	'DEBUG_dpin_num': '',	# only GPIO 2 or None: for debug blinking
	'PIN_RF_IN': '',		# GPIO5 tested working
	'PIN_RF_OUT': '',		# GPIO4 tested working
	'PIN_IR_IN': '',		# GPIO14 tested working
	'PIN_IR_OUT': '',		# GPIO12 tested working
	'PIN_ASR_IN': '',		# GPIO 13 or 3: generic ASR chip sending UART output upon voice commands
	'PIN_LD1115H': '',		# GPIO 13 or 3: HLK-LD1115H motion sensor
	}

url_string = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~/?'
is_valid_pin = lambda pin, P=P: type(P.get(pin, ''))==int
read_py_obj = lambda f: Try(lambda: eval(open(f).read()), '')
execRC = lambda *args: None

# None (=>null): the control will not be shown; to disable, set to empty string
def dft_eval(s, dft):
	try:
		return eval(s, globals(), globals())
	except:
		return dft

def Try(*args):
	exc = ''
	for arg in args:
		try:
			if callable(arg):
				return arg()
		except Exception as e:
			exc = e
	return str(exc)


class PIN:
	""" Either pass a machine.Pin object, or an Integer with a pin_name '_*pin_num' to create the pin
	where * can be:
		d: output digital pin
		i: input digital pin
		p: PWM pin
		a: ADC pin
	"""
	def __init__(self, pin, pin_name='', dtype=int, invert=None):
		self.pin_name = f'PIN({pin})'
		if type(pin)==int:
			self.pin = abs(pin)
			self.invert = pin<0 if invert is None else invert
			if pin_name.endswith('pin_num'):
				self.pin_name = pin_name[:-4]
				pt = pin_name[:-7].split('_')[-1]
				if pt=='d':
					self.pin = Try(lambda:Pin(self.pin, Pin.OUT), '')
				elif pt=='p':
					self.pin = Try(lambda:PWM(self.pin, freq=1000, duty=0),'')
				elif pt=='i':
					self.pin = Try(lambda:Pin(self.pin, Pin.IN), '')
				elif pt=='a':
					self.pin = Try(lambda:ADC(self.pin), '')
		else:
			self.pin = pin
			self.invert = invert or False
			self.state = False
		self.type = dtype

	def __call__(self, *args):
		prt(self.pin_name, ':', args)
		if self.invert:
			if type(self.pin)==PWM:
				if self.type == int:
					return self.pin.duty(1023-args[0]) if args else 1023-self.pin.duty()
				return self.pin.duty((1-args[0])*1023) if args else 1-self.pin.duty()/1023
			elif type(self.pin)==Pin:
				return self.pin(1-args[0]) if args else 1-self.pin()
			elif type(self.pin)==ADC:
				return 1023-self.pin.read() if self.type==int else 1.0-self.pin.read_u16()/65535
			elif type(self.pin)==int:
				return Pin(self.pin)(1-args[0]) if args else 1-Pin(self.pin)()
		else:
			if type(self.pin)==PWM:
				if self.type == int:
					return self.pin.duty(args[0]) if args else self.pin.duty()
				return self.pin.duty(args[0]*1023) if args else self.pin.duty()/1023
			elif type(self.pin)==Pin:
				return self.pin(*args)
			elif type(self.pin)==ADC:
				return self.pin.read() if self.type==int else self.pin.read_u16()/65535
			elif type(self.pin)==int:
				return Pin(self.pin)(*args)

		if type(self.pin) in [tuple,list]:
			if not args:
				return self.state
			self.state = args[0]
			return execRC(self.pin[self.state])

		return self.pin(*args) if callable(self.pin) else None


_auto_pins = set()
def auto_makepins(ns, dct):
	for k, v in dct.items():
		if k.endswith('pin_num'):
			setattr(ns, k[:-4], PIN(v, k))
			_auto_pins.add(k[:-4])

def auto_status(ns, dct):
	for name in _auto_pins:
		if hasattr(ns, name) and name not in dct:
			dct[name] = getattr(ns, name)()
	for k, v in dct.items():
		if type(v)==dict and hasattr(ns, k):
			auto_status(getattr(ns, k), v)
	return dct


getDateTime = lambda: time.localtime(time.time()+3600*P['timezone'])

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
	if P['DEBUG']:
		print(getFullDateTime(), end=' ')
		print(*args, **kwarg)
	if P['SAVELOG']:
		try:
			if os.stat(LOGFILE)[6]>1000000:
				os.rename(LOGFILE, LOGFILE+'.old')
		except:
			pass
		with open(LOGFILE, 'a') as fp:
			print(getFullDateTime(), end=' ', file=fp)
			print(*args, **kwarg, file=fp)

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
