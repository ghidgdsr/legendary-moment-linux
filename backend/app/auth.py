from __future__ import annotations

import ipaddress
import secrets

from fastapi import HTTPException, Request


class Auth:
    def __init__(self, token: str, allow_cidrs: str | None = None) -> None:
        self.token = token
        self.networks = []
        if allow_cidrs:
            for part in allow_cidrs.split(","):
                part = part.strip()
                if part:
                    self.networks.append(ipaddress.ip_network(part, strict=False))

    def check(self, request: Request) -> None:
        if self.networks:
            host = request.client.host if request.client else ""
            try:
                addr = ipaddress.ip_address(host)
            except ValueError:
                raise HTTPException(status_code=403, detail="来源地址不允许")
            if not any(addr in net for net in self.networks):
                raise HTTPException(status_code=403, detail="来源地址不允许")

        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="需要访问令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
        supplied = header[7:].strip()
        if not secrets.compare_digest(supplied, self.token):
            raise HTTPException(
                status_code=401,
                detail="访问令牌无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
