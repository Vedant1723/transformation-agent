"""Configuration for the organisation's Java execution service."""
import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RuntimeSettings:
    base_url: str = 'http://127.0.0.1:8090'
    transform_path: str = '/transform'
    health_path: str = '/health'
    timeout_seconds: float = 10.0
    bearer_token: str = field(default='', repr=False)

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('JAVA_RUNTIME_URL must be an HTTP(S) service URL without credentials, query or fragment.')
        for path in (self.transform_path, self.health_path):
            if not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path or '..' in path or '\\' in path:
                raise ValueError('Java runtime paths must be absolute service paths, not URLs or traversal paths.')
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ValueError('JAVA_RUNTIME_TIMEOUT_SECONDS must be greater than zero and at most 120.')
        if '\r' in self.bearer_token or '\n' in self.bearer_token:
            raise ValueError('Java runtime bearer token must not contain line breaks.')

    @classmethod
    def from_environment(cls, env=None):
        env = os.environ if env is None else env
        try:
            timeout = float(env.get('JAVA_RUNTIME_TIMEOUT_SECONDS', '10'))
        except (ValueError, TypeError):
            raise ValueError('JAVA_RUNTIME_TIMEOUT_SECONDS must be numeric.') from None
        return cls(
            base_url=env.get('JAVA_RUNTIME_URL', 'http://127.0.0.1:8090').rstrip('/'),
            transform_path=env.get('JAVA_RUNTIME_TRANSFORM_PATH', '/transform'),
            health_path=env.get('JAVA_RUNTIME_HEALTH_PATH', '/health'),
            timeout_seconds=timeout,
            bearer_token=env.get('JAVA_RUNTIME_BEARER_TOKEN', ''),
        )

    def headers(self):
        return {'Authorization': 'Bearer ' + self.bearer_token} if self.bearer_token else {}
