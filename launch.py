import argparse
import errno
import functools
import http.server
from pathlib import Path
import threading
import webbrowser

parser = argparse.ArgumentParser(description='АвтоПуть Бюджет')
parser.add_argument('--port', type=int, default=8000)
parser.add_argument('--no-browser', action='store_true')
args = parser.parse_args()
if not 1 <= args.port <= 65535:
    parser.error('Номер порта должен быть от 1 до 65535')
folder = Path(__file__).resolve().parent / 'app'
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))

ports = list(range(args.port, min(args.port + 20, 65536))) + [0]
for port in ports:
    try:
        server = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
        break
    except OSError as error:
        if error.errno != errno.EADDRINUSE or port == 0:
            print('Не удалось запустить приложение: ' + str(error))
            raise SystemExit(1)

url = f'http://127.0.0.1:{server.server_port}/'
if server.server_port != args.port:
    print('Выбран свободный порт: ' + str(server.server_port), flush=True)
print('АвтоПуть Бюджет: ' + url, flush=True)
print('Для остановки нажмите Ctrl+C', flush=True)
if not args.no_browser:
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
try:
    server.serve_forever()
except KeyboardInterrupt:
    print('\nПриложение остановлено')
finally:
    server.server_close()
