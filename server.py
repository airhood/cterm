#!/usr/bin/env python3
"""Web access to explicitly registered tmux panes; never owns terminal lifetime."""
import argparse
import asyncio
import hmac
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web
import core

HTML = (Path(__file__).parent / 'web.html').read_text()
SECRET = web.AppKey('token', str)
SOCKETS = web.AppKey('sockets', set)
LOCKS = web.AppKey('locks', dict)
SECURE_COOKIE = web.AppKey('secure_cookie', bool)

def token_matches(candidate, secret):
    return hmac.compare_digest(candidate.encode('utf-8'), secret.encode('utf-8'))

@web.middleware
async def access(request, handler):
    secret = request.app[SECRET]
    if request.path == '/' and 'token' in request.query:
        if not token_matches(request.query['token'], secret):
            raise web.HTTPUnauthorized(text='Invalid access token.')
        response = web.HTTPFound('/')
        response.set_cookie('cterm', secret, httponly=True, samesite='Lax', secure=request.secure or request.app[SECURE_COOKIE])
        response.headers['Referrer-Policy'] = 'no-referrer'
        raise response
    if not token_matches(request.cookies.get('cterm', ''), secret):
        raise web.HTTPUnauthorized(text='Run cterm url on the host to retrieve your access link.')
    if request.headers.get('Origin') and urlsplit(request.headers['Origin']).netloc != request.host:
        raise web.HTTPForbidden(text='Cross-origin connections are not allowed.')
    response = await handler(request)
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                             'X-Cterm-Process': str(os.getpid()), 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY'})
    return response

async def index(request):
    return web.Response(text=HTML, content_type='text/html')

async def sessions(request):
    return web.json_response(await asyncio.to_thread(core.shared_list))

async def websocket(request):
    key = request.match_info['key']
    try:
        await asyncio.to_thread(core.target, key)
    except core.TerminalError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=65536)
    await ws.prepare(request)
    request.app[SOCKETS].add(ws)
    lock = request.app[LOCKS].setdefault(key, asyncio.Lock())
    previous = None
    try:
        while not ws.closed:
            try:
                state = await asyncio.to_thread(core.snapshot, key)
            except core.TerminalError as exc:
                await ws.send_json({'type': 'removed', 'message': str(exc)})
                await ws.close()
                break
            if state != previous:
                await ws.send_json(state)
                previous = state
            try:
                msg = await ws.receive(timeout=0.2)
            except asyncio.TimeoutError:
                continue
            if msg.type in (web.WSMsgType.CLOSED, web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                break
            if msg.type != web.WSMsgType.TEXT:
                continue
            payload = None
            try:
                payload = json.loads(msg.data)
                if not isinstance(payload, dict):
                    raise core.TerminalError('Invalid input format.')
                async with lock:
                    if payload.get('type') == 'text':
                        text = payload.get('text')
                        enter = payload.get('enter', True)
                        if not isinstance(text, str) or len(text.encode('utf-8')) > 16384 or not isinstance(enter, bool):
                            raise core.TerminalError('Input must be a string no larger than 16 KiB in UTF-8.')
                        await asyncio.to_thread(core.send_text, key, text, enter)
                    elif payload.get('type') == 'key':
                        name = payload.get('key')
                        if not isinstance(name, str):
                            raise core.TerminalError('Invalid key name.')
                        await asyncio.to_thread(core.send_key, key, name)
                    else:
                        raise core.TerminalError('Unsupported input type.')
                await ws.send_json({'type': 'ack', 'id': payload.get('id')})
            except (ValueError, core.TerminalError) as exc:
                await ws.send_json({'type': 'error', 'message': str(exc)})
    finally:
        request.app[SOCKETS].discard(ws)
    return ws

async def shutdown(app):
    await asyncio.gather(*(ws.close(code=1001, message=b'Bridge stopped') for ws in list(app[SOCKETS])))

def create_app(secret=None, secure_cookie=False):
    app = web.Application(middlewares=[access])
    app[SECRET] = secret or core.token()
    app[SECURE_COOKIE] = secure_cookie
    app[SOCKETS] = set()
    app[LOCKS] = {}
    app.router.add_get('/', index)
    app.router.add_get('/api/sessions', sessions)
    app.router.add_get('/ws/{key}', websocket)
    app.on_shutdown.append(shutdown)
    return app

def allowed_bind(value):
    address = ipaddress.ip_address(value)
    if not address.is_loopback and address not in ipaddress.ip_network('100.64.0.0/10') and address not in ipaddress.ip_network('fd7a:115c:a1e0::/48'):
        raise ValueError('Only loopback or Tailscale addresses may be used for binding.')
    return value

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', default='127.0.0.1', type=allowed_bind)
    parser.add_argument('--port', default=8765, type=int)
    parser.add_argument('--secure-cookie', action='store_true')
    args = parser.parse_args()
    web.run_app(create_app(secure_cookie=args.secure_cookie), host=args.bind, port=args.port, access_log=None, print=None, shutdown_timeout=3)
