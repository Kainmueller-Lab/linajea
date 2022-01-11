import logging
import os
import re

import pandas

from linajea import (CandidateDatabase,
                     checkOrCreateDB)
from linajea.tracking import TrackingParameters

logger = logging.getLogger(__name__)


def get_sample_from_setup(setup):
    sample_int = int(re.search(re.compile(r"\d*"), setup).group())
    if sample_int < 100:
        return '140521'
    elif sample_int < 200:
        return '160328'
    elif sample_int < 300:
        return '120828'
    else:
        raise ValueError("Setup number must be < 300 to infer sample")


def get_result(
        db_name,
        tracking_parameters,
        db_host,
        frames=None,
        sample=None,
        iteration='400000'):
    ''' Get the scores, statistics, and parameters for given
    setup, region, and parameters.
    Returns a dictionary containing the keys and values of the score
    object.

    tracking_parameters can be a dict or a TrackingParameters object'''
    candidate_db = CandidateDatabase(db_name, db_host, 'r')
    if isinstance(tracking_parameters, dict):
        tracking_parameters = TrackingParameters(**tracking_parameters)
    parameters_id = candidate_db.get_parameters_id(
            tracking_parameters,
            fail_if_not_exists=True)
    result = candidate_db.get_score(parameters_id, frames=frames)
    return result


def get_greedy(
        db_name,
        db_host,
        key="selected_greedy",
        frames=None):

    candidate_db = CandidateDatabase(db_name, db_host, 'r')
    result = candidate_db.get_score(key, frames=frames)
    if result is None:
        logger.error("Greedy result for db %d is None", db_name)
    return result


def get_tgmm_results(
        db_name,
        db_host,
        frames=None):
    candidate_db = CandidateDatabase(db_name, db_host, 'r')
    results = candidate_db.get_scores(frames=frames)
    if results is None or len(results) == 0:
        return None
    all_results = pandas.DataFrame(results)
    return all_results


def get_best_tgmm_result(
        db_name,
        db_host,
        frames=None,
        score_columns=None,
        score_weights=None):
    if not score_columns:
        score_columns = ['fn_edges', 'identity_switches',
                         'fp_divisions', 'fn_divisions']
    if not score_weights:
        score_weights = [1.]*len(score_columns)
    results_df = get_tgmm_results(db_name, db_host, frames=frames)
    if results_df is None:
        logger.warn("No TGMM results for db %s, and frames %s"
                    % (db_name, str(frames)))
        return None
    results_df['sum_errors'] = sum([results_df[col]*weight for col, weight
                                   in zip(score_columns, score_weights)])
    results_df.sort_values('sum_errors', inplace=True)
    best_result = results_df.iloc[0].to_dict()
    best_result['setup'] = 'TGMM'
    return best_result


def get_results(
        db_name,
        db_host,
        sample=None,
        iteration='400000',
        frames=None,
        filter_params=None):
    ''' Gets the scores, statistics, and parameters for all
    grid search configurations run for the given setup and region.
    Returns a pandas dataframe with one row per configuration.'''
    candidate_db = CandidateDatabase(db_name, db_host, 'r')
    scores = candidate_db.get_scores(frames=frames, filters=filter_params)
    dataframe = pandas.DataFrame(scores)
    logger.debug("data types of dataframe columns: %s"
                 % str(dataframe.dtypes))
    if 'param_id' in dataframe:
        dataframe['_id'] = dataframe['param_id']
        dataframe.set_index('param_id', inplace=True)
    return dataframe


def get_best_result(db_name, db_host,
                    sample=None,
                    iteration='400000',
                    frames=None,
                    filter_params=None,
                    score_columns=None,
                    score_weights=None):
    ''' Gets the best result for the given setup and region according to
    the sum of errors in score_columns, with optional weighting.

    Returns a dictionary'''
    if not score_columns:
        score_columns = ['fn_edges', 'identity_switches',
                         'fp_divisions', 'fn_divisions']
    if not score_weights:
        score_weights = [1.]*len(score_columns)
    results_df = get_results(db_name, db_host,
                             frames=frames,
                             sample=sample, iteration=iteration,
                             filter_params=filter_params)
    results_df['sum_errors'] = sum([results_df[col]*weight for col, weight
                                   in zip(score_columns, score_weights)])
    results_df.sort_values('sum_errors', inplace=True)
    best_result = results_df.iloc[0].to_dict()
    for key, value in best_result.items():
        try:
            best_result[key] = value.item()
        except AttributeError:
            pass
    return best_result


