import uasyncio as asyncio
import usocket as socket
import gc, time

class CaptiveDNS:
	def __init__(self, this_ip, max_pkt_len=1024):
		self.max_pkt_len = max_pkt_len
		self.this_ip = this_ip
		self.task = self.sock = None
		if this_ip:
			self.run(host=this_ip)

	def answer(self, data):
		packet = data[:2] + b"\x81\x80" + data[4:6] + data[4:6] + b"\x00\x00\x00\x00"
		packet += data[12:] + b"\xC0\x0C\x00\x01\x00\x01\x00\x00\x00\x3C\x00\x04"
		packet += bytes(map(int, self.this_ip.split(".")))
		gc.collect()
		return packet
	
	async def task_func(self):
		while True:
			gc.collect()
			try:
				packet, sender = self.sock.recvfrom(self.max_pkt_len)
				print("DNS query from", sender)
				self.sock.sendto(self.answer(packet), sender)
			except asyncio.CancelledError:
				return
			except:
				await time.sleep(1)
				continue

	def run(self, host='0.0.0.0', port=53):
		# Start UDP server
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.setblocking(False)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		sock.bind((host, port))
		self.sock = sock
		self.task = asyncio.create_task(self.task_func())

	def shutdown(self):
		if self.sock:
			self.sock.close()
			self.sock = None
		if self.task:
			asyncio.cancel(self.task)
			self.task = None
