# Copyright (c) 2017, Lehrstuhl fuer Angewandte Mechanik, Technische Universitaet Muenchen.
#
# Distributed under BSD-3-Clause License. See LICENSE-File for more information.
#
"""
Module handling the whole mechanical system, no matter if it's a finite element system, defined by certain parameters
or a multibody system.
"""


import time
import os
import copy
import h5py
import numpy as np
from scipy.sparse import bmat

from .mesh import Mesh
from .assembly import Assembly
from .boundary import DirichletBoundary
from .solver import *


__all__ = [
    'MechanicalSystem',
    'MechanicalSystemStateSpace',
    'ReducedSystem',
    'ReducedSystemStateSpace',
    'reduce_mechanical_system',
    'convert_mechanical_system_to_state_space',
    'reduce_mechanical_system_state_space'
]


class MechanicalSystem():
    '''
    Master class for mechanical systems with the goal to black-box the routines of assembly and element selection.

    Attributes
    ----------
    mesh_class : instance of Mesh()
        Class handling the mesh.
    assembly_class : instance of Assembly()
        Class handling the assembly.
    dirichlet_class : instance of DirichletBoundary
        Class handling the Dirichlet boundary conditions.
    T_output : list of floats
        List of timesteps saved.
    u_output : list of ndarrays
        List of unconstrained displacement arrays corresponding to the timesteps in T_output.
    S_output : list of ndarrays
        List of stress arrays corresponding to the timesteps in T_output.
    E_output : list of ndarrays
        List of strain arrays corresponding to the timesteps in T_output.
    stress : ndarray
        Array of nodal stress of the last assembly run. Shape is (no_of_nodes, 6).
    strain : ndarray
        Array of nodal strain of the last assembly run. Shape is (no_of_nodes, 6).
    stress_recovery : bool
        Flag for option stress_recovery.
    iteration_info : ndarray
        Array containing the information of an iterative solution procedure. Eteration_info[:,0] is the time
        information, iteration_info[:,1] is the number of iterations, iteration_info[:,3] is the residual.
    M_constr : ?
        Mass matrix
    D_constr : ?
        Damping matrix
    '''

    def __init__(self, stress_recovery=False):
        '''
        Parameters
        ----------
        stress_recovery : bool, optional
            Flag, for setting stress recovery option. Default is False.

        '''
        self.stress_recovery = stress_recovery
        self.T_output = []
        self.u_output = []
        self.S_output = []
        self.E_output = []
        self.stress = None
        self.strain = None
        self.iteration_info = np.array([])

        # instantiate the important classes needed for the system:
        self.mesh_class = Mesh()
        self.assembly_class = Assembly(self.mesh_class)
        self.dirichlet_class = DirichletBoundary(np.nan)

        # make syntax a little bit leaner
        # !Christian Meyer: ! careful: This prohibits to easily change dirichlet_class instance, because old instance
        # still will be referenced!
        self.unconstrain_vec = self.dirichlet_class.unconstrain_vec
        self.constrain_vec = self.dirichlet_class.constrain_vec
        self.constrain_matrix = self.dirichlet_class.constrain_matrix

        # initializations to be overwritten by loading functions
        self.M_constr = None
        self.D_constr = None
        self.no_of_dofs_per_node = None

        # external force to be overwritten by user-defined external forces
        # self._f_ext_unconstr = lambda t: np.zeros(self.mesh_class.no_of_dofs)

    def load_mesh_from_gmsh(self, msh_file, phys_group, material, scale_factor=1):
        '''
        Load the mesh from a msh-file generated by gmsh.

        Parameters
        ----------
        msh_file : str
            File name to an existing .msh file.
        phys_group : int
            Integer key of the physical group which is considered as the mesh part.
        material : amfe.Material
            Material associated with the physical group to be computed.
        scale_factor : float, optional
            Scale factor for the mesh to adjust the units. The default value is 1, i.e. no scaling is done.
        '''

        self.mesh_class.import_msh(msh_file, scale_factor=scale_factor)
        self.mesh_class.load_group_to_mesh(phys_group, material)
        self.no_of_dofs_per_node = self.mesh_class.no_of_dofs_per_node

        self.assembly_class.preallocate_csr()
        self.dirichlet_class.no_of_unconstrained_dofs = self.mesh_class.no_of_dofs
        self.dirichlet_class.update()

    def deflate_mesh(self):
        '''
        Remove free floating nodes not connected to a selected element from the mesh.
        '''

        self.mesh_class.deflate_mesh()
        self.assembly_class.preallocate_csr()
        self.dirichlet_class.no_of_unconstrained_dofs = self.mesh_class.no_of_dofs
        self.dirichlet_class.update()

    def load_mesh_from_csv(self, node_list_csv, element_list_csv, no_of_dofs_per_node=2,
                           explicit_node_numbering=False,
                           ele_type=False):
        '''
        Loads the mesh from two csv-files containing the node and the element list.

        Parameters
        ----------
        node_list_csv: str
            Filename of the csv-file containing the coordinates of the nodes (x, y, z)
        element_list_csv: str
            Filename of the csv-file containing the nodes which belong to one element
        no_of_dofs_per_node: int, optional
            Degree of freedom per node as saved in the csv-file
        explicit_node_numbering : bool, optional
            Flag stating, if the node numbers are explcitly numbered in the csv file, i.e. if the first column gives
            the numbers of the nodes.
        ele_type: str
            Spezifiy elements type of the mesh (e.g. for a Tri-Mesh different elements types as Tri3, Tri4, Tri6 can be
            used). If not spezified value is set to 'False'.
        '''

        self.mesh_class.import_csv(node_list_csv, element_list_csv,
                                   explicit_node_numbering=explicit_node_numbering,
                                   ele_type=ele_type)
        self.no_of_dofs_per_node = no_of_dofs_per_node
        self.assembly_class.preallocate_csr()
        return

    def tie_mesh(self, master_key, slave_key,
                 master_prop='phys_group',
                 slave_prop='phys_group',
                 tying_type='fixed',
                 verbose=False,
                 conform_slave_mesh=False,
                 fix_mesh_dist=1E-3):
        '''
        Tie nonconforming meshes for a given master and slave side.

        Parameters
        ----------
        master_key : int or string
            Mesh key of the master face mesh. The master face mesh has to be at least the size of the slave mesh. It is
            better, when the master mesh is larger than the slave mesh.
        slave_key : int or string
            Mesh key of the slave face mesh or point cloud
        master_prop : string, optional
            Mesh property for which master_key is specified. Default value: 'phys_group'.
        slave_prop : string, optional
            Mesh property for which slave_key is specified. Default value: 'phys_group'
        tying_type : string {'fixed', 'slide'}
            Mesh tying type. 'fixed' glues the meshes together while 'slide' allows for a sliding motion between the
            meshes.

        Notes
        -----
        The master mesh has to embrace the full slave mesh. If this is not the case, the routine will fail, a slave
        point outside the master mesh cannot be addressed to a specific element.
        '''

        vals = self.mesh_class.tie_mesh(master_key=master_key,
                                        slave_key=slave_key,
                                        master_prop=master_prop,
                                        slave_prop=slave_prop,
                                        tying_type=tying_type,
                                        verbose=verbose,
                                        fix_mesh_dist=fix_mesh_dist)

        self.dirichlet_class.add_constraints(*vals)
        self.dirichlet_class.update()
        return

    def apply_dirichlet_boundaries(self, key, coord, mesh_prop='phys_group'):
        '''
        Apply dirichlet-boundaries to the system.

        Parameters
        ----------
        key : int
            Key for mesh property which is to be chosen. Matches the group given in the gmsh file. For help, the
            function mesh_information or boundary_information gives the groups.
        coord : str {'x', 'y', 'z', 'xy', 'xz', 'yz', 'xyz'}
            Coordinates which should be fixed.
        mesh_prop : str {'phys_group', 'geom_entity', 'el_type'}, optional
            Label of which the element should be chosen from. Default is 'phys_group'.
        '''

        self.mesh_class.set_dirichlet_bc(key, coord, mesh_prop)
        self.dirichlet_class.constrain_dofs(self.mesh_class.dofs_dirichlet)
        return

    def apply_neumann_boundaries(self, key, val, direct,
                                 time_func=None,
                                 shadow_area=False,
                                 mesh_prop='phys_group'):
        '''
        Apply neumann boundaries to the system via skin elements.

        Parameters
        ----------
        key : int
            Key of the physical domain to be chosen for the neumann bc.
        val : float
            Value for the pressure/traction onto the element.
        direct : ndarray or str 'normal'
            Direction, in which force should act at.
        time_func : function object
            Function object returning a value between -1 and 1 given the input t:

            >>> val = time_func(t)

        shadow_area : bool, optional
            Flag, if force should be proportional to shadow area of surface with respect to direction. Default: False.
        mesh_prop : str {'phys_group', 'geom_entity', 'el_type'}, optional
            Label of which the element should be chosen from. Default is phys_group.
        '''

        self.mesh_class.set_neumann_bc(key=key,
                                       val=val,
                                       direct=direct,
                                       time_func=time_func,
                                       shadow_area=shadow_area,
                                       mesh_prop=mesh_prop)
        self.assembly_class.compute_element_indices()
        return

    def export_paraview(self, filename, field_list=None):
        '''
        Export the system with the given information to paraview.

        Parameters
        ----------
        filename : str
            Filename to which the xdmf file and the hdf5 file will be saved.
        field_list : list, optional
            List of tuples containing a field to be exported as well as a dictionary with the attribute information of
            the hdf5 file. Example:

                >>> # example field list with reduced displacement not to export
                >>> # ParaView and strain epsilon to be exported to ParaView
                >>> field_list = [(q_red, {'ParaView':False, 'Name':'q_red'}),
                                  (eps, {'ParaView':True,
                                         'Name':'epsilon',
                                         'AttributeType':'Tensor6',
                                         'Center':'Node',
                                         'NoOfComponents':6})]
        '''

        if field_list is None:
            field_list = []
        t1 = time.time()
        if len(self.T_output) is 0:
            self.T_output.append(0)
            self.u_output.append(np.zeros(self.mesh_class.no_of_dofs))
            if self.stress_recovery:
                self.S_output.append(np.zeros((self.mesh_class.no_of_nodes, 6)))
                self.E_output.append(np.zeros((self.mesh_class.no_of_nodes, 6)))
        print('Start exporting mesh for paraview to:\n    ', filename)

        if self.stress_recovery and len(self.S_output) > 0 \
           and len(self.E_output) > 0:
            no_of_timesteps = len(self.T_output)
            S_array = np.array(self.S_output).reshape((no_of_timesteps, -1))
            E_array = np.array(self.E_output).reshape((no_of_timesteps, -1))
            S_export = (S_array.T, {'ParaView':True,
                                  'Name':'stress',
                                  'AttributeType':'Tensor6',
                                  'Center':'Node',
                                  'NoOfComponents':6})
            E_export = (E_array.T, {'ParaView':True,
                                  'Name':'strain',
                                  'AttributeType':'Tensor6',
                                  'Center':'Node',
                                  'NoOfComponents':6})
            field_list.append(S_export)
            field_list.append(E_export)

        bmat = self.dirichlet_class.b_matrix()
        self.mesh_class.save_mesh_xdmf(filename, field_list, bmat, u=self.u_output, timesteps=self.T_output)
        t2 = time.time()
        print('Mesh for paraview successfully exported in ' +
              '{0:4.2f} seconds.'.format(t2 - t1))
        return

    def M(self, u=None, t=0, force_update = False):
        '''
        Compute the Mass matrix of the dynamical system.

        Parameters
        ----------
        u : ndarray, optional
            Array of the displacement.
        t : float
            Time.

        Returns
        -------
        M : sp.sparse.sparse_matrix
            Mass matrix with applied constraints in sparse csr-format.
        '''

        if self.M_constr is None or force_update:
            if u is not None:
                u_unconstr = self.unconstrain_vec(u)
            else:
                u_unconstr = None

            M_unconstr = self.assembly_class.assemble_m(u_unconstr, t)
            self.M_constr = self.constrain_matrix(M_unconstr)
        return self.M_constr

    def K(self, u=None, t=0):
        '''
        Compute the stiffness matrix of the mechanical system.

        Parameters
        ----------
        u : ndarray, optional
            Displacement field in voigt notation.
        t : float, optional
            Time.

        Returns
        -------
        K : sp.sparse.sparse_matrix
            Stiffness matrix with applied constraints in sparse csr-format.
        '''

        if u is None:
            u = np.zeros(self.dirichlet_class.no_of_constrained_dofs)

        K_unconstr = \
            self.assembly_class.assemble_k_and_f(self.unconstrain_vec(u), t)[0]

        return self.constrain_matrix(K_unconstr)

    def D(self, u=None, t=0, force_update=False):
        '''
        Return the damping matrix of the mechanical system.

        Parameters
        ----------
        u : ndarray, optional
            Displacement field in voigt notation.
        t : float, optional
            Time.
        force_update : bool (default=False)
            Flag to force update of D otherwise already calcuated D is returned

        Returns
        -------
        D : sp.sparse.sparse_matrix
            Damping matrix with applied constraints in sparse csr-format.
        '''

        if self.D_constr is None or force_update:
            if self.D_constr is None:
                return self.K()*0
            else:
                return self.D_constr
        else:
            return self.D_constr

    def f_int(self, u, t=0):
        '''
        Return the elastic restoring force of the system.
        '''
        f_unconstr = \
            self.assembly_class.assemble_k_and_f(self.unconstrain_vec(u), t)[1]
        return self.constrain_vec(f_unconstr)

    def _f_ext_unconstr(self, u, t):
        '''
        Return the unconstrained external force coming from the Neumann BCs. This function is just a placeholder if you
        want to change the behavior of f_ext: This function may be monkeypatched if necessary, for instance, when a
        global external force, e.g. gravity, should be applied.
        '''

        f_unconstr = \
            self.assembly_class.assemble_k_and_f_neumann(self.unconstrain_vec(u), t)[1]
        return f_unconstr

    def f_ext(self, u, du, t):
        '''
        Return the nonlinear external force of the right hand side of the equation, i.e. the excitation.
        '''

        if u is None:
            u = np.zeros(self.dirichlet_class.no_of_constrained_dofs)
        return self.constrain_vec(self._f_ext_unconstr(u, t))

    def K_and_f(self, u=None, t=0):
        '''
        Compute tangential stiffness matrix and nonlinear force vector in one assembly run.
        '''

        if u is None:
            u = np.zeros(self.dirichlet_class.no_of_constrained_dofs)
        if self.stress_recovery: # make sure, that current stress / strain is exported
            K_unconstr, f_unconstr, self.stress, self.strain = \
                self.assembly_class.assemble_k_f_S_E(self.unconstrain_vec(u), t)
        else:
            K_unconstr, f_unconstr = \
                self.assembly_class.assemble_k_and_f(self.unconstrain_vec(u), t)
        K = self.constrain_matrix(K_unconstr)
        f = self.constrain_vec(f_unconstr)
        return K, f

    def apply_rayleigh_damping(self, alpha, beta):
        '''
        Apply Rayleigh damping to the system. The damping matrix D is defined as D = alpha*M + beta*K(0). Thus, it is
        Rayleigh Damping applied to the linearized system around zero deformation.

        Parameters
        ----------
        alpha : float
            Damping coefficient for the mass matrix.
        beta : float
            Damping coefficient for the stiffness matrix.
        '''

        self.D_constr = alpha*self.M() + beta*self.K()
        return

    def write_timestep(self, t, u):
        '''
        Write the timestep to the mechanical_system class.
        '''

        self.T_output.append(t)
        self.u_output.append(self.unconstrain_vec(u))
        # Check both, if stress recovery and if stress and strain is there
        if self.stress_recovery:
            # catch the case when no stress was computed, for instance in time
            # integration
            if self.stress is None and self.strain is None:
                self.stress = np.zeros((self.mesh_class.no_of_nodes,6))
                self.strain = np.zeros((self.mesh_class.no_of_nodes,6))
            self.S_output.append(self.stress.copy())
            self.E_output.append(self.strain.copy())

    def clear_timesteps(self):
        '''
        Clear the timesteps gathered internally.
        '''

        self.T_output = []
        self.u_output = []
        self.S_output = []
        self.E_output = []
        self.stress = None
        self.strain = None
        self.iteration_info = np.array([])
        return

    def set_solver(self, solver, **solver_options):
        '''
        Set solver to be able to use shortcut my_system.solve() for solving the system.
        '''

        self.solver = solver(mechanical_system=self, **solver_options)
        return

    def solve(self):
        '''
        Shortcut to solve system.
        '''

        if not hasattr(self, 'solver'):
            raise ValueError('No solver set. Use my_system.set_solver(solver, **solver_options) to set solver first.')

        self.solver.solve()
        return


