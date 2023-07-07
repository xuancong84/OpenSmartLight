import os, gc, network

sta_if = network.WLAN(network.STA_IF)
sta_if.active(False)
ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)

gc.collect()

mains = [f for f in os.listdir() if f.startswith('main')]

if mains:
    main = __import__(mains[0].split('.')[0])
    main.run()
