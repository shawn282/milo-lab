#!/usr/bin/python

import json
import logging
import re
import numpy as np

from pygibbs import kegg_errors, kegg_parser
from toolbox.molecule import Molecule, OpenBabelError
from pygibbs.kegg_errors import KeggParseException

class Compound(object):
    """A class representing a compound in KEGG."""
    
    free_cid = -1 # class static variable
    
    def __init__(self,
                 cid=None,
                 name=None,
                 all_names=None,
                 mass=None,
                 formula=None,
                 inchi=None,
                 from_kegg=True):
        """Initialize the Compound.
        
        Args:
            cid: the KEGG ID as an integer.
        
        Attributes:
            cid: the KEGG ID
            name: the primary name or "?"
            all_names: the list of common names all_names or []
            mass
            formula
            inchi
            from_kegg: whether the compound is from KEGG
            pubchem_id
            cas
            pmap: a PseudoisomerMap object - formation energies
            pmap_source: the source for the pmap (or "")
        """
        if cid == None:
            self.cid = Compound.free_cid
            Compound.free_cid -= 1
        else:
            self.cid = cid
        
        self.all_names = all_names or []
        self.name = name or "?"
        if self.all_names and name is None:
            self.name = self.all_names[0]
        
        self.mass = mass
        self.formula = formula
        self.inchi = inchi
        self.mol = None
        self.from_kegg = from_kegg
        self.pubchem_id = None
        self.cas = ""
        self.pmaps = []
        self.pmap_error = None
        self.groupvector_string = None
        
    def AddThermodynamicData(self, pseudoisomer_map, priority=1, source_string=None):
        """Add thermodynamic data.
        
        Args:
            pseudoisomer_map: a pseudoisomer.PseudoisomerMap object.
            source_string: a string denoting the source of the thermodynamic data.
        """
        d = {'species':[], 'priority':priority, 'source':source_string}
        for nH, z, nMg, dG0 in pseudoisomer_map.ToMatrix():
            ref = pseudoisomer_map.GetRef(nH, z, nMg)
            d['species'].append({"nH":nH, "z":z, "nMg":nMg, 
                                 "dG0_f":np.round(dG0, 2), "ref":ref})
        self.pmaps.append(d)
    
    def SetThermodynamicError(self, error_string):
        """Sets an explanatory error for why there's no thermodynamic data.
        
        Args:
            error_string: the explanatory error.
        """
        self.pmap_error = error_string

    def GetMolecule(self):
        """Gets a Molecule for this compound if possible.
        
        Returns None if no molecular data is available.
        """
        if self.mol:
            return self.mol
        
        if self.inchi:
            self.mol = Molecule.FromInChI(self.inchi)
            self.mol.SetTitle(self.name)
            return self.mol
        
        raise kegg_errors.KeggParseException(
             "C%05d (%s) doesn't have an explicit molecular structure" % 
             (self.cid, self.name))

    @staticmethod
    def FromEntryDict(key, field_map):
        if not key.startswith('C'):
            return None
        
        cid = int(key[1:])
        comp = Compound(cid)
        if "NAME" in field_map:
            all_names = kegg_parser.NormalizeNames(field_map.GetStringField("NAME"))
            comp.name = all_names[0]
            comp.all_names = all_names
        if "EXACT_MASS" in field_map:
            comp.mass = field_map.GetFloatField('EXACT_MASS')
        if "FORMULA" in field_map:    
            comp.formula = field_map.GetStringField('FORMULA')
        if "DBLINKS" in field_map:
            for sid in re.findall("PubChem: (\d+)", field_map.GetStringField("DBLINKS")):
                comp.pubchem_id = int(sid)
            for cas in re.findall("CAS:\s+([\d\-]+)", field_map.GetStringField("DBLINKS")):
                comp.cas = cas
        return comp

    @staticmethod
    def FromDBRow(row_dict):
        """Build a Compound from a database row."""
        comp = Compound(cid=row_dict['cid'])
        comp.name = row_dict['name']
        comp.all_names = list(set(json.loads(row_dict['all_names'])))
        comp.mass = row_dict['mass']
        if not comp.mass: # fixing a bug where mass was sometimes ""
            comp.mass = None
        comp.formula = row_dict['formula']
        
        inchi = row_dict['inchi']
        if inchi is not None:
            comp.inchi = str(inchi)
        
        cas = row_dict['cas']
        if cas is not None:
            comp.cas = str(cas)
        
        return comp
    
    def ToDBRow(self):
        """Format the compound as a database row.
        
        Returns:
            A list of field values in the appropriate order:
            [CID, name, all_names, mass, formula, inchi, num_electrons,
            is from KEGG, pubchem ID, CAS number]
        """
        inchi = None
        try:
            inchi = self.get_inchi()
        except Exception, e:
            logging.debug(e)
        
        num_electrons = None
        try:
            num_electrons = self.get_num_electrons()
        except Exception, e:
            logging.debug(e)
        
        row = [self.cid,
               self.name,
               json.dumps(self.all_names),
               self.mass,
               self.formula,
               inchi,
               num_electrons,
               self.from_kegg,
               self.pubchem_id,
               self.cas]
        return row
    
    def SetInChI(self, inchi):
        if inchi == None:
            self.inchi = None
            self.mol = None
            self.formula = None
            self.mass = None
        else:
            self.inchi = inchi
            self.mol = Molecule.FromInChI(inchi)
            self.formula = self.mol.GetFormula()
            self.mass = self.mol.GetExactMass() 
    
    def get_atom_bag(self):
        """Returns a dict containing the count for
           each atom in the compound.
        """
        if (self.formula == None or
            self.formula.find("(") != -1 or
            self.formula.find(")") != -1):
            return None
        
        atom_bag = {}
        for atom, count in re.findall("([A-Z][a-z]*)([0-9]*)", self.formula):
            if count == '':
                count = 1
            else:
                count = int(count)
            atom_bag[atom] = count

        if "R" in atom_bag or "X" in atom_bag:
            # This formula is not full ('R' is a wildcard for a side-chain, 'X'
            # is a single halogen atom)
            return None
        return atom_bag
    
    def get_atom_vector(self):
        """
            Returns a NumPy row array describing the number of atoms
            from each element (the column index is the atomic number
            of that element).
            The first column (index=0) contains the number of electrons.
        """
        atom_bag = self.get_atom_bag()
        if not atom_bag:
            return None
        
        atom_vector = np.zeros((Molecule.GetNumberOfElements()+1), dtype='int')
        for elem, count in atom_bag.iteritems():
            if elem in ['R', 'X']:
                return None # wildcard compound!
            an = Molecule.GetAtomicNum(elem)
            if not an:
                logging.warning("Unsupported element in (C%05d): %s",
                                (self.cid, elem))
                return None
            atom_vector[an] = count
            
        atom_vector[0] = self.get_num_electrons()
        return atom_vector
    
    def get_inchi(self):
        """Get the inchi code for this compound."""
        return self.inchi or self.GetMolecule().ToInChI()
    
    def get_smiles(self):
        """Get a SMILES expression for this compound."""
        return self.GetMolecule().ToSmiles()

    def get_nH_and_charge(self):
        if not self.mol and self.inchi:
            self.mol = Molecule.FromInChI(self.inchi)

        if self.mol:
            return self.mol.GetHydrogensAndCharge()

        # if there is no InChI assume that self.formula is correct and that
        # it represents the number of H for the neutral species
        atom_bag = self.get_atom_bag()
        if not atom_bag:
            return None
        return atom_bag.get('H', 0), 0
        
    def get_num_electrons(self):
        """Return the putative number of electrons in the molecule."""
        mol = self.GetMolecule()
        if mol:
            return mol.GetNumElectrons()
        
        # if there is no InChI assume that self.formula is correct and that
        # the charge is 0.
        atom_bag = self.get_atom_bag()
        if not atom_bag:
            return None
        n_protons = 0
        for elem, count in atom_bag.iteritems():
            n_protons += count * Molecule.GetAtomicNum(elem)
        return n_protons

    @staticmethod
    def cid2link(cid):
        return "http://www.genome.jp/dbget-bin/www_bget?cpd:C%05d" % cid

    def get_link(self):
        """Returns a link to KEGG for this compound."""
        return Compound.cid2link(self.cid)
        
    kegg_link = property(get_link)

    def get_string_cid(self):
        """Returns a string of the CID."""
        if self.cid is None:
            return None
        
        return "C%05d" % self.cid

    def ToJSONDict(self, light=False):
        """Converts to a JSON-formatted dictionary."""
        d = {'CID': self.get_string_cid(),
             'mass': self.mass,
             'formula': self.formula}
        
        # the official name of this compound
        d['name'] = self.name
        
        # rid of duplicate names and convert to ASCII
        if not light:
            d['names'] = sorted(set([str(x) for x in self.all_names]))

        try:
            d['InChI'] = self.get_inchi()
        except KeggParseException:
            d['InChI'] = None
        
        try:
            d['num_electrons'] = self.get_num_electrons()
        except KeggParseException:
            d['num_electrons'] = None
        except OpenBabelError as e:
            logging.warning("Error calculating #electrons (%s): %s"
                            % (self.get_string_cid(), str(e)))
            d['num_electrons'] = None
        
        if self.pmaps:
            d['pmaps'] = self.pmaps
        elif self.pmap_error:
            d['error'] = self.pmap_error

        if self.groupvector_string and not light:
            d['group_vector'] = self.groupvector_string
            
        d['from_kegg'] = str(self.from_kegg)
            
        return d
    
    def __str__(self):
        return '%s: %s' % (self.cid, self.name)

    def PredictFormationEnergy(self, thermodynamics):
        return thermodynamics.GetTransformedFormationEnergies(self.cid)

def GetAllCompoundsFromDB(db):
    """Fetch all the compounds from the database."""
    compound_list = []
    for row_dict in db.DictReader('kegg_compound'):
        compound_list.append(Compound.FromDBRow(row_dict))
    return compound_list
