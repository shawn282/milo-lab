import numpy as np
import matplotlib.pyplot as plt
import logging
from pygibbs.kegg_parser import ParsedKeggFile
from pygibbs.pathway import PathwayData
from toolbox.html_writer import HtmlWriter, NullHtmlWriter
from pygibbs.pathway_modelling import KeggPathway
from pygibbs.thermodynamic_estimators import LoadAllEstimators
from pygibbs.thermodynamic_constants import R, symbol_dr_G_prime, default_T
from pygibbs.kegg_reaction import Reaction
import csv

def pareto(kegg_file, html_writer, thermo, pH=None,
           plot_profile=False, section_prefix="", balance_water=True,
           override_bounds={}):
    """
        Return values are (data, labels)
        
        data - a matrix where the rows are the pathways (entries) and the columns are
               max Total dG and ODB
        labels - a list of the names of the pathways
    """
    
    entries = kegg_file.entries()
    plot_data = np.zeros((len(entries), 5)) # ODB, ODFE, min TG, max TG, sum(fluxes)
    
    html_writer.write('<h2 id="%s_tables">Individual result tables</h1>\n' % section_prefix)
    remarks = []
    good_entries = []
    for i, entry in enumerate(entries):
        field_map = kegg_file[entry]
        p_data = PathwayData.FromFieldMap(field_map)
        
        if p_data.skip:
            logging.info("Skipping pathway: %s", entry)
            remarks.append('skipping')
            continue
        
        if pH is None:
            pH = p_data.pH
        thermo.SetConditions(pH=pH, I=p_data.I, T=p_data.T, pMg=p_data.pMg)
        thermo.c_range = p_data.c_range

        #html_writer.write('<a name="%s"></a>\n' % entry)
        html_writer.write('<h3 id="%s_%s">%s</h2>\n' % (section_prefix, entry, entry))

        S, rids, fluxes, cids = p_data.get_explicit_reactions(balance_water=balance_water)
        thermo.bounds = p_data.GetBounds().GetOldStyleBounds(cids)
        for cid, (lb, ub) in override_bounds.iteritems():
            thermo.bounds[cid] = (lb, ub)
        
        fluxes = np.matrix(fluxes)
        dG0_r_prime = thermo.GetTransfromedReactionEnergies(S, cids)
        keggpath = KeggPathway(S, rids, fluxes, cids, reaction_energies=dG0_r_prime,
                               cid2bounds=thermo.bounds, c_range=thermo.c_range)

        if np.any(np.isnan(dG0_r_prime)):
            remarks.append('NaN reaction energy')
            html_writer.write('NaN reaction energy')
            keggpath.WriteProfileToHtmlTable(html_writer)
            keggpath.WriteConcentrationsToHtmlTable(html_writer)
            continue

        _ln_conc, obd = keggpath.FindMtdf()
        odfe = 100 * np.tanh(obd / (2*R*thermo.T))

        _ln_conc, min_tg = keggpath.GetTotalReactionEnergy(obd, maximize=False) # min TG - maximal Total dG
        ln_conc, max_tg = keggpath.GetTotalReactionEnergy(obd, maximize=True) # max TG - maximal Total dG
        concentrations = np.exp(ln_conc)
        
        good_entries.append(i)
        remarks.append('okay')
        plot_data[i, :] = [obd, odfe, min_tg, max_tg, np.sum(fluxes)]

        logging.info('%20s: ODB = %.1f [kJ/mol], maxTG = %.1f [kJ/mol]' % (entry, obd, max_tg))
        html_writer.write_ul(["pH = %.1f, I = %.2fM, T = %.2f K" % (thermo.pH, thermo.I, thermo.T),
                              "ODB = %.1f [kJ/mol]" % obd,
                              "ODFE = %.1f%%" % odfe,
                              "Min Total %s = %.1f [kJ/mol]" % (symbol_dr_G_prime, min_tg),
                              "Max Total %s = %.1f [kJ/mol]" % (symbol_dr_G_prime, max_tg)])
        keggpath.WriteProfileToHtmlTable(html_writer, concentrations)
        keggpath.WriteConcentrationsToHtmlTable(html_writer, concentrations)

    html_writer.write('<h2 id="%s_summary">Summary table</h1>\n' % section_prefix)
    dict_list = [{'Name':'<a href="#%s_%s">%s</a>' % (section_prefix, entries[i], entries[i]),
                  'ODB [kJ/mol]':'%.1f' % plot_data[i, 0],
                  'ODFE':'%.1f%%' % plot_data[i, 1],
                  'Total dG\' [kJ/mol]':'%6.1f - %6.1f' % (plot_data[i, 2], plot_data[i, 3]),
                  'sum(flux)':'%g' % plot_data[i, 4],
                  'remark':remarks[i]}
                 for i in xrange(len(entries))]
    html_writer.write_table(dict_list,
        headers=['Name', 'ODB [kJ/mol]', 'ODFE', 'Total dG\' [kJ/mol]', 'sum(flux)', 'remark'])
    
    data = plot_data[good_entries, :]
    data = data[:, (3, 0)]
    labels = [entries[i] for i in good_entries] 
    return data, labels
            
