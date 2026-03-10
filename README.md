# DynDNS Update Forwarding Server

Small http server that receives dyndns update requests and forwards them to multiple DynDNS providers.

Written in Python using `aiohttp` and `fastapi`; running on `uvicorn`.

Tailored towards receiving requests from a FritzBox.

## Usage

1. Copy files in [src/](./src/) to server (recommended location: `/opt/dyndns-update-server/`)
1. Install dependencies:
   - [fastapi](https://fastapi.tiangolo.com/#installation)
   - [uvicorn](https://uvicorn.dev/installation/)
   - [aiohttp](https://docs.aiohttp.org/en/stable/index.html#library-installation)
1. Create and configure environment file (see top of [dyndns-update-server.py](./src/dyndns-update-server.py) for possible vars).
   Optionally create and configure secrets environment file for tokens/etc. and restrict it's file permissions.
1. Copy [dyndns-update-server.service](./systemd/dyndns-update-server.service) to `/etc/systemd/system/` and edit it for your configuration
  (**HIGHLY RECOMMENDED** to run service as an unprivileged user!)
1. Add your provider specific code and stuff to the top of [dyndns-update-server.py](./src/dyndns-update-server.py)
   (Below `### EDIT THE FOLLOWING SECTION`)
1. Enable service with `systemctl`

## DynDNS failures in FritzBox log

The FritzBox might be sending requests right after a reconnect, upon which requests initiated by this server might hang for a while.
This might cause the FritzBox to timeout the request, log a dyndns update failure and send another one.
This *should* be fine, unless the providers start rate limiting us ...

