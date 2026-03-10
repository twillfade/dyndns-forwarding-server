#!/usr/bin/env python3

# Small http server for forwarding FritzBox dyndns updates to several dyndns providers
# Built using FastAPI
# Runs uvicorn webserver

import asyncio
import hashlib
import logging
import os
import secrets
from ipaddress import (
    AddressValueError,
    IPv4Address,
    IPv6Address,
    IPv6Network,
    NetmaskValueError,
)
from typing import Annotated

import aiohttp
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from dyndnsutil import (
    DynDNSTarget,
    INWXDynDNSTarget,
    IonosDynDNSTarget,
    NamecheapDynDNSTarget,
)

### EDIT THE FOLLOWING SECTION

# Read provider specific stuff from env
# e.g.
# DYNDNS_IONOS_Q_1 = os.getenv("DYNDNS_IONOS_Q_1", "")

# Append your dyndns targets to this list
dyndns_targets: list[DynDNSTarget] = []
# dyndns_targets.append(IonosDynDNSTarget(DYNDNS_IONOS_Q_1, "name", IPv6Address("::dead:beef")))

### DON'T EDIT BELOW

# Read general settings from env
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
ACCESS_LOG = False if os.getenv("ACCESS_LOG", "").lower() in ["false", "0"] else True
BIND = os.getenv("BIND", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
PASS_SHA256 = os.getenv(
    "PASS_SHA256",
    hashlib.sha256("password".encode("utf8")).hexdigest(),
)

app = FastAPI(debug=False, openapi_url=None, docs_url=None, redoc_url=None)

logger = logging.getLogger("DynDNS Updater Server")
logger.setLevel(logging.getLevelNamesMapping()[LOG_LEVEL.upper()])
lh = logging.StreamHandler()
lh.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
logger.addHandler(lh)

# Just simple HTTP basic auth
# Server is most likely deployed locally without tls anyway,
# so we're just trying to prevent the most basic of abuse
security = HTTPBasic()


@app.get("/dyndns")
async def dyndns(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
    ipv4: str,
    ipv6: str,
    ipv6prefix: str,
):
    if not secrets.compare_digest(
        hashlib.sha256(credentials.password.encode("utf8")).hexdigest(), PASS_SHA256
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )
    # Parameters are mandatory, but might be empty
    # Because we might not be able to change how the requester builds requests (FritzBox ...), lets ignore wrong/empty values
    try:
        ipv4 = IPv4Address(ipv4)
    except AddressValueError:
        ipv4 = None
    try:
        ipv6 = IPv6Address(ipv6)
    except AddressValueError:
        ipv6 = None
    try:
        ipv6prefix = IPv6Network(ipv6prefix, strict=False)
    except (AddressValueError, NetmaskValueError):
        ipv6prefix = None

    if ipv4 is None and ipv6 is None and ipv6prefix is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One of ipv4, ipv6 or ipv6prefix has to be set and be valid",
        )

    logger.info(
        f"Received dyndns update request from {credentials.username}: IPv4={ipv4} IPv6={ipv6} IPv6-Prefix={ipv6prefix}"
    )

    # The FritzBox (usually) sends two update requests: One without ipv6 and one with (Yes, it's stupid. I know).
    # For now lets ignore the one without ipv6 to avoid sending multiple requests for the FritzBox domain name
    # ! Keep an eye on this and remove it if it causes missed updates. Who knows how the FritzBox logic might be changed ...
    if ipv4 is not None and ipv6 is None and ipv6prefix is not None:
        logger.info(
            f"No ipv6 but everything else, is the FritzBox being stupid again? Ignoring this request."
        )
        return Response(status_code=status.HTTP_200_OK)

    # Update targets ips
    updated_targets: list[DynDNSTarget] = []
    for target in dyndns_targets:
        target.update_ips(ipv4, ipv6, ipv6prefix)
        if target.needs_update:
            updated_targets.append(target)
        else:
            logger.info(f"{target.name} does not need an update, skipping")

    # Do update requests for every target that actually needs an update
    # ? Maybe do this in background task
    # ? Specifiying timeouts may be necessary, because after the daily IP reconnect the connection might hang for a bit
    async with aiohttp.ClientSession(
        raise_for_status=True, cookie_jar=aiohttp.DummyCookieJar()
    ) as client_session:
        responses = await asyncio.gather(
            *(target.do_update(client_session) for target in updated_targets),
            return_exceptions=True,
        )

    # Parse the responses
    error_codes: set[int] = set()
    for i in range(len(responses)):
        target = updated_targets[i]
        response = responses[i]

        if isinstance(response, aiohttp.ClientResponseError):
            logger.warning(
                f"{target.name} update request returned http status code {response.status}"
            )
            error_codes.add(response.status)
        elif isinstance(response, Exception):
            logger.warning(f"{target.name} update request raised an exception: {e}")
            error_codes.add(500)
        # Response is bool
        elif response:
            logger.info(f"{target.name} update request was successfull")
        # Since all http status codes >= 400 raise an exception (ClientSession(raise_for_status=True))
        # and redirects are followed / raise TooManyRedirects this should only be reached
        # if one of the providers implements some cursed response logic
        # (e.g. sending HTTP 200 but putting "error" in the body or something)
        else:
            logger.warning(f"{target.name} update request failed")
            error_codes.add(500)

    # Return useful response code so requester can use their own retry logic
    if len(error_codes) == 0:
        return Response(status_code=status.HTTP_200_OK)
    elif len(error_codes) == 1 and status.HTTP_429_TOO_MANY_REQUESTS in error_codes:
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    else:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# If run from command line, start webserver
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=BIND,
        port=PORT,
        log_level=LOG_LEVEL,
        access_log=ACCESS_LOG,
    )
