import network, time

ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)

sta_if = network.WLAN(network.STA_IF)
sta_if.active(True)
sta_if.connect('WXC1', '')
[(1 if sta_if.isconnected() else time.sleep(2)) for x in range(30)]

sta_if.ifconfig()

