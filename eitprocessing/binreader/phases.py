"""
Copyright 2023 Netherlands eScience Center and Erasmus University Medical Center.
Licensed under the Apache License, version 2.0. See LICENSE for details.

This file contains methods related to when electrical impedance tomographs are read.
"""

from dataclasses import dataclass


@dataclass
class PhaseIndicator:
    index: int
    time: float

    # TODO (#78): QUESTION: how does this differ the default __eq__ function for a dataclass?
    def __eq__(self, other:'PhaseIndicator') -> bool:
        if self.index != other.index:
            return False
        if self.time != other.time:
            return False
        if not isinstance(other, type(self)):
            return False
        return True


@dataclass
class MinValue(PhaseIndicator):
    pass


@dataclass
class MaxValue(PhaseIndicator):
    pass


@dataclass
class QRSMark(PhaseIndicator):
    pass
