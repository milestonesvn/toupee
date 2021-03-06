#!/usr/bin/python
"""
Run an ensemble experiment from a yaml file

Alan Mosca
Department of Computer Science and Information Systems
Birkbeck, University of London

All code released under GPLv2.0 licensing.
"""
__docformat__ = 'restructedtext en'


import numpy
import argparse
import os
import re
import copy
from toupee.common import accuracy

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train a single MLP')
    parser.add_argument('params_file', help='the parameters file')
    parser.add_argument('save_file', nargs='?',
                        help='the file where the trained MLP is to be saved')
    parser.add_argument('--seed', type=int, nargs='?', default=42,
                        help='random seed to use for this sim')
    parser.add_argument('--epochs', type=int, nargs='?',
                        help='number of epochs to run')
    parser.add_argument('--results-db', nargs='?',
                        help='mongodb db name for storing results')
    parser.add_argument('--results-host', nargs='?',
                        help='mongodb host name for storing results')
    parser.add_argument('--results-table', nargs='?',
                        help='mongodb table name for storing results')
    parser.add_argument('--device', nargs='?',
                        help='gpu/cpu device to use for training')
    parser.add_argument('--dump-shapes-to', type=str, nargs='?', default=42,
                        help='location where to save the shape of the ensemble members')

    args = parser.parse_args()
    #this needs to come before all the toupee and theano imports
    #because theano starts up with gpu0 and never lets you change it
    if args.device is not None:
        if 'THEANO_FLAGS' in os.environ is not None:
            env = os.environ['THEANO_FLAGS']
            env = re.sub(r'/device=[a-zA-Z0-9]+/',r'/device=' + args.device, env)
        else:
            env = 'device=' + args.device
        os.environ['THEANO_FLAGS'] = env

    arg_param_pairings = [
        (args.results_db, 'results_db'),
        (args.results_host, 'results_host'),
        (args.results_table, 'results_table'),
        (args.epochs, 'n_epochs'),
    ]
    
    if 'seed' in args.__dict__:
        print "setting random seed to: {0}".format(args.seed)
        numpy.random.seed(args.seed)
    from toupee import data
    from toupee import config 
    from toupee.mlp import sequential_model

    params = config.load_parameters(args.params_file)

    def arg_params(arg_value,param):
        if arg_value is not None:
            params.__dict__[param] = arg_value

    for arg, param in arg_param_pairings:
        arg_params(arg,param)
    original_params = copy.deepcopy(params)
    dataset = data.load_data(params.dataset,
                             pickled = params.pickled,
                             one_hot_y = params.one_hot,
                             join_train_and_valid = params.join_train_and_valid,
                             zca_whitening = params.zca_whitening)
    method = params.method
    method.prepare(params,dataset)
    train_set = method.resampler.get_train()
    valid_set = method.resampler.get_valid()
    members = []
    intermediate_scores = []
    final_score = None
    for i in range(0,params.ensemble_size):
        print 'training member {0}'.format(i)
        members.append(method.create_member())
        ensemble = method.create_aggregator(params,members,train_set,valid_set)
        test_set_x, test_set_y = method.resampler.get_test()
        test_score = accuracy(ensemble,test_set_x,test_set_y)
        print 'Intermediate test accuracy: {0} %'.format(test_score * 100.)
        intermediate_scores.append(test_score)
        final_score = test_score
    print "\nFinal Ensemble test accuracy: {0} %".format(final_score * 100.)
    print "Preparing distillation dataset.."
    train_set_yhat = ensemble.predict(dataset[0][0])
    distilled_dataset = ((dataset[0][0], train_set_yhat), dataset[1], dataset[2])
    params = original_params
    mlp = sequential_model(distilled_dataset, params, model_yaml = members[-1][0])
    if args.dump_shapes_to is not None:
        for i in range(len(members)):
            with open("{0}member-{1}.model".format(args.dump_shapes_to, i),"w") as f:
                f.truncate()
                f.write(members[i][0])
    if 'results_db' in params.__dict__:
        if 'results_host' in params.__dict__:
            host = params.results_host
        else:
            host = None
        print "saving results to {0}@{1}".format(params.results_db,host)
        conn = MongoClient(host=host)
        db = conn[params.results_db]
        if 'results_table' in params.__dict__: 
            table_name = params.results_table
        else:
            table_name = 'results'
        table = db[table_name]
        results = {
                    "params": params.__dict__,
                    "intermediate_test_scores" : intermediate_scores,
                    "final_test_score" : final_score,
                  }
        table.insert(json.loads(json.dumps(results,default=common.serialize)))
