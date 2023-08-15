import os, sys, gc
from machine import Pin
from time import ticks_us, ticks_diff, sleep
from math import sqrt
from array import array

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

# For 24GHz microwave micro-motion sensor HLK-LD1115H
class LD1115H:
	def __init__(self, rx_pin, sensor_pwr_pin, ctrl_output_pin, led_master_pin=None,
	      led_level_pin=None, params=default_params):  # Typically ~15 frames
		self.sensor_log = ''
		self.P = params
		self.logging = False
		gc.collect()

	def handle_UART(self):
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
		s_mask = 0
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

