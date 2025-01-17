"""
Licensed under the GNU General Public License, Version 3.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.gnu.org/licenses/gpl-3.0.html.en

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Copyright: (c) 2023, Deutsches Zentrum fuer Luft- und Raumfahrt e.V.
Contact: jasper.bussemaker@dlr.de
"""
import logging
import warnings
import itertools
import numpy as np
from typing import Optional, Tuple, List
from scipy.stats.qmc import Sobol
from scipy.spatial import distance

from pymoo.core.repair import Repair
from pymoo.core.variable import Real
from pymoo.core.problem import Problem
from pymoo.core.sampling import Sampling
from pymoo.core.initialization import Initialization
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.core.duplicate import DefaultDuplicateElimination
from pymoo.operators.sampling.lhs import LatinHypercubeSampling, sampling_lhs_unit

from sb_arch_opt.problem import ArchOptProblemBase, ArchOptRepair

__all__ = ['HierarchicalExhaustiveSampling', 'HierarchicalLatinHypercubeSampling', 'HierarchicalRandomSampling',
           'get_init_sampler', 'LargeDuplicateElimination', 'TrailRepairWarning']

log = logging.getLogger('sb_arch_opt.sampling')


def get_init_sampler(repair: Repair = None, remove_duplicates=True):
    """Helper function to get an Initialization class with hierarchical sampling"""

    if repair is None:
        repair = ArchOptRepair()
    sampling = HierarchicalRandomSampling(repair=repair, sobol=True)

    # Samples are already repaired because we're using the hierarchical samplers
    eliminate_duplicates = LargeDuplicateElimination() if remove_duplicates else None
    return Initialization(sampling, eliminate_duplicates=eliminate_duplicates)


class TrailRepairWarning(RuntimeWarning):
    pass


