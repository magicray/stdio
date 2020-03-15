import os
import sys
import ssl
import time
import json
import runpy
import signal
import socket
import select
import logging
import argparse
import mimetypes
import urllib.parse

from . import Cmd, fetch


logfd = dict()


def logger(filename='stdio'):
    if not args.logs:
        return logging.critical

    x = args.logs + '/' + filename

    if x not in logfd:
        logfd[x] = os.open(x, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)

    os.dup2(logfd[x], 2)

    return logging.critical


def server(conn, addr):
    sys.stdin = conn.makefile('r')
    sys.stdout = conn.makefile('w')

    line = urllib.parse.unquote(sys.stdin.readline())
    sys.argv = line.split()[1:-1]
    sys.argv[0] = sys.argv[0][1:]

    os.environ['METHOD'] = line[0].strip().upper()
    while True:
        hdr = sys.stdin.readline().strip()
        if not hdr:
            break
        k, v = hdr.split(':', 1)
        os.environ[k.strip().upper()] = v.strip()

    print('HTTP/1.0 200 OK')

    if 1 == len(sys.argv) and '/' in sys.argv[0]:
        mime_type = mime.guess_type(sys.argv[0])[0]
        mime_type = mime_type if mime_type else 'application/octet-stream'
        print('Content-Type: {}\n'.format(mime_type))
        sys.stdout.flush()

        with open(os.path.join(os.getcwd(), sys.argv[0]), 'rb') as fd:
            length = 0
            while True:
                buf = fd.read(2**20)
                if not buf:
                    break

                conn.sendall(buf)
                length += len(buf)

            logger()('client%s file(%s) bytes(%d)', addr, sys.argv[0], length)
    else:
        print()
        sys.stdout.flush()
        logger(sys.argv[0])
        runpy.run_module(sys.argv[0], run_name='__main__')
        sys.stdout.flush()

        logger()('client%s cmd(%s)', addr, ' '.join(sys.argv))


def jobs():
    for job in json.load(open(args.jobs)):
        if os.fork():
            continue

        sys.argv = job['cmd'].split()

        logger(sys.argv[0])

        if 'stdin' in job:
            sys.stdin = open(os.path.join(os.getcwd(), job['stdin']), 'r')
        if 'stdout' in job:
            sys.stdout = open(os.path.join(os.getcwd(), job['stdout']), 'w')

        runpy.run_module(sys.argv[0], run_name='__main__')

        sys.stdout.flush()
        sys.stdout.close()

        return logger()('cmd(%s) stdin(%s) stdout(%s)',
                        job['cmd'], job['stdin'], job['stdout'])


def main():
    logging.basicConfig(format='%(asctime)s %(process)d : %(message)s')
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    if args.logs and not os.path.isdir(args.logs):
        os.mkdir(args.logs)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', args.port))
    sock.listen()

    next_timestamp = 0
    while True:
        r, _, _ = select.select([sock], [], [], 1)

        if time.time() > next_timestamp:
            next_timestamp = int(time.time() / 60) * 60 + 60

            if args.jobs and 0 == os.fork():
                return jobs()

        if sock in r:
            conn, addr = sock.accept()

            if all([not addr[0].startswith(ip) for ip in args.allowed_ip]):
                logger()('rejected%s', addr)
                conn.close()
                continue

            if os.fork():
                conn.close()
                continue

            sock.close()
            sock = ssl.wrap_socket(conn, 'ssl.key', 'ssl.cert', True)
            return server(sock, addr)


if __name__ == '__main__':
    # openssl req -x509 -nodes -subj / -sha256 --keyout ssl.key --out ssl.cert

    args = argparse.ArgumentParser()
    args.add_argument('--ip', dest='ip')
    args.add_argument('--port', dest='port', type=int)

    args.add_argument('--jobs', dest='jobs')
    args.add_argument('--logs', dest='logs')
    args.add_argument('--allowed_ip', dest='allowed_ip', default='')

    args.add_argument('--cmd', dest='cmd')
    args.add_argument('--fetch', dest='fetch')

    args = args.parse_args()
    logger()

    args.allowed_ip = set([ip.strip() for ip in args.allowed_ip.split(',')])

    if args.cmd:
        cmd = Cmd(args.ip, args.port, args.cmd)

        if not os.isatty(0):
            cmd.stdin.write(sys.stdin.read())

        while os.write(1, cmd.stdout.read().encode()):
            pass
    elif args.fetch:
        os.write(1, fetch(args.ip, args.port, args.fetch))
    else:
        mime = mimetypes.MimeTypes()
        main()
