"""Loading and processing binary EIT data from the Dräger Pulmovista 500"""

__version__ = "0.1"

from .frameset import Frameset
from .phases import MaxValue
from .phases import MinValue
from .reader import Reader
from .sequence import Sequence


__all__ = ['Frameset', 'MaxValue', 'MinValue', 'Reader',  'Sequence', ]