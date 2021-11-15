from multiprocessing import Queue
import threading
import logging
import json
import socket
import time

class doorbell:
    def __init__(self, parent):
        self.parent = parent
        self.logger = parent.logger

        self.sound = 10
        self.volume = 10

    ## TODO: rewrite
    def set_doorbell_sound(self, sound, volume):
        if sound:
            self.sound = sound
            param = [1, str(self.sound)]
            self.parent.queue_cmd('set_doorbell_sound', param, True)
        if volume:
            self.volume = volume
            self.parent.queue_cmd('set_doorbell_volume', [self.volume])

    def set_doorbell_push(self, push):
        if push != 'on' or push != 'off':
            self.logger.error('Invalid doorbell param')
        self.parent.queue_cmd('set_doorbell_push', push, True)

    def get_doorbell_push(self):
        self.parent.queue_cmd('get_doorbell_push', None, True)

class alarm:
    def __init__(self, parent):
        self.parent = parent

class clock:
    def __init__(self, parent):
        self.parent = parent

class lightring:
    def __init__(self, parent):
        self.parent = parent

        self.color = 0xffffff
        self.brightness = 54

    def set_color(self, color):
        self.set_all(color, self.brightness)

    def set_brightness(self, brightness):
        self.set_all(self.color, brightness)

    def set_all(self, color, brightness):
        self.parent.queue_cmd('set_rgb', (brightness << 24) + int(color, 16), True)

    def handle_props(self, props):
        for key, value in props.items():
            if key == 'rgb':
                self.brightness, self.color = divmod(value, 0x1000000)
                self.color = self.color ^ self.brightness

