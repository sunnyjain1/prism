from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

# Keep rate-limit policy centralized in config while using client IP as the throttle key.
limiter = Limiter(key_func=get_remote_address, default_limits=[])
rate_limit_exceeded_handler = _rate_limit_exceeded_handler
