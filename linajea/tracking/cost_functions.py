"""Provides a set of cost functions to use in solver

Should return a list of costs that will be applied to some indicator
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)


def score_times_weight_plus_th_costs_fn(weight, threshold, key="score",
                                        feature_func=lambda x: x):

    def cost_fn(obj):
        # feature_func(obj score) times a weight plus a threshold
        score_costs = [feature_func(obj[key]) * weight, threshold]
        logger.debug("set score times weight plus th costs %s", score_costs)
        return score_costs

    return cost_fn


def score_times_weight_costs_fn(weight, key="score",
                                feature_func=lambda x: x):

    def cost_fn(obj):
        # feature_func(obj score) times a weight
        score_costs = [feature_func(obj[key]) * weight]
        logger.debug("set score times weight costs %s", score_costs)
        return score_costs

    return cost_fn


def constant_costs_fn(weight, zero_if_true=lambda _: False):

    def cost_fn(obj):
        costs = [0] if zero_if_true(obj) else [weight]
        logger.debug("set constant costs if %s = True costs %s",
                     zero_if_true(obj), costs)
        return costs

    return cost_fn


def is_nth_frame(n, frame_key='t'):

    def is_frame(obj):
        return obj[frame_key] == n

    return is_frame


def is_close_to_roi_border(roi, distance):

    def is_close(obj):
        '''Return true if obj is within distance to the z,y,x edge
        of the roi. Assumes 4D data with t,z,y,x'''
        if isinstance(distance, dict):
            dist = min(distance.values())
        else:
            dist = distance

        begin = roi.get_begin()[1:]
        end = roi.get_end()[1:]
        for index, dim in enumerate(['z', 'y', 'x']):
            node_dim = obj[dim]
            begin_dim = begin[index]
            end_dim = end[index]
            if node_dim + dist >= end_dim or\
               node_dim - dist < begin_dim:
                logger.debug("Obj %s with value %s in dimension %s "
                             "is within %s of range [%d, %d]",
                             obj, node_dim, dim, dist,
                             begin_dim, end_dim)
                return True
        logger.debug("Obj %s is not within %s to edge of roi %s",
                     obj, dist, roi)
        return False

    return is_close


def get_default_node_indicator_costs(config, parameters, graph):
    """Get a predefined map of node indicator costs functions

    Args
    ----
    config: TrackingConfig
        Configuration object used, should contain information on which solver
        type to use.
    parameters: SolveParametersConfig
        Current set of weights and parameters used to compute costs.
    graph: TrackGraph
        Graph containing the node candidates for which the costs will be
        computed.
    """
    if parameters.feature_func == "noop":
        feature_func = lambda x: x  # noqa: E731
    elif parameters.feature_func == "log":
        feature_func = np.log
    elif parameters.feature_func == "square":
        feature_func = np.square
    else:
        raise RuntimeError("unknown (non-linear) feature function: %s",
                           parameters.feature_func)

    solver_type = config.solve.solver_type
    fn_map = {
        "node_selected":
        score_times_weight_plus_th_costs_fn(
            parameters.weight_node_score,
            parameters.selection_constant,
            key="score", feature_func=feature_func),
        "node_appear": constant_costs_fn(
            parameters.track_cost,
            zero_if_true=lambda obj: (
                is_nth_frame(graph.begin)(obj) or
                (config.solve.check_node_close_to_roi and
                 is_close_to_roi_border(
                     graph.roi, parameters.max_cell_move)(obj))))
    }
    if solver_type == "basic":
        fn_map["node_split"] = constant_costs_fn(1)
    elif solver_type == "cell_state":
        fn_map["node_split"] = score_times_weight_plus_th_costs_fn(
            parameters.weight_division,
            parameters.division_constant,
            key="score_mother", feature_func=feature_func)
        fn_map["node_child"] = score_times_weight_costs_fn(
            parameters.weight_child,
            key="score_daughter", feature_func=feature_func)
        fn_map["node_continuation"] = score_times_weight_costs_fn(
            parameters.weight_continuation,
            key="score_continuation", feature_func=feature_func)
    else:
        logger.info("solver_type %s unknown for node indicators, skipping",
                    solver_type)

    return fn_map


def get_default_edge_indicator_costs(config, parameters):
    """Get a predefined map of edge indicator costs functions

    Args
    ----
    config: TrackingConfig
        Configuration object used, should contain information on which solver
        type to use.
    parameters: SolveParametersConfig
        Current set of weights and parameters used to compute costs.
    """
    if parameters.feature_func == "noop":
        feature_func = lambda x: x  # noqa: E731
    elif parameters.feature_func == "log":
        feature_func = np.log
    elif parameters.feature_func == "square":
        feature_func = np.square
    else:
        raise RuntimeError("unknown (non-linear) feature function: %s",
                           parameters.feature_func)

    solver_type = config.solve.solver_type
    fn_map = {
        "edge_selected":
        score_times_weight_costs_fn(parameters.weight_edge_score,
                                    key="prediction_distance",
                                    feature_func=feature_func)
    }
    if solver_type == "basic":
        pass
    else:
        logger.info("solver_type %s unknown for edge indicators, skipping",
                    solver_type)

    return fn_map
