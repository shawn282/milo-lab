#!/usr/bin/python

import logging
import sys
import numpy as np

from optparse import OptionParser
from os import path

from pygibbs.metabolic_modelling import feasible_concentrations_iterator
from pygibbs.metabolic_modelling import kinetic_data
from pygibbs.metabolic_modelling import protein_optimizer
from pygibbs.metabolic_modelling import optimized_pathway
from pygibbs.metabolic_modelling import thermodynamic_data
from pygibbs import kegg
from pygibbs import thermodynamic_estimators
from pygibbs import pathway
from pygibbs import templates
from toolbox import util


def MakeOpts():
    """Returns an OptionParser object with all the default options."""
    opt_parser = OptionParser()
    opt_parser.add_option("-k", "--kegg_database_location", 
                          dest="kegg_db_filename",
                          default="../data/public_data.sqlite",
                          help="The KEGG database location")
    opt_parser.add_option("-d", "--database_location", 
                          dest="db_filename",
                          default="../res/gibbs.sqlite",
                          help="The Thermodynamic database location")
    opt_parser.add_option("-s", "--thermodynamics_source",
                          dest="thermodynamics_source",
                          type="choice",
                          choices=thermodynamic_estimators.EstimatorNames(),
                          default="merged",
                          help="The thermodynamic data to use")
    opt_parser.add_option("-i", "--input_filename",
                          dest="input_filename",
                          default="../data/thermodynamics/pathways.txt",
                          help="The file to read for pathways to analyze.")
    opt_parser.add_option("-o", "--output_dir",
                          dest="output_dir",
                          default='../res/protein_analysis/',
                          help="Where to write output to.")
    return opt_parser


def Main():
    options, _ = MakeOpts().parse_args(sys.argv)
    estimators = thermodynamic_estimators.LoadAllEstimators()
    
    input_filename = path.abspath(options.input_filename)
    if not path.exists(input_filename):
        logging.fatal('Input filename %s doesn\'t exist' % input_filename)
        
    print 'Will read pathway definitions from %s' % input_filename

    # Make thermodynamic and kinetic data containers
    thermo = estimators[options.thermodynamics_source]
    print "Using the thermodynamic estimations of: " + thermo.name
    thermo_data = thermodynamic_data.WrapperThermoData(thermo)
    
    # Uniform kinetic data
    #kin_data = kinetic_data.UniformKineticData(kcat=100, km=1e-4)
    kin_data = kinetic_data.KineticDataWithDefault.FromFiles(
        '../data/enzymatics/glycolytic_pathway_enzymes_kcat.csv',
        '../data/enzymatics/glycolytic_pathway_enzymes_km.csv')
    
    # Create a kegg instance
    kegg_instance = kegg.Kegg.getInstance()

    # Create output directories
    out_dir = options.output_dir
    if not path.exists(out_dir):
        util._mkdir(out_dir)
    pathgraph_dir = path.join(out_dir, 'pathway_graphs/')
    util._mkdir(pathgraph_dir)
    
    print 'Executing Protein Cost analysis'
    pathway_iterator = pathway.KeggPathwayIterator.FromFilename(input_filename)
    results = []
    for pathway_data in pathway_iterator:
        if pathway_data.skip:
            print 'Skipping pathway', pathway_data.name
            continue
        
        print 'Analyzing pathway', pathway_data.name
                
        model = pathway_data.GetStoichiometricModel(kegg_instance)
        model_bounds = pathway_data.GetBounds()
        
        feasible_iter = feasible_concentrations_iterator.FeasibleConcentrationsIterator(
            model, thermo_data, model_bounds)
        opt = protein_optimizer.ProteinOptimizer(model, thermo_data, kin_data)
        
        """
        # Try a bunch of feasible solutions as starting points
        optima = []
        for feasible_concs in feasible_iter:
            result = opt.FindOptimum(
                model_bounds, initial_concentrations=feasible_concs)
            status = result.status
            if status.IsSuccessful():
                optima.append(result.opt_val)
                
        # Check that the optima are really close to each other
        optima = np.array(optima)
        residuals = np.abs(optima - np.mean(optima))
        if (residuals > 1e-5).any():
            print '\tOptima are not consistent:'
            print optima
        else:
            print '\t', pathway_data.name, 'optima are consistent'
        """
        
        # Now solve with the default initial conditions.
        result = opt.FindOptimum(model_bounds)
        status = result.status
        if status.IsFailure():          
            print '\tFailed to optimize', pathway_data.name
            continue
        
        if status.IsInfeasible():            
            print '\t', pathway_data.name, 'is infeasible!'
            continue
        
        result.WriteAllGraphs(pathgraph_dir)
        results.append(result)
        
        cost = result.opt_val
        print '\tProtein Cost for', pathway_data.name, '= %.2g' % cost
    
    
    output_filename = path.join(out_dir, 'results.html')
    print 'Writing output to', output_filename
    template_data = {'analysis_type': 'Protein Cost',
                     'results':results}
    templates.render_to_file('protein_optimization_results.html',
                             template_data,
                             output_filename)
    

if __name__ == "__main__":
    Main()
    