def get_best_result_per_setup(db_names, db_host,
                              frames=None, sample=None, iteration='400000',
                              filter_params=None,
                              score_columns=None, score_weights=None):
    ''' Returns the best result for each db in db_names
    according to the sum of errors in score_columns, with optional weighting,
    sorted from best to worst (lowest to highest sum errors)'''
    best_results = []
    for db_name in db_names:
        best = get_best_result(db_name, db_host,
                               frames=frames,
                               sample=sample, iteration=iteration,
                               filter_params=filter_params,
                               score_columns=score_columns,
                               score_weights=score_weights)
        best_results.append(best)

    best_df = pandas.DataFrame(best_results)
    best_df.sort_values('sum_errors', inplace=True)
    return best_df


def get_results_sorted(config,
                       filter_params=None,
                       score_columns=None,
                       score_weights=None,
                       sort_by="sum_errors"):
    if not score_columns:
        score_columns = ['fn_edges', 'identity_switches',
                         'fp_divisions', 'fn_divisions']
    if not score_weights:
        score_weights = [1.]*len(score_columns)

    db_name = config.inference.data_source.db_name

    logger.info("checking db: %s", db_name)

    candidate_db = CandidateDatabase(db_name, config.general.db_host, 'r')
    scores = candidate_db.get_scores(filters=filter_params,
                                     eval_params=config.evaluate.parameters)

    if len(scores) == 0:
        raise RuntimeError("no scores found!")

    results_df = pandas.DataFrame(scores)
    logger.debug("data types of results_df dataframe columns: %s"
                 % str(results_df.dtypes))
    if 'param_id' in results_df:
        results_df['_id'] = results_df['param_id']
        results_df.set_index('param_id', inplace=True)

    results_df['sum_errors'] = sum([results_df[col]*weight for col, weight
                                   in zip(score_columns, score_weights)])
    results_df['sum_divs'] = sum(
        [results_df[col]*weight for col, weight
         in zip(score_columns[-2:], score_weights[-2:])])
    results_df = results_df.astype({"sum_errors": int, "sum_divs": int})
    ascending = True
    if sort_by == "matched_edges":
        ascending = False
    results_df.sort_values(sort_by, ascending=ascending, inplace=True)
    return results_df


def get_best_result_with_config(config,
                                filter_params=None,
                                score_columns=None,
                                score_weights=None):
    ''' Gets the best result for the given setup and region according to
    the sum of errors in score_columns, with optional weighting.

    Returns a dictionary'''

    results_df = get_results_sorted(config,
                                    filter_params=filter_params,
                                    score_columns=score_columns,
                                    score_weights=score_weights)
    best_result = results_df.iloc[0].to_dict()
    for key, value in best_result.items():
        try:
            best_result[key] = value.item()
        except AttributeError:
            pass
    return best_result


def get_results_sorted_db(db_name,
                          db_host,
                          filter_params=None,
                          score_columns=None,
                          score_weights=None,
                          sort_by="sum_errors"):
    if not score_columns:
        score_columns = ['fn_edges', 'identity_switches',
                         'fp_divisions', 'fn_divisions']
    if not score_weights:
        score_weights = [1.]*len(score_columns)

    logger.info("checking db: %s", db_name)

    candidate_db = CandidateDatabase(db_name, db_host, 'r')
    scores = candidate_db.get_scores(filters=filter_params)

    if len(scores) == 0:
        raise RuntimeError("no scores found!")

    results_df = pandas.DataFrame(scores)
    logger.debug("data types of results_df dataframe columns: %s"
                 % str(results_df.dtypes))
    if 'param_id' in results_df:
        results_df['_id'] = results_df['param_id']
        results_df.set_index('param_id', inplace=True)

    results_df['sum_errors'] = sum([results_df[col]*weight for col, weight
                                   in zip(score_columns, score_weights)])
    results_df['sum_divs'] = sum(
        [results_df[col]*weight for col, weight
         in zip(score_columns[-2:], score_weights[-2:])])
    results_df = results_df.astype({"sum_errors": int, "sum_divs": int})
    ascending = True
    if sort_by == "matched_edges":
        ascending = False
    results_df.sort_values(sort_by, ascending=ascending, inplace=True)
    return results_df


def get_result_id(
        config,
        parameters_id):
    ''' Get the scores, statistics, and parameters for given
    setup, region, and parameters.
    Returns a dictionary containing the keys and values of the score
    object.

    tracking_parameters can be a dict or a TrackingParameters object'''
    db_name = config.inference.data_source.db_name
    candidate_db = CandidateDatabase(db_name, config.general.db_host, 'r')

    result = candidate_db.get_score(parameters_id,
                                    eval_params=config.evaluate.parameters)
    return result