class HierarchicalExhaustiveSampling(Sampling):
    """Exhaustively samples the design space, taking n_cont samples for each continuous variable.
    Can take a long time if the design space is large and the problem doesn't provide a way to generate all discrete
    design vectors, and doesn't work well for purely continuous problems."""

    def __init__(self, repair: Repair = None, n_cont=5):
        super().__init__()
        if repair is None:
            repair = ArchOptRepair()
        self._repair = repair
        self._n_cont = n_cont

    def _do(self, problem: Problem, n_samples, **kwargs):
        return self.do_sample(problem)

    def do_sample(self, problem: Problem):
        # First sample only discrete dimensions
        x_discr, is_act_discr = self.get_all_x_discrete(problem)

        # Expand along continuous dimensions
        n_cont = self._n_cont
        is_cont_mask = self.get_is_cont_mask(problem)
        if n_cont > 1 and np.any(is_cont_mask):
            x = x_discr
            is_act = is_act_discr
            for i_dv in np.where(is_cont_mask)[0]:
                # Expand when continuous variable is active
                is_act_i = is_act[:, i_dv]
                n_repeat = np.ones(len(is_act_i), dtype=int)
                n_repeat[is_act_i] = n_cont

                x = np.repeat(x, n_repeat, axis=0)
                is_act = np.repeat(is_act, n_repeat, axis=0)

                # Fill sampled values
                rep_idx = np.cumsum([0]+list(n_repeat))[:-1]
                dv_sampled = np.linspace(problem.xl[i_dv], problem.xu[i_dv], n_cont)
                for i in np.where(is_act_i)[0]:
                    x[rep_idx[i]:rep_idx[i]+n_cont, i_dv] = dv_sampled

        else:
            x = x_discr

        return x

    @staticmethod
    def has_cheap_all_x_discrete(problem: Problem):
        if isinstance(problem, ArchOptProblemBase):
            # Check if the problem itself provides all discrete design vectors
            x_discrete, _ = problem.all_discrete_x
            if x_discrete is not None:
                return True

        return False

    def get_all_x_discrete(self, problem: Problem):
        # Check if the problem itself can provide all discrete design vectors
        if isinstance(problem, ArchOptProblemBase):
            x_discr, is_act_discr = problem.all_discrete_x
            if x_discr is not None:
                return x_discr, is_act_discr

        # Otherwise, use trail and repair (costly!)
        warnings.warn(f'Generating hierarchical discrete samples by trial and repair for {problem!r}! '
                      f'Consider implementing `_gen_all_discrete_x`', TrailRepairWarning)
        return self.get_all_x_discrete_by_trial_and_repair(problem)

    def get_all_x_discrete_by_trial_and_repair(self, problem: Problem):
        # First sample only discrete dimensions
        opt_values = self.get_exhaustive_sample_values(problem, 1)
        x = np.array(list(itertools.product(*opt_values)))

        is_cont_mask = self.get_is_cont_mask(problem)
        is_discrete_mask = ~is_cont_mask

        # Create and repair the sampled design vectors in batches
        n_batch = 1000
        x_later = x
        x_repaired = x[:0, :]
        is_active_repaired = np.zeros(x_repaired.shape, dtype=bool)
        while x_later.shape[0] > 0:
            # Repair current batch
            x_repair = x_later[:n_batch, :]
            x_later = x_later[x_repair.shape[0]:, :]
            # print(f'Sampling {x_repair.shape[0]} ({x_later.shape[0]} to go; {x_repaired.shape[0]} sampled)')

            x_repair_input = x_repair
            x_repair = self._repair.do(problem, x_repair)
            if isinstance(self._repair, ArchOptRepair):
                is_active = self._repair.latest_is_active
            else:
                is_active = np.ones(x_repair.shape, dtype=bool)

            # Remove repaired points
            is_not_repaired = ~np.any(x_repair[:, is_discrete_mask] != x_repair_input[:, is_discrete_mask], axis=1)
            x_repair = x_repair[is_not_repaired, :]
            is_active = is_active[is_not_repaired, :]

            x_repaired = np.row_stack([x_repaired, x_repair])
            is_active_repaired = np.row_stack([is_active_repaired, is_active.astype(bool)])

        x_discr = np.row_stack(x_repaired)
        is_act_discr = np.row_stack(is_active_repaired)

        # Impute continuous values
        if isinstance(problem, ArchOptProblemBase):
            problem.impute_x(x_discr, is_act_discr)

        return x_discr, is_act_discr

    @classmethod
    def get_exhaustive_sample_values(cls, problem: Problem, n_cont=5):
        # Determine bounds and which design variables are discrete
        xl, xu = problem.bounds()
        is_cont = cls.get_is_cont_mask(problem)

        # Get values to be sampled for each design variable
        return [np.linspace(xl[i], xu[i], n_cont) if is_cont[i] else np.arange(xl[i], xu[i]+1) for i in range(len(xl))]

    @staticmethod
    def get_is_cont_mask(problem: Problem):
        if isinstance(problem, ArchOptProblemBase):
            return problem.is_cont_mask

        is_cont = np.ones((problem.n_var,), dtype=bool)
        if problem.vars is not None:
            for i, var in enumerate(problem.vars.values()):
                if not isinstance(var, Real):
                    is_cont[i] = False
        return is_cont

    @classmethod
    def get_n_sample_exhaustive(cls, problem: Problem, n_cont=5):
        values = cls.get_exhaustive_sample_values(problem, n_cont=n_cont)
        return int(np.prod([len(opts) for opts in values], dtype=np.float))

    def __repr__(self):
        return f'{self.__class__.__name__}()'


class HierarchicalLatinHypercubeSampling(LatinHypercubeSampling):
    """
    Latin hypercube sampling only returning repaired samples. Additionally, the hierarchical random sampling procedure
    is used to get the best distribution corresponding to the real distribution of hierarchical variables.
    """

    def __init__(self, repair: Repair = None, **kwargs):
        super().__init__(**kwargs)
        if repair is None:
            repair = ArchOptRepair()
        self._repair = repair

    def _do(self, problem: Problem, n_samples, **kwargs):
        if self._repair is None:
            return super()._do(problem, n_samples, **kwargs)

        # Prepare sampling
        x_all, is_act = HierarchicalRandomSampling.get_hierarchical_cartesian_product(problem, self._repair)
        xl, xu = problem.bounds()

        # Sample several times to find the best-scored samples
        best_x = best_score = None
        for _ in range(self.iterations):
            x = HierarchicalRandomSampling.randomly_sample(problem, n_samples, self._repair, x_all, is_act, lhs=True)
            if self.criterion is None:
                return x

            x_unit = (x-xl)/(xu-xl)
            score = self.criterion(x_unit)
            if best_score is None or score > best_score:
                best_x = x
                best_score = score

        return best_x

    def __repr__(self):
        return f'{self.__class__.__name__}()'


