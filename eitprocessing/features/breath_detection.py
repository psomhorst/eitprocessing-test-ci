import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import singledispatchmethod

import numpy as np
from numpy.typing import ArrayLike
from scipy import signal

from eitprocessing.datahandling.breath import Breath
from eitprocessing.datahandling.continuousdata import ContinuousData
from eitprocessing.datahandling.intervaldata import IntervalData
from eitprocessing.datahandling.sequence import Sequence
from eitprocessing.features.moving_average import MovingAverage


@dataclass
class BreathDetection:
    """Algorithm for detecting breaths in data representing respiration.

    This algorithm detects the position of breaths in data by detecting valleys (local minimum values) and peaks (local
    maximum values) in data. When initializing `BreathDetection`, the sample frequency of the data and the minimum
    duration of a breath have to be provided. The minimum duration should be short enough to include the shortest
    expected breath in the data. The minimum duraiton is implemted as the minimum time between peaks and between
    valleys.

    Examples:
    >>> bd = BreathDetection(sample_frequency=50, minimum_duration=0.5)
    >>> breaths = bd.find_breaths(sequency=seq, continuousdata_label="global_impedance_(raw)")

    >>> global_impedance = seq.continuous_data["global_impedance_(raw)"]
    >>> breaths = bd.find_breaths(continuous_data=global_impedance)

    Args:
        sample_frequency: sample frequency of the data
        minimum_duration: minimum expected duration of breaths, defaults
        to 2/3 of a second
        averaging_window_duration: duration of window used for averaging the data, defaults to 15 seconds
        averaging_window_function: function used to create a window for averaging the data, defaults to np.blackman
        amplitude_cutoff_fraction: fraction of the median amplitude below which breaths are removed, defaults to 0.25.
        invalid_data_removal_window_length: window around invalid data in which breaths are removed, defaults to 0.5.
        invalid_data_removal_percentile: the nth percentile of values used to remove outliers, defaults to 5
        invalid_data_removal_multiplier: the multiplier used to remove outliers, defaults to 4.
    """

    # TODO: remove after continuousdata gets its own sample frequency #209
    sample_frequency: float
    minimum_duration: float = 2 / 3
    averaging_window_duration: float = 15
    averaging_window_function: Callable[[int], ArrayLike] | None = np.blackman
    amplitude_cutoff_fraction: float | None = 0.25
    invalid_data_removal_window_length: float = 0.5
    invalid_data_removal_percentile: int = 5
    invalid_data_removal_multiplier: int = 4

    @singledispatchmethod
    def find_breaths(self, container: Sequence | ContinuousData) -> IntervalData:
        """Find breaths in the data.

        You can either pass a `ContinuousData` object as first argument, or a
        `Sequence` as first argument and the label of a `ContinuousData` object.
        When passing a `ContinuousData` object, optionally, you can pass a
        `Sequence` object as second argument.
        If a `Sequence` is passed to `find_breaths()`, the resulting breaths
        are stored in the Sequence as `intervaldata["breaths"]`.

        This method attempts to find peaks and valleys in the data in a
        multi-step process. First, it naively finds any peaks that are a
        certain distance apart and higher than the moving average, and
        similarly valleys that are a certain distance apart and below the
        moving average.

        Next, valleys at the start and end of the signal are removed
        to ensure the first and last valleys are actual valleys, and not just
        the start or end of the signal. Peaks before the first or after the
        last valley are removed, to ensure peaks always fall between two
        valleys.

        At this point, it is possible multiple peaks exist between two valleys.
        Lower peaks are removed leaving only the highest peak between two
        valleys. Similarly, multiple valleys between two peaks are reduced to
        only the lowest valley.

        As a last step, breaths with a low amplitude (the average between the
        inspiratory and expiratory amplitudes) are removed.

        Breaths are constructed as a valley-peak-valley combination,
        representing the start of inspiration, the end of inspiration/start of
        expiration, and end of expiration.

        Args:
            container: a ContinuousData object that contains the data or a Sequence object
                that that contains the continuous data
            continuousdata_label: optional, label of the continuous data contained in the sequence

        Returns:
            A list of Breath objects.
        """
        msg = f"`find_breaths()` expects a Sequence or ContinuousData object as first argument, not {type(container)}."
        raise TypeError(msg)

    @find_breaths.register(Sequence)
    def _(self, sequence: Sequence, continuousdata_label: str) -> IntervalData:
        continuous_data = sequence.continuous_data[continuousdata_label]
        return self._find_breaths(continuous_data, sequence)

    @find_breaths.register(ContinuousData)
    def _(self, continuous_data: ContinuousData, sequence: Sequence | None = None) -> IntervalData:
        return self._find_breaths(continuous_data, sequence=sequence)

    def _find_breaths(self, continuous_data: ContinuousData, sequence: Sequence | None = None) -> IntervalData:
        data = continuous_data.values
        time = continuous_data.time

        invalid_data_indices = self._detect_invalid_data(data)
        data = self._remove_invalid_data(data, invalid_data_indices)

        peak_indices, valley_indices = self._detect_peaks_and_valleys(data)

        breaths = self._create_breaths_from_peak_valley_data(
            time,
            peak_indices,
            valley_indices,
        )
        breaths = self._remove_breaths_around_invalid_data(breaths, time, invalid_data_indices)
        breaths_container = IntervalData(
            label="breaths",
            name="Breaths as determined by BreathDetection",
            unit=None,
            category="breath",
            intervals=[(breath.start_time, breath.end_time) for breath in breaths],
            values=breaths,
            parameters={type(self): dict(vars(self))},
            derived_from=[continuous_data],
        )
        if sequence:
            sequence.interval_data.add(breaths_container)

        return breaths_container

    def _detect_invalid_data(self, data: np.ndarray) -> np.ndarray:
        """Detects invalid data as outliers outside an upper and lower cutoff.

        This function defines a lower and upper cutoff. Data beyond those cutoffs is considered invalid for the purposes
        of breath detection.

        The lower cutoff is a distance away from the mean. The distance is m times the distance between the mean and the
        nth percentile of the data. The upper cutoff is m times the distance between the mean and the (100 - n)th
        percentile. m is given by `invalid_data_removal_multiplier` and n is given by `invalid_data_removal_percentile`.

        For example, with m = 4 and n = 5, the mean = 100, 5% of the data is below/equal to 90, and 5% of the data is
        above/equal to 120, all data below 100 - (4 * 10) = 60 and above 100 + (4 * 20) = 180 is considerd invalid.

        Args:
            data (np.ndarray): _description_

        Returns:
            np.ndarray: the indices of the data points with values outside the lower and upper cutoff values.
        """
        data_mean = np.mean(data)

        lower_percentile = np.percentile(data, self.invalid_data_removal_percentile)
        cutoff_low = data_mean - (data_mean - lower_percentile) * self.invalid_data_removal_multiplier

        upper_percentile = np.percentile(data, 100 - self.invalid_data_removal_percentile)
        cutoff_high = data_mean + (upper_percentile - data_mean) * self.invalid_data_removal_multiplier

        # detect indices of outliers
        return np.flatnonzero((data < cutoff_low) | (data > cutoff_high))

    def _remove_invalid_data(self, data: np.ndarray, invalid_data_indices: np.ndarray) -> np.ndarray:
        """Removes invalid data points and replace them with the nearest non-np.nan value.."""
        data = np.copy(data)
        data[invalid_data_indices] = np.nan
        return self._fill_nan_with_nearest_neighbour(data)

    def _detect_peaks_and_valleys(self, data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        window_size = int(self.sample_frequency * self.averaging_window_duration)
        averager = MovingAverage(window_size=window_size, window_function=self.averaging_window_function)
        moving_average = averager.apply(data)

        peak_indices = self._find_features(data, moving_average)
        valley_indices = self._find_features(data, moving_average, invert=True)

        peak_indices, valley_indices = self._remove_edge_cases(data, peak_indices, valley_indices, moving_average)
        peak_indices, valley_indices = self._remove_doubles(data, peak_indices, valley_indices)
        peak_indices, valley_indices = self._remove_low_amplitudes(data, peak_indices, valley_indices)
        return peak_indices, valley_indices

    def _find_features(
        self,
        data: np.ndarray,
        moving_average: np.ndarray,
        invert: float = False,
    ) -> np.ndarray:
        """
        Find features (peaks or valleys) in the data.

        This method finds features (either peaks or valleys) in the data using
        the `scipy.signal.find_peaks()` function. The minimum distance (in
        time) between peaks is determined by the `minimum_duration` attribute.

        To find peaks, `invert` should be False. To find valleys, `invert`
        should be True, which flips the data before finding peaks.

        Args:
            data (np.ndarray): a 1D array containing the data.
            moving_average (NDArrag): a 1D array containing the moving average
                of the data.
            invert (float, optional): whether to invert the data before
            detecting peaks. Defaults to False.

        Returns:
            A tuple containing two 1D arrays of length N with the indices (int)
            and values (float) of the features, where N is the number of
            features found.
        """
        data_ = -data if invert else data
        moving_average_ = -moving_average if invert else moving_average
        feature_indices, _ = signal.find_peaks(
            data_,
            distance=self.minimum_duration * self.sample_frequency,
            height=moving_average_,
        )

        return feature_indices

    def _remove_edge_cases(
        self,
        data: np.ndarray,
        peak_indices: np.ndarray,
        valley_indices: np.ndarray,
        moving_average: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Remove overdetected peaks/valleys at the start and end of the data.

        This method removes a valley at the start of the data if the data before said valley stays below the moving
        average of the data at said valley. Likewise, it removes the last valley if the data after the last valley stays
        below the moving average of the data at said valley. This ensures a valley is a true valley, and not just a
        local minimum while the true valley is cut off.

        Then, all peaks that occur before the first and after the last valley
        are removed. This ensures peaks only fall between valleys.

        Args:
            peak_indices (np.ndarray): indices of the peaks
            peak_values (np.ndarray): values of the peaks
            valley_indices (np.ndarray): indices of the valleys
            valley_values (np.ndarray): values of the valleys
            data (np.ndarray): the data in which the peaks/valleys were detected
            moving_average (np.ndarray): the moving average of data

        Returns:
            A tuple (peak_indices, peak_values, valley_indices, valley_values)
            with edge cases removed.
        """
        if max(data[: valley_indices[0]]) < moving_average[valley_indices[0]]:
            # remove the first valley, if the data before that valley is not
            # high enough to be sure it's a valley
            valley_indices = np.delete(valley_indices, 0)

        if max(data[valley_indices[-1] :]) < moving_average[valley_indices[-1]]:
            # remove the last valley, if the data after that valley is not high
            # enough to be sure it's a valley
            valley_indices = np.delete(valley_indices, -1)

        # remove peaks that come before the first valley
        keep_peaks = peak_indices > valley_indices[0]
        peak_indices = peak_indices[keep_peaks]

        # remove peaks that come after the last valley
        keep_peaks = peak_indices < valley_indices[-1]
        peak_indices = peak_indices[keep_peaks]

        return peak_indices, valley_indices

    def _remove_doubles(
        self,
        data: np.ndarray,
        peak_indices: np.ndarray,
        valley_indices: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Remove double peaks/valleys.

        This method ensures there is only one peak between valleys, and only
        one valley between peaks. If there are multiple peaks between two
        valleys, the peak with the highest value is kept and the others are
        removed. If there are no peaks between several valleys (i.e. multiple
        valleys between peaks) the valley with the lowest value is kept, while
        the others are removed.

        This method does not remove peaks before the first or after the last
        valley.

        Args:
            data: data the peaks and valleys were found in
            peak_indices: indices of the peaks
            valley_indices: indices of the valleys

        Returns:
            A tuple (peak_indices, peak_values, valley_indices, valley_values)
            with double peaks/valleys removed.
        """
        peak_values = data[peak_indices]
        valley_values = data[valley_indices]

        current_valley_index = 0
        while current_valley_index < len(valley_indices) - 1:
            start_index = valley_indices[current_valley_index]
            end_index = valley_indices[current_valley_index + 1]
            peaks_between_valleys = np.argwhere(
                (peak_indices > start_index) & (peak_indices < end_index),
            )
            if not len(peaks_between_valleys):
                # no peak between valleys, remove highest valley
                delete_valley_index = (
                    current_valley_index
                    if valley_values[current_valley_index] > valley_values[current_valley_index + 1]
                    else current_valley_index + 1
                )
                valley_indices = np.delete(valley_indices, delete_valley_index)
                valley_values = np.delete(valley_values, delete_valley_index)
                continue

            if len(peaks_between_valleys) > 1:
                # multiple peaks between valleys, remove lowest peak
                delete_peak_index = (
                    peaks_between_valleys[0]
                    if peak_values[peaks_between_valleys[0]] < peak_values[peaks_between_valleys[1]]
                    else peaks_between_valleys[1]
                )
                peak_indices = np.delete(peak_indices, delete_peak_index)
                peak_values = np.delete(peak_values, delete_peak_index)
                continue

            current_valley_index += 1

        return peak_indices, valley_indices

    def _remove_low_amplitudes(
        self,
        data: np.ndarray,
        peak_indices: np.ndarray,
        valley_indices: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Remove peaks if the amplitude is low compared to the median amplitude.

        The amplitude of a peak is determined as the average vertical distance
        between the peak value and the two valley values besides it. The cutoff
        value for the amplitude is calculated as the median amplitude times
        `amplitude_cutoff_fraction`. Peaks that have an amplitude below the
        cutoff are removed. Then, `_remove_doubles()` is called to remove
        either of the valleys next to the peak.

        If `amplitude_cutoff_fraction` is None, the input is returned
        unchanged.

        Args:
            data: the data the peaks and valleys were found in
            peak_indices (np.ndarray): the indices of the peaks
            valley_indices (np.ndarray): the indices of the valleys

        Returns:
            A tuple (peak_indices, valley_indices)
            with low-amplitude breaths removed.
        """
        if not self.amplitude_cutoff_fraction:
            return peak_indices, valley_indices

        peak_values = data[peak_indices]
        valley_values = data[valley_indices]

        inspiratory_amplitude = peak_values - valley_values[:-1]
        expiratory_amplitude = peak_values - valley_values[1:]
        amplitude = (inspiratory_amplitude + expiratory_amplitude) / 2

        amplitude_cutoff = self.amplitude_cutoff_fraction * np.median(amplitude)
        delete_peaks = np.argwhere(amplitude < amplitude_cutoff)

        peak_indices = np.delete(peak_indices, delete_peaks)
        peak_values = np.delete(peak_values, delete_peaks)

        return self._remove_doubles(data, peak_indices, valley_indices)

    def _create_breaths_from_peak_valley_data(
        self,
        time: np.ndarray,
        peak_indices: np.ndarray,
        valley_indices: np.ndarray,
    ) -> list[Breath]:
        return [
            Breath(time[start], time[middle], time[end])
            for middle, (start, end) in zip(
                peak_indices,
                itertools.pairwise(valley_indices),
                strict=True,
            )
        ]

    def _remove_breaths_around_invalid_data(
        self,
        breaths: list[Breath],
        time: np.ndarray,
        invalid_data_indices: np.ndarray,
    ) -> list[Breath]:
        """Remove breaths overlapping with invalid data.

        Breaths that start within a window length (given by invalid_data_removal_window_length) of invalid data are
        removed.

        Args:
            breaths: list of detected breath objects
            data: data the breaths were detected in
            time: time axis belonging to the data
            invalid_data_indices: indices of invalid data points
        """
        # TODO: write more general(ized) method of determining invalid data

        new_breaths = breaths[:]

        if not len(invalid_data_indices):
            return new_breaths

        invalid_data_values = np.zeros(time.shape)
        invalid_data_values[invalid_data_indices] = 1  # gives the value 1 to each invalid datapoint

        window_length = math.ceil(self.invalid_data_removal_window_length * self.sample_frequency)

        for breath in new_breaths[:]:
            breath_start_minus_window = max(0, np.argmax(time == breath.start_time) - window_length)
            breath_end_plus_window = min(len(invalid_data_values), np.argmax(time == breath.end_time) + window_length)

            # if no invalid datapoints are within the window, np.max() will return 0
            # if any invalid datapoints are within the window, np.max() will return 1
            if np.max(invalid_data_values[breath_start_minus_window:breath_end_plus_window]):
                new_breaths.remove(breath)

        return new_breaths

    @staticmethod
    def _fill_nan_with_nearest_neighbour(data: np.ndarray) -> np.ndarray:
        """Fill np.nan values in a 1D array with the nearest non-np.nan value.

        Each np.nan-value is replaced with the nearest (backwards and forwards) non-np.nan value. If the nearest earlier
        and a later value are the same distance away, the earlier value is preferred. np.nan-values at the start are
        filled with the first non-nan value.

        Example:
            foo = np.ndarray([np.nan, 1, np.nan, np.nan, np.nan, 3, np.nan, np.nan])
            bar = BreathDetection._fill_nan_with_nearest_neighbour(foo)
            assert bar == np.ndarray([1, 1, 1, 1, 3, 3, 3, 3])
        """
        data = np.copy(data)
        nan_indices = np.flatnonzero(np.isnan(data))

        if not len(nan_indices):
            return data

        if len(nan_indices) == len(data):
            msg = "`data` only contains np.nan values. "
            raise ValueError(msg)

        grouped_nan_indices = np.split(nan_indices, np.where(np.diff(nan_indices) != 1)[0] + 1)

        for group in grouped_nan_indices:
            if group[0] == 0:
                data[group] = data[group[-1] + 1]
                continue

            if group[-1] == len(data) - 1:
                data[group] = data[group[0] - 1]
                continue

            middle = len(group) // 2
            data[group[:middle]] = data[group[0] - 1]
            data[group[middle:]] = data[group[-1] + 1]
        return data
