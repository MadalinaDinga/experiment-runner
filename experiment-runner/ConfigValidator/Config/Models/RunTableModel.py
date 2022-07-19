import itertools
import random
from typing import Dict, List, Tuple, Set

from ConfigValidator.Config.Models.FactorModel import FactorModel
from ProgressManager.RunTable.Models.RunProgress import RunProgress


class RunTableModel:
    __factors:       List[FactorModel] = None
    __exclude_variations:            List[Set]   = None
    __data_columns:                  List[str]   = None

    def __init__(self, factors: List[FactorModel], exclude_variations: List[Set] = None, data_columns: List[str] = None):
        self.__factors = factors
        self.__exclude_variations = exclude_variations
        self.__data_columns = data_columns

    def get_factors(self) -> List[FactorModel]:
        return self.__factors

    def get_data_columns(self) -> List[str]:
        return self.__data_columns

    def generate_experiment_run_table(self) -> List[Dict]:
        def __filter_list(filter_list: List[Tuple]):
            if self.__exclude_variations is None:
                return filter_list

            #FIXME: we should use dictionaries instead of sets
            #For example, imagine that you have 2 numerical factors in range [0,100] and you want to skip combination (factor1=20, factor2=50)
            #With the current setupt, you will end up skipping (factor1=20, factor2=50) AND (factor2=20, factor1=50)
            #The user, as a temporary workaround, can prefix their factor levels to distinguish them.
            for exclusion in self.__exclude_variations:
                filter_list = [x for x in filter_list if not exclusion <= set(x)]

            return filter_list

        list_of_lists = []
        for treatment in self.__factors:
            list_of_lists.append(treatment.get_treatments())

        combinations_list = list(itertools.product(*list_of_lists))
        filtered_list = __filter_list(combinations_list)

        column_names = ['__run_id', '__done']   # Needed for experiment-runner functionality
        for factor in self.__factors:
            column_names.append(factor.get_factor_name())

        if self.__data_columns:
            for data_column in self.__data_columns:
                column_names.append(data_column)

        experiment_run_table = []
        for i in range(0, len(filtered_list)):
            row_list = list(filtered_list[i])
            row_list.insert(0, f'run_{i}')         # __run_id
            row_list.insert(1, RunProgress.TODO)   # __done

            if self.__data_columns:
                for data_column in self.__data_columns:
                    row_list.append(" ")

            experiment_run_table.append(dict(zip(column_names, row_list)))

        randomized_table = []

        groups = itertools.groupby(experiment_run_table, lambda row: row['trial_number'])
        for group in groups:
            tests_for_run = [run for run in group[1]]
            random.shuffle(tests_for_run)
            randomized_table.extend(tests_for_run)

        return randomized_table
