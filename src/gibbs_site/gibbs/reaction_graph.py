import logging
import pylab
import PIL, PIL.Image, StringIO

from django.http import Http404
from django.http import HttpResponse
from gibbs import reaction
from gibbs import reaction_graph_form


def ReactionGraph(request):    
    """Renders a page for a particular reaction."""
    form = reaction_graph_form.ReactionGraphForm(request.GET)
    if not form.is_valid():
        logging.error(form.errors)
        raise Http404

    rxn = reaction.Reaction.FromForm(form)
    
    xvals = None
    dgs = None
    if form.cleaned_vary_pmg:
        xvals = pylab.arange(0.001, 14.0, 0.1)
        dgs = [rxn.DeltaGTag(pMg=x) for x in xvals]
        pylab.xlabel('pMg')
    if form.cleaned_vary_is:
        xvals = pylab.arange(0.001, 0.35, 0.01)
        dgs = [rxn.DeltaGTag(ionic_strength=x) for x in xvals]
        pylab.xlabel('ionic strength')
    else:
        xvals = pylab.arange(0.001, 14.0, 0.1)
        dgs = [rxn.DeltaGTag(pH=x) for x in xvals]
        pylab.xlabel('pH')
        
    pylab.ylabel('dG\'')
    pylab.plot(xvals, dgs, '.')

    response = HttpResponse(mimetype="image/png")
    pylab.savefig(response, format="png")
    return response