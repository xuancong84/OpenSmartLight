import network, time

ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)

sta_if = network.WLAN(network.STA_IF)
sta_if.active(True)
sta_if.connect('WXC1', '12345abcde')

for x in range(30):
	if sta_if.isconnected():
		break
	time.sleep(2)
	print('.', end='')

print(f'Connected successfully {sta_if.ifconfig()}' if sta_if.isconnected() else 'Connection failed')
