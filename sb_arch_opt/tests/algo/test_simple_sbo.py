import pytest
import tempfile
from sb_arch_opt.problem import *
from sb_arch_opt.algo.simple_sbo import *
from pymoo.optimize import minimize

check_dependency = lambda: pytest.mark.skipif(not HAS_SIMPLE_SBO, reason='Simple SBO dependencies not installed')


@check_dependency()
def test_simple_sbo_rbf(problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    sbo = get_simple_sbo_rbf(init_size=10)
    result = minimize(problem, sbo, termination=('n_eval', 12), verbose=True, progress=True)
    assert len(result.pop) == 12


@check_dependency()
def test_simple_sbo_rbf_termination(problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    sbo = get_simple_sbo_rbf(init_size=10)
    termination = get_sbo_termination(n_max_infill=12, tol=1e-3)
    assert minimize(problem, sbo, termination=termination, verbose=True, progress=True)


@check_dependency()
def test_simple_sbo_rbf_failing(failing_problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    sbo = get_simple_sbo_rbf(init_size=10)
    result = minimize(failing_problem, sbo, termination=('n_eval', 12), verbose=True, progress=True)
    assert len(result.pop) == 12


@check_dependency()
def test_simple_sbo_krg(problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    sbo = get_simple_sbo_krg(init_size=10)
    result = minimize(problem, sbo, termination=('n_eval', 12))
    assert len(result.pop) == 12


@check_dependency()
def test_simple_sbo_krg_y(problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    sbo = get_simple_sbo_krg(init_size=10, use_mvpf=False)
    result = minimize(problem, sbo, termination=('n_eval', 12))
    assert len(result.pop) == 12


@check_dependency()
def test_simple_sbo_krg_ei(problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    sbo = get_simple_sbo_krg(init_size=10, use_ei=True)
    result = minimize(problem, sbo, termination=('n_eval', 12))
    assert len(result.pop) == 12


@check_dependency()
def test_store_results_restart(problem: ArchOptProblemBase):
    assert HAS_SIMPLE_SBO

    with tempfile.TemporaryDirectory() as tmp_folder:
        for i in range(2):
            sbo = get_simple_sbo_rbf(init_size=10)
            sbo.store_intermediate_results(tmp_folder)
            sbo.initialize_from_previous_results(problem, tmp_folder)

            n_eval = 11 if i == 0 else 1
            result = minimize(problem, sbo, termination=('n_eval', n_eval))
            assert len(result.pop) == 10+(i+1)
