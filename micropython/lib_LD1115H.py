import os, sys, gc, select
from machine import Pin, PWM
from time import sleep, sleep_ms
from math import sqrt
from array import array
from lib_common import *
from microWebSrv import MicroWebSrv as MWS

gc.collect()

# For 24GHz microwave micro-motion sensor HLK-LD1115H
class LD1115H:
	default_P = {
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
		'N_CONSEC_TRIG': 1,
		'sensor_pwr_dpin_num': '',
		'ctrl_output_dpin_num': '',
		'led_master_dpin_num': '',
		'led_level_ppin_num': '',
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
		if 'LD1115H' not in P:
			P['LD1115H'] = self.default_P
		self.P = P['LD1115H']
		auto_makepins(self, self.P)

		# turn on motion sensor if night time, otherwise, cannot enter auto mode by powering on
		if self.is_night():
			self.set_sensor(True)

		gc.collect()
		
	def status(self):
		return {
			'is_smartlight_on': self.is_smartlight_on,
			'is_dark_mode': self.is_dark_mode,
			'lux_level': self.lux_level,
			'thermal_level': self.thermal_level,
			'logging': self.logging,
			'sensor_log': self.sensor_log if self.logging else None
			}

	def is_midnight(self):
		tm = getDateTime()
		return isTimeInBetween(getTimeString(tm)[:5], self.P['midnight_starts'][tm[6]], self.P['midnight_stops'][tm[6]])

	def is_night(self):
		return isTimeInBetween(getTimeString()[:5], self.P['night_start'], self.P['night_stop'])
	
	def set_output(self, state):
		self.ctrl_output_dpin(state)
		prt("light on" if state else "light off")

	def set_sensor(self, state):
		self.sensor_pwr_dpin(state)
		prt("sensor on" if state else "sensor off")

	def set_onboard_led(self, state):
		self.led_master_dpin(state)
		prt("Onboard LED =", "On" if state else "Off")
	
	def glide_onboard_led(self, state):
		if self.P['led_master_dpin_num']=='': return

		prt("glide LED on" if state else "glide LED off")
		GLIDE_TIME = self.P['GLIDE_TIME']
		LED_END = self.P['LED_END']
		LED_BEGIN = self.P['LED_BEGIN']
		if GLIDE_TIME == 0:
			self.set_onboard_led(state)
			self.led_level_ppin(LED_END if state else LED_BEGIN)
			return
		level = 0
		spd = float(GLIDE_TIME) / ((LED_BEGIN + LED_END + 1) * (abs(int(LED_END - LED_BEGIN)) + 1) / 2)
		if state:
			self.led_level_ppin(LED_BEGIN)
			self.led_master_dpin(1)
			for level in range(LED_BEGIN, LED_END + 1):
				sleep_ms(int(level * spd))
				self.led_level_ppin(level)
		else:
			self.led_level_ppin(LED_END)
			for level in range(LED_END, LED_BEGIN - 1, -1):
				sleep_ms(int(level * spd))
				self.led_level_ppin(level)
			self.led_master_dpin(0)
			self.led_level_ppin(0)

	def smartlight_on(self):
		prt("smartlight on")
		self.glide_onboard_led(True) if self.is_midnight() else self.set_output(True)
		self.is_smartlight_on = True

	def smartlight_off(self):
		prt("smartlight off")
		self.set_output(False)
		self.glide_onboard_led(False)
		self.is_smartlight_on = False

	def handleUART(self):
		s_mask = 0

		while select.select([sys.stdin], [], [], 0)[0]:
			try:
				L = sys.stdin.readline().strip()
				assert L

				# append sensor log
				if self.logging:
					self.sensor_log += L+'\n'
					while len(self.sensor_log)>120:
						p = self.sensor_log.find('\n')
						self.sensor_log = self.sensor_log[p+1:] if p>=0 else ''
						gc.collect()

				# parse sensor UART output
				its = L.replace(',', ' ').split()
				cmd, val = its[0], int(its[-1])
				if cmd == 'mov' and val>=self.P['MOV_CONT_TH']:
					s_mask |= 1
				elif cmd == 'occ' and val>=self.P['OCC_CONT_TH']:
					s_mask |= 2
				if (cmd == 'mov' and val>=self.P['MOV_TRIG_TH']) or (cmd == 'occ' and val>=self.P['OCC_TRIG_TH']):
					self.n_consec_trig += 1
					if self.n_consec_trig >= self.P['N_CONSEC_TRIG']:
						s_mask |= 4
				else:
					self.n_consec_trig = 0
			except:
				pass

			# run ets for PWM
			sleep_ms(1)

		self.run1(s_mask)

	def run1(self, s_mask=0):
		millis = round(time.time()*1000)

		# Update ambient level
		if millis-self.tm_last_ambient>=4000:
			self.lux_level = dft_eval(self.P['F_read_lux'], '')
			self.thermal_level = dft_eval(self.P['F_read_thermal'], '')
			self.tm_last_ambient = millis

		if self.is_dark_mode: # in night
			if self.is_smartlight_on: # when light/led is on
				if s_mask & 1:
					self.elapse = max(self.elapse, millis + self.P['DELAY_ON_MOV'])
				if s_mask & 2:
					self.elapse = max(self.elapse, millis + self.P['DELAY_ON_OCC'])
				if millis > self.elapse:
					self.smartlight_off()
					sleep_ms(400) # wait for light sensor to stablize and refresh lux value
					self.lux_level = dft_eval(self.P['F_read_lux'], '')
			else:  # when light/led is off
				if s_mask & 4:
					self.smartlight_on()
					self.elapse = millis+self.P['DELAY_ON_MOV']
				elif (type(self.lux_level)==int and self.lux_level<self.P['DARK_TH_LOW']): # return to day mode
					if not self.is_night():
						self.set_sensor(False)
					self.is_dark_mode = False
		else: # in day
			if (type(self.lux_level)==int and self.lux_level>self.P['DARK_TH_HIGH']):
				self.set_sensor(True)
				self.is_dark_mode = True
