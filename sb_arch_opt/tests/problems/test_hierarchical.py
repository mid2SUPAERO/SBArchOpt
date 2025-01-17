import pytest
import numpy as np
from sb_arch_opt.sampling import *
from sb_arch_opt.problems.hierarchical import *
from pymoo.core.evaluator import Evaluator


def run_test_hierarchy(problem, imp_ratio, check_n_valid=True, validate_exhaustive=False):
    x_discrete, is_act_discrete = problem.all_discrete_x
    if check_n_valid or x_discrete is not None:
        if x_discrete is not None:
            assert np.all(~LargeDuplicateElimination.eliminate(x_discrete))
            assert x_discrete.shape[0] == problem.get_n_valid_discrete()

            if validate_exhaustive:
                x_trail_repair, _ = HierarchicalExhaustiveSampling().get_all_x_discrete_by_trial_and_repair(problem)
                assert {tuple(ix) for ix in x_trail_repair} == {tuple(ix) for ix in x_discrete}

        pop = HierarchicalExhaustiveSampling(n_cont=1).do(problem, 0)
        assert len(pop) == problem.get_n_valid_discrete()
    assert HierarchicalExhaustiveSampling.has_cheap_all_x_discrete(problem) == (x_discrete is not None)

    assert problem.get_imputation_ratio() == pytest.approx(imp_ratio, rel=.02)
    problem.print_stats()

    if HierarchicalExhaustiveSampling.get_n_sample_exhaustive(problem, n_cont=3) < 1e3:
        pop = HierarchicalExhaustiveSampling(n_cont=3).do(problem, 0)
    else:
        pop = HierarchicalRandomSampling().do(problem, 100)
    Evaluator().eval(problem, pop)
    return pop


def test_hier_goldstein():
    run_test_hierarchy(HierarchicalGoldstein(), 2.25)


def test_mo_hier_goldstein():
    run_test_hierarchy(MOHierarchicalGoldstein(), 2.25)


def test_hier_rosenbrock():
    run_test_hierarchy(HierarchicalRosenbrock(), 1.5)


def test_mo_hier_rosenbrock():
    run_test_hierarchy(MOHierarchicalRosenbrock(), 1.5)


def test_hier_zaefferer():
    run_test_hierarchy(ZaeffererHierarchical.from_mode(ZaeffererProblemMode.A_OPT_INACT_IMP_PROF_UNI), 1)


def test_hier_test_problem():
    run_test_hierarchy(MOHierarchicalTestProblem(), 72)


def test_jenatton():
    run_test_hierarchy(Jenatton(), 2)


def test_comb_hier_branin():
    run_test_hierarchy(CombHierBranin(), 6.72, validate_exhaustive=True)


def test_comb_hier_mo():
    run_test_hierarchy(CombHierMO(), 6.17, validate_exhaustive=True)


def test_comb_hier_discr_mo():
    run_test_hierarchy(CombHierDMO(), 13.69)
