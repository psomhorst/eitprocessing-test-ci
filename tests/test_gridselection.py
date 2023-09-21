import numpy as np
import pytest
from eitprocessing.roi_selection.gridselection import GridSelection


def matrices_from_string(string: str, boolean: bool = False) -> list[np.ndarray]:
    """Generates a list of matrices from a string containing a matrix representation.

    A matrix represtation contains one character per cell that describes the value of that cell.
    Rows are delimited by commas. Matrices are delimited by semi-colons.

    The returned matrices by default have `np.floating` as dtype. When `boolean` is set to True, the
    dtype is `bool`. That means that the actual values in the matrices depend on the value of `boolean`.

    The following characters are transformed to these corresponding values in either `np.floating` or
    `bool` mode:
    - T -> 1. or True
    - F -> 0. or False
    - 1 -> 1. or True
    - N -> np.nan or False
    - R -> np.random.int(1, 100) or True

    Examples:
    >>> matrices_from_string("1T1,FNR")
    [array([[ 1.,  1.,  1.],
            [ 0., nan, 40.]])]
    >>> matrices_from_string("1T1,FNR", boolean=True)
    [array([[ True,  True,  True],
            [False, False,  True]])]
    >>> matrices_from_string("RR,RR;RRR;1R")
    [array([[21., 80.],
            [43., 10.]]),
    array([[26., 43., 62.]]),
    array([[ 1., 89.]])]
    """

    matrices = []
    for part in string.split(";"):
        str_matrix = np.array([tuple(row) for row in part.split(",")], dtype="object")
        if boolean:
            matrix = np.full(str_matrix.shape, False, dtype=bool)
            matrix[np.nonzero(str_matrix == "N")] = False
            matrix[np.nonzero(str_matrix == "1")] = True
            matrix[np.nonzero(str_matrix == "R")] = True

        else:
            matrix = np.full(str_matrix.shape, np.nan, dtype=np.floating)
            matrix[np.nonzero(str_matrix == "N")] = np.nan
            matrix[np.nonzero(str_matrix == "1")] = 1
            matrix = np.where(
                str_matrix == "R",
                np.random.default_rng().integers(1, 100, matrix.shape),
                matrix,
            )

        matrix[np.nonzero(str_matrix == "T")] = True
        matrix[np.nonzero(str_matrix == "F")] = False

        matrices.append(matrix)

    return matrices


@pytest.mark.parametrize(
    "shape,split_vh,result_string",
    [
        ((2, 1), (2, 1), "T,F;F,T"),
        ((3, 1), (3, 1), "T,F,F;F,T,F;F,F,T"),
        ((1, 3), (1, 3), "TFF;FTF;FFT"),
        ((1, 3), (1, 2), "TTF;FFT"),
        (
            (4, 4),
            (2, 2),
            "TTFF,TTFF,FFFF,FFFF;"
            "FFTT,FFTT,FFFF,FFFF;"
            "FFFF,FFFF,TTFF,TTFF;"
            "FFFF,FFFF,FFTT,FFTT",
        ),
        (
            (5, 5),
            (2, 2),
            "TTTFF,TTTFF,TTTFF,FFFFF,FFFFF;"
            "FFFTT,FFFTT,FFFTT,FFFFF,FFFFF;"
            "FFFFF,FFFFF,FFFFF,TTTFF,TTTFF;"
            "FFFFF,FFFFF,FFFFF,FFFTT,FFFTT",
        ),
        ((5, 2), (1, 2), "TF,TF,TF,TF,TF;FT,FT,FT,FT,FT"),
        ((1, 9), (1, 6), "TTFFFFFFF;FFTFFFFFF;FFFTTFFFF;FFFFFTFFF;FFFFFFTTF;FFFFFFFFT"),
        ((2, 2), (1, 1), "TT,TT"),
    ],
)
def test_no_split_pixels_no_nans(shape, split_vh, result_string):
    data = np.random.default_rng().integers(1, 100, shape)
    result_matrices = matrices_from_string(result_string)

    gs = GridSelection(*split_vh)
    matrices = gs.find_grid(data)

    num_appearances = np.sum(np.stack(matrices, axis=-1), axis=-1)

    assert len(matrices) == np.prod(split_vh)
    assert np.array_equal(num_appearances, (~np.isnan(data) * 1))
    assert np.array_equal(matrices, result_matrices)


@pytest.mark.parametrize(
    "data_string,split_vh,result_string",
    [
        ("NNN,NRR,NRR", (1, 1), "NNN,NTT,NTT"),
        (
            "NNN,RRR,RRR,RRR,RRR",
            (2, 2),
            "FFF,TTF,TTF,FFF,FFF;"
            "FFF,FFT,FFT,FFF,FFF;"
            "FFF,FFF,FFF,TTF,TTF;"
            "FFF,FFF,FFF,FFT,FFT",
        ),
        (
            "NNNNNN,NNNNNN,NRRRRR,RNRRRR,NNNNNN",
            (2, 2),
            "FFFFFF,FFFFFF,FTTFFF,FFFFFF,FFFFFF;"
            "FFFFFF,FFFFFF,FFFTTT,FFFFFF,FFFFFF;"
            "FFFFFF,FFFFFF,FFFFFF,TFTFFF,FFFFFF;"
            "FFFFFF,FFFFFF,FFFFFF,FFFTTT,FFFFFF",
        ),
    ],
)
def test_no_split_pixels_nans(data_string, split_vh, result_string):
    data = matrices_from_string(data_string)[0]
    result = matrices_from_string(result_string, boolean=True)

    v_split, h_split = split_vh
    gs = GridSelection(v_split, h_split)

    matrices = gs.find_grid(data)
    num_appearances = np.sum(np.stack(matrices, axis=-1), axis=-1)

    assert len(matrices) == h_split * v_split
    assert np.array_equal(num_appearances, (~np.isnan(data) * 1))
    assert np.array_equal(matrices, result)
