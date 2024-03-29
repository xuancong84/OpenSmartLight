import os, sys, time, struct, random, machine, gc, bluetooth
from micropython import const

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)
_IRQ_GATTC_DESCRIPTOR_RESULT = const(13)
_IRQ_GATTC_DESCRIPTOR_DONE = const(14)
_IRQ_GATTC_READ_RESULT = const(15)
_IRQ_GATTC_READ_DONE = const(16)
_IRQ_GATTC_WRITE_DONE = const(17)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_GATTC_INDICATE = const(19)

_ADV_IND = const(0x00)
_ADV_DIRECT_IND = const(0x01)
_ADV_SCAN_IND = const(0x02)
_ADV_NONCONN_IND = const(0x03)

gc.collect()

class BLEcentral:
	def __init__(self):
		self._ble = bluetooth.BLE()
		self._ble.irq(self._irq)
		self._reset()
		self.nbestn = 5
		self.nbest = {}

	def _reset(self):
		# Cached name and address from a successful scan.
		self._name = None
		self._addr_type = None
		self._addr = None

		# Callbacks for completion of various operations.
		# These reset back to None after being invoked.
		self._scan_callback = None
		self._conn_callback = None
		self._read_callback = None

		# Persistent callback for when new data is notified from the device.
		self._notify_callback = None

		# Connected device.
		self._conn_handle = None
		self._start_handle = None
		self._end_handle = None
		self._tx_handle = None
		self._rx_handle = None

	def _irq(self, event, data):
		if event == _IRQ_SCAN_RESULT:
			addr_type, addr, adv_type, rssi, adv_data = data
			adv_data = bytes(adv_data)
			print(f'RSSI={rssi} adv_type={adv_type} data_len={len(adv_data)}')
			if adv_data in self.nbest:
				self.nbest[adv_data] = max(rssi, self.nbest[adv_data])
			elif len(self.nbest)<self.nbestn:
				self.nbest[adv_data] = rssi
			else:
				min_rssi = min(self.nbest.values())
				if rssi>min_rssi:
					key_min = [k for k,v in self.nbest.items() if v==min_rssi][0]
					self.nbest.pop(key_min)
					self.nbest[adv_data] = rssi


		elif event == _IRQ_SCAN_DONE:
			if self._scan_callback:
				if self._addr:
					# Found a device during the scan (and the scan was explicitly stopped).
					self._scan_callback(self._addr_type, self._addr, self._name)
					self._scan_callback = None
				else:
					# Scan timed out.
					self._scan_callback(None, None, None)

		elif event == _IRQ_PERIPHERAL_CONNECT:
			# Connect successful.
			conn_handle, addr_type, addr = data
			if addr_type == self._addr_type and addr == self._addr:
				self._conn_handle = conn_handle
				self._ble.gattc_discover_services(self._conn_handle)

		elif event == _IRQ_PERIPHERAL_DISCONNECT:
			# Disconnect (either initiated by us or the remote end).
			conn_handle, _, _ = data
			if conn_handle == self._conn_handle:
				# If it was initiated by us, it'll already be reset.
				self._reset()

		elif event == _IRQ_GATTC_SERVICE_RESULT:
			# Connected device returned a service.
			conn_handle, start_handle, end_handle, uuid = data
			print("service", data)
			if conn_handle == self._conn_handle and uuid == _UART_SERVICE_UUID:
				self._start_handle, self._end_handle = start_handle, end_handle

		elif event == _IRQ_GATTC_SERVICE_DONE:
			# Service query complete.
			if self._start_handle and self._end_handle:
				self._ble.gattc_discover_characteristics(
					self._conn_handle, self._start_handle, self._end_handle
				)
			else:
				print("Failed to find uart service.")

		elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
			# Connected device returned a characteristic.
			conn_handle, def_handle, value_handle, properties, uuid = data
			if conn_handle == self._conn_handle and uuid == _UART_RX_CHAR_UUID:
				self._rx_handle = value_handle
			if conn_handle == self._conn_handle and uuid == _UART_TX_CHAR_UUID:
				self._tx_handle = value_handle

		elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
			# Characteristic query complete.
			if self._tx_handle is not None and self._rx_handle is not None:
				# We've finished connecting and discovering device, fire the connect callback.
				if self._conn_callback:
					self._conn_callback()
			else:
				print("Failed to find uart rx characteristic.")

		elif event == _IRQ_GATTC_WRITE_DONE:
			conn_handle, value_handle, status = data
			print("TX complete")

		elif event == _IRQ_GATTC_NOTIFY:
			conn_handle, value_handle, notify_data = data
			if conn_handle == self._conn_handle and value_handle == self._tx_handle:
				if self._notify_callback:
					self._notify_callback(notify_data)

	# Returns true if we've successfully connected and discovered characteristics.
	def is_connected(self):
		return (
			self._conn_handle is not None
			and self._tx_handle is not None
			and self._rx_handle is not None
		)

	# Find a device advertising the environmental sensor service.
	def scan(self, interval_us=11250, window_us=11250, callback=None):
		self._addr_type = None
		self._addr = None
		self._scan_callback = callback
		self._ble.active(True)
		self._ble.gap_scan(0, interval_us, window_us, False)

	def stop_scan(self):
		self._ble.gap_scan(None)
		self._ble.active(False)

	def advertise(self, data, interval_us=125000):
		self._ble.active(True)
		self._ble.gap_advertise(interval_us, adv_data=data, connectable=False)
		time.sleep(0.5)
		self._ble.gap_advertise(None)
		self._ble.active(False)

	# Connect to the specified device (otherwise use cached address from a scan).
	def connect(self, addr_type=None, addr=None, callback=None):
		self._addr_type = addr_type or self._addr_type
		self._addr = addr or self._addr
		self._conn_callback = callback
		if self._addr_type is None or self._addr is None:
			return False
		self._ble.gap_connect(self._addr_type, self._addr)
		return True

	# Disconnect from current device.
	def disconnect(self):
		if self._conn_handle is None:
			return
		self._ble.gap_disconnect(self._conn_handle)
		self._reset()

	# Send data over the UART
	def write(self, v, response=False):
		if not self.is_connected():
			return
		self._ble.gattc_write(self._conn_handle, self._rx_handle, v, 1 if response else 0)

	# Set handler for when data is received over the UART.
	def on_notify(self, callback):
		self._notify_callback = callback


ble = None

def main():
	global ble
	ble = ble or BLEcentral()

	while True:
		print('BLE scan started, press Enter to stop and show results ...', end='')
		ble.nbest = {}
		ble.scan()
		input()

		ble.stop_scan()
		nbl = sorted(list(ble.nbest.items()), reverse=True, key=lambda t:t[1])
		print('BLE scan stopped')

		while True:
			print(f'NBest:')
			for ii,(msg,rssi) in enumerate(nbl):
				print(f'{ii}: RSSI={rssi} len={len(msg)} {msg.hex()}')
			print('Enter the index to send or empty to re-start BLE scan:')
			res = input()
			try:
				msg = bytes.fromhex(res[2:]) if res.startswith('0x') else nbl[int(res)][0]
			except:
				break

			print(f'Sending {msg.hex()}')
			ble.advertise(msg)

gc.collect()
