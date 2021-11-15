# python-migw

A python lib to talk with lumi's xiaomi gateway.

## Notes

* This is early software, don't expect any stability in here!
* Only tested with `lumi.gateway.mieu01`, YMMV on other gateways
* A lot of features are still missing
* It requires [roth-m's version of miio_client](https://github.com/roth-m/miioclient-mqtt)
* * As such, it will not work on stock firmware due to the lack of cryptography
* * This code itself is based on his miioclient_mqtt code, but heavily modified
* * There's no MQTT inside this one
* As usual, PRs are welcome!

## How to use it

```python
from migw import gateway

# Callback function
def callback(name, data):
  print(f'Got callback {name} data={data}')

gateway = gateway('your_gw_ip', 54321)
gw.set_callback(callback)
gw.start()

# Set the light ring color
gw.light_ring.set_all('0xffffff', 100)

# migw runs in the background in a separate thread,
# do an infinite loop here to avoid exiting immediatly
while True:
  pass
```

### Callback names and data

| Event name | Data                                   |
|------------|----------------------------------------|
|`event`     |`event, device_id, device_model, params`|
|`properties`|`device_id, device_model, props`        |
|`status`    |`device_id, device_model, status`       |
|`result`    |`cmd, result`                           | 

#### Events

This is zigbee devices' events, such as `motion`/`no_motion` for motion sensors or `open`/`close` for magnet sensors
Details TODO

#### Properties

This is the properties of the gateway or the zigbee devices, details TODO

#### Status

This is the status of the gateway or the zigbee devices, details TODO

#### Results

This is the result of a command that generates immediate feedback, it contains the command and it's results, that's it.