def analyze(prefix, thermo):    
    kegg_file = ParsedKeggFile.FromKeggFile('../data/thermodynamics/%s.txt' % prefix)
    html_writer = HtmlWriter('../res/%s.html' % prefix)

    co2_hydration = Reaction.FromFormula("C00011 + C00001 => C00288")
    
    #pH_vec = np.arange(5, 9.001, 0.5)
    #pH_vec = np.array([6, 7, 8])
    pH_vec = np.array([6, 7, 8]) # this needs to be fixed so that the txt file will set the pH
    #co2_conc_vec = np.array([1e-5, 1e-3])
    co2_conc_vec = np.array([1e-5])
    data_mat = []
    override_bounds = {}
    
    for pH in pH_vec.flat:
        co2_hydration_dG0_prime = float(thermo.GetTransfromedKeggReactionEnergies([co2_hydration], pH=pH))
        for co2_conc in co2_conc_vec.flat:
            carbonate_conc = co2_conc * np.exp(-co2_hydration_dG0_prime / (R*default_T))
            #print "[CO2] = %g, [carbonate] = %g, pH = %.1f, I = %.2fM" % (co2_conc, carbonate_conc, pH, I)
            override_bounds[11] = (co2_conc, co2_conc)
            override_bounds[288] = (carbonate_conc, carbonate_conc)
            
            section_prefix = 'pH_%g_CO2_%g' % (pH, co2_conc*1000)
            section_title = 'pH = %g, [CO2] = %g mM' % (pH, co2_conc*1000)
            html_writer.write('<h1 id="%s_title">%s</h1>\n' %
                              (section_prefix, section_title))
            html_writer.write_ul(['<a href="#%s_tables">Individual result tables</a>' % section_prefix,
                                  '<a href="#%s_summary">Summary table</a>' % section_prefix,
                                  '<a href="#%s_figure">Summary figure</a>' % section_prefix])

            data, labels = pareto(kegg_file, html_writer, thermo,
                pH=pH, section_prefix=section_prefix, balance_water=True,
                override_bounds=override_bounds)
            data_mat.append(data)
    
    data_mat = np.array(data_mat)
    if data_mat.shape[0] == 1:
        pareto_fig = plt.figure(figsize=(6, 6), dpi=90)
        plt.plot(data_mat[0, :, 0], data_mat[0, :, 1], '.', figure=pareto_fig)
        for i in xrange(data_mat.shape[1]):
            if data[i, 1] < 0:
                color = 'grey'
            else:
                color = 'black'
            plt.text(data_mat[0, i, 0], data_mat[0, i, 1], labels[i],
                     ha='left', va='bottom',
                     fontsize=8, color=color, figure=pareto_fig)
        plt.title(section_title, figure=pareto_fig)
    else:
        pareto_fig = plt.figure(figsize=(10, 10), dpi=90)
        for i in xrange(data_mat.shape[1]):
            plt.plot(data_mat[:, i, 0], data_mat[:, i, 1], '-', figure=pareto_fig)
            plt.text(data_mat[0, i, 0], data_mat[0, i, 1], '%g' % pH_vec[0],
                     ha='center', fontsize=6, color='black', figure=pareto_fig)
            plt.text(data_mat[-1, i, 0], data_mat[-1, i, 1], '%g' % pH_vec[-1],
                     ha='center', fontsize=6, color='black', figure=pareto_fig)
        plt.legend(labels, loc='upper right')
        plt.title('Pareto', figure=pareto_fig)
    
    plt.xlabel('Optimal Energetic Efficiency [kJ/mol]', figure=pareto_fig)
    plt.ylabel('Optimized Distributed Bottleneck [kJ/mol]', figure=pareto_fig)
    html_writer.write('<h2 id="%s_figure">Summary figure</h1>\n' % section_prefix)

    # plot the Pareto figure showing all values (including infeasible)
    html_writer.embed_matplotlib_figure(pareto_fig, name=prefix + '_0')

    # set axes to hide infeasible pathways and focus on feasible ones
    pareto_fig.axes[0].set_xlim(None, 0)
    pareto_fig.axes[0].set_ylim(0, None)
    html_writer.embed_matplotlib_figure(pareto_fig, name=prefix + '_1')
    
    html_writer.close()
    
