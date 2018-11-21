#
# Copyright (c) 2018 TECHNICAL UNIVERSITY OF MUNICH, DEPARTMENT OF MECHANICAL ENGINEERING, CHAIR OF APPLIED MECHANICS,
# BOLTZMANNSTRASSE 15, 85748 GARCHING/MUNICH, GERMANY, RIXEN@TUM.DE.
#
# Distributed under 3-Clause BSD license. See LICENSE file for more information.
#

from collections.abc import Iterable


class ComponentComposite:
    """
    Class which handles child-components and child-ComponentComposites and acts as an interface to foreign clients
    """
    
    TYPE = 'ComponentComposite'
    
    def __init__(self, leafpaths, arg_components=None):
        
        self.components = []
        
        # Stores the addresses of leaves in the composite-tree-structure
        self.leaf_paths = leafpaths

        if arg_components:
            if not isinstance(arg_components, Iterable):
                arg_components = [arg_components]
            for component in arg_components:
                self.add_component(component)

    @property
    def no_of_components(self):
        return len(self.components)

    def add_component(self, new_component):
        """
        Adds component to composite as child

        Parameters
        ----------
        new_component : ComponentBase
            iterable containing component objects that shall be added as children to composite

        Returns
        -------
        iloc : int
            local index where the component is added in components property
        """
        self.components.append(new_component)
        return self.no_of_components-1
        
    def delete_component(self, target_component_id):
        """
        Deletes a local child component by indexlocation

        Parameters
        ----------
        target_component_id : int
            local index location of child component to delete

        Returns
        -------
        None

        TODO: Check connections (e.g. constraints to other components and delete them first
        """
        del(self.components[target_component_id])
        
    def update_tree(self, leaf_paths):
        """
        Updates leaf path reference in case of merging trees

        (This step is necessary if child components contain composites that have an old leaf path reference)

        Parameters
        ----------
        leaf_paths : LeafPaths
            LeafPaths object the composite shall be updated with

        Returns
        -------
        None
        """
        self.leaf_paths = leaf_paths

        for component in self.components:
            if isinstance(component, ComponentComposite):
                component.update_tree(leaf_paths)

    def get_mat(self, matrix_type="K", u=None, t=0):
        """
        Returns a requested matrix
        
        Parameters
        ----------
        matrix_type : str
            Matrix type that is returned (e.g. M, K, ...)
        u : ndarray
            primal variable (e.g. displacements)
        t : float
            time

        Returns
        -------
        matrix : ndarray or csc_matrix
            the requested matrix
        """
        for comp in self.components:
            #################################
            ## ASSEMBLE LOCAL MATRICES!!!
            #################################
            mat = comp.get_mat(matrix_type, u, t)

        return mat
        
    #PRIVATE METHODS
    
    def _test_input(self, input_to_test, valid_input):
        try:
            return valid_input.index(input_to_test)
        except AttributeError as error:
            print('{} not a valid input. Please try one of the following instead: '.format(input_to_test))
            print(valid_input)

