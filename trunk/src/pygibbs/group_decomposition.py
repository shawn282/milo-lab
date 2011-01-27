#!/usr/bin/python

import pybel
import sys
import logging

from toolbox import smarts_util
from toolbox import util
from pygibbs import groups_data
from pygibbs import group_vector

class GroupDecompositionError(Exception):
    pass
    

class GroupDecomposition(object):
    """Class representing the group decomposition of a molecule."""
    
    def __init__(self, groups_data, mol, groups, unassigned_nodes):
        self.groups_data = groups_data
        self.mol = mol
        self.groups = groups
        self.unassigned_nodes = unassigned_nodes
    
    def ToTableString(self):
        """Returns the decomposition as a tabular string."""
        spacer = '-' * 50 + '\n'
        l = ['%30s | %2s | %2s | %3s | %s\n' % ("group name", "nH", "z", "nMg", "nodes"),
             spacer]
                
        for group, node_sets in self.groups:
            for n_set in node_sets:
                s = '%30s | %2d | %2d | %2d | %s\n' % (group.name, group.hydrogens,
                                                       group.charge, group.nMg,
                                                       ','.join([str(i) for i in n_set]))
                l.append(s)

        if self.unassigned_nodes:
            l.append('\nUnassigned nodes: \n')
            l.append('%10s | %10s | %10s | %10s\n' % ('index', 'atomicnum',
                                                      'valence', 'charge'))
            l.append(spacer)
            
            for i in self.unassigned_nodes:
                a = self.mol.atoms[i]
                l.append('%10d | %10d | %10d | %10d\n' % (i, a.atomicnum,
                                                          a.heavyvalence, a.formalcharge))
        return ''.join(l)

    def __str__(self):
        """Convert the groups to a string."""        
        group_strs = []
        for group, node_sets in self.NonEmptyGroups():
            group_strs.append('%s [H%d %d %d] x %d' % (group.name, group.hydrogens,
                                                       group.charge, group.nMg,
                                                       len(node_sets)))
        return " | ".join(group_strs)
    
    def AsVector(self):
        """Return the group in vector format.
        
        Note: self.groups contains an entry for *all possible* groups, which is
        why this function returns consistent values for all compounds.
        """
        group_vec = group_vector.GroupVector(self.groups_data)
        for unused_group, node_sets in self.groups:
            group_vec.append(len(node_sets))
        group_vec.append(1) # The origin
        return group_vec
    
    def NonEmptyGroups(self):
        """Generator for non-empty groups."""
        for group, node_sets in self.groups:
            if node_sets:
                yield group, node_sets
    
    def UnassignedAtoms(self):
        """Generator for unassigned atoms."""
        for i in self.unassigned_nodes:
            yield self.mol.atoms[i], i
    
    def SparseRepresentation(self):
        """Returns a dictionary representation of the group.
        
        TODO(flamholz): make this return some custom object.
        """
        return dict((group, node_sets) for group, node_sets in self.NonEmptyGroups())
    
    def NetCharge(self):
        """Returns the net charge."""
        return self.AsVector().NetCharge()
    
    def Hydrogens(self):
        """Returns the number of hydrogens."""
        return self.AsVector().Hydrogens()
    
    def Magnesiums(self):
        """Returns the number of Mg2+ ions."""
        return self.AsVector().Magnesiums()
    
    def CountGroups(self):
        """Returns the total number of groups in the decomposition."""
        return sum([len(gdata[-1]) for gdata in self.groups])

    def PseudoisomerVectors(self):
        """Returns a list of group vectors, one per pseudo-isomer."""    
        if not self.CountGroups():
            logging.info('No groups in this decomposition, not calculating pseudoisomers.')
            return []
        
        # A map from each group name to its indices in the group vector.
        # Note that some groups appear more than once (since they can have
        # multiple protonation levels).
        group_name_to_index = {}

        # 'group_name_to_count' is a map from each group name to its number of appearances in 'mol'
        group_name_to_count = {}
        for i, gdata in enumerate(self.groups):
            group, node_sets = gdata
            group_name_to_index.setdefault(group.name, []).append(i)
            group_name_to_count[group.name] = group_name_to_count.get(group.name, 0) + len(node_sets)
        
        index_vector = [] # maps the new indices to the original ones that are used in groupvec

        # A list of per-group pairs (count, # possible protonation levels).
        total_slots_pairs = [] 

        for group_name, groupvec_indices in group_name_to_index.iteritems():
            index_vector += groupvec_indices
            total_slots_pairs.append((group_name_to_count[group_name],
                                      len(groupvec_indices)))

        # generate all possible assignments of protonations. Each group can appear several times, and we
        # can assign a different protonation level to each of the instances.
        groupvec_list = []
        for assignment in util.multi_distribute(total_slots_pairs):
            v = [0] * len(index_vector)
            for i in xrange(len(v)):
                v[index_vector[i]] = assignment[i]
            v += [1]  # add 1 for the 'origin' group
            groupvec_list.append(group_vector.GroupVector(self.groups_data, v))
        return groupvec_list

    # Various properties
    nonempty_groups = property(NonEmptyGroups)
    unassigned_atoms = property(UnassignedAtoms)
    hydrogens = property(Hydrogens)
    net_charge = property(NetCharge)
    magnesiums = property(Magnesiums)
    group_count = property(CountGroups)


