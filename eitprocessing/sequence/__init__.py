"""
Copyright 2023 Netherlands eScience Center and Erasmus University Medical Center.
Licensed under the Apache License, version 2.0. See LICENSE for details.

This file contains methods related to parts of electrical impedance tomographs
as they are read.
"""
from __future__ import annotations
import bisect
import copy
import warnings
from dataclasses import dataclass
from dataclasses import field
import numpy as np
from ..eit_data import EITData
from ..eit_data.eit_data_variant import EITDataVariant
from ..eit_data.event import Event
from ..eit_data.phases import PhaseIndicator
from ..eit_data.timing_error import TimingError
from ..helper import NotEquivalent


@dataclass(eq=False)
class Sequence:
    """Sequence of timepoints containing EIT and/or waveform data.

    A Sequence is a representation of a continuous set of data points, either EIT frames,
    waveform data, or both. A Sequence can consist of an entire measurement, a section of a
    measurement, a single breath, or even a portion of a breath.
    A sequence can be split up into separate sections of a measurement or multiple (similar)
    Sequence objects can be merged together to form a single Sequence.

    EIT data is contained within Framesets. A Frameset shares the time axis with a Sequence.

    Args:
        label (str): description of object for human interpretation.
            Defaults to "Sequence_<unique_id>".
        framesets (dict[str, Frameset]): dictionary of framesets
        events (list[Event]): list of Event objects in data
        timing_errors (list[TimingError]): list of TimingError objects in data
        phases (list[PhaseIndicator]): list of PhaseIndicator objects in data
    """

    label: str | None = None
    eit_data: EITData | None = None

    def __post_init__(self):
        if self.label is None:
            self.label = f"Sequence_{id(self)}"

    def __eq__(self, other) -> bool:
        # TODO: rewrite
        try:
            self.check_equivalence(self, other)
        except (TypeError, ValueError, AttributeError):
            return False

        for attr in ["nframes", "framerate", "framesets", "vendor"]:
            if getattr(self, attr) != getattr(other, attr):
                return False
        for attr in ["time", "phases", "events", "timing_errors"]:
            self_attr, other_attr = getattr(self, attr), getattr(other, attr)
            if len(self_attr) != len(other_attr):
                return False
            if not np.all(np.equal(self_attr, other_attr)):
                return False

        return True

    @staticmethod
    def check_equivalence(a: Sequence, b: Sequence, raise_=False):
        """Checks whether content of two Sequence objects is equivalent."""
        # TODO: rewrite
        try:
            if any((a.eit_data, b.eit_data)):
                if not all((a.eit_data, b.eit_data)):
                    raise NotEquivalent("Only one of the sequences contains EIT data")

                EITData.check_equivalence(a.eit_data, b.eit_data, raise_=raise_)

        except NotEquivalent:
            # re-raises the exceptions if raise_ is True, or returns False
            if raise_:
                raise
            return False

        return True

    def __add__(self, other: Sequence) -> Sequence:
        return self.concatenate(self, other)

    @classmethod
    def concatenate(
        cls,
        a: Sequence,
        b: Sequence,
        label: str | None = None,
    ) -> Sequence:
        """Create a merge of two Sequence objects."""
        # TODO: rewrite
        try:
            Sequence.check_equivalence(a, b, raise_=True)
        except NotEquivalent as e:
            raise type(e)(f"Sequences could not be merged: {e}") from e

        if a.eit_data:
            eit_data = EITData.concatenate(a.eit_data, b.eit_data)
        else:
            eit_data = None

        def merge_attribute(attr: str) -> list:
            a_items = getattr(a, attr)
            b_items = getattr(b.deepcopy(), attr)  # deepcopy avoids overwriting
            for item in b_items:
                item.index += a.nframes
                item.time = time[item.index]
            return a_items + b_items

        label = label or f"Concatenation of <{a.label}> and <{b.label}>"

        return a.__class__(label=label, eit_data=eit_data)

    def select_by_index(
        self,
        indices: slice,
        label: str | None = None,
    ):
        # TODO: reconsider usage, rewrite to use EITData, SparseData and ContinuousData
        if not isinstance(indices, slice):
            raise NotImplementedError("Slicing only implemented using a slice object")
        if indices.step not in (None, 1):
            raise NotImplementedError(
                "Skipping intermediate frames while slicing is not implemented."
            )
        if indices.start is None:
            indices = slice(0, indices.stop, indices.step)
        if indices.stop is None:
            indices = slice(indices.start, self.nframes, indices.step)

        obj = self.deepcopy()
        obj.time = self.time[indices]
        obj.nframes = len(obj.time)
        obj.eit_data = {k: v[indices] for k, v in self.eit_data.items()}
        obj.label = (
            f"Slice ({indices.start}-{indices.stop}) of <{self.label}>"
            if label is None
            else label
        )

        range_ = range(indices.start, indices.stop)
        for attr in ["events", "timing_errors", "phases"]:
            setattr(obj, attr, [x for x in getattr(obj, attr) if x.index in range_])
            for x in getattr(obj, attr):
                x.index -= indices.start

        return obj

    def __getitem__(self, indices: slice):
        # TODO: reconsider API
        return self.select_by_index(indices)

    def select_by_time(  # pylint: disable=too-many-arguments
        self,
        start: float | int | None = None,
        end: float | int | None = None,
        start_inclusive: bool = True,
        end_inclusive: bool = False,
        label: str | None = None,
    ) -> Sequence:
        """Select subset of sequence by the `Sequence.time` information (i.e.
        based on the time stamp).

        Args:
            start (float | int | None, optional): starting time point.
                Defaults to None.
            end (float | int | None, optional): ending time point.
                Defaults to None.
            start_inclusive (bool, optional): include starting timepoint if
                `start` is present in `Sequence.time`.
                Defaults to True.
            end_inclusive (bool, optional): include ending timepoint if
                `end` is present in `Sequence.time`.
                Defaults to False.

        Raises:
            ValueError: if the Sequence.time is not sorted

        Returns:
            Sequence: a slice of `self` based on time information given.
        """

        # TODO: rewrite

        if not any((start, end)):
            warnings.warn("No starting or end timepoint was selected.")
            return self
        if not np.all(np.sort(self.time) == self.time):
            raise ValueError(
                f"Time stamps for {self} are not sorted and therefor data"
                "cannot be selected by time."
            )

        if start is None:
            start_index = 0
        elif start_inclusive:
            start_index = bisect.bisect_left(self.time, start)
        else:
            start_index = bisect.bisect_right(self.time, start)

        if end is None:
            end_index = len(self)
        elif end_inclusive:
            end_index = bisect.bisect_right(self.time, end) - 1
        else:
            end_index = bisect.bisect_left(self.time, end) - 1

        return self.select_by_index(slice(start_index, end_index), label=label)

    def deepcopy(
        self,
        label: str | None = None,
        relabel: bool | None = True,
    ) -> Sequence:
        """Create a deep copy of `Sequence` object.

        Args:
            label (str): Create a new `label` for the copy.
                Defaults to None, which will trigger behavior described for relabel (below)
            relabel (bool): If `True` (default), the label of self is re-used for the copy,
                otherwise the following label is assigned f"Deepcopy of {self.label}".
                Note that this setting is ignored if a label is given.

        Returns:
            Sequence: a deep copy of self
        """

        # TODO: rewrite for efficiency

        obj = copy.deepcopy(self)
        if label:
            obj.label = label
        elif relabel:
            obj.label = f"Copy of <{self.label}>"
        return obj
