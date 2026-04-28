"""Shared runtime state populated during app lifespan."""

from typing import Optional

from redis.asyncio import Redis

redis_client: Optional[Redis] = None
providers: dict = {}
health_tracker = None
routing_policy = None