class MechanicalSystemStateSpace(MechanicalSystem):
    def __init__(self, regular_matrix=None, **kwargs):
        MechanicalSystem.__init__(self, **kwargs)
        if regular_matrix is None:
            self.R_constr = self.K()
        else:
            self.R_constr = regular_matrix
        self.x_red_output = []
        self.E_constr = None

    def M(self, x=None, t=0, force_update=False):
        if self.M_constr is None or force_update:
            if x is not None:
                self.M_constr = MechanicalSystem.M(self, x[0:int(x.size/2)], t)
            else:
                self.M_constr = MechanicalSystem.M(self, None, t)
        return self.M_constr

    def E(self, x=None, t=0, force_update=False):
        if self.E_constr is None or force_update:
            if self.M_constr is None:
                self.M(x, t)
            self.E_constr = bmat([[self.R_constr, None],
                              [None, self.M_constr]])
        return self.E_constr

    def D(self, x=None, t=0, force_update=False):
        if self.D_constr is None or force_update:
            if x is not None:
                self.D_constr = MechanicalSystem.D(self, x[0:int(x.size/2)], t)
            else:
                self.D_constr = MechanicalSystem.D(self, None, t)
        return self.D_constr

    def K(self, x=None, t=0):
        if x is not None:
            K = MechanicalSystem.K(self, x[0:int(x.size/2)], t)
        else:
            K = MechanicalSystem.K(self, None, t)
        return K

    def A(self, x=None, t=0):
        if self.D_constr is None:
            A = bmat([[None, self.R_constr], [-self.K(x, t), None]])
        else:
            A = bmat([[None, self.R_constr], [-self.K(x, t), -self.D_constr]])
        return A

    def f_int(self, x=None, t=0):
        if x is None:
            x = np.zeros(2*self.dirichlet_class.no_of_constrained_dofs)
        f_int = MechanicalSystem.f_int(self, x[0:int(x.size/2)], t)
        return f_int

    def F_int(self, x=None, t=0):
        if x is None:
            x = np.zeros(2*self.dirichlet_class.no_of_constrained_dofs)
        if self.D_constr is None:
            F_int = np.concatenate((self.R_constr@x[int(x.size/2):],
                                    -self.f_int(x, t)), axis=0)
        else:
            F_int = np.concatenate((self.R_constr@x[int(x.size/2):],
                                    -self.D_constr@x[int(x.size/2):]
                                     - self.f_int(x, t)), axis=0)
        return F_int

    def f_ext(self, x, t):
        if x is None:
            f_ext = MechanicalSystem.f_ext(self, None, None, t)
        else:
            f_ext = MechanicalSystem.f_ext(self, x[0:int(x.size/2)],
                                           x[int(x.size/2):], t)
        return f_ext

    def F_ext(self, x, t):
        F_ext = np.concatenate((np.zeros(self.dirichlet_class.no_of_constrained_dofs),
                                self.f_ext(x, t)), axis=0)
        return F_ext

    def K_and_f(self, x=None, t=0):
        if x is not None:
            K, f_int = MechanicalSystem.K_and_f(self, x[0:int(x.size/2)], t)
        else:
            K, f_int = MechanicalSystem.K_and_f(self, None, t)
        return K, f_int

    def A_and_F(self, x=None, t=0):
        if x is None:
            x = np.zeros(2*self.dirichlet_class.no_of_constrained_dofs)
        K, f_int = self.K_and_f(x, t)
        if self.D_constr is None:
            A = bmat([[None, self.R_constr], [-K, None]])
            F_int = np.concatenate((self.R_constr@x[int(x.size/2):], -f_int), axis=0)
        else:
            A = bmat([[None, self.R_constr], [-K, -self.D_constr]])
            F_int = np.concatenate((self.R_constr@x[int(x.size/2):],
                                    -self.D_constr@x[int(x.size/2):] - f_int), axis=0)
        return A, F_int

    def write_timestep(self, t, x):
        MechanicalSystem.write_timestep(self, t, x[0:int(x.size/2)])
        self.x_output.append(x.copy())
        return

    def export_paraview(self, filename, field_list=None):
        x_export = np.array(self.x_output).T
        x_dict = {'ParaView':'False', 'Name':'x'}
        if field_list is None:
            new_field_list = []
        else:
            new_field_list = field_list.copy()
        new_field_list.append((x_export, x_dict))
        MechanicalSystem.export_paraview(self, filename, new_field_list)
        return

    def clear_timesteps(self):
        MechanicalSystem.clear_timesteps(self)
        self.x_output = []
        return


