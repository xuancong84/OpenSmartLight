import os, sys, gc, select
from machine import Pin, PWM
from time import sleep_ms, ticks_ms
from math import sqrt
from array import array
from lib_common import *
from microWebSrv import MicroWebSrv as MWS

gc.collect()

# For 24GHz microwave micro-motion sensor HLK-LD1115H
class LD1115H:
	P = {
		'DARK_TH_LOW': 700,		# the darkness level below which sensor will be turned off
		'DARK_TH_HIGH': 800,	# the darkness level above which light will be turned on if motion
		'DELAY_ON_MOV': 30000,
		'DELAY_ON_OCC': 20000,
		'OCC_TRIG_TH': 65530,
		'OCC_CONT_TH': 600,
		'MOV_TRIG_TH': 400,
		'MOV_CONT_TH': 250,
		'LED_BEGIN': 300,
		'LED_END': 400,
		'GLIDE_TIME': 1200,
		'N_CONSEC_TRIG': 1,
		'sensor_pwr_dpin_num': '',
		'ctrl_output_dpin_num': '',
		'led_master_dpin_num': '',
		'led_level_ppin_num': '',
		'led_discharge_dpin_num': '',
		'F_read_lux': '',
		'F_read_thermal': '',
		'night_start': '18:00',
		'night_stop': '07:00',
		'midnight_starts': ["23:00", "23:00", "23:00", "23:00", "00:00", "00:00", "23:00"],
		'midnight_stops': ["07:00", "07:00", "07:00", "07:00", "07:00", "07:00", "07:00"]
	}
	def __init__(self, mws:MWS):  # Typically ~15 frames
		# init status
		self.tm_last_ambient = int(time.time()*1000)
		self.elapse = 0
		self.is_smartlight_on = False
		self.is_dark_mode = False
		self.logging = False
		self.lux_level = None
		self.thermal_level = None
		self.sensor_log = ''
		self.n_consec_trig = 0

		# load default params if necessary and create pins
		self.P.update(P.get('LD1115H', {}))
		P['LD1115H'] = self.P
		auto_makepins(self, self.P)

		# must turn on motion sensor first then turn it off, otherwise it will keeps outputing null
		self.sensor_pwr_dpin(True)

		# keep PWM capacitor discharged before LED smooth on
		self.led_discharge_dpin(False)

		gc.collect()
		
	def status(self):
		return {
			'is_smartlight_on': self.is_smartlight_on,
			'is_dark_mode': self.is_dark_mode,
			'lux_level': self.lux_level,
			'thermal_level': self.thermal_level,
			'logging': self.logging,
			'sensor_log': self.sensor_log if self.logging else None,
			'LED_smooth_switch_dpin': self.LED_smooth_switch_dpin(),
			'smartlight_dpin': self.smartlight_dpin()
			}

	def is_midnight(self):
		tm = getDateTime()
		return isTimeInBetween(getTimeString(tm)[:5], self.P['midnight_starts'][tm[6]], self.P['midnight_stops'][tm[6]])

	def is_night(self):
		return isTimeInBetween(getTimeString()[:5], self.P['night_start'], self.P['night_stop'])

	def LED_smooth_switch_dpin(self, state=None):
		if state is None:
			return self.led_master_dpin()
			
		if not is_valid_pin('led_master_dpin_num', self.P) or self.led_master_dpin()==state:
			return

		prt("glide LED on" if state else "glide LED off")
		GLIDE_TIME = abs(self.P['GLIDE_TIME'])
		LED_END = self.P['LED_END']
		LED_BEGIN = self.P['LED_BEGIN']
		tm0 = ticks_ms()
		spd = abs(LED_END - LED_BEGIN)/max(GLIDE_TIME, 1)
		if state:
			Try(lambda: Pin(self.P['led_discharge_dpin_num'], Pin.IN))
			self.led_level_ppin(LED_BEGIN)
			self.led_master_dpin(1)
			tm_dif = ticks_ms()-tm0
			while tm_dif<GLIDE_TIME and tm_dif>=0:
				self.led_level_ppin(round(LED_BEGIN+spd*tm_dif))
				tm_dif = ticks_ms()-tm0
			self.led_level_ppin(LED_END)
		else:
			# self.led_level_ppin(LED_END)
			# tm_dif = ticks_ms()-tm0
			# while tm_dif<GLIDE_TIME and tm_dif>=0:
			# 	self.led_level_ppin(round(LED_END-spd*tm_dif))
			# 	tm_dif = ticks_ms()-tm0
			self.led_level_ppin(LED_BEGIN)
			sleep_ms(GLIDE_TIME)
			Try(lambda: Pin(self.P['led_discharge_dpin_num'], Pin.OUT)(0))
			self.led_master_dpin(0)

	def smartlight_dpin(self, state=None):
		if state is None:
			return self.is_smartlight_on

		if state:
			prt("smartlight on")
			self.LED_smooth_switch_dpin(True) if self.is_midnight() else self.ctrl_output_dpin(True)
			self.is_smartlight_on = True
		else:
			prt("smartlight off")
			self.ctrl_output_dpin(False)
			self.LED_smooth_switch_dpin(False)
			self.is_smartlight_on = False

	def handleUART(self):
		s_mask = 0
		while select.select([sys.stdin], [], [], 0)[0]:
			try:
				L = sys.stdin.readline().strip()
				if not L:
					continue
				if L.startswith('null'):
					break

				# append sensor log
				if self.logging:
					self.sensor_log += L+'\n'
					while len(self.sensor_log)>120:
						p = self.sensor_log.find('\n')
						self.sensor_log = self.sensor_log[p+1:] if p>=0 else ''
						gc.collect()

				# parse sensor UART output
				its = L.split()
				cmd, val = its[0], int(its[-1])
				if cmd == 'mov,':
					if val>=self.P['MOV_TRIG_TH']:
						self.n_consec_trig += 1
					else:
						self.n_consec_trig = 0
					if val>=self.P['MOV_CONT_TH']:
						s_mask |= 1
				elif cmd == 'occ,':
					if val>=self.P['OCC_TRIG_TH']:
						self.n_consec_trig += 1
					else:
						self.n_consec_trig = 0
					if val>=self.P['OCC_CONT_TH']:
						s_mask |= 2
				else:
					continue
				if self.n_consec_trig >= self.P['N_CONSEC_TRIG']:
					s_mask |= 4
			except:
				pass

			# run ets for PWM
			sleep_ms(0)

		if s_mask:
			self.run1(s_mask)


	def run1(self, s_mask=0):
		millis = round(time.time()*1000)

		# Update ambient level
		if millis-self.tm_last_ambient>=1000:
			self.lux_level = dft_eval(self.P['F_read_lux'], '')
			self.thermal_level = dft_eval(self.P['F_read_thermal'], '')
			self.tm_last_ambient = millis

		if self.is_dark_mode: # in night
			if self.smartlight_dpin(): # when light/led is on
				if s_mask & 1:
					self.elapse = max(self.elapse, millis + self.P['DELAY_ON_MOV'])
				if s_mask & 2:
					self.elapse = max(self.elapse, millis + self.P['DELAY_ON_OCC'])
				if millis > self.elapse:
					self.smartlight_dpin(False)
					sleep_ms(400) # wait for light sensor to stablize and refresh lux value
					self.lux_level = dft_eval(self.P['F_read_lux'], '')
			else:  # when light/led is off
				if (s_mask&4) and self.lux_level>=self.P['DARK_TH_HIGH']:
					self.smartlight_dpin(True)
					self.elapse = millis+self.P['DELAY_ON_MOV']
				elif (type(self.lux_level)==int and self.lux_level<self.P['DARK_TH_LOW']): # return to day mode
					if not self.is_night():
						self.sensor_pwr_dpin(False)
					self.is_dark_mode = False
		else: # in day
			if (type(self.lux_level)==int and self.lux_level>(self.P['DARK_TH_HIGH']+self.P['DARK_TH_LOW'])/2):
				self.sensor_pwr_dpin(True)
				self.is_dark_mode = True