class GroupDecomposer(object):
    """Decomposes compounds into their constituent groups."""
    
    def __init__(self, groups_data):
        """Construct a GroupDecomposer.
        
        Args:
            groups_data: a GroupsData object.
        """
        self.groups_data = groups_data

    @staticmethod
    def FromGroupsFile(filename):
        """Factory that initializes a GroupDecomposer from a CSV file."""
        assert filename
        gd = groups_data.GroupsData.FromGroupsFile(filename)
        return GroupDecomposer(gd)
    
    @staticmethod
    def FromDatabase(db, filename=None):
        """Factory that initializes a GroupDecomposer from the database.
        
        Args:
            db: a Database object.
            filename: an optional filename to load data from when
                it's not in the DB. Will write to DB if reading from file.
        
        Returns:
            An initialized GroupsData object.
        """
        assert db
        gd = groups_data.GroupsData.FromDatabase(db, filename)
        return GroupDecomposer(gd)

    @staticmethod
    def _InternalPChainSmarts(length):
        return ''.join(['CO', 'P(=O)([OH,O-])O' * length, 'C'])
    
    @staticmethod
    def _TerminalPChainSmarts(length):
        return ''.join(['[OH,O-]', 'P(=O)([OH,O-])O' * length, 'C'])

    @staticmethod
    def AttachMgToPhosphateChain(mol, chain_map, assigned_mgs):
        """Attaches Mg2+ ions the appropriate groups in the chain.
        
        Args:
            mol: the molecule.
            chain_map: the groups in the chain.
            assigned_mgs: the set of Mg2+ ions that are already assigned.
        
        Returns:
            The updated list of assigned Mg2+ ions. 
        """
        # For each Mg2+ we see, we attribute it to a phosphate group if
        # possible. We prefer to assign it to a terminal phosphate, but otherwise 
        # we assign it to a 'middle' group when there are 2 of them.
        def AddMg(p_group, pmg_group, mg):
            node_set = chain_map[p_group].pop(0)
            mg_index = mg[0]
            node_set.add(mg_index)
            assigned_mgs.add(mg_index)
            chain_map[pmg_group].append(node_set)
        
        all_pmg_groups = (groups_data.GroupsData.FINAL_PHOSPHATES_TO_MGS +
                          groups_data.GroupsData.MIDDLE_PHOSPHATES_TO_MGS)
        for mg in smarts_util.FindSmarts(mol, '[Mg+2]'):
            if mg[0] in assigned_mgs:
                continue
            
            for p_group, pmg_group in all_pmg_groups:
                if chain_map[p_group]:
                    AddMg(p_group, pmg_group, mg)
                    break

        return assigned_mgs

    @staticmethod
    def UpdateGroupMapFromChain(group_map, chain_map):
        """Updates the group_map by adding the chain."""
        for group, node_sets in chain_map.iteritems():
            group_map.get(group, []).extend(node_sets)
        return group_map

    @staticmethod
    def FindPhosphateChains(mol, max_length=3, ignore_protonations=False):
        """
        Chain end should be 'OC' for chains that do not really end, but link to carbons.
        Chain end should be '[O-1,OH]' for chains that end in an hydroxyl.
    
        Args:
            mol: the molecule to decompose.
            max_length: the maximum length of a phosphate chain to consider.
            ignore_protonations: whether or not to ignore protonation values.
        
        Returns:
            A list of 2-tuples (phosphate group, # occurrences).
        """
        group_map = dict((pg, []) for pg in groups_data.GroupsData.PHOSPHATE_GROUPS)
        v_charge = [a.formalcharge for a in mol.atoms]
        assigned_mgs = set()
        
        def pop_phosphate(pchain, p_size):
            if len(pchain) < p_size:
                raise Exception('trying to pop more atoms than are left in the pchain')
            phosphate = pchain[0:p_size]
            charge = sum(v_charge[i] for i in phosphate)
            del pchain[0:p_size]
            return set(phosphate), charge
            
        def add_group(chain_map, group_name, charge, atoms):
            default = groups_data.GroupsData.DEFAULTS[group_name]
            
            if ignore_protonations:
                chain_map[default].append(atoms)
            else:
                # NOTE(flamholz): We rely on the default number of magnesiums being 0 (which it is).
                hydrogens = default.hydrogens + charge - default.charge
                group = groups_data.Group(default.id, group_name, hydrogens,
                                          charge, default.nMg)
                if group not in chain_map:
                    logging.warning('This protonation (%d) level is not allowed for terminal phosphate groups.' % hydrogens)
                    logging.warning('Using the default protonation level (%d) for this name ("%s").' %
                                    (default.hydrogens, default.name))
                    chain_map[default].append(atoms)
                else:
                    chain_map[group].append(atoms)
        
        # For each allowed length
        for length in xrange(1, max_length + 1):
            # Find internal phosphate chains (ones in the middle of the molecule).
            smarts_str = GroupDecomposer._InternalPChainSmarts(length)
            chain_map = dict((k, []) for (k, _) in group_map.iteritems())
            for pchain in smarts_util.FindSmarts(mol, smarts_str):
                working_pchain = list(pchain)
                working_pchain.pop() # Lose the carbons
                working_pchain.pop(0)
                
                if length % 2:
                    atoms, charge = pop_phosphate(working_pchain, 5)
                    add_group(chain_map, '-OPO3-', charge, atoms)                    
                else:
                    atoms, charge = pop_phosphate(working_pchain, 9)
                    add_group(chain_map, '-OPO3-OPO2-', charge, atoms)
                
                while working_pchain:
                    atoms, charge = pop_phosphate(working_pchain, 8)
                    add_group(chain_map, '-OPO2-OPO2-', charge, atoms)
            
            assigned_mgs = GroupDecomposer.AttachMgToPhosphateChain(mol, chain_map,
                                                                    assigned_mgs)
            GroupDecomposer.UpdateGroupMapFromChain(group_map, chain_map)
            
            # Find terminal phosphate chains.
            smarts_str = GroupDecomposer._TerminalPChainSmarts(length)
            chain_map = dict((k, []) for (k, _) in group_map.iteritems())
            for pchain in smarts_util.FindSmarts(mol, smarts_str):
                working_pchain = list(pchain)
                working_pchain.pop() # Lose the carbon
                
                atoms, charge = pop_phosphate(working_pchain, 5)
                add_group(chain_map, '-OPO3', charge, atoms)
                
                if not length % 2:
                    atoms, charge = pop_phosphate(working_pchain, 4)
                    add_group(chain_map, '-OPO2-', charge, atoms)
                
                while working_pchain:
                    atoms, charge = pop_phosphate(working_pchain, 8)
                    add_group(chain_map, '-OPO2-OPO2-', charge, atoms)
                
            assigned_mgs = GroupDecomposer.AttachMgToPhosphateChain(mol, chain_map,
                                                                    assigned_mgs)
            GroupDecomposer.UpdateGroupMapFromChain(group_map, chain_map)

        return [(pg, group_map[pg]) for pg in groups_data.GroupsData.PHOSPHATE_GROUPS]

    def Decompose(self, mol, ignore_protonations=False, strict=False):
        """
        Decompose a molecule into groups.
        
        The flag 'ignore_protonations' should be used when decomposing a compound with lacing protonation
        representation (for example, the KEGG database doesn't posses this information). If this flag is
        set to True, it overrides the '(C)harge sensitive' flag in the groups file (i.e. - *PC)
        
        Args:
            mol: the molecule to decompose.
            ignore_protonations: whether to ignore protonation levels.
            strict: whether to assert that there are no unassigned atoms.
        
        Returns:
            A GroupDecomposition object containing the decomposition.
        """
        unassigned_nodes = set(range(len(mol.atoms)))
        groups = []
        
        def _AddCorrection(group, count):
            l = [set() for _ in xrange(count)]
            groups.append((group, l))
        
        for group in self.groups_data.groups:
            # Phosphate chains require a special treatment
            if group.IsPhosphate():
                pchain_groups = None
                if group.IgnoreCharges() or ignore_protonations:
                    pchain_groups = self.FindPhosphateChains(mol, ignore_protonations=True)
                elif group.ChargeSensitive():
                    pchain_groups = self.FindPhosphateChains(mol, ignore_protonations=False)
                else:
                    raise groups_data.MalformedGroupDefinitionError(
                        'Unrecognized phosphate wildcard: %s' % group.name)
                
                for phosphate_group, group_nodesets in pchain_groups:
                    current_groups = []
                    
                    for focal_set in group_nodesets:
                        if focal_set.issubset(unassigned_nodes):
                            # Check that the focal-set doesn't override an assigned node
                            current_groups.append(focal_set)
                            unassigned_nodes = unassigned_nodes - focal_set
                    groups.append((phosphate_group, current_groups))
            elif group.IsCodedCorrection():
                _AddCorrection(group, group.GetCorrection(mol))
            # Not a phosphate group or expanded correction.
            else:  
                current_groups = []
                for nodes in smarts_util.FindSmarts(mol, group.smarts):
                    try:
                        focal_set = group.FocalSet(nodes)
                    except IndexError:
                        logging.error('Focal set for group %s is out of range: %s'
                                      % (str(group), str(group.focal_atoms)))
                        sys.exit(-1)

                    # check that the focal-set doesn't override an assigned node
                    if focal_set.issubset(unassigned_nodes): 
                        current_groups.append(focal_set)
                        unassigned_nodes = unassigned_nodes - focal_set
                groups.append((group, current_groups))
        
        # Ignore the hydrogen atoms when checking which atom is unassigned
        for nodes in smarts_util.FindSmarts(mol, '[H]'): 
            unassigned_nodes = unassigned_nodes - set(nodes)
        
        decomposition = GroupDecomposition(self.groups_data, mol,
                                           groups, unassigned_nodes)
        
        if strict and decomposition.unassigned_nodes:
            raise GroupDecompositionError('Unable to decompose %s into groups.\n%s' %
                                          (mol.title, decomposition.ToTableString()))
        
        return decomposition