class ReducedSystem(MechanicalSystem):
    '''
    Class for reduced systems. It is directly inherited from MechanicalSystem. Provides the interface for an
    integration scheme and so on where a basis vector is to be chosen...

    Notes
    -----
    The Basis V is a Matrix with x = V*q mapping the reduced set of coordinates q onto the physical coordinates x. The
    coordinates x are constrained, i.e. the x denotes the full system in the sense of the problem set and not of the
    pure finite element set.

    The system runs without providing a V_basis when constructing the method only for the unreduced routines.

    Attributes
    ----------
    V : ?
        Set of basis vectors the system has been reduced with u_constr = V*q.
    V_unconstr : ?
        Extended reduction basis that is extended by the displacement coordinates of the constrained degrees of freedom.
    u_red_output : ?
        Stores the timeseries of the generalized coordinates (similar to u_output).
    assembly_type : {'indirect', 'direct'}
        Stores the type of assembly method how the reduced system is computed.
    
    Examples
    --------
    my_system = amfe.MechanicalSystem()
    V = vibration_modes(my_system, n=20)
    my_reduced_system = amfe.reduce_mechanical_system(my_system, V)
    '''

    def __init__(self, V_basis=None, assembly='indirect', **kwargs):
        '''
        Parameters
        ----------
        V_basis : ndarray, optional
            Basis onto which the problem will be projected with an Galerkin-Projection.
        assembly : str {'direct', 'indirect'}
            flag setting, if direct or indirect assembly is done. For larger reduction bases, the indirect method is
            much faster.
        **kwargs : dict, optional
            Keyword arguments to be passed to the mother class MechanicalSystem.
        '''

        MechanicalSystem.__init__(self, **kwargs)
        self.V = V_basis
        self.u_red_output = []
        self.V_unconstr = self.dirichlet_class.unconstrain_vec(V_basis)
        self.assembly_type = assembly

    def K_and_f(self, u=None, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])
        if self.assembly_type == 'direct':
            # this is really slow! So this is why the assembly is done diretly
            K, f_int = self.assembly_class.assemble_k_and_f_red(self.V_unconstr,
                                                                u, t)
        elif self.assembly_type == 'indirect':
            K_raw, f_raw = self.assembly_class.assemble_k_and_f(self.V_unconstr @ u,
                                                                t)
            K = self.V_unconstr.T @ K_raw @ self.V_unconstr
            f_int = self.V_unconstr.T @ f_raw
        else:
            raise ValueError('The given assembly type for a reduced system '
                             + 'is not valid.')
        return K, f_int

    def K(self, u=None, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])

        if self.assembly_type == 'direct':
            # this is really slow! So this is why the assembly is done diretly
            K, f_int = self.assembly_class.assemble_k_and_f_red(self.V_unconstr,
                                                                u, t)
        elif self.assembly_type == 'indirect':
            K_raw, f_raw = self.assembly_class.assemble_k_and_f(self.V_unconstr @ u,
                                                                t)
            K = self.V_unconstr.T @ K_raw @ self.V_unconstr
        else:
            raise ValueError('The given assembly type for a reduced system '
                             + 'is not valid.')
        return K

    def f_ext(self, u, du, t):
        return self.V.T @ MechanicalSystem.f_ext(self, self.V @ u, du, t)

    def f_int(self, u, t=0):

        if self.assembly_type == 'direct':
            # this is really slow! So this is why the assembly is done diretly
            K, f_int = self.assembly_class.assemble_k_and_f_red(self.V_unconstr,
                                                                u, t)
        elif self.assembly_type == 'indirect':
            K_raw, f_raw = self.assembly_class.assemble_k_and_f(self.V_unconstr @ u,
                                                                t)
            f_int = self.V_unconstr.T @ f_raw
        else:
            raise ValueError('The given assembly type for a reduced system '
                             + 'is not valid.')

        return f_int

    def D(self, u=None, t=0, force_update=False):
        if self.D_constr is None or force_update:
            if self.D_constr is None:
                self.D_constr = self.V.T @ MechanicalSystem.K(self)*0 @ self.V
        return self.D_constr

    def M(self, u=None, t=0, force_update=False):
        # Just a plain projection
        # not so well but works...
        if self.M_constr is None or force_update:
            if u is None:
                u_full = None
            else:
                u_full = self.V @ u
            self.M_constr = self.V.T @ MechanicalSystem.M(self, u_full, t, force_update=True) @ self.V
        return self.M_constr

    def write_timestep(self, t, u):
        MechanicalSystem.write_timestep(self, t, self.V @ u)
        self.u_red_output.append(u.copy())

    def K_unreduced(self, u=None, t=0):
        '''
        Unreduced Stiffness Matrix.

        Parameters
        ----------
        u : ndarray, optional
            Displacement of constrained system. Default is zero vector.
        t : float, optionial
            Time. Default is 0.

        Returns
        -------
        K : sparse csr matrix
            Stiffness matrix.
        '''

        return MechanicalSystem.K(self, u, t)

    def f_int_unreduced(self, u, t=0):
        '''
        Internal nonlinear force of the unreduced system.

        Parameters
        ----------
        u : ndarray
            Displacement of unreduces system.
        t : float, optional
            Time, default value: 0.

        Returns
        -------
        f_nl : ndarray
            nonlinear force of unreduced system.
        '''

        return MechanicalSystem.f_int(self, u, t)

    def M_unreduced(self):
        '''
        Unreduced mass matrix.
        '''

        return MechanicalSystem.M(self)

    def export_paraview(self, filename, field_list=None):
        '''
        Export the produced results to ParaView via XDMF format.
        '''

        u_red_export = np.array(self.u_red_output).T
        u_red_dict = {'ParaView':'False', 'Name':'q_red'}

        if field_list is None:
            new_field_list = []
        else:
            new_field_list = field_list.copy()

        new_field_list.append((u_red_export, u_red_dict))

        MechanicalSystem.export_paraview(self, filename, new_field_list)

        # add V and Theta to the hdf5 file
        filename_no_ext, _ = os.path.splitext(filename)
        with h5py.File(filename_no_ext + '.hdf5', 'r+') as f:
            f.create_dataset('reduction/V', data=self.V)

        return

    def clear_timesteps(self):
        MechanicalSystem.clear_timesteps(self)
        self.u_red_output = []


