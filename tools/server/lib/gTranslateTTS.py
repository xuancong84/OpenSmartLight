import requests

class TranslateTTS:

	TTS_API = "https://translate.google.com/translate_tts"

	def __init__(self):
		pass

	def speak(self, msg, lang_code='th-TH'):
		r = requests.get(self.TTS_API, params={
			'q'     : msg,
			'tl'    : lang_code,
			'ie'    : 'UTF-8',
			'client': 'tw-ob',
		})
		return r

	def save_mp3(self, msg, lang_code='th', out_mp3='out.mp3'):
		r = self.speak(msg, lang_code+'-TH')
		with open(out_mp3, 'wb') as f:
			f.write(r.content)


_gtts = TranslateTTS()
def gTransTTS(txt, lang, out_mp3):
    _gtts.save_mp3(txt, lang, out_mp3)