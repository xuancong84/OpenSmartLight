import gc, machine
from machine import Pin
from time import ticks_us, ticks_diff, sleep
from math import sqrt
from array import array

class RC():
	def __init__(self, rx_pin, tx_pin, nedges, nrepeat, min_nframes, gap_tol, recv_dur, proto={}):  # Typically ~15 frames
		# negative PIN number means inverted output, HIGH=unpowered, LOW=powered
		self.rx_pin, self.rx_inv = (None, False) if rx_pin==None else (Pin(abs(rx_pin), Pin.IN, Pin.PULL_UP), rx_pin<0)
		self.tx_pin, self.tx_inv = (None, False) if tx_pin==None else (Pin(abs(tx_pin), Pin.OUT), tx_pin<0)
		if self.tx_pin != None:
			self.tx_pin(self.tx_inv)	# turn off radio
		self.nedges = nedges
		self.nrepeat = nrepeat
		self.min_nframes = min_nframes
		self.gap_tol = gap_tol
		self.recv_dur = recv_dur
		self.proto = proto
		gc.collect()

	def recv(self):
		#prt('Receiving RC data ...')
		gc.collect()
		nedges = self.nedges
		p = self.rx_pin
		arr = array('I',  [0]*nedges)

		# ** Time critical **
		cur_freq = machine.freq()
		machine.freq(160000000)
		sleep(0.1)
		st_irq = machine.disable_irq()
		tm_til = ticks_us()+self.recv_dur
		init_level = v = p()
		for x in range(nedges):
			while v == p() and ticks_us()<tm_til: pass
			arr[x] = ticks_us()
			if arr[x]>tm_til: break
			v = p()
		machine.enable_irq(st_irq)
		machine.freq(cur_freq)
		# ** End of time critical **

		if x <= self.min_nframes*2:
			return 'No signal received'
		nedges = x
		arr = arr[:nedges]
		gc.collect()

        # Compute diffs
		for x in range(nedges-1, 0, -1):
			arr[x] = ticks_diff(arr[x], arr[x-1])
		arr[0] = 0
		arr[0] = max(arr)

		# Extract segments
		gap = round(arr[0]*self.gap_tol)
		gap_pos = [0]+[i for i,v in enumerate(arr) if v>=gap]+[nedges]
		if len(gap_pos) < self.min_nframes:
			return f'Too few frames {len(gap_pos)}'
		segs = [arr[gap_pos[i-1]:gap_pos[i]] for i in range(1, len(gap_pos))]
		del arr

		lengths = [len(x) for x in segs]
		#prt(f'Received data size = {nedges}, segment lengths: {lengths}') #DEBUG

		# Select segments with most common frame length
		cnter = {x:lengths.count(x) for x in set(lengths)}
		cnt_max = max(cnter.values())
		len_most = [i for i,j in cnter.items() if j==cnt_max][0]
		N_old = len(segs)
		seg0id = [ii for ii,seg in enumerate(segs) if len(seg)==len_most][0]
		segs = [seg for seg in segs if len(seg)==len_most]
		init_level = 1-init_level if (gap_pos[seg0id]&1) else init_level
		N_new = len(segs)

		if N_new < self.min_nframes:
			return f'Too few selected frames: {N_new}'
		
		# if N_old != N_new:
			#prt('Deleted {} frames of different length'.format(N_old - N_new))

		#prt(f'Averaging {N_new} frames')
		m = [sum(x)/N_new for x in zip(*segs)]	# compute mean
		for seg in segs:	# ignore STD due to gaps difference, clam gap duration to 0.2 sec
			m[0] = seg[0] = min(m[0], 100000)
		std = [sqrt(sum([(y - m[i])**2 for y in x])/N_new) for i, x in enumerate(zip(*segs))]
		del segs
		#prt('Capture quality {:5.1f} (0: perfect)'.format(sum(std)/len(std)))
		ret = {'init_level':init_level, 'data':list(map(round, m))}
		ret.update(self.proto)
	
		return ret

	def send(self, obj):
		if 'fPWM' in obj:
			return self.sendPWM(obj)
		
		gc.collect()

		try:
			init_level, arr = obj['init_level'], obj['data']
		except Exception as e:
			#prt(e)
			return str(e)
		
		#prt('Sending RC data ...')
		p = self.tx_pin

		# ** Time critical **
		st_irq = machine.disable_irq()
		for i in range(self.nrepeat):
			level = init_level^self.tx_inv
			p(level)
			tm_til = ticks_us()
			for dt in arr:
				tm_til += dt
				level = 1-level
				while ticks_us()<tm_til: pass
				p(level)
		machine.enable_irq(st_irq)
		# ** End of time critical **

		p(self.tx_inv)	# turn off radio
		return 'OK'

	def sendPWM(self, obj):
		gc.collect()

		try:
			init_level, arr, fPWM = obj['init_level'], obj['data'], int(obj['fPWM'])
		except Exception as e:
			#prt(e)
			return str(e)
		
		#prt('Sending PWM data ...')
		cur_freq = machine.freq()
		machine.freq(160000000)
		sleep(0.1)	# must wait for frequency to stablize, or will fail randomly
		zero = self.tx_inv*1023
		p = machine.PWM(self.tx_pin, fPWM, zero)

		# ** Time critical **
		for i in range(self.nrepeat):
			level = 512 if init_level else zero
			p.duty(level)
			while not self.tx_pin():pass
			tm_til = ticks_us()
			for dt in arr:
				tm_til += dt
				level = zero if level==512 else 512
				while ticks_us()<tm_til: pass
				p.duty(level)
		# ** End of time critical **

		p.duty(zero)	# turn off signal
		p.deinit()
		self.tx_pin(self.tx_inv)
		machine.freq(cur_freq)
		return 'OK'


# For RF 433MHz remote controller
class RF433RC(RC):
	def __init__(self, rx_pin=None, tx_pin=None, nedges=800, nrepeat=5, min_nframes=5, recv_dur=3000000, gap_tol=0.8):
		super().__init__(rx_pin, tx_pin, nedges, nrepeat, min_nframes, gap_tol, recv_dur, proto={'protocol':'RF433'})

# For infrared remote controller
class IRRC(RC):
	def __init__(self, rx_pin=None, tx_pin=None, nedges=600, nrepeat=1, min_nframes=1, recv_dur=5000000, gap_tol=0.5):
		super().__init__(rx_pin, tx_pin, nedges, nrepeat, min_nframes, gap_tol, recv_dur, proto={'protocol':'IRRC', 'fPWM':43000})