class ReducedSystemStateSpace(MechanicalSystemStateSpace):
    def __init__(self, right_basis=None, left_basis=None, **kwargs):
        MechanicalSystemStateSpace.__init__(self, **kwargs)
        self.V = right_basis
        self.W = left_basis
        self.x_red_output = []

    def E(self, x=None, t=0, force_update=False):
        if self.E_constr is None or force_update:
            if x is not None:
                self.E_constr = self.W.T@MechanicalSystemStateSpace.E(self, self.V@x, \
                                                                  t)@self.V
            else:
                self.E_constr = self.W.T@MechanicalSystemStateSpace.E(self, None, t)@self.V
        return self.E_constr

    def E_unreduced(self, x_unreduced=None, t=0, force_update=False):
        return MechanicalSystemStateSpace.E(self, x_unreduced, t, force_update)

    def A(self, x=None, t=0):
        if x is not None:
            A = self.W.T@MechanicalSystemStateSpace.A(self, self.V@x, t)@self.V
        else:
            A = self.W.T@MechanicalSystemStateSpace.A(self, None, t)@self.V
        return A

    def A_unreduced(self, x_unreduced=None, t=0):
        return MechanicalSystemStateSpace.A(self, x_unreduced, t)

    def F_int(self, x=None, t=0):
        if x is not None:
            F_int = self.W.T@MechanicalSystemStateSpace.F_int(self, self.V@x, t)
        else:
            F_int = self.W.T@MechanicalSystemStateSpace.F_int(self, None, t)
        return F_int

    def F_int_unreduced(self, x_unreduced=None, t=0):
        return MechanicalSystemStateSpace.F_int(self, x_unreduced, t)

    def F_ext(self, x, t):
        if x is not None:
            F_ext = self.W.T@MechanicalSystemStateSpace.F_ext(self, self.V@x, t)
        else:
            F_ext = self.W.T@MechanicalSystemStateSpace.F_ext(self, None, t)
        return F_ext

    def F_ext_unreduced(self, x_unreduced, t):
        return MechanicalSystemStateSpace.F_ext(self, x_unreduced, t)

    def A_and_F(self, x=None, t=0):
        if x is not None:
            A_, F_int_ = MechanicalSystemStateSpace.A_and_F(self, self.V@x, t)
        else:
            A_, F_int_ = MechanicalSystemStateSpace.A_and_F(self, None, t)
        A = self.W.T@A_@self.V
        F_int = self.W.T@F_int_
        return A, F_int

    def A_and_F_unreduced(self, x_unreduced=None, t=0):
        return MechanicalSystemStateSpace.A_and_F(self, x_unreduced, t)

    def write_timestep(self, t, x):
        MechanicalSystemStateSpace.write_timestep(self, t, self.V@x)
        self.x_red_output.append(x.copy())
        return

    def export_paraview(self, filename, field_list=None):
        x_red_export = np.array(self.x_red_output).T
        x_red_dict = {'ParaView':'False', 'Name':'x_red'}
        if field_list is None:
            new_field_list = []
        else:
            new_field_list = field_list.copy()
        new_field_list.append((x_red_export, x_red_dict))
        MechanicalSystemStateSpace.export_paraview(self, filename, new_field_list)
        return

    def clear_timesteps(self):
        MechanicalSystemStateSpace.clear_timesteps(self)
        self.x_red_output = []
        return


