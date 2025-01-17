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
import math
import numpy as np

from pymoo.core.individual import Individual
from pymoo.core.infill import InfillCriterion
from pymoo.core.population import Population
from pymoo.core.problem import Problem
from pymoo.core.variable import Choice, Real, Integer, Binary
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.crossover.ux import UX
from pymoo.operators.mutation.bitflip import BFM
from pymoo.operators.mutation.pm import PM
from pymoo.operators.mutation.rm import ChoiceRandomMutation
from pymoo.operators.repair.rounding import RoundingRepair
from pymoo.operators.selection.rnd import RandomSelection

__all__ = ['MixedDiscreteMating']


class MixedDiscreteMating(InfillCriterion):
    """SBArchOpt implementation of mixed-discrete mating (crossover and mutation) operations. Similar functionality as
    `pymoo.core.mixed.MixedVariableMating`, however keeps x as a matrix."""

    def __init__(self,
                 selection=RandomSelection(),
                 crossover=None,
                 mutation=None,
                 repair=None,
                 eliminate_duplicates=True,
                 n_max_iterations=100,
                 **kwargs):

        super().__init__(repair, eliminate_duplicates, n_max_iterations, **kwargs)

        if crossover is None:
            crossover = {
                Binary: UX(),
                Real: SBX(),
                Integer: SBX(vtype=float, repair=RoundingRepair()),
                Choice: UX(),
            }

        if mutation is None:
            mutation = {
                Binary: BFM(),
                Real: PM(),
                Integer: PM(vtype=float, repair=RoundingRepair()),
                Choice: ChoiceRandomMutation(),
            }

        self.selection = selection
        self.crossover = crossover
        self.mutation = mutation

    def _do(self, problem, pop, n_offsprings, parents=False, **kwargs):

        # So far we assume all crossover need the same amount of parents and create the same number of offsprings
        n_parents_crossover = 2
        n_offspring_crossover = 2

        # the variables with the concrete information
        var_defs = problem.vars

        # group all the variables by their types
        vars_by_type = {}
        for k, v in var_defs.items():
            clazz = type(v)

            if clazz not in vars_by_type:
                vars_by_type[clazz] = []
            vars_by_type[clazz].append(k)

        # # all different recombinations (the choices need to be split because of data types)
        recomb = []
        idx = 0
        for clazz, list_of_vars in vars_by_type.items():
            if clazz == Choice:
                for e in list_of_vars:
                    recomb.append((clazz, [e], np.array([idx])))
                    idx += 1
            else:
                recomb.append((clazz, list_of_vars, np.array(range(idx, idx+len(list_of_vars)))))
                idx += len(list_of_vars)

        # create an empty population that will be set in each iteration
        x_out = np.empty((n_offsprings, len(var_defs)))

        if not parents:
            n_select = math.ceil(n_offsprings / n_offspring_crossover)
            pop = self.selection(problem, pop, n_select, n_parents_crossover, **kwargs)

        for clazz, list_of_vars, x_idx in recomb:

            crossover = self.crossover[clazz]
            assert crossover.n_parents == n_parents_crossover and crossover.n_offsprings == n_offspring_crossover

            _parents = [[Individual(X=parent.X[x_idx]) for parent in parents] for parents in pop]

            _vars = [var_defs[e] for e in list_of_vars]
            _xl, _xu = None, None

            if clazz in [Real, Integer]:
                _xl, _xu = np.array([v.bounds for v in _vars]).T

            _problem = Problem(vars=_vars, xl=_xl, xu=_xu)

            while True:
                _off = crossover(_problem, _parents, **kwargs)

                mutation = self.mutation[clazz]
                _off = mutation(_problem, _off, **kwargs)

                # Sometimes NaN's might sneak into the outputs, try again if this is the case
                x_off = _off.get('X')[:n_offsprings, :]
                if np.any(np.isnan(x_off)):
                    continue
                break

            x_out[:, x_idx] = x_off

        return Population.new(X=x_out)
