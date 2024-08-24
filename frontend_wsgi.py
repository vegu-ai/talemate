import os
from whitenoise import WhiteNoise
from urllib.parse import urlparse

# Get the directory of the current file
current_dir = os.path.dirname(os.path.abspath(__file__))
# Construct the path to the dist directory
dist_dir = os.path.join(current_dir, "talemate_frontend", "dist")

def application(environ, start_response):
    path = environ.get('PATH_INFO', '')
    if path == '/' or not os.path.exists(os.path.join(dist_dir, path.lstrip('/'))):
        # Serve index.html for root path or any path that doesn't exist as a file
        try:
            with open(os.path.join(dist_dir, 'index.html'), 'rb') as f:
                content = f.read()
            status = '200 OK'
            headers = [('Content-type', 'text/html')]
            start_response(status, headers)
            return [content]
        except IOError:
            status = '404 NOT FOUND'
            headers = [('Content-type', 'text/plain')]
            start_response(status, headers)
            return [b'Not Found']
    
    # Let WhiteNoise handle existing static files
    return application.whitenoise(environ, start_response)

# Wrap the WSGI application with WhiteNoise
application.whitenoise = WhiteNoise(application, root=dist_dir)
application.whitenoise.add_files(dist_dir, prefix='')