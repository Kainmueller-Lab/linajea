import daisy
import json
from linajea import CandidateDatabase
from .daisy_check_functions import (
        check_function, write_done,
        check_function_all_blocks, write_done_all_blocks)
from linajea.tracking import track
import logging
import os
import time

logger = logging.getLogger(__name__)


def solve_blockwise(
        db_host,
        db_name,
        sample,
        parameters,  # list of TrackingParameters
        num_workers=8,
        frames=None,
        limit_to_roi=None,
        from_scratch=False,
        data_dir='../01_data',
        **kwargs):

    block_size = daisy.Coordinate(parameters[0].block_size)
    context = daisy.Coordinate(parameters[0].context)
    # block size and context must be the same for all parameters!
    for i in range(len(parameters)):
        assert list(block_size) == parameters[i].block_size,\
                "%s not equal to %s" %\
                (block_size, parameters[i].block_size)
        assert list(context) == parameters[i].context

    # get absolute paths
    if os.path.isfile(sample) or sample.endswith((".zarr", ".n5")):
        sample_dir = os.path.abspath(os.path.join(data_dir,
                                                  os.path.dirname(sample)))
    else:
        sample_dir = os.path.abspath(os.path.join(data_dir, sample))
    # get ROI of source
    with open(os.path.join(sample_dir, 'attributes.json'), 'r') as f:
        attributes = json.load(f)

    voxel_size = daisy.Coordinate(attributes['resolution'])
    shape = daisy.Coordinate(attributes['shape'])
    offset = daisy.Coordinate(attributes['offset'])
    source_roi = daisy.Roi(offset, shape*voxel_size)

    # determine parameters id from database
    graph_provider = CandidateDatabase(
        db_name,
        db_host)
    parameters_id = [graph_provider.get_parameters_id(p) for p in parameters]

    if from_scratch:
        for pid in parameters_id:
            graph_provider.set_parameters_id(pid)
            graph_provider.reset_selection()

    # limit to specific frames, if given
    if frames:
        logger.info("Solving in frames %s" % frames)
        begin, end = frames
        crop_roi = daisy.Roi(
            (begin, None, None, None),
            (end - begin, None, None, None))
        source_roi = source_roi.intersect(crop_roi)
    # limit to roi, if given
    if limit_to_roi:
        logger.info("limiting to roi %s" % str(limit_to_roi))
        source_roi = source_roi.intersect(limit_to_roi)

    block_write_roi = daisy.Roi(
        (0, 0, 0, 0),
        block_size)
    block_read_roi = block_write_roi.grow(
        context,
        context)
    total_roi = source_roi.grow(
        context,
        context)

    logger.info("Solving in %s", total_roi)
    if len(parameters_id) == 1:
        step_name = 'solve_' + str(parameters_id[0])
    else:
        step_name = 'solve_' + str(hash(frozenset(parameters_id)))

    if check_function_all_blocks(step_name, db_name, db_host):
        logger.info("Step %s is already completed. Exiting" % step_name)
        return True

    success = daisy.run_blockwise(
        total_roi,
        block_read_roi,
        block_write_roi,
        process_function=lambda b: solve_in_block(
            db_host,
            db_name,
            parameters,
            b,
            parameters_id,
            solution_roi=source_roi),
        check_function=lambda b: check_function(
            b,
            step_name,
            db_name,
            db_host),
        num_workers=num_workers,
        fit='overhang')
    if success:
        write_done_all_blocks(
            step_name,
            db_name,
            db_host)
    logger.info("Finished solving")
    return success


def solve_in_block(
        db_host,
        db_name,
        parameters,
        block,
        parameters_id,
        solution_roi=None):
    # Solution_roi is the total roi that you want a solution in
    # Limiting the block to the solution_roi allows you to solve
    # all the way to the edge, without worrying about reading
    # data from outside the solution roi
    # or paying the appear or disappear costs unnecessarily

    if len(parameters_id) == 1:
        step_name = 'solve_' + str(parameters_id[0])
    else:
        _id = hash(frozenset(parameters_id))
        step_name = 'solve_' + str(_id)
    logger.debug("Solving in block %s", block)

    if solution_roi:
        # Limit block to source_roi
        logger.debug("Block write roi: %s", block.write_roi)
        logger.debug("Solution roi: %s", solution_roi)
        read_roi = block.read_roi.intersect(solution_roi)
        write_roi = block.write_roi.intersect(solution_roi)
    else:
        read_roi = block.read_roi
        write_roi = block.write_roi

    logger.debug("Write roi: %s", str(write_roi))

    graph_provider = CandidateDatabase(
        db_name,
        db_host,
        mode='r+')
    start_time = time.time()
    selected_keys = ['selected_' + str(pid) for pid in parameters_id]
    edge_attrs = selected_keys.copy()
    edge_attrs.extend(["prediction_distance", "distance"])
    graph = graph_provider.get_graph(
            read_roi,
            edge_attrs=edge_attrs
            )

    # remove dangling nodes and edges
    dangling_nodes = [
        n
        for n, data in graph.nodes(data=True)
        if 't' not in data
    ]
    graph.remove_nodes_from(dangling_nodes)

    num_nodes = graph.number_of_nodes()
    num_edges = graph.number_of_edges()
    logger.info("Reading graph with %d nodes and %d edges took %s seconds"
                % (num_nodes, num_edges, time.time() - start_time))

    if num_edges == 0:
        logger.info("No edges in roi %s. Skipping"
                    % read_roi)
        write_done(block, step_name, db_name, db_host)
        return 0

    frames = [read_roi.get_offset()[0],
              read_roi.get_offset()[0] + read_roi.get_shape()[0]]
    track(graph, parameters, selected_keys, frames=frames)
    start_time = time.time()
    graph.update_edge_attrs(
            write_roi,
            attributes=selected_keys)
    logger.info("Updating %d keys for %d edges took %s seconds"
                % (len(selected_keys),
                   num_edges,
                   time.time() - start_time))
    write_done(block, step_name, db_name, db_host)
    return 0