def main():
    from pseudoisomers_data import PseudoisomersData
    decomposer = GroupDecomposer.FromGroupsFile('../data/thermodynamics/groups_species.csv')
    pdata = PseudoisomersData.FromFile("../data/thermodynamics/dG0.csv")
    
    for ps_isomer in pdata:
        if ps_isomer.Skip():
            continue

        if not ps_isomer.Complete():
            continue
        
        try:
            mol = ps_isomer.Mol()
            mol.removeh()
            mol.title = str(ps_isomer)
            decomposition = decomposer.Decompose(mol, strict=True)
        except GroupDecompositionError as e:
            logging.error('Cannot decompose %s', mol.title)
            continue
        except (TypeError, AttributeError), e:
            logging.error(e)
            continue
    
    return
    
    atp = 'C1=NC2=C(C(=N1)N)N=CN2C3C(C(C(O3)COP(=O)(O)OP(=O)(O)OP(=O)(O)O)O)O'
    coa = 'C1C=CN(C=C1C(=O)N)C2C(C(C(O2)COP(=O)(O)OP(=O)(O)OCC3C(C(C(O3)N4C=NC5=C4N=CN=C5N)O)O)O)O'
    glucose = 'C(C1C(C(C(C(O1)O)O)O)O)O'
    mgatp = 'C([C@@H]1[C@H]([C@H]([C@H](n2cnc3c(N)[nH+]cnc23)O1)O)O)OP(=O)([O-])OP(=O)([O-])OP(=O)([O-])[O-].[Mg+2].[Mg+2]'
    ctp = 'C1=CN(C(=O)N=C1N)C2C(C(C(O2)COP(=O)(O)OP(=O)(O)OP(=O)(O)O)O)O'

    smiless = [
               ('ATP', atp),
               ('CoA', coa), ('Glucose', glucose), ('MgAtp', mgatp),
               #('CTP', ctp)
               ]
    mols = [(name, pybel.readstring('smiles', s)) for name, s in smiless]

    for name, mol in mols:
        print name    
        decomposition = decomposer.Decompose(mol)
        print decomposition.ToTableString()
        print 'Group count', decomposition.group_count
        print 'Net charge', decomposition.net_charge
        print 'Hydrogens', decomposition.hydrogens
        print 'Magnesiums', decomposition.magnesiums
        
        print 'Group Vector:'
        print decomposition.AsVector()
        
        print 'Pseudoisomer Vectors:'
        for v in decomposition.PseudoisomerVectors():
            print v


if __name__ == '__main__':
    main()   