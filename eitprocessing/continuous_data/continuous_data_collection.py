from typing import Any

from typing_extensions import Self

from eitprocessing.continuous_data import ContinuousData
from eitprocessing.mixins.equality import Equivalence, EquivalenceError


class ContinuousDataCollection(dict, Equivalence):
    def __setitem__(self, __key: Any, __value: Any) -> None:
        self._check_data(__value, key=__key)
        return super().__setitem__(__key, __value)

    def add(self, data: ContinuousData, overwrite: bool = False) -> None:
        self._check_data(data, overwrite=overwrite)
        return super().__setitem__(data.name, data)

    def _check_data(
        self, data: ContinuousData, key=None, overwrite: bool = False
    ) -> None:
        if not isinstance(data, ContinuousData):
            raise TypeError(f"type of `data` is {type(data)}, not 'ContinuousData'")

        if key and key != data.name:
            raise KeyError(f"'{key}' does not match variant name '{data.name}'.")

        if not overwrite and key in self:
            raise DuplicateContinuousDataName(
                f"Variant with name {key} already exists. Use `overwrite=True` to overwrite."
            )

    @classmethod
    def concatenate(cls, a: Self, b: Self) -> Self:
        try:
            cls.isequivalent(a, b, raise_=True)
        except EquivalenceError as e:
            raise EquivalenceError(
                "ContinuousDataCollections could not be concatenated"
            ) from e

        obj = ContinuousDataCollection()
        for key in a.keys() & b.keys():
            obj.add(ContinuousData.concatenate(a[key], b[key]))

        return obj


class DuplicateContinuousDataName(Exception):
    """Raised when a variant with the same name already exists in the collection."""