class HierarchicalRandomSampling(FloatRandomSampling):
    """
    Hierarchical mixed-discrete sampling. There are two ways the random sampling is performed:
    A: Generate and select:
       1. Generate all possible discrete design vectors
       2. Separate discrete design vectors by nr of active discrete variables
       3. Within each group, uniformly sample discrete design vectors
       4. Concatenate and randomize active continuous variables
    B: One-shot:
       1. Randomly select design variable values
       2. Repair/impute design vectors

    The first way yields better results, as there is an even chance of selecting every valid discrete design vector,
    however it takes more memory and might be too much for very large design spaces.
    """

    _n_comb_gen_all_max = 100e3

    def __init__(self, repair: Repair = None, sobol=True):
        if repair is None:
            repair = ArchOptRepair()
        self._repair = repair
        self.sobol = sobol
        super().__init__()

    def _do(self, problem, n_samples, **kwargs):
        # Get Cartesian product of all discrete design variables (only available if design space is not too large)
        x, is_active = self.get_hierarchical_cartesian_product(problem, self._repair)

        return self.randomly_sample(problem, n_samples, self._repair, x, is_active, sobol=self.sobol)

    @classmethod
    def get_hierarchical_cartesian_product(cls, problem: Problem, repair: Repair) \
            -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        # Get values to be sampled for each discrete design variable
        exhaustive_sampling = HierarchicalExhaustiveSampling(repair=repair, n_cont=1)
        opt_values = exhaustive_sampling.get_exhaustive_sample_values(problem, n_cont=1)

        # Get the number of samples in the cartesian product
        n_opt_values = int(np.prod([len(values) for values in opt_values], dtype=float))

        # If less than some threshold, sample all and then select (this gives a better distribution)
        if n_opt_values < cls._n_comb_gen_all_max or exhaustive_sampling.has_cheap_all_x_discrete(problem):
            try:
                x, is_active = exhaustive_sampling.get_all_x_discrete(problem)
                return x, is_active
            except MemoryError:
                pass

        warnings.warn(f'Hierarchical sampling is not possible for {problem!r}, falling back to non-hierarchical '
                      f'sampling! Consider implementing `_gen_all_discrete_x`', TrailRepairWarning)
        return None, None

    @classmethod
    def randomly_sample(cls, problem, n_samples, repair: Repair, x_all: Optional[np.ndarray],
                        is_act_all: Optional[np.ndarray], lhs=False, sobol=False):
        is_cont_mask = HierarchicalExhaustiveSampling.get_is_cont_mask(problem)
        has_x_cont = np.any(is_cont_mask)
        xl, xu = problem.xl, problem.xu
        needs_repair = False

        def _choice(n_choose, n_from, replace=True):
            return cls._choice(n_choose, n_from, replace=replace, sobol=sobol)

        # If the population of all available discrete design vectors is available, sample from there
        is_active = is_act_all
        if x_all is not None:
            x, is_active = cls._sample_discrete_x(n_samples, is_cont_mask, x_all, is_act_all, sobol=sobol)

        # Otherwise, sample randomly
        else:
            needs_repair = True
            opt_values = HierarchicalExhaustiveSampling.get_exhaustive_sample_values(problem, n_cont=1)
            x = np.empty((n_samples, problem.n_var))
            for i_dv in range(problem.n_var):
                if not is_cont_mask[i_dv]:
                    i_opt_sampled = _choice(n_samples, len(opt_values[i_dv]))
                    x[:, i_dv] = opt_values[i_dv][i_opt_sampled]

        # Randomize continuous variables
        if has_x_cont:
            if is_active is None:
                needs_repair = True
                is_active = np.ones(x.shape, dtype=bool)

            nx_cont = len(np.where(is_cont_mask)[0])
            if lhs:
                x_unit = sampling_lhs_unit(x.shape[0], nx_cont)
            elif sobol:
                x_unit = cls._sobol(x.shape[0], nx_cont)
            else:
                x_unit = np.random.random((x.shape[0], nx_cont))

            x_unit_abs = x_unit*(xu[is_cont_mask]-xl[is_cont_mask])+xl[is_cont_mask]

            # Do not overwrite inactive imputed continuous variables
            is_inactive_override = ~is_active[:, is_cont_mask]
            x_unit_abs[is_inactive_override] = x[:, is_cont_mask][is_inactive_override]

            x[:, is_cont_mask] = x_unit_abs

        # Repair
        if needs_repair:
            x = repair.do(problem, x)
        return x

    @classmethod
    def _sample_discrete_x(cls, n_samples: int, is_cont_mask, x_all: np.ndarray, is_act_all: np.ndarray, sobol=False):

        def _choice(n_choose, n_from, replace=True):
            return cls._choice(n_choose, n_from, replace=replace, sobol=sobol)

        # Separate by nr of active discrete variables
        x_all_grouped, is_act_all_grouped, i_x_groups = cls.split_by_discrete_n_active(x_all, is_act_all, is_cont_mask)

        # Uniformly choose from which group to sample
        i_groups = np.sort(_choice(n_samples, len(x_all_grouped)))
        x = []
        is_active = []
        has_x_cont = np.any(is_cont_mask)
        i_x_sampled = np.ones((x_all.shape[0],), dtype=bool)
        for i_group in range(len(x_all_grouped)):
            i_x_group = np.where(i_groups == i_group)[0]
            if len(i_x_group) == 0:
                continue

            # Randomly select values within group
            x_group = x_all_grouped[i_group]
            if len(i_x_group) < x_group.shape[0]:
                i_x = _choice(len(i_x_group), x_group.shape[0], replace=False)

            # If there are more samples requested than points available, only repeat points if there are continuous vars
            elif has_x_cont:
                i_x_add = _choice(len(i_x_group)-x_group.shape[0], x_group.shape[0])
                i_x = np.sort(np.concatenate([np.arange(x_group.shape[0]), i_x_add]))
            else:
                i_x = np.arange(x_group.shape[0])

            x.append(x_group[i_x, :])
            is_active.append(is_act_all_grouped[i_group][i_x, :])
            i_x_sampled[i_x_groups[i_group][i_x]] = True

        x = np.row_stack(x)
        is_active = np.row_stack(is_active)

        # Uniformly add discrete vectors if there are not enough (can happen if some groups are very small and there
        # are no continuous dimensions)
        if x.shape[0] < n_samples:
            n_add = n_samples-x.shape[0]
            x_available = x_all[~i_x_sampled, :]
            is_act_available = is_act_all[~i_x_sampled, :]

            if n_add < x_available.shape[0]:
                i_x = _choice(n_add, x_available.shape[0], replace=False)
            else:
                i_x = np.arange(x_available.shape[0])

            x = np.row_stack([x, x_available[i_x, :]])
            is_active = np.row_stack([is_active, is_act_available[i_x, :]])

        return x, is_active

    @staticmethod
    def split_by_discrete_n_active(x_discrete: np.ndarray, is_act_discrete: np.ndarray, is_cont_mask) \
            -> Tuple[List[np.ndarray], List[np.ndarray], List[np.ndarray]]:

        # Calculate nr of active variables for each design vector
        is_discrete_mask = ~is_cont_mask
        n_active = np.sum(is_act_discrete[:, is_discrete_mask], axis=1)

        # Sort by nr active
        i_sorted = np.argsort(n_active)
        x_discrete = x_discrete[i_sorted, :]
        is_act_discrete = is_act_discrete[i_sorted, :]

        # Split by nr active
        # https://stackoverflow.com/a/43094244
        i_split = np.unique(n_active[i_sorted], return_index=True)[1][1:]
        x_all_grouped = np.split(x_discrete, i_split, axis=0)
        is_act_all_grouped = np.split(is_act_discrete, i_split, axis=0)
        i_x_groups = np.split(np.arange(x_discrete.shape[0]), i_split)

        return x_all_grouped, is_act_all_grouped, i_x_groups

    @staticmethod
    def _sobol(n_samples, n_dims=None) -> np.ndarray:
        """
        Sample using a Sobol sequence, which supposedly gives a better distribution of points in a hypercube.
        More info: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html
        """

        # Get the power of 2 for generating samples (generating a power of 2 gives points with the lowest discrepancy)
        pow2 = int(np.ceil(np.log2(n_samples)))

        # Sample points and only return the amount needed
        x = Sobol(d=n_dims or 1).random_base2(m=pow2)
        x = x[:n_samples, :]
        return x[:, 0] if n_dims is None else x

    @classmethod
    def _choice(cls, n_choose, n_from, replace=True, sobol=False):
        if sobol:
            return cls._sobol_choice(n_choose, n_from, replace=replace)
        return np.random.choice(n_from, n_choose, replace=replace)

    @classmethod
    def _sobol_choice(cls, n_choose, n_from, replace=True):
        """
        Randomly choose n_choose from n_from values, optionally replacing (i.e. allow choosing values multiple times).
        If n_choose > n_from
        """
        if n_choose <= 0:
            return np.zeros((0,), dtype=int)

        # If replace (i.e. values can be chosen multiple times)
        if replace:
            # Generate unit samples
            x_unit = cls._sobol(n_choose)

            # Scale to nr of possible values and round
            return np.round(x_unit*(n_from-.01)-.5).astype(np.int)

        # If we cannot replace, we cannot choose more values than available
        if n_choose > n_from:
            raise ValueError(f'Nr of values to choose should be lower than available values: {n_choose} > {n_from}')

        # Generate unit samples from total nr available
        x_unit = cls._sobol(n_from)

        # Get sorting arguments: this places each float value on an increasing integer scale
        x_unit = x_unit.argsort()

        # Only return the amount that we actually want to choose
        return x_unit[:n_choose]

    def __repr__(self):
        return f'{self.__class__.__name__}()'


