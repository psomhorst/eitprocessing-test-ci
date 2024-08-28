from dataclasses import dataclass, field
from functools import singledispatchmethod
from typing import Literal

import numpy as np

from eitprocessing.datahandling.breath import Breath
from eitprocessing.datahandling.continuousdata import ContinuousData
from eitprocessing.datahandling.eitdata import EITData
from eitprocessing.datahandling.intervaldata import IntervalData
from eitprocessing.datahandling.sequence import Sequence
from eitprocessing.features.breath_detection import BreathDetection
from eitprocessing.features.pixel_inflation import PixelInflation
from eitprocessing.parameters import ParameterCalculation


@dataclass
class TIV(ParameterCalculation):
    """Compute the tidal impedance variation (TIV) per breath."""

    method: str = "extremes"
    breath_detection_kwargs: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        pass

    @singledispatchmethod
    def compute_parameter(
        self,
        data: ContinuousData | EITData,
    ) -> str:
        """Compute the tidal impedance variation per breath on either ContinuousData or EITData.

        Args:
            data: either continuous_data or eit_data to compute TIV on.
        """
        msg = f"This method is implemented for ContinuousData or EITData, not {type(data)}."
        raise TypeError(msg)

    @compute_parameter.register(ContinuousData)
    def compute_continuous_parameter(
        self,
        continuous_data: ContinuousData,
        tiv_method: Literal["inspiratory", "expiratory", "mean"] = "inspiratory",
    ) -> list:
        """Compute the tidal impedance variation per breath.

        Args:
            continuous_data: The ContinuousData to compute the TIV on.
            tiv_method: The label of which part of the breath the TIV
                should be determined on (inspiratory, expiratory, or mean).
                Defaults to 'inspiratory'.

        Returns:
            A list with the computed TIV values.
        """
        if self.method != "extremes":
            msg = f"Method {self.method} is not implemented."
            raise NotImplementedError(msg)

        breaths = self._detect_breaths(continuous_data)
        return self._calculate_tiv_values(
            continuous_data.values,
            continuous_data.time,
            breaths.values,
            tiv_method,
            tiv_timing="continuous",
        )

    @compute_parameter.register(EITData)
    def compute_pixel_parameter(
        self,
        eit_data: EITData,
        continuous_data: ContinuousData,
        sequence: Sequence,
        tiv_method: Literal["inspiratory", "expiratory", "mean"] = "inspiratory",
        tiv_timing: Literal["pixel", "continuous"] = "pixel",
    ) -> np.ndarray:
        """Compute the tidal impedance variation per breath on pixel level.

        Args:
            sequence: The sequence containing the data.
            eit_data: The eit pixel level date to determine the TIV of.
            continuous_data: The continuous data to determine the continuous data breaths or pixel level inflations.
            tiv_method: The label of which part of the breath the TIV should be determined on
                        (inspiratory, expiratory or mean). Defaults to 'inspiratory'.
            tiv_timing: The label of which timing should be used to compute the TIV, either based on breaths
                        detected in continuous data ('continuous') or based on pixel inflations ('pixel').
                        Defaults to 'pixel'.

        Returns:
            An np.ndarray with the computed TIV values.

        Raises:
            NotImplementedError: If the method is not 'extremes'.
            ValueError: If tiv_method is not one of 'inspiratory', 'expiratory', or 'mean'.
            ValueError: If tiv_timing is not one of 'continuous' or 'pixel'.
        """
        if self.method != "extremes":
            msg = f"Method {self.method} is not implemented."
            raise NotImplementedError(msg)

        if tiv_method not in ["inspiratory", "expiratory", "mean"]:
            msg = "tiv_method must be either 'inspiratory', 'expiratory' or 'mean'"
            raise ValueError(msg)

        if tiv_timing not in ["continuous", "pixel"]:
            msg = "tiv_timing must be either 'continuous' or 'pixel'"
            raise ValueError(msg)

        data = eit_data.pixel_impedance
        _, rows, cols = data.shape

        if tiv_timing == "pixel":
            pixel_inflations = self._detect_pixel_inflations(
                eit_data,
                continuous_data,
                sequence,
            )
            breath_data = pixel_inflations.values
        else:  # tiv_timing == "continuous"
            global_breaths = self._detect_breaths(
                continuous_data,
            )
            breath_data = global_breaths.values

        number_of_breaths = breath_data.shape[0] if tiv_timing == "pixel" else len(breath_data)
        tiv_values_array = np.empty((number_of_breaths, rows, cols), dtype=object)

        for i in range(number_of_breaths):
            for row in range(rows):
                for col in range(cols):
                    if tiv_timing == "pixel" and not breath_data[i, row, col]:
                        tiv_values_array[i, row, col] = np.nan
                    else:
                        time_series = data[:, row, col]
                        tiv_values = self._calculate_tiv_values(
                            time_series,
                            eit_data.time,
                            breath_data[:, row, col] if tiv_timing == "pixel" else breath_data,
                            tiv_method,
                            tiv_timing,
                        )
                        tiv_values_array[i, row, col] = tiv_values[i]

        return tiv_values_array.astype(float)

    def _detect_breaths(self, data: ContinuousData) -> IntervalData:
        bd_kwargs = self.breath_detection_kwargs.copy()
        breath_detection = BreathDetection(**bd_kwargs)
        return breath_detection.find_breaths(data)

    def _detect_pixel_inflations(
        self,
        eit_data: EITData,
        continuous_data: ContinuousData,
        sequence: Sequence,
    ) -> IntervalData:
        bd_kwargs = self.breath_detection_kwargs.copy()
        pi = PixelInflation(**bd_kwargs)
        return pi.find_pixel_inflations(eit_data, continuous_data, result_label="pixel inflations", sequence=sequence)

    def _calculate_tiv_values(
        self,
        data: np.ndarray,
        time: np.ndarray,
        breaths: list[Breath],
        tiv_method: str,
        tiv_timing: str,
    ) -> list:
        # start_indices = [
        #     np.argmax(time == start_time)
        #     for breath in breaths
        #     if breath is not None
        #     for start_time in [breath.start_time]
        # ]

        # middle_indices = [
        #     np.argmax(time == middle_time)
        #     for breath in breaths
        #     if breath is not None
        #     for middle_time in [breath.middle_time]
        # ]

        # end_indices = [
        #     np.argmax(time == end_time) for breath in breaths if breath is not None for end_time in [breath.end_time]
        # ]
        start_indices = [np.searchsorted(time, breath.start_time) for breath in breaths if breath is not None]
        middle_indices = [np.searchsorted(time, breath.middle_time) for breath in breaths if breath is not None]
        end_indices = [np.searchsorted(time, breath.end_time) for breath in breaths if breath is not None]

        if tiv_method == "inspiratory":
            end_inspiratory_values = data[middle_indices]
            start_inspiratory_values = data[start_indices]
            tiv_values = end_inspiratory_values - start_inspiratory_values

        elif tiv_method == "expiratory":
            start_expiratory_values = data[middle_indices]
            end_expiratory_values = data[end_indices]
            tiv_values = start_expiratory_values - end_expiratory_values

        elif tiv_method == "mean":
            start_inspiratory_values = data[start_indices]
            end_inspiratory_values = data[middle_indices]
            end_expiratory_values = data[end_indices]
            tiv_values = end_inspiratory_values - [
                np.mean(k)
                for k in zip(start_inspiratory_values, end_expiratory_values)  # noqa: B905
            ]

        if tiv_timing == "pixel":
            tiv_values = [None, *tiv_values, None]

        return tiv_values
