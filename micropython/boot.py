import uos, machine, gc, network

sta_if = network.WLAN(network.STA_IF)
sta_if.active(False)
ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)

def connect_wifi():
	if sta_if.active():
		print(f'Already exist: {sta_if.ifconfig()}')
		return
	import secret as cred
	sta_if.active(True)
	sta_if.ifconfig((cred.WIFI_IP,cred.WIFI_SUBNET,cred.WIFI_GATEWAY,cred.WIFI_DNS))
	sta_if.connect(cred.WIFI_SSID,cred.WIFI_PASSWD)
	print(sta_if.ifconfig())

def create_hotspot():
	if ap_if.active():
		print(f'Already exist: {ap_if.ifconfig()}')
		return
	ap_if.active(True)
	ap_if.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))
	ap_if.config(ssid='ESP-AP', authmode=network.AUTH_OPEN)
	print(ap_if.ifconfig())

def create_webserver():	
	import socket
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.bind(('', 80))
	s.listen(5)

	while True:
		conn, addr = s.accept()
		print('Got a connection from %s' % str(addr))
		request = conn.recv(1024)
		print('Content = %s' % str(request))
		conn.send("""<html><head><meta name="viewport" content="width=device-width, initial-scale=1"</head><body><h1>Hello, World!</h1></body></html>""")
		conn.close()
