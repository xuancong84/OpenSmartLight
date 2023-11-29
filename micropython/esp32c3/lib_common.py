import os, time, ntptime
from machine import Timer, ADC, Pin, PWM

DEBUG = False
SMART_CTRL = True
SAVELOG = False
LOGFILE = 'static/log.txt'
Timers = {}	# {'timer-name': [last-stamp-sec, period-in-sec, True (is periodic or oneshot), callback_func]}
timezone = 8
A0 = ADC(0)

digitalWrite = lambda pin, val: Pin(pin, Pin.OUT)(val) if type(pin)==int else None
digitalRead = lambda pin: Pin(pin, Pin.OUT)() if type(pin)==int else None
analogWrite = lambda pin, val: PWM(Pin(pin), freq=1000, duty=val) if type(pin)==int else None
analogRead = lambda pin: PWM(Pin(pin)).duty() if type(pin)==int else None

getDateTime = lambda: time.localtime(time.time()+3600*timezone)

def getTimeString(tm=None):
	tm = tm or getDateTime()
	return '%02d:%02d:%02d'%(tm[3],tm[4],tm[5])

def getDateString(tm, showDay=True):
	ds = "%04d-%02d-%02d"%(tm[0],tm[1],tm[2])
	return ds if showDay else ds[:-3]

weekDays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
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
	for tmr in Timers:
		tmr[0] += t

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
