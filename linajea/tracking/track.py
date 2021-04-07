from __future__ import absolute_import
from .solver import Solver
from .track_graph import TrackGraph
import logging
import time
import networkx as nx

logger = logging.getLogger(__name__)


def track(graph, config, selected_key, frame_key='t', frames=None,
          block_id=None):
    ''' A wrapper function that takes a daisy subgraph and input parameters,
    creates and solves the ILP to create tracks, and updates the daisy subgraph
    to reflect the selected nodes and edges.

    Args:

        graph (``daisy.SharedSubgraph``):

            The candidate graph to extract tracks from

        config (``TrackingConfig``)

            Configuration object to be used. The parameters to use when
            optimizing the tracking ILP are at config.solve.parameters
            (can also be a list of parameters).

        selected_key (``string``)

            The key used to store the `true` or `false` selection status of
            each node and edge in graph. Can also be a list of keys
            corresponding to the list of parameters.

        frame_key (``string``, optional):

            The name of the node attribute that corresponds to the frame of the
            node. Defaults to "t".

        frames (``list`` of ``int``):

            The start and end frames to solve in (in case the graph doesn't
            have nodes in all frames). Start is inclusive, end is exclusive.
            Defaults to graph.begin, graph.end

        block_id (``int``, optional):

            The ID of the current daisy block.

    '''
    # cell_cycle_keys = [p.cell_cycle_key for p in config.solve.parameters]
    cell_cycle_keys = [p.cell_cycle_key + "mother" for p in config.solve.parameters]
    if any(cell_cycle_keys):
        # remove nodes that don't have a cell cycle key, with warning
        to_remove = []
        for node, data in graph.nodes(data=True):
            for key in cell_cycle_keys:
                if key not in data:
                    logger.warning("Node %d does not have cell cycle key %s",
                                   node, key)
                    to_remove.append(node)
                    break

        for node in to_remove:
            logger.debug("Removing node %d", node)
            graph.remove_node(node)

    # assuming graph is a daisy subgraph
    if graph.number_of_nodes() == 0:
        logger.info("No nodes in graph - skipping solving step")
        return

    parameters = config.solve.parameters
    if not isinstance(parameters, list):
        parameters = [parameters]
        selected_key = [selected_key]

    assert len(parameters) == len(selected_key),\
        "%d parameter sets and %d selected keys" %\
        (len(parameters), len(selected_key))

    logger.debug("Creating track graph...")
    track_graph = TrackGraph(graph_data=graph,
                             frame_key=frame_key,
                             roi=graph.roi)

    logger.debug("Creating solver...")
    solver = None
    total_solve_time = 0
    for parameter, key in zip(parameters, selected_key):
        if not solver:
            solver = Solver(
                track_graph, parameter, key, frames=frames,
                write_struct_svm=config.solve.write_struct_svm,
                block_id=block_id,
                check_node_close_to_roi=config.solve.check_node_close_to_roi,
                add_node_density_constraints=config.solve.add_node_density_constraints)
        else:
            solver.update_objective(parameter, key)

        logger.debug("Solving for key %s", str(key))
        start_time = time.time()
        solver.solve()
        end_time = time.time()
        total_solve_time += end_time - start_time
        logger.info("Solving ILP took %s seconds", str(end_time - start_time))

        for u, v, data in graph.edges(data=True):
            if (u, v) in track_graph.edges:
                data[key] = track_graph.edges[(u, v)][key]
    logger.info("Solving ILP for all parameters took %s seconds",
                str(total_solve_time))


def greedy_track(
        graph,
        selected_key,
        metric='prediction_distance',
        frame_key='t',
        frames=None,
        node_threshold=None):
    ''' A wrapper function that takes a daisy subgraph and input parameters,
    greedily chooses edges to create tracks, and updates the daisy subgraph to
    reflect the selected nodes and edges.

    Args:

        graph (``daisy.SharedSubgraph``):
            The candidate graph to extract tracks from

        selected_key (``string``)
            The key used to store the `true` or `false` selection status of
            each edge in graph.

        metric (``string``)
            Type of distance to use when finding "shortest" edges. Options are
            'prediction_distance' (default) and 'distance'

        frame_key (``string``, optional):

            The name of the node attribute that corresponds to the frame of the
            node. Defaults to "t".

        frames (``list`` of ``int``):
            The start and end frames to solve in (in case the graph doesn't
            have nodes in all frames). Start is inclusive, end is exclusive.
            Defaults to graph.begin, graph.end

        node_threshold (``float``):
            Don't use nodes with score below this values. Defaults to None.
    '''
    # assuming graph is a daisy subgraph
    if graph.number_of_nodes() == 0:
        return

    selected = nx.DiGraph()
    unselected = nx.DiGraph()
    unselected.add_nodes_from(graph.nodes(data=True))
    unselected.add_edges_from(graph.edges(data=True))
    nx.set_edge_attributes(graph, False, selected_key)

    if node_threshold:
        logger.debug("Removing nodes below threshold")
        for node, data in list(unselected.nodes(data=True)):
            if data['score'] < node_threshold:
                unselected.remove_node(node)

    logger.debug("Sorting edges")
    sorted_edges = sorted(list(graph.edges(data=True)),
                          key=lambda e: e[2][metric])

    logger.debug("Selecting shortest edges")
    for u, v, data in sorted_edges:
        if unselected.has_edge(u, v):
            graph.edges[(u, v)][selected_key] = True
            selected.add_edge(u, v)
            unselected.remove_edges_from(list(graph.out_edges(u)))
            if selected.in_degree(v) > 1:
                unselected.remove_edges_from(list(unselected.in_edges(v)))
