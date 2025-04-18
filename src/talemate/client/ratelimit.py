from limits.strategies import MovingWindowRateLimiter
from limits.storage import MemoryStorage
from limits import parse, RateLimitItemPerMinute
import time

__all__ = ["CounterRateLimiter"]

class CounterRateLimiter:
    def __init__(self, rate_per_minute:int=99999, identifier:str="ratelimit"):
        self.storage = MemoryStorage()
        self.limiter = MovingWindowRateLimiter(self.storage)
        self.rate = RateLimitItemPerMinute(rate_per_minute, 1)
        self.identifier = identifier
        
    def update_rate_limit(self, rate_per_minute:int):
        """Update the rate limit with a new value"""
        self.rate = RateLimitItemPerMinute(rate_per_minute, 1)
        
    def increment(self) -> bool:
        limiter = self.limiter
        rate = self.rate
        return limiter.hit(rate, self.identifier)
    
    def reset_time(self) -> float:
        """
        Returns the time in seconds until the rate limit is reset
        """
        
        window = self.limiter.get_window_stats(self.rate, self.identifier)
        return window.reset_time - time.time()