def reduce_mechanical_system(
        mechanical_system, V,
        overwrite=False,
        assembly='indirect'):
    '''
    Reduce the given mechanical system with the linear basis V.

    Parameters
    ----------
    mechanical_system : instance of MechanicalSystem
        Mechanical system which will be transformed to a ReducedSystem.
    V : ndarray
        Reduction Basis for the reduced system
    overwrite : bool, optional
        Switch, if mechanical system should be overwritten (is less memory intensive for large systems) or not.
    assembly : str {'direct', 'indirect'}
        flag setting, if direct or indirect assembly is done. For larger reduction bases, the indirect method is much
        faster.

    Returns
    -------
    reduced_system : instance of ReducedSystem
        Reduced system with same properties of the mechanical system and reduction basis V.
    '''

    if overwrite:
        reduced_sys = mechanical_system
    else:
        reduced_sys = copy.deepcopy(mechanical_system)
    reduced_sys.__class__ = ReducedSystem
    reduced_sys.V = V.copy()
    reduced_sys.V_unconstr = reduced_sys.dirichlet_class.unconstrain_vec(V)
    reduced_sys.u_red_output = []
    reduced_sys.M_constr = None
    reduced_sys.assembly_type = assembly
    reduced_sys.M(force_update=True)
    # reduce Rayleigh damping matrix
    if mechanical_system.D_constr is not None:
        reduced_sys.D_constr = reduced_sys.V.T @ mechanical_system.D_constr @ reduced_sys.V
    return reduced_sys


