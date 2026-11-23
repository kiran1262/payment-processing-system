"""Trusted reverse-proxy client IP resolution."""
from __future__ import annotations

import ipaddress
from ipaddress import IPv4Address, IPv6Address, IPv4Network, IPv6Network


def _is_trusted(address: IPv4Address | IPv6Address, networks) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def resolve_forwarded_client_ip(
    peer_host: str,
    forwarded_for: str | None,
    trusted_networks: tuple[IPv4Network | IPv6Network, ...],
) -> str:
    """Resolve the first untrusted hop only when the immediate peer is trusted.

    Proxies must append to or overwrite X-Forwarded-For. Malformed chains are
    ignored completely. The right-to-left walk prevents trusting spoofed entries
    to the left of an untrusted hop.
    """
    if not forwarded_for or not trusted_networks:
        return peer_host
    try:
        peer = ipaddress.ip_address(peer_host)
    except ValueError:
        return peer_host
    if not _is_trusted(peer, trusted_networks):
        return peer_host
    try:
        forwarded = [ipaddress.ip_address(item.strip()) for item in forwarded_for.split(",")]
        if not forwarded or any(not item for item in forwarded):
            return peer_host
    except ValueError:
        return peer_host

    chain = [*forwarded, peer]
    for address in reversed(chain):
        if not _is_trusted(address, trusted_networks):
            return str(address)
    # If every hop is trusted, don't promote an unverified leftmost value.
    return peer_host


def resolve_vercel_client_ip(forwarded_for: str | None) -> str | None:
    """Read Vercel's platform-overwritten client IP header.

    Vercel documents that it overwrites X-Forwarded-For to prevent IP spoofing.
    Treat the header as a single IP and fail closed when it is absent or malformed.
    Do not use this helper for arbitrary, self-hosted reverse proxies.
    """
    if not forwarded_for:
        return None
    try:
        return str(ipaddress.ip_address(forwarded_for.strip()))
    except ValueError:
        return None
