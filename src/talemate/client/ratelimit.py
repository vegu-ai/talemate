from limits import RateLimiter
from limits.strategies import MovingWindowRateLimiter
from limits.storage import MemoryStorage

__all__ = ["CounterRateLimiter"]

class CounterRateLimiter:
    def __init__(self, rate_string):
        self.limiter = RateLimiter(
            MovingWindowRateLimiter(MemoryStorage()),
            rate_string
        )
        self.counter = 0
        
    def increment(self, amount=1):
        """Try to increment counter by amount, respecting rate limit"""
        if self.limiter.hit(amount):
            self.counter += amount
            return True
        return False
        
    def get_count(self):
        return self.counter