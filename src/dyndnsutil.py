# Utility stuff for dyndns updates

from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network

from aiohttp import BasicAuth, ClientSession


# Represents a generic DynDNS target (provider + identifying token + ip addresses)
class DynDNSTarget:
    def __init__(self, name: str, ipv6_suffix: IPv6Address | None = None):
        # Some identifying name
        self.name: str = name

        # Optional: IPv6-Suffix
        # If set, on an update it is combined with the given ipv6 prefix to create the actual new ipv6
        # If unset, the given ipv6 is used
        self.__ipv6_suffix: IPv6Address | None = ipv6_suffix

        self._new_ipv4: IPv4Address | None = None
        self._new_ipv6: IPv6Address | None = None
        self._last_successful_ipv4: IPv4Address | None = None
        self._last_successful_ipv6: IPv6Address | None = None

    @property
    def needs_update(self) -> bool:
        return (
            self._new_ipv4 != self._last_successful_ipv4
            or self._new_ipv6 != self._last_successful_ipv6
        )

    # Update the ips of this target
    # Does NOT actually perform the update request!
    def update_ips(
        self,
        ipv4: IPv4Address | None = None,
        ipv6: IPv6Address | None = None,
        ipv6_prefix: IPv6Network | None = None,
    ):
        self._new_ipv4 = ipv4

        if self.__ipv6_suffix is not None:
            # Ignore ipv6 and construct ip from prefix and suffix instead
            if ipv6_prefix is not None:
                self._new_ipv6 = ip_from_network_and_suffix(
                    ipv6_prefix, self.__ipv6_suffix
                )
            else:
                self._new_ipv6 = None
        else:
            self._new_ipv6 = ipv6

    # Do an actual update request with the new ips
    # Sets last successful ips if the request was successful
    # Must be passed a aiohttp.ClientSession to use for the request
    # Returns True if the request was successfull
    # May raise all exceptions aiohttp.ClientSession.request may raise
    async def do_update(self, session: ClientSession) -> bool:
        self._last_successful_ipv4 = self._new_ipv4
        self._last_successful_ipv6 = self._new_ipv6
        return True


# Represents an IONOS DynDNS target
# See https://developer.hosting.ionos.de/docs/dns -> Dynamic DNS
class IonosDynDNSTarget(DynDNSTarget):
    __URL: str = "https://api.hosting.ionos.com/dns/v1/dyndns"

    def __init__(self, q: str, name: str, ipv6_suffix: IPv6Address | None = None):
        super().__init__(name, ipv6_suffix)
        self.__q: str = q

    async def do_update(self, session: ClientSession) -> bool:
        params = {"q": self.__q}
        if self._new_ipv4 is not None:
            params["ipv4"] = self._new_ipv4.compressed
        if self._new_ipv6 is not None:
            params["ipv6"] = self._new_ipv6.compressed

        async with session.get(self.__URL, params=params) as response:
            response_ok = response.ok

        if response_ok:
            # Success
            self._last_successful_ipv4 = self._new_ipv4
            self._last_successful_ipv6 = self._new_ipv6

        return response_ok


# Represents an Namecheap DynDNS target
# See https://www.namecheap.com/support/knowledgebase/article.aspx/29/11/how-to-dynamically-update-the-hosts-ip-with-an-https-request/
class NamecheapDynDNSTarget(DynDNSTarget):
    __URL: str = "https://dynamicdns.park-your-domain.com/update"

    def __init__(
        self,
        ddns_password: str,
        host: str,
        domain: str,
        ipv6_suffix: IPv6Address | None = None,
    ):
        super().__init__(f"{host}.{domain}")
        self.__ddns_password: str = ddns_password
        self.__host: str = host
        self.__domain: str = domain

    # Namecheap currently only supports ipv4, ignore changes to ipv6
    # ! remove this when Namecheap supports ipv6 dyndns
    @property
    def needs_update(self):
        return self._new_ipv4 != self._last_successful_ipv4

    async def do_update(self, session: ClientSession) -> bool:
        params = {
            "host": self.__host,
            "domain": self.__domain,
            "password": self.__ddns_password,
        }
        if self._new_ipv4 is not None:
            params["ip"] = self._new_ipv4.compressed

        async with session.get(self.__URL, params=params) as response:
            response_ok = response.ok

        if response_ok:
            # Success
            self._last_successful_ipv4 = self._new_ipv4
            self._last_successful_ipv6 = self._new_ipv6

        return response_ok


# Represents an INWX DynDNS target
# See https://www.inwx.de/offer/dyndns
class INWXDynDNSTarget(DynDNSTarget):
    __URL: str = "https://dyndns.inwx.com/nic/update"

    def __init__(
        self, username: str, password: str, ipv6_suffix: IPv6Address | None = None
    ):
        super().__init__(username, ipv6_suffix)
        self.__basic_auth: BasicAuth = BasicAuth(username, password)

    async def do_update(self, session: ClientSession) -> bool:
        params = {}
        if self._new_ipv4 is not None:
            params["myip"] = self._new_ipv4.compressed
        if self._new_ipv6 is not None:
            params["myipv6"] = self._new_ipv6.compressed

        async with session.get(
            self.__URL, auth=self.__basic_auth, params=params
        ) as response:
            response_ok = response.ok

        if response_ok:
            # Success
            self._last_successful_ipv4 = self._new_ipv4
            self._last_successful_ipv6 = self._new_ipv6

        return response_ok


# Construct ip address from network and suffix
# Essentially bitwise-ors the network-address and suffix;
# making sure there is no overlap is the responsibility of the caller
def ip_from_network_and_suffix(
    network: IPv4Network | IPv6Network,
    suffix: IPv4Address | IPv6Address,
) -> IPv4Address | IPv6Address:
    if network.version != suffix.version:
        raise TypeError("Network and suffix must be of same version (v4 or v6)")

    ip: int = int.from_bytes(
        network.network_address.packed, byteorder="big", signed=False
    ) | int.from_bytes(suffix.packed, byteorder="big", signed=False)

    # Make sure we return the correct version
    if network.version == 4:
        return IPv4Address(ip)
    else:
        return IPv6Address(ip)
