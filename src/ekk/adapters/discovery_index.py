"""Incremental SQLite fragment cache, fed only after current read authorization."""
from .derived_cache import DerivedCache


class DiscoveryIndex:
    def __init__(self, directory):
        self.cache = DerivedCache(directory, 'ekk.discovery-fragments/0.1')
        self.hits = self.misses = 0

    def text(self, raw):
        result = self.cache.get('utf8', raw)
        if isinstance(result, str):
            self.hits += 1
            return result
        self.misses += 1
        result = raw.decode('utf-8')
        self.cache.put('utf8', raw, result)
        return result
