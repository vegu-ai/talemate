import http.server
import socketserver
import os

PORT = 8080
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "talemate_frontend", "dist")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        if self.path == '/':
            self.path = '/index.html'
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

if __name__ == "__main__":
    print(f"Serving files from: {DIRECTORY}")
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()