def convert_mechanical_system_to_state_space(
        mechanical_system,
        regular_matrix=None,
        overwrite=False):
    if overwrite:
        sys = mechanical_system
    else:
        sys = copy.deepcopy(mechanical_system)
    sys.__class__ = MechanicalSystemStateSpace
    sys.x_output = []
    if regular_matrix is None:
        sys.R_constr = sys.K()
    else:
        sys.R_constr = regular_matrix
    sys.E_constr = None
    sys.E(force_update=True)
    return sys


def reduce_mechanical_system_state_space(
        mechanical_system_state_space, right_basis,
        left_basis=None,
        overwrite=False):
    if overwrite:
        red_sys = mechanical_system_state_space
    else:
        red_sys = copy.deepcopy(mechanical_system_state_space)
    red_sys.__class__ = ReducedSystemStateSpace
    red_sys.V = right_basis.copy()
    if left_basis is None:
        red_sys.W = right_basis.copy()
    else:
        red_sys.W = left_basis.sopy()
    red_sys.x_red_output = []
    red_sys.E_constr = None
    return red_sys


# This class is not integrated in AMfe yet.
# It should apply linear combinations of external forces
# f_ext = B(x) * F(t)
# This function is not integrated in the Neumann Boundary conditions.
#
# class ExternalForce:
#     '''
#     Class for mimicking the external forces based on a force basis and time
#     values. The force values are linearly interpolated.
#     '''
#
#     def __init__(self, force_basis, force_series, t_series):
#         '''
#         Parameters
#         ----------
#         force_basis : ndarray, shape(ndim, n_dofs)
#             force basis for the force series
#         force_seris : ndarray, shape(n_timesteps, n_dofs)
#             array containing the force dofs corresponding to the time values
#             given in t_series
#         t_series : ndarray, shape(n_timesteps)
#             array containing the time values
#
#         '''
#         self.force_basis = force_basis
#         self.force_series= force_series
#         self.T = t_series
#         return
#
#     def f_ext(self, u, du, t):
#         '''
#         Mimicked external force for the given force time series
#         '''
#         # Catch the case that t is larger than the data set
#         if t >= self.T[-1]:
#             return self.force_basis @ self.force_series[-1]
#
#         t2_idx = np.where(self.T > t)[0][0]
#
#         # if t is smaller than lowest value of T, pick the first value in the
#         # force series
#         if t2_idx == 0:
#             force_amplitudes = self.force_series[0]
#         else:
#             t1_idx = t2_idx - 1
#             t2 = self.T[t2_idx]
#             t1 = self.T[t1_idx]
#
#             force_amplitudes = ( (t2-t)*self.force_series[t1_idx]
#                                + (t-t1)*self.force_series[t2_idx]) / (t2-t1)
#         return self.force_basis @ force_amplitudes
