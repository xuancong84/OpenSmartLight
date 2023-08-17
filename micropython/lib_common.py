import os, time, ntptime

DEBUG = False
SAVELOG = False
LOGFILE = 'static/log.txt'
timezone = 8
is_NTP_set = False

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

def setNTP():
	try:
		ntptime.settime()
		is_NTP_set = True
	except:
		pass

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
