from .base import Scheme, priority_order
from .ckks_full import CkksFull
from .fas import Fas
from .he_backend import make_backend
from .none import NoneScheme

SCHEMES = {'none': NoneScheme, 'ckks_full': CkksFull, 'fas': Fas}


def make_scheme(name, M, he=None, **kw):
    return SCHEMES[name](M, he=he, **kw)
