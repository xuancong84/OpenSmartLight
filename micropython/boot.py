import os, gc, network

gc.collect()

mains = [f for f in os.listdir() if f.startswith('main')]

if mains:
    exec(f'from {mains[0].split(".")[0]} import *')
    # run()
