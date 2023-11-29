import os, sys, gc, select
from machine import Pin, PWM
from time import sleep, sleep_ms
from math import sqrt
from array import array
from lib_common import *
from microWebSrv import MicroWebSrv as MWS

gc.collect()

# None (=>null): the control will not be shown; to disable, set to empty string
def dft_eval(s, dft):
	try:
		return eval(s, globals(), globals())
	except:
		return dft

# For 24GHz microwave micro-motion sensor HLK-LD1115H
class LD1115H:
	def __init__(self, mws:MWS, uart):  # Typically ~15 frames
		self.load_params()
		self.tm_last_ambient = int(time.time()*1000)
		self.elapse = 0
		self.uart = uart

		# status
		self.is_smartlight_on = False
		self.is_dark_mode = False
		self.logging = False
		self.lux_level = None
		self.thermal_level = None
		self.sensor_log = ''
		self.n_consec_trig = 0

		# turn on motion sensor if night time, otherwise, cannot enter auto mode by powering on
		if self.is_night():
			self.set_sensor(True)

		mws.add_route('/ms_getParams', 'GET', lambda clie, resp: resp.WriteResponseJSONOk(self.P))
		mws.add_route('/ms_setParams', 'GET', lambda clie, resp: self.setParams(clie.GetRequestQueryParams()))
		mws.add_route('/ms_save', 'GET', lambda *_: self.save_params())
		mws.add_route('/ms_load', 'GET', lambda *_: self.load_params())
		gc.collect()

	def load_params(self):
		self.P = {
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
			'sensor_pwr_pin': '',
			'ctrl_output_pin': '',
			'led_master_pin': '',
			'led_level_pin': '',
			'F_read_lux': '',
			'F_read_thermal': '',
			'night_start': '18:00',
			'night_stop': '07:00',
			'midnight_starts': ["23:00", "23:00", "23:00", "23:00", "00:00", "00:00", "23:00"],
			'midnight_stops': ["07:00", "07:00", "07:00", "07:00", "07:00", "07:00", "07:00"]
		}
		try:
			self.P.update(eval(open('LD1115H.conf').read()))
			return 'OK'
		except:
			return 'Load default OK'

	def save_params(self):
		try:
			with open('LD1115H.conf', 'w') as fp:
				fp.write(str(self.P))
			return 'OK'
		except Exception as e:
			return str(e)

	def setParams(self, params:dict):
		try:
			for k,v in params.items():
				self.P[k] = v.split(',') if k.startswith('midnight_') else dft_eval(v, '')
			return 'OK'
		except Exception as e:
			return str(e)
		
	def status(self):
		return {
			'is_smartlight_on': self.is_smartlight_on,
			'is_dark_mode': self.is_dark_mode,
			'lux_level': self.lux_level,
			'thermal_level': self.thermal_level,
			'logging': self.logging,
			'sensor_log': self.sensor_log if self.logging else None,
			'ctrl_output': digitalRead(self.P['ctrl_output_pin']),
			'sensor_pwr': digitalRead(self.P['sensor_pwr_pin']),
			'led_master': digitalRead(self.P['led_master_pin']),
			'led_level': analogRead(self.P['led_level_pin']),
			}

	def is_midnight(self):
		tm = getDateTime()
		return isTimeInBetween(getTimeString(tm)[:5], self.P['midnight_starts'][tm[6]], self.P['midnight_stops'][tm[6]])

	def is_night(self):
		return isTimeInBetween(getTimeString()[:5], self.P['night_start'], self.P['night_stop'])
	
	def set_output(self, state):
		digitalWrite(self.P['ctrl_output_pin'], state)
		prt("light on" if state else "light off")

	def set_sensor(self, state):
		digitalWrite(self.P['sensor_pwr_pin'], state)
		prt("sensor on" if state else "sensor off")

	def set_onboard_led(self, state):
		digitalWrite(self.P['led_master_pin'], state)
		prt("Onboard LED =", "On" if state else "Off")
	
	def glide_onboard_led(self, state):
		if not self.P['led_master_pin']: return

		prt("glide LED on" if state else "glide LED off")
		GLIDE_TIME = self.P['GLIDE_TIME']
		LED_END = self.P['LED_END']
		LED_BEGIN = self.P['LED_BEGIN']
		if GLIDE_TIME == 0:
			self.set_onboard_led(state)
			analogWrite(self.P['led_level_pin'], LED_END if state else LED_BEGIN)
			return
		level = 0
		spd = float(GLIDE_TIME) / ((LED_BEGIN + LED_END + 1) * (abs(int(LED_END - LED_BEGIN)) + 1) / 2)
		if state:
			analogWrite(self.P['led_level_pin'], LED_BEGIN)
			digitalWrite(self.P['led_master_pin'], 1)
			for level in range(LED_BEGIN, LED_END + 1):
				sleep_ms(int(level * spd))
				analogWrite(self.P['led_level_pin'], level)
		else:
			analogWrite(self.P['led_level_pin'], LED_END)
			for level in range(LED_END, LED_BEGIN - 1, -1):
				sleep_ms(int(level * spd))
				analogWrite(self.P['led_level_pin'], level)
			digitalWrite(self.P['led_master_pin'], 0)
			analogWrite(self.P['led_level_pin'], 0)

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

		while select.select([self.uart], [], [], 0)[0]:
			try:
				L = self.uart.readline().strip()
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
