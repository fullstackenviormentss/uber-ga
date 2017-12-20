"""
Deterministic mutation noise generation.
"""

import numpy as np
import tensorflow as tf

# pylint: disable=R0903
class NoiseSource:
    """
    A deterministic noise generator.
    """
    def __init__(self, seed=1337, size=(1 << 26), max_cache=(1<<29)):
        state = np.random.RandomState(seed=seed)
        self.noise = state.normal(size=size).astype('float32')
        self._cache = {}
        self._max_cache = max_cache

    def block(self, size, seed):
        """
        Generate a block of noise for the given seed.
        """
        state = np.random.RandomState(seed=seed)
        indices = state.randint(0, high=self.noise.shape[0], size=size)
        return self.noise[indices]

    def cumulative_block(self, size, mutations):
        """
        Generate a block of noise representing the sum of
        the blocks of noise generated by the seeds.

        Args:
          size: the size of the parameter vectors.
          mutations: a sequence of (seed, scale) tuples.

        This caches seed prefixes (i.e. the sum of all but
        the last seed).
        """
        if not mutations:
            return np.zeros(size, dtype='float32')
        final_block = self.block(size, mutations[-1][0]) * mutations[-1][1]
        if len(mutations) == 1:
            return final_block
        cache_key = tuple(mutations[:-1])
        if cache_key in self._cache:
            return self._cache[cache_key] + final_block
        prefix = np.sum(self.block(size, seed) * scale for seed, scale in mutations[:-1])
        self._cache[cache_key] = prefix
        return prefix + final_block

    def _evict_cache(self):
        while self._cache_size() > self._max_cache:
            del self._cache[self._cache.keys()[0]]

    def _cache_size(self):
        return sum(x.shape[0] for x in self._cache.values())

class NoiseAdder:
    """
    A context manager that temporarily adds noise to some
    TensorFlow variables.
    """
    def __init__(self, sess, variables, noise):
        self._sess = sess
        self._variables = variables
        self._noise = noise
        self._placeholders = [tf.placeholder(v.dtype, shape=v.get_shape()) for v in variables]
        self._assigns = [tf.assign(v, ph) for v, ph in zip(variables, self._placeholders)]
        self._seeds = None
        self._old_vals = None

    def seed(self, seeds):
        """
        Update the current seed and return self.
        """
        self._seeds = seeds
        return self

    def __enter__(self):
        size = int(np.sum(np.prod(x.value for x in v.get_shape()) for v in self._variables))
        noise = self._noise.cumulative_block(size, self._seeds)
        self._old_vals = self._sess.run(self._variables)
        new_vals = []
        for old_val in self._old_vals:
            sub_size = int(np.prod(old_val.shape))
            new_vals.append(old_val + noise[:sub_size].reshape(old_val.shape))
            noise = noise[sub_size:]
        self._set_values(new_vals)
        return self

    def __exit__(self, *_):
        self._set_values(self._old_vals)

    def _set_values(self, values):
        self._sess.run(self._assigns, feed_dict=dict(zip(self._placeholders, values)))

def noise_seeds(num_seeds):
    """
    Generate random seeds for NoiseSource.block().
    """
    return [int(x) for x in np.random.randint(0, high=2**32, size=num_seeds)]