class LargeDuplicateElimination(DefaultDuplicateElimination):
    """
    Duplicate elimination that can deal with a large amount of individuals in a population: instead of creating one big
    n_pop x n_pop cdist matrix, it does so in batches, thereby staying fast and saving in memory at the same time.
    """
    _n_per_batch = 200

    def _do(self, pop, other, is_duplicate):
        x = self.func(pop)
        other = self.func(other) if other is not None else None
        return self.eliminate(x, other, is_duplicate, self.epsilon)

    @classmethod
    def eliminate(cls, x, other=None, is_duplicate=None, epsilon=1e-16):
        # Either compare x to itself or to another x
        x = x.copy().astype(float)
        if is_duplicate is None:
            is_duplicate = np.zeros((x.shape[0],), dtype=bool)

        to_itself = False
        if other is None:
            x_ = x
            to_itself = True
        else:
            x_ = other.copy().astype(float)

        # Determine how many batches we need
        n_per_batch = cls._n_per_batch
        nx = x.shape[0]
        n = (x_.shape[0] - 1) if to_itself else x_.shape[0]
        if n == 0:
            return is_duplicate
        n_batches = int(np.ceil(n / n_per_batch))
        n_in_batch = np.ones((n_batches,), dtype=np.int16)*n_per_batch
        n_in_batch[-1] = n - (n_batches-1)*n_per_batch

        for ib, n_batch in enumerate(n_in_batch):
            i_compare_to = np.arange(n_batch)+ib*n_per_batch
            i = i_compare_to[0]

            # Only compare points in the population to other points that are not already marked as duplicate
            non_dup = ~is_duplicate
            x_check = x[i+1:, ][non_dup[i+1:], :] if to_itself else x[non_dup, :]
            if x_check.shape[0] == 0:
                break

            # Do the comparison: the result is an n_x_check x n_i_compare_to boolean matrix
            i_is_dup = distance.cdist(x_check, x_[i_compare_to, :], metric='cityblock') < epsilon

            if to_itself:
                # Expand to all indices from non-duplicate indices
                i_is_dup_expanded = np.zeros((nx-i-1, n_batch), dtype=bool)
                i_is_dup_expanded[non_dup[i+1:], :] = i_is_dup

                # If we compare to ourselves, we will have a diagonal that is always true, and we should ignore anything
                # above the triangle, otherwise the indices are off
                i_is_dup_expanded[np.triu_indices(n_batch, k=1)] = False

                # Mark as duplicate rows where any of the columns is true
                is_duplicate[i+1:][np.any(i_is_dup_expanded, axis=1)] = True

            else:
                # Expand to all indices from non-duplicate indices
                i_is_dup_expanded = np.zeros((nx, n_batch), dtype=bool)
                i_is_dup_expanded[non_dup, :] = i_is_dup

                # Mark as duplicate rows where any of the columns is true
                is_duplicate[np.any(i_is_dup_expanded, axis=1)] = True

        return is_duplicate