class gateway:
    def __init__(self, ip, port):
        # Network config
        self.ip = ip
        self.port = port

        # Queue
        self.queue = Queue(maxsize=100)

        # Miio config
        self.maxlen = 1480
        self.id = 0

        # Logger
        self.logger = logging.getLogger(__name__)

        # Heartbeat timestamps
        self.lastping = 0
        self.lastpong = 0
        self.warn_offline = True

        # Socket
        self.socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.socket.settimeout(1)

        # Callback
        self.callback = None

        # Sub-functions
        self.light_ring = lightring(self)
        self.doorbell = doorbell(self)
        self.alarm = alarm(self)
        self.clock = clock(self)

    # Msg is a device event
    def msg_event(self, msg):
        event = '.'.join(msg['method'].split('.')[1:])
        data = {
            'event': event,
            'device_id': msg['sid'],
            'device_model': msg['model'],
            'params': msg['params']
        }
        self.logger.debug(f'callback for event {event}')
        self.callback('event', data)

    def msg_props(self, msg):
        data = {
            'device_id': msg.get('sid'),
            'device_model': msg['model'] if 'model' in msg else 'internal',
            'props': msg['params']
        }

        # Props dispatcher, for own properties
        if data['device_model'] in ['internal', 'lumi.gateway.mieu01']:
            if 'rgb' in data['props']:
                self.light_ring.handle_props(data['props'])

        # Discard device_log properties
        if 'device_log' in data['props']:
            return

        self.logger.debug(f'callback for {data["device_model"]} properties')
        self.callback('properties', data)

    def msg_otc(self, msg):
        data = {
            'device_id': msg.get('sid'),
            'device_model': msg['model'] if 'model' in msg else 'internal',
            'status': msg['params']
        }

        self.logger.debug(f'callback for {data["device_model"]} status')
        self.callback('status', data)

    def recv_msg(self, msg):
        method = msg.get('method')

        # If there's no method, there's nothing to handle
        if not method:
            self.logger.warning(f'msg with no method: {msg}')
            return

        # Remove id (useless)
        del msg['id']

        # Msg dispatcher
        self.logger.debug(f'msg=> {msg}')

        ## Keepalive events => DGAF
        if method == 'event.keepalive':
            return

        ## local events (query_time, query_status, time, status) => DGAF
        elif method.startswith('local.'):
            return

        ## sync events (getUserSceneInfo, upLocalSceneRunningLog, check_dev_version, neighborDevInfo) => DGAF
        elif method.startswith('_sync.'):
            return

        ## async events (store) => DGAF
        elif method.startswith('_async.'):
            return

        ## props (properties???)
        ## don't know what to do with that
        ## apparently, if there's no model, it's internal
        elif method == 'props':
            self.msg_props(msg)

        ## otc events (log) => parse device status
        elif method.startswith('_otc.'):
            self.msg_otc(msg)

        ## pong/heartbeat => just update the timer
        elif method == 'internal.PONG' or method == 'event.heartbeat':
            self.pong()

        ## device event => handle that in dedicated function
        elif method.startswith('event.'):
            self.msg_event(msg)

        ## that should not happen
        else:
            self.logger.warn(f'unknown event {method} received')

    def msg_decode(self, data):
        #self.logger.debug(f'Decode called with {data.decode()}')

        if data[-1] == 0:
            data = data[:-1]
        res = [{''}]

        try:
            fixed_str = data.decode().replace('}{', '},{')
            res = json.loads(f'[{fixed_str}]')
        except:
            self.logger.warning('Bad JSON received')

        return res

    def msg_encode(self, data):
        if data.get('method', '') == "internal.PING":
            msg = data
        else:
            if self.id != 12345:
                self.id = self.id + 1
            else:
                self.id = self.id + 2
            if self.id > 999999999:
                self.id = 1
            msg = {'id': self.id}
            msg.update(data)
        return json.dumps(msg).encode()


    def callback(self, topic, value):
        if self.callback:
            self.callback(topic, value)
        else:
            self.logger.warning('no callback function defined')

    def set_callback(self, callback):
        self.callback = callback

    def send_cmd(self, cmd, params = None, expect_result = False):
        self.logger.debug(f'sending cmd {cmd} (params={params})')
        data = {}

        if params:
            encoded = self.msg_encode({'method': cmd, 'params': params})
        else:
            encoded = self.msg_encode({'method': cmd})
        self.socket.sendto(encoded, (self.ip, self.port))
        self.socket.settimeout(2)

        # Wait for result
        try:
            msgs = self.msg_decode(self.socket.recvfrom(self.maxlen)[0])
            while len(msgs) > 0:
                msg = msgs.pop()
                if expect_result and 'result' in msg:
                    self.logger.debug(f'got result for cmd {cmd}')
                    data = {'cmd': cmd, 'result': msg['result'][0]}
                    if not cmd == 'internal.PING':
                        self.callback(f'result', data)
                else:
                    # Other message/event
                    self.recv_msg(msg)
        except socket.timeout:
            self.logger.warning(f'no reply for cmd {cmd}')

        self.socket.settimeout(1)
        return data

    def queue_cmd(self, cmd, params = None, expect_result = False):
        self.queue.put({'cmd': cmd, 'params': params, 'expect_result': expect_result})

    def ping(self):
        self.queue_cmd('internal.PING', None, True)
        self.lastping = time.time()

    def pong(self):
        self.logger.debug('hearbeat received')
        self.lastpong = time.time()

    def run(self):
        while self.thread_running:
            # Manage hearbeat (ping)
            if (time.time() - self.lastping) > 200:
                self.ping()
                self.warn_offline = True

            # Send queued messages
            while not self.queue.empty():
                req = self.queue.get()
                res = self.send_cmd(req['cmd'], req.get('params'), req.get('expect_result', False))
                if req['cmd'] == 'internal.PING' and res.get('result') == 'online':
                    self.pong()

            # Receive messages
            try:
                msgs = self.msg_decode(self.socket.recvfrom(self.maxlen)[0])
                while len(msgs) > 0:
                    self.recv_msg(msgs.pop())
            except socket.timeout:
                pass

            # Manage heartbeat (pong)
            if (time.time() - self.lastpong) > 300:
                if self.warn_offline:
                    self.logger.debug('gateway is offline!')
                    self.warn_offline = False

    def start(self):
        self.thread_running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.thread_running = False