def AnalyzeConcentrationGradient(prefix, thermo, csv_output_fname, cid=13): # default compound is PPi
    compound_name = thermo.kegg.cid2name(cid)
    kegg_file = ParsedKeggFile.FromKeggFile('../data/thermodynamics/%s.txt' % prefix)
    html_writer = HtmlWriter('../res/%s.html' % prefix)
    null_html_writer = NullHtmlWriter()
    if csv_output_fname:
        csv_output = csv.writer(open(csv_output_fname, 'w'))
        csv_output.writerow(['pH', 'I', 'T', '[C%05d]' % cid] + kegg_file.entries())
    else:
        csv_output = None

    pH_vec = np.array([7]) # this needs to be fixed so that the txt file will set the pH
    conc_vec = 10**(-np.arange(2, 6.0001, 0.25)) # logarithmic scale between 10mM and 1nM
    override_bounds = {}
    
    fig = plt.figure(figsize=(6, 6), dpi=90)
    legend = []
    for pH in pH_vec.flat:
        obd_vec = []
        for conc in conc_vec.flat:
            override_bounds[cid] = (conc, conc)
            logging.info("pH = %g, [%s] = %.1e M" % (pH, compound_name, conc))
            data, labels = pareto(kegg_file, null_html_writer, thermo,
                pH=pH, section_prefix="", balance_water=True,
                override_bounds=override_bounds)
            obd_vec.append(data[:, 1])
            csv_output.writerow([pH, thermo.I, thermo.T, conc] + list(data[:, 1].flat))
        obd_mat = np.matrix(obd_vec) # rows are pathways and columns are concentrations
        plt.plot(conc_vec, obd_mat, '.-', figure=fig)
        legend += ['%s, pH = %g' % (l, pH) for l in labels]
    
    plt.title("ODB vs. [%s] (I = %gM, T = %gK)" % (compound_name, thermo.I, thermo.T), figure=fig)
    plt.xscale('log')
    plt.xlabel('Concentration of %s [M]' % thermo.kegg.cid2name(cid), figure=fig)
    plt.ylabel('Optimized Distributed Bottleneck [kJ/mol]', figure=fig)
    plt.legend(legend)
    html_writer.write('<h2 id="figure_%s">Summary figure</h1>\n' % prefix)
    html_writer.embed_matplotlib_figure(fig, name=prefix)
    
    html_writer.close()

if __name__ == "__main__":
    plt.rcParams['legend.fontsize'] = 6
    estimators = LoadAllEstimators()
    
    experiments = [('obd_vs_otg_CCR', 'UGC'),
                   ('obd_vs_otg_formate', 'UGC'),
                   ('obd_vs_otg_oxidative', 'UGC'),
                   ('obd_vs_otg_reductive', 'UGC'),
                   ('obd_vs_otg_RPP', 'UGC')]

    experiments = [('obd_fermentative_short', 'UGC')]

    for prefix, thermo_name in experiments:
        thermo = estimators[thermo_name]
        analyze(prefix, thermo)

