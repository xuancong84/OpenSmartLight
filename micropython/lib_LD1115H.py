import os, sys, gc
from machine import Pin, PWM, ADC
from time import sleep, time, sleep_ms
from math import sqrt
from array import array
from select import select
from lib_common import *

gc.collect()

default_params = {
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
	'midnight_starts': ["23:00", "23:00", "23:00", "23:00", "00:00", "00:00", "23:00"],
	'midnight_stops': ["07:00", "07:00", "07:00", "07:00", "07:00", "07:00", "07:00"]
}

def digitalWrite(pin, val):
	if pin != None:
		pin(val)

def analogWrite(pin, val):
	if pin != None:
		pin.duty(val)

# For 24GHz microwave micro-motion sensor HLK-LD1115H
class LD1115H:
	def __init__(self, sensor_pwr_pin, ctrl_output_pin, led_master_pin=None, led_level_pin=None,
	    	F_read_lux=None, F_read_thermal=None, params=default_params):  # Typically ~15 frames
		self.sensor_pwr_pin = None if sensor_pwr_pin==None else Pin(sensor_pwr_pin, Pin.OUT)
		self.ctrl_output_pin = None if ctrl_output_pin==None else Pin(ctrl_output_pin, Pin.OUT)
		self.led_master_pin = None if led_master_pin==None else Pin(led_master_pin, Pin.OUT)
		self.led_level_pin = None if led_level_pin==None else PWM(Pin(led_level_pin), 1000, 0)
		self.F_read_lux = F_read_lux
		self.F_read_thermal = F_read_thermal

		self.sensor_log = ''
		self.P = params
		self.logging = False
		self.tm_last_ambient = time()
		self.is_smartlight_on = False
		self.ctrl_output = False
		self.sensor_pwr = False
		self.led_master = False

		self.is_dark_mode = False
		self.elapse = 0
		self.lux_level = 0
		gc.collect()

	def is_midnight(self):
		tm = getDateTime()
		midnight_start = self.P['midnight_starts'][tm[6]]
		midnight_stop = self.P['midnight_stops'][tm[6]]
		midnight_time = getTimeString(tm)[:5]
		if not midnight_start or not midnight_stop:
			return False
		if midnight_stop > midnight_start: # midnight starts after 0am
			return midnight_time>=midnight_start and midnight_time<=midnight_stop
		return midnight_time>=midnight_start or midnight_time<=midnight_stop
	
	def set_output(self, state):
		digitalWrite(self.ctrl_output_pin, state)
		self.ctrl_output = state
		prt("light on" if state else "light off")

	def set_sensor(self, state):
		digitalWrite(self.sensor_pwr_pin, state)
		self.sensor_pwr = state
		prt("sensor on" if state else "sensor off")

	def set_onboard_led(self, state):
		digitalWrite(self.led_master_pin, state)
		self.led_master = state
		prt("Onboard LED =", "On" if state else "Off")
	
	def glide_onboard_led(self, state):
		if self.led_master_pin==None: return

		prt("glide LED on" if state else "glide LED off")
		GLIDE_TIME = self.P['GLIDE_TIME']
		LED_END = self.P['LED_END']
		LED_BEGIN = self.P['LED_BEGIN']
		if GLIDE_TIME == 0:
			self.set_onboard_led(state)
			analogWrite(self.led_level_pin, LED_END if state else LED_BEGIN)
			return
		level = 0
		spd = float(GLIDE_TIME) / ((LED_BEGIN + LED_END + 1) * (abs(int(LED_END - LED_BEGIN)) + 1) / 2)
		if state:
			analogWrite(self.led_level_pin, LED_BEGIN)
			digitalWrite(self.led_master_pin, 1)
			for level in range(LED_BEGIN, LED_END + 1):
				sleep_ms(int(level * spd))
				analogWrite(self.led_level_pin, level)
		else:
			analogWrite(self.led_level_pin, LED_END)
			for level in range(LED_END, LED_BEGIN - 1, -1):
				sleep_ms(int(level * spd))
				analogWrite(self.led_level_pin, level)
			digitalWrite(self.led_master_pin, 0)
			analogWrite(self.led_level_pin, 0)
		self.led_master = state
		self.led_level = level

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

		while select([sys.stdin], [], [], 0)[0]:
			L = sys.stdin.readline().strip()

			# append sensor log
			if self.logging:
				self.sensor_log += L+'\n'
				while len(self.sensor_log)>120:
					p = self.sensor_log.find('\n')
					self.sensor_log = self.sensor_log[p+1:] if p>=0 else ''
					gc.collect()

			# parse sensor UART output
			its = L.split()
			try:
				cmd, val = its[0], int(its[-1])
				if cmd == 'mov' and val>=self.P['MOV_CONT_TH']:
					s_mask |= 1
				elif cmd == 'occ' and val>=self.P['OCC_CONT_TH']:
					s_mask |= 2
				if (cmd == 'mov' and val>=self.P['MOV_TRIG_TH']) or (cmd == 'occ' and val>=self.P['OCC_TRIG_TH']):
					s_mask |= 4
			except:
				pass

		self.run1(s_mask)

	def run1(self, s_mask=0):
		millis = round(time()*1000)

		# Update ambient level
		if self.F_read_lux and millis-self.tm_last_ambient>=1000:
			self.lux_level = self.F_read_lux()
			self.tm_last_ambient = millis

		if self.is_dark_mode: # in night
			if self.is_smartlight_on: # when light/led is on
				if s_mask & 1:
					self.elapse = max(self.elapse, millis + self.P['DELAY_ON_MOV'])
				if s_mask & 2:
					self.elapse = max(self.elapse, millis + self.P['DELAY_ON_OCC'])
				if millis > self.elapse:
					self.smartlight_off()
					sleep_ms(500) # wait for light sensor to stablize
			else:  # when light/led is off
				if s_mask & 4:
					self.smartlight_on()
					self.elapse = millis+self.P['DELAY_ON_MOV']
				elif self.lux_level<self.P['DARK_TH_LOW']: # return to day mode
					self.set_sensor(False)
					self.is_dark_mode = False
		else: # in day
			if self.lux_level>self.P['DARK_TH_HIGH']:
				self.set_sensor(True)
				self.is_dark_mode = True
