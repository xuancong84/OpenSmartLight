import time, gc, bluetooth
from micropython import const
from lib_common import *

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
		self.nbestn = 10
		self.filter_addr = ''
		self.filter_uuid = ''
		self.nbest = {}

	def _irq(self, event, data):
		if event == _IRQ_SCAN_RESULT:
			addr_type, addr, adv_type, rssi, adv_data = data
			adv_data = bytes(adv_data)
			if self.filter_addr and self.filter_addr != bytes(addr):
				return
			if self.filter_uuid and self.filter_uuid != bytes(uuid):
				return

			# print(f'RSSI={rssi} adv_type={adv_type} data_len={len(adv_data)}')
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
			self._ble.active(False)

	# Returns true if we've successfully connected and discovered characteristics.
	def is_connected(self):
		return (
			self._conn_handle is not None
			and self._tx_handle is not None
			and self._rx_handle is not None
		)

	# Find a device advertising the environmental sensor service.
	def scan(self, duration_s=0, interval_us=11250, window_us=11250, nbestn=0, filter_addr=b'', filter_uuid=b'', **kwargs):
		self.filter_addr = filter_addr or self.filter_addr
		self.filter_uuid = filter_uuid or self.filter_uuid
		self.nbestn = nbestn or self.nbestn
		self.nbest = {}
		self._ble.active(True)
		self._ble.gap_scan(duration_s, interval_us, window_us, False)

	def stop_scan(self):
		self._ble.gap_scan(None)
		self._ble.active(False)

	def advertise(self, data, interval_us=125000, duration_s=0.6, connectable=False, **kwargs):
		self._ble.active(True)
		self._ble.gap_advertise(interval_us, adv_data=parse_data(data), connectable=connectable)
		time.sleep(duration_s)
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

g_ble = BLEcentral()

def ble_task(obj: dict):
	global g_ble
	cmd = obj.get('cmd', 'gap_advertise')
	try:
		if cmd == 'gap_advertise':
			g_ble.advertise(**obj)
		elif cmd == 'gap_scan':
			g_ble.scan(**obj)
		return 'OK'
	except Exception as e:
		return str(e)

# def main():
# 	central = BLEcentral()

# 	while True:
# 		print('BLE scan started, press Enter to stop and show results ...', end='')
# 		central.scan()
# 		input()

# 		central.stop_scan()
# 		nbl = sorted(list(central.nbest.items()), reverse=True, key=lambda t:t[1])
# 		print('BLE scan stopped')

# 		while True:
# 			print(f'NBest:')
# 			for ii,(msg,rssi) in enumerate(nbl):
# 				print(f'{ii}: RSSI={rssi} len={len(msg)} {msg.hex()}')
# 			print('Enter the index to send or empty to re-start BLE scan:')
# 			res = input()
# 			try:
# 				msg = bytes.fromhex(res[2:]) if res.startswith('0x') else nbl[int(res)][0]
# 			except:
# 				break

# 			print(f'Sending {msg.hex()}')
# 			central.advertise(msg)

gc.collect()
