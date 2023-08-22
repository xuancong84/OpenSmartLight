import os, time, ntptime
from machine import Timer

DEBUG = False
SAVELOG = False
LOGFILE = 'static/log.txt'
Timers = {}	# {'timer-name': [last-stamp-sec, period-in-sec, True (is periodic or oneshot), callback_func]}
timezone = 8

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
	try:
		t = time.time()
		ntptime.settime()
		t = time.time()-t
		for tmr in Timers:
			tmr[0] += t
	except:
		pass

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
