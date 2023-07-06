"""
The MIT License (MIT)
Copyright © 2018 Jean-Christophe Bos & HC² (www.hc2.fr)
"""


from    json        import loads, dumps
from    os          import stat
import  socket
import  gc
import  re

try :
	from microWebTemplate import MicroWebTemplate
except :
	pass

try :
	from microWebSocket import MicroWebSocket
except :
	pass

class MicroWebSrvRoute :
	def __init__(self, route, method, func, routeArgNames, routeRegex) :
		self.route         = route        
		self.method        = method       
		self.func          = func         
		self.routeArgNames = routeArgNames
		self.routeRegex    = routeRegex   


class MicroWebSrv :

	# ============================================================================
	# ===( Constants )============================================================
	# ============================================================================

	_indexPages = [
		"index.pyhtml",
		"index.html",
		"index.htm",
		"default.pyhtml",
		"default.html",
		"default.htm"
	]

	_mimeTypes = {
		".txt"   : "text/plain",
		".htm"   : "text/html",
		".html"  : "text/html",
		".css"   : "text/css",
		".csv"   : "text/csv",
		".js"    : "application/javascript",
		".xml"   : "application/xml",
		".xhtml" : "application/xhtml+xml",
		".json"  : "application/json",
		".zip"   : "application/zip",
		".pdf"   : "application/pdf",
		".ts"    : "application/typescript",
		".woff"  : "font/woff",
		".woff2" : "font/woff2",
		".ttf"   : "font/ttf",
		".otf"   : "font/otf",
		".jpg"   : "image/jpeg",
		".jpeg"  : "image/jpeg",
		".png"   : "image/png",
		".gif"   : "image/gif",
		".svg"   : "image/svg+xml",
		".ico"   : "image/x-icon"
	}

	_html_escape_chars = {
		"&" : "&amp;",
		'"' : "&quot;",
		"'" : "&apos;",
		">" : "&gt;",
		"<" : "&lt;"
	}

	_pyhtmlPagesExt = '.pyhtml'

	# ============================================================================
	# ===( Utils  )===============================================================
	# ============================================================================

	_RouteHandlers = []

	@classmethod
	def Route(cls, url, method='GET'):
		""" Adds a route handler function to the routing list """
		def route_decorator(func):
			cls._RouteHandlers += [(url, method, func)]
			return func
		return route_decorator
	
	def route(self, url, method='GET'):
		""" Adds a route handler function to the routing list """
		def route_decorator(func):
			self.add_route(url, method, func)
			return func
		return route_decorator

	# ----------------------------------------------------------------------------

	@staticmethod
	def HTMLEscape(s) :
		return ''.join(MicroWebSrv._html_escape_chars.get(c, c) for c in s)

	# ----------------------------------------------------------------------------

	@staticmethod
	def _unquote(s) :
		r = str(s).split('%')
		try :
			b = r[0].encode()
			for i in range(1, len(r)) :
				try :
					b += bytes([int(r[i][:2], 16)]) + r[i][2:].encode()
				except :
					b += b'%' + r[i].encode()
			return b.decode('UTF-8')
		except :
			return str(s)

	# ------------------------------------------------------------------------------

	@staticmethod
	def _unquote_plus(s) :
		return MicroWebSrv._unquote(s.replace('+', ' '))

	# ------------------------------------------------------------------------------

	@staticmethod
	def _fileExists(path) :
		try :
			stat(path)
			return True
		except :
			return False

	# ----------------------------------------------------------------------------

	@staticmethod
	def _isPyHTMLFile(filename) :
		return filename.lower().endswith(MicroWebSrv._pyhtmlPagesExt)

	# ============================================================================
	# ===( Constructor )==========================================================
	# ============================================================================

	def add_route(self, route, method, func):
		routeParts = route.split('/')
		# -> ['', 'users', '<uID>', 'addresses', '<addrID>', 'test', '<anotherID>']
		routeArgNames = []
		routeRegex    = ''
		for s in routeParts :
			if s.startswith('<') and s.endswith('>') :
				routeArgNames.append(s[1:-1])
				routeRegex += '/(\\w*)'
			elif s :
				routeRegex += '/' + s
		routeRegex += '$'
		# -> '/users/(\w*)/addresses/(\w*)/test/(\w*)$'
		routeRegex = re.compile(routeRegex)

		self._routeHandlers.append(MicroWebSrvRoute(route, method, func, routeArgNames, routeRegex))

	def __init__( self,
				routeHandlers = [],
				port          = 80,
				bindIP        = '0.0.0.0',
				webPath       = "/flash/www" ) :

		self._srvAddr       = (bindIP, port)
		self._webPath       = webPath
		self._notFoundUrl   = None

		self.MaxWebSocketRecvLen        = 1024
		self.WebSocketThreaded          = True
		self.AcceptWebSocketCallback    = None
		self.LetCacheStaticContentLevel = 2

		self._routeHandlers = []
		for route, method, func in routeHandlers+self._RouteHandlers:
			self.add_route(route, method, func)

	# ============================================================================
	# ===( Server Process )=======================================================
	# ============================================================================

	def run(self, max_conn=4, loop_forever=True):
		self._server = socket.socket()
		self._server.setsockopt( socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 )
		self._server.bind(self._srvAddr)
		self._server.listen(max_conn)
		if not loop_forever:
			return self._server
		while True:
			self.run_once()

	def run_once(self):
		try :
			client, cliAddr = self._server.accept()
		except Exception as ex:
			if ex.args and ex.args[0] == 113:
				return
		self._client(self, client, cliAddr)

	# ----------------------------------------------------------------------------

	def SetNotFoundPageUrl(self, url=None) :
		self._notFoundUrl = url

	# ----------------------------------------------------------------------------

	def GetMimeTypeFromFilename(self, filename) :
		filename = filename.lower()
		for ext in self._mimeTypes :
			if filename.endswith(ext) :
				return self._mimeTypes[ext]
		return None

	# ----------------------------------------------------------------------------
	
	def GetRouteHandler(self, resUrl, method) :
		if self._routeHandlers :
			#resUrl = resUrl.upper()
			if resUrl.endswith('/') :
				resUrl = resUrl[:-1]
			method = method.upper()
			for rh in self._routeHandlers :
				if rh.method == method :
					m = rh.routeRegex.match(resUrl)
					if m :   # found matching route?
						if rh.routeArgNames :
							routeArgs = {}
							for i, name in enumerate(rh.routeArgNames) :
								value = m.group(i+1)
								try :
									value = int(value)
								except :
									pass
								routeArgs[name] = value
							return (rh.func, routeArgs)
						else :
							return (rh.func, None)
		return (None, None)

	# ----------------------------------------------------------------------------

	def _physPathFromURLPath(self, urlPath) :
		if urlPath == '/' :
			for idxPage in self._indexPages :
				physPath = self._webPath + '/' + idxPage
				if MicroWebSrv._fileExists(physPath) :
					return physPath
		else :
			physPath = self._webPath + urlPath.replace('../', '/')
			if MicroWebSrv._fileExists(physPath) :
				return physPath
		return None

	# ============================================================================
	# ===( Class Client  )========================================================
	# ============================================================================

	class _client :

		# ------------------------------------------------------------------------

		def __init__(self, microWebSrv, socket, addr) :
			socket.settimeout(2)
			self._microWebSrv   = microWebSrv
			self._socket        = socket
			self._addr          = addr
			self._method        = None
			self._path          = None
			self._httpVer       = None
			self._resPath       = "/"
			self._queryString   = ""
			self._queryParams   = { }
			self._headers       = { }
			self._contentType   = None
			self._contentLength = 0
			
			if hasattr(socket, 'readline'):   # MicroPython
				self._socketfile = self._socket
			else:   # CPython
				self._socketfile = self._socket.makefile('rwb')
						
			self._processRequest()

		# ------------------------------------------------------------------------

		def _processRequest(self) :
			try :
				response = MicroWebSrv._response(self)
				if self._parseFirstLine(response) :
					if self._parseHeader(response) :
						upg = self._getConnUpgrade()
						if not upg :
							routeHandler, routeArgs = self._microWebSrv.GetRouteHandler(self._resPath, self._method)
							if routeHandler :
								try :
									if routeArgs is not None:
										ret = routeHandler(self, response, routeArgs)
									else :
										ret = routeHandler(self, response)
									if type(ret)==str:
										response.WriteResponseOk(content=ret, headers=None, contentType="text/html", contentCharset="UTF-8")
								except Exception as ex :
									print(f'MicroWebSrv handler exception:\r\n  - In route {self._method} {self._resPath}\r\n  - {ex}')
									raise ex
							elif self._method.upper() == "GET" :
								filepath = self._microWebSrv._physPathFromURLPath(self._resPath)
								if filepath :
									if MicroWebSrv._isPyHTMLFile(filepath) :
										response.WriteResponsePyHTMLFile(filepath)
									else :
										contentType = self._microWebSrv.GetMimeTypeFromFilename(filepath)
										if contentType :
											if self._microWebSrv.LetCacheStaticContentLevel > 0 :
												if self._microWebSrv.LetCacheStaticContentLevel > 1 and \
												'if-modified-since' in self._headers :
													response.WriteResponseNotModified()
												else:
													headers = { 'Last-Modified' : 'Fri, 1 Jan 2018 23:42:00 GMT', \
																'Cache-Control' : 'max-age=315360000' }
													response.WriteResponseFile(filepath, contentType, headers)
											else :
												response.WriteResponseFile(filepath, contentType)
										else :
											response.WriteResponseForbidden()
								else :
									response.WriteResponseNotFound()
							else :
								response.WriteResponseMethodNotAllowed()
						elif upg == 'websocket' and 'MicroWebSocket' in globals() \
							and self._microWebSrv.AcceptWebSocketCallback :
								MicroWebSocket( socket         = self._socket,
												httpClient     = self,
												httpResponse   = response,
												maxRecvLen     = self._microWebSrv.MaxWebSocketRecvLen,
												threaded       = self._microWebSrv.WebSocketThreaded,
												acceptCallback = self._microWebSrv.AcceptWebSocketCallback )
								return
						else :
							response.WriteResponseNotImplemented()
					else :
						response.WriteResponseBadRequest()
			except :
				response.WriteResponseInternalServerError()
			try :
				if self._socketfile is not self._socket:
					self._socketfile.close()
				self._socket.close()
			except :
				pass

		# ------------------------------------------------------------------------

		def _parseFirstLine(self, response) :
			try :
				elements = self._socketfile.readline().decode().strip().split()
				if len(elements) == 3 :
					self._method  = elements[0].upper()
					self._path    = elements[1]
					self._httpVer = elements[2].upper()
					elements      = self._path.split('?', 1)
					if len(elements) > 0 :
						self._resPath = MicroWebSrv._unquote_plus(elements[0])
						if len(elements) > 1 :
							self._queryString = elements[1]
							elements = self._queryString.split('&')
							for s in elements :
								param = s.split('=', 1)
								if len(param) > 0 :
									value = MicroWebSrv._unquote(param[1]) if len(param) > 1 else ''
									self._queryParams[MicroWebSrv._unquote(param[0])] = value
					return True
			except :
				pass
			return False
	
		# ------------------------------------------------------------------------

		def _parseHeader(self, response) :
			while True :
				elements = self._socketfile.readline().decode().strip().split(':', 1)
				if len(elements) == 2 :
					self._headers[elements[0].strip().lower()] = elements[1].strip()
				elif len(elements) == 1 and len(elements[0]) == 0 :
					if self._method == 'POST' or self._method == 'PUT' :
						self._contentType   = self._headers.get("content-type", None)
						self._contentLength = int(self._headers.get("content-length", 0))
					return True
				else :
					return False

		# ------------------------------------------------------------------------

		def _getConnUpgrade(self) :
			if 'upgrade' in self._headers.get('connection', '').lower() :
				return self._headers.get('upgrade', '').lower()
			return None

		# ------------------------------------------------------------------------

		def GetServer(self) :
			return self._microWebSrv

		# ------------------------------------------------------------------------

		def GetAddr(self) :
			return self._addr

		# ------------------------------------------------------------------------

		def GetIPAddr(self) :
			return self._addr[0]

		# ------------------------------------------------------------------------

		def GetPort(self) :
			return self._addr[1]

		# ------------------------------------------------------------------------

		def GetRequestMethod(self) :
			return self._method

		# ------------------------------------------------------------------------

		def GetRequestTotalPath(self) :
			return self._path

		# ------------------------------------------------------------------------

		def GetRequestPath(self) :
			return self._resPath

		# ------------------------------------------------------------------------

		def GetRequestQueryString(self) :
			return self._queryString

		# ------------------------------------------------------------------------

		def GetRequestQueryParams(self) :
			return self._queryParams

		# ------------------------------------------------------------------------

		def GetRequestHeaders(self) :
			return self._headers

		# ------------------------------------------------------------------------

		def GetRequestContentType(self) :
			return self._contentType

		# ------------------------------------------------------------------------

		def GetRequestContentLength(self) :
			return self._contentLength

		# ------------------------------------------------------------------------

		def ReadRequestContent(self, size=None) :
			if size is None :
				size = self._contentLength
			if size > 0 :
				try :
					return self._socketfile.read(size)
				except :
					pass
			return b''

		# ------------------------------------------------------------------------

		def ReadRequestPostedFormData(self) :
			res  = { }
			data = self.ReadRequestContent()
			if data :
				elements = data.decode().split('&')
				for s in elements :
					param = s.split('=', 1)
					if len(param) > 0 :
						value = MicroWebSrv._unquote_plus(param[1]) if len(param) > 1 else ''
						res[MicroWebSrv._unquote_plus(param[0])] = value
			return res

		# ------------------------------------------------------------------------

		def ReadRequestContentAsJSON(self) :
			data = self.ReadRequestContent()
			if data :
				try :
					return loads(data.decode())
				except :
					pass
			return None
		
	# ============================================================================
	# ===( Class Response  )======================================================
	# ============================================================================

	class _response :

		# ------------------------------------------------------------------------

		def __init__(self, client) :
			self._client = client

		# ------------------------------------------------------------------------

		def _write(self, data, strEncoding='ISO-8859-1') :
			if data :
				if type(data) == str :
					data = data.encode(strEncoding)
				data = memoryview(data)
				while data :
					n = self._client._socketfile.write(data)
					if n is None :
						return False
					data = data[n:]
				return True
			return False

		# ------------------------------------------------------------------------

		def _writeFirstLine(self, code) :
			return self._write(f"HTTP/1.1 {code}\r\n")

		# ------------------------------------------------------------------------

		def _writeHeader(self, name, value) :
			return self._write("%s: %s\r\n" % (name, value))

		# ------------------------------------------------------------------------

		def _writeContentTypeHeader(self, contentType, charset=None) :
			if contentType :
				ct = contentType + (("; charset=%s" % charset) if charset else "")
			else :
				ct = "application/octet-stream"
			self._writeHeader("Content-Type", ct)

		# ------------------------------------------------------------------------

		def _writeServerHeader(self) :
			self._writeHeader("Server", "MicroWebSrv by JC`zic")

		# ------------------------------------------------------------------------

		def _writeEndHeader(self) :
			return self._write("\r\n")

		# ------------------------------------------------------------------------

		def _writeBeforeContent(self, code, headers, contentType, contentCharset, contentLength) :
			self._writeFirstLine(code)
			if isinstance(headers, dict) :
				for header in headers :
					self._writeHeader(header, headers[header])
			if contentLength > 0 :
				self._writeContentTypeHeader(contentType, contentCharset)
				self._writeHeader("Content-Length", contentLength)
			self._writeServerHeader()
			self._writeHeader("Connection", "close")
			self._writeEndHeader()

		# ------------------------------------------------------------------------

		def WriteSwitchProto(self, upgrade, headers=None) :
			self._writeFirstLine(101)
			self._writeHeader("Connection", "Upgrade")
			self._writeHeader("Upgrade",    upgrade)
			if isinstance(headers, dict) :
				for header in headers :
					self._writeHeader(header, headers[header])
			self._writeServerHeader()
			self._writeEndHeader()
			if self._client._socketfile is not self._client._socket :
				self._client._socketfile.flush()   # CPython needs flush to continue protocol

		# ------------------------------------------------------------------------

		def WriteResponse(self, code, headers, contentType, contentCharset, content) :
			try :
				if content :
					if type(content) == str :
						content = content.encode(contentCharset)
					contentLength = len(content)
				else :
					contentLength = 0
				self._writeBeforeContent(code, headers, contentType, contentCharset, contentLength)
				if content :
					return self._write(content)
				return True
			except :
				return False

		# ------------------------------------------------------------------------

		def WriteResponsePyHTMLFile(self, filepath, headers=None, vars=None) :
			if 'MicroWebTemplate' in globals() :
				with open(filepath, 'r') as file :
					code = file.read()
				mWebTmpl = MicroWebTemplate(code, escapeStrFunc=MicroWebSrv.HTMLEscape, filepath=filepath)
				try :
					tmplResult = mWebTmpl.Execute(None, vars)
					return self.WriteResponse(200, headers, "text/html", "UTF-8", tmplResult)
				except Exception as ex :
					return self.WriteResponse( 500,
											None,
											"text/html",
											"UTF-8",
											self._execErrCtnTmpl % {
													'module'  : 'PyHTML',
													'message' : str(ex)
											} )
			return self.WriteResponseNotImplemented()

		# ------------------------------------------------------------------------

		def WriteResponseFile(self, filepath, contentType=None, headers=None) :
			try :
				size = stat(filepath)[6]
				if size > 0 :
					with open(filepath, 'rb') as file :
						self._writeBeforeContent(200, headers, contentType, None, size)
						try :
							buf = bytearray(1024)
							while size > 0 :
								x = file.readinto(buf)
								if x < len(buf) :
									buf = memoryview(buf)[:x]
								if not self._write(buf) :
									return False
								size -= x
							return True
						except :
							self.WriteResponseInternalServerError()
							return False
			except :
				pass
			self.WriteResponseNotFound()
			return False

		# ------------------------------------------------------------------------

		def WriteResponseFileAttachment(self, filepath, attachmentName, headers=None) :
			if not isinstance(headers, dict) :
				headers = { }
			headers["Content-Disposition"] = "attachment; filename=\"%s\"" % attachmentName
			return self.WriteResponseFile(filepath, None, headers)

		# ------------------------------------------------------------------------

		def WriteResponseOk(self, headers=None, contentType=None, contentCharset=None, content=None) :
			return self.WriteResponse(200, headers, contentType, contentCharset, content)

		# ------------------------------------------------------------------------

		def WriteResponseJSONOk(self, obj=None, headers=None) :
			return self.WriteResponse(200, headers, "application/json", "UTF-8", dumps(obj))

		# ------------------------------------------------------------------------

		def WriteResponseRedirect(self, location) :
			headers = { "Location" : location }
			return self.WriteResponse(302, headers, None, None, None)

		# ------------------------------------------------------------------------

		def WriteResponseError(self, code) :
			return self.WriteResponse(code, None, "text/html", "UTF-8", f'Error: HTTP {code}')

		# ------------------------------------------------------------------------

		def WriteResponseJSONError(self, code, obj=None) :
			return self.WriteResponse( code,
									None,
									"application/json",
									"UTF-8",
									dumps(obj if obj else { }) )

		# ------------------------------------------------------------------------

		def WriteResponseNotModified(self) :
			return self.WriteResponseError(304)

		# ------------------------------------------------------------------------

		def WriteResponseBadRequest(self) :
			return self.WriteResponseError(400)

		# ------------------------------------------------------------------------

		def WriteResponseForbidden(self) :
			return self.WriteResponseError(403)

		# ------------------------------------------------------------------------

		def WriteResponseNotFound(self) :
			if self._client._microWebSrv._notFoundUrl :
				self.WriteResponseRedirect(self._client._microWebSrv._notFoundUrl)
			else :
				return self.WriteResponseError(404)

		# ------------------------------------------------------------------------

		def WriteResponseMethodNotAllowed(self) :
			return self.WriteResponseError(405)

		# ------------------------------------------------------------------------

		def WriteResponseInternalServerError(self) :
			return self.WriteResponseError(500)

		# ------------------------------------------------------------------------

		def WriteResponseNotImplemented(self) :
			return self.WriteResponseError(501)

		# ------------------------------------------------------------------------

		def FlashMessage(self, messageText, messageStyle='') :
			if 'MicroWebTemplate' in globals() :
				MicroWebTemplate.MESSAGE_TEXT = messageText
				MicroWebTemplate.MESSAGE_STYLE = messageStyle

		# ------------------------------------------------------------------------

		_execErrCtnTmpl = """\
		<html>
			<head>
				<title>Page execution error</title>
			</head>
			<body>
				<h1>%(module)s page execution error</h1>
				%(message)s
			</body>
		</html>
		"""

	# ============================================================================
	# ============================================================================
	# ============================================================================

