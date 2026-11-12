import http.server,sys
class H(http.server.BaseHTTPRequestHandler):
    def _log(self,body=b''):
        open(sys.argv[2],'a').write(f"{self.command} {self.path} BODY={body.decode(errors='replace')}\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def do_GET(self): self._log()
    def do_POST(self):
        n=int(self.headers.get('content-length',0)); self._log(self.rfile.read(n))
    def log_message(self,*a): pass
http.server.HTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()
