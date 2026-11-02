import numpy as np
import pytest

from aetherguard.integrity import arbiter

NAN = np.nan


def refs(imd=NAN, chirps=NAN, nbr=NAN):
    return {"imd": np.atleast_1d(np.asarray(imd, float)), "chirps_aligned": np.atleast_1d(np.asarray(chirps, float)),
            "neighbours": np.atleast_1d(np.asarray(nbr, float))}


def corroborate(obs, r, p=0.5, use_imd=True):
    retained, why = arbiter.corroborate(np.atleast_1d(np.asarray(obs, float)), r, np.atleast_1d(np.asarray(p, float)), use_imd)
    return bool(retained[0]), why[0]


def test_obs_threshold_is_20_mm_inclusive():
    r = refs(imd=100.0, chirps=100.0)
    assert corroborate(19.9, r)[0] is False
    assert corroborate(20.0, r)[0] is True
    assert corroborate(np.nan, r)[0] is False


def test_agreement_ratio_edge_is_30_percent_inclusive():
    obs = 100.0
    assert corroborate(obs, refs(imd=30.0, chirps=30.0))[0] is True          # exactly 0.3 * obs
    assert corroborate(obs, refs(imd=29.9, chirps=30.0))[0] is False         # one just below: only one agrees
    assert corroborate(obs, refs(imd=30.0, chirps=30.0, nbr=0.0))[0] is True  # two of three agree


def test_two_available_references_both_must_agree_one_is_not_enough():
    assert corroborate(50.0, refs(imd=40.0, chirps=2.0))[0] is False
    assert corroborate(50.0, refs(imd=40.0, nbr=20.0))[0] is True


def test_a_single_reference_needs_60_percent_and_a_model_probability_below_09():
    assert corroborate(50.0, refs(chirps=30.0), p=0.5)[0] is True           # 0.6 * obs inclusive
    assert corroborate(50.0, refs(chirps=29.9), p=0.5)[0] is False
    assert corroborate(50.0, refs(chirps=45.0), p=0.9)[0] is False          # P(fault) must be < 0.9
    assert corroborate(50.0, refs(chirps=45.0), p=0.89)[0] is True


def test_no_reference_means_never_retained():
    assert corroborate(500.0, refs())[0] is False


def test_imd_excluded_variant_loses_the_imd_corroboration():
    r = refs(imd=80.0, chirps=60.0)                                         # both agree with obs 100
    assert corroborate(100.0, r, use_imd=True)[0] is True
    retained, why = corroborate(100.0, r, p=0.95, use_imd=False)            # only chirps is left: single-reference rule
    assert retained is False
    assert corroborate(100.0, r, p=0.5, use_imd=False)[0] is True           # chirps >= 0.6 * obs and p < 0.9
    assert corroborate(100.0, refs(imd=80.0, chirps=40.0), p=0.5, use_imd=False)[0] is False


def test_reasons_name_the_supporting_references():
    retained, why = corroborate(100.0, refs(imd=50.0, chirps=40.0, nbr=1.0))
    assert retained and why == "corroborated_by:imd,chirps"
    retained, why = corroborate(100.0, refs(chirps=70.0))
    assert retained and why == "corroborated_by:chirps"
    assert corroborate(100.0, refs(imd=1.0, chirps=2.0))[1] == ""


def test_vectorised_over_many_rows():
    obs = np.array([100.0, 100.0, 10.0, 100.0])
    r = {"imd": np.array([50, 50, 50, NAN]), "chirps_aligned": np.array([40, 1, 40, NAN]),
         "neighbours": np.array([NAN, NAN, NAN, NAN])}
    retained, why = arbiter.corroborate(obs, r, np.full(4, 0.5))
    assert retained.tolist() == [True, False, False, False]
    assert why.tolist() == ["corroborated_by:imd,chirps", "", "", ""]


def test_stuck_exception_needs_two_references_within_30_percent():
    obs = np.array([10.0, 10.0, 10.0, 10.0])
    r = {"imd": np.array([13.0, 13.1, 10.0, 10.0]), "chirps_aligned": np.array([7.0, 10.0, NAN, 10.0]),
         "neighbours": np.array([NAN, NAN, NAN, 14.0])}
    retained, why = arbiter.stuck_exception(obs, r)
    assert retained.tolist() == [True, False, False, True]            # |13-10| = 3 = 0.3 * 10 is inside; 13.1 is not
    assert why[0] == "stuck_corroborated_by:imd,chirps" and why[2] == ""
    retained, _ = arbiter.stuck_exception(obs, r, use_imd=False)
    assert retained.tolist() == [False, False, False, False]


def test_rule_constants_are_the_documented_ones():
    assert (arbiter.EXTREME_MIN_MM, arbiter.AGREE_FRACTION, arbiter.SINGLE_REF_FRACTION,
            arbiter.SINGLE_REF_MAX_P_FAULT, arbiter.STUCK_TOLERANCE) == (20.0, 0.3, 0.6, 0.9, 0.3)
