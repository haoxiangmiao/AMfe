# -*- coding: utf-8 -*-

"""
Module handling the whole mechanical system, no matter if it's a finite element 
system, defined by certain parameters or a multibody system. 
"""

import time

import numpy as np
import scipy as sp

from amfe.mesh import Mesh
from amfe.assembly import Assembly
from amfe.boundary import DirichletBoundary, NeumannBoundary



class MechanicalSystem():
    '''
    Mase class for mechanical systems with the goal to black-box the routines
    of assembly and element selection.
    
    Attributes
    ----------
    mesh_class : instance of Mesh()
        Class handling the mesh. 
    assembly_class : instance of Assembly()
        Class handling the assembly. 
    dirichlet_class : instance of DirichletBoundary
        Class handling the Dirichlet boundary conditions. 
    neumann_class : instance of NeumannBoundary
        This boundary type is deprecated. 
    
    '''

    def __init__(self):
        '''
        '''      
        self.T_output = []
        self.u_output = []
        
        # instanciate the important classes needed for the system:
        self.mesh_class = Mesh()
        self.assembly_class = Assembly(self.mesh_class)
        self.dirichlet_class = DirichletBoundary(np.nan)
        self.neumann_class = NeumannBoundary(self.mesh_class.no_of_dofs, [])

        # make syntax a little bit leaner
        self.unconstrain_vec = self.dirichlet_class.unconstrain_vec
        self.constrain_vec = self.dirichlet_class.constrain_vec
        self.constrain_matrix = self.dirichlet_class.constrain_matrix
        
        # initializations to be overwritten by loading functions
        self.M_constr = None
        self.no_of_dofs_per_node = None

        # external force to be overwritten by user-defined external forces
        self._f_ext_unconstr = lambda t: np.zeros(self.mesh_class.no_of_dofs)


    def load_mesh_from_gmsh(self, msh_file, phys_group, material):
        '''
        Load the mesh from a msh-file generated by gmsh.

        Parameters
        ----------
        msh_file : str
            file name to an existing .msh file
        phys_group : int
            integer key of the physical group which is considered as the 
            mesh part 
        material : amfe.Material
            Material associated with the physical group to be computed
        
        Returns
        -------
        None
        '''
        self.mesh_class.import_msh(msh_file)
        self.mesh_class.load_group_to_mesh(phys_group, material)
        self.no_of_dofs_per_node = self.mesh_class.no_of_dofs_per_node
        
        self.assembly_class.preallocate_csr()
        self.dirichlet_class.no_of_unconstrained_dofs = self.mesh_class.no_of_dofs


    def load_mesh_from_csv(self, node_list_csv, element_list_csv, 
                           no_of_dofs_per_node=2, 
                           explicit_node_numbering=False, 
                           ele_type=False):
        '''
        Loads the mesh from two csv-files containing the node and the element list.

        Parameters
        ----------
        node_list_csv: str
            filename of the csv-file containing the coordinates of the nodes (x, y, z)
        element_list_csv: str
            filename of the csv-file containing the nodes which belong to one element
        no_of_dofs_per_node: int, optional
            degree of freedom per node as saved in the csv-file
        explicit_node_numbering : bool, optional
            flag stating, if the node numbers are explcitly numbered in the 
            csv file, i.e. if the first column gives the numbers of the nodes.
        ele_type: str
            Spezifiy elements type of the mesh (e.g. for a Tri-Mesh different
            elements types as Tri3, Tri4, Tri6 can be used)
            If not spezified value is set to 'False'

        Returns
        -------
        None

        Examples
        --------
        todo

        '''
        self.mesh_class.import_csv(node_list_csv, element_list_csv, 
                                   explicit_node_numbering=explicit_node_numbering,
                                   ele_type=ele_type)
        self.no_of_dofs_per_node = no_of_dofs_per_node
        self.assembly_class.preallocate_csr()


    def apply_dirichlet_boundaries(self, key, coord, mesh_prop='phys_group'):
        '''
        Apply dirichlet-boundaries to the system.
        
        Parameters
        ----------
        key : int
            Key for mesh property which is to be chosen. Matches the group given 
            in the gmsh file. For help, the function mesh_information or 
            boundary_information gives the groups
        coord : str {'x', 'y', 'z', 'xy', 'xz', 'yz', 'xyz'}
            coordinates which should be fixed
        mesh_prop : str {'phys_group', 'geom_entity', 'el_type'}, optional
            label of which the element should be chosen from. Default is 
            'phys_group'. 
            
        Returns
        -------
        None
        '''
        self.mesh_class.select_dirichlet_bc(key, coord, mesh_prop)
        self.dirichlet_class.constrain_dofs(self.mesh_class.dofs_dirichlet)

    def apply_neumann_boundaries(self, key, val, direct, time_func=None, 
                                 mesh_prop='phys_group'):
        '''
        Apply neumann boundaries to the system via skin elements. 
        
        Parameters
        ----------
        key : int
            Key of the physical domain to be chosen for the neumann bc
        val : float
            value for the pressure/traction onto the element
        direct : str {'normal', 'x_n', 'y_n', 'z_n', 'x', 'y', 'z'}
            direction, in which the traction should point at: 
            
            'normal'
                Pressure acting onto the normal face of the deformed configuration
            'x_n'
                Traction acting in x-direction proportional to the area 
            projected onto the y-z surface
            'y_n'
                Traction acting in y-direction proportional to the area 
                projected onto the x-z surface            
            'z_n'
                Traction acting in z-direction proportional to the area 
                projected onto the x-y surface
            'x'
                Traction acting in x-direction proportional to the area
            'y'
                Traction acting in y-direction proportional to the area
            'z'
                Traction acting in z-direction proportional to the area
            
        time_func : function object
            Function object returning a value between -1 and 1 given the 
            input t: 

            >>> val = time_func(t)
            
        mesh_prop : str {'phys_group', 'geom_entity', 'el_type'}, optional
            label of which the element should be chosen from. Default is 
            phys_group. 
            
        Returns
        -------
        None
        '''
        self.mesh_class.select_neumann_bc(key=key, val=val, direct=direct, 
                                          time_func=time_func, mesh_prop=mesh_prop)
        self.assembly_class.compute_element_indices()
        
    def apply_neumann_boundaries_old(self, neumann_boundary_list):
        '''Apply neumann-boundaries to the system.

        Parameters
        ----------
        neumann_boundary_list : list
            list containing the neumann boundary NB lists:

            >>> NB = [dofs_list, type, properties, B_matrix=None]

        Notes
        -----
        the neumann_boundary_list is a list containing the neumann_boundaries:

        >>> [dofs_list, load_type, properties, B_matrix=None]

        dofs_list : list
            list containig the dofs which are loaded
        load_type : str out of {'stepload', 'dirac', 'harmonic', 'ramp', 'static'}
            string specifying the load type
        properties : tupel
            tupel with the properties for the given load_type (see table below)
        B_matrix : ndarray / None
            Vector giving the load weights for the given dofs in dofs_list. 
            If None is chosen, the weight will be 1 for every dof by default.

        the load_type-Keywords and the corresponding properties are:


        ===========  =====================
        load_type    properties
        ===========  =====================
        'stepload'   (amplitude, time)
        'dirac'      (amplitude, time)
        'harmonic'   (amplitude, frequency)
        'ramp'       (slope, time)
        'static'      (amplitude)
        ===========  =====================

        Examples
        --------

        Stepload on dof 1, 2 and 3 starting at 0.1 s with amplitude 1KN:

        >>> mysystem = MechanicalSystem()
        >>> NB = [[1, 2, 3], 'stepload', (1E3, 0.1), None]
        >>> mysystem.apply_neumann_boundaries([NB, ])

        Harmonic loading on dof 4, 6 and 8 with frequency 8 Hz = 2*2*pi rad and 
        amplitude 100N:

        >>> mysystem = MechanicalSystem()
        >>> NB = [[1, 2, 3], 'harmonic', (100, 8), None]
        >>> mysystem.apply_neumann_boundaries([NB, ])


        '''
        self.neumann_class = \
            NeumannBoundary(self.mesh_class.no_of_dofs, neumann_boundary_list)
        self._f_ext_unconstr = self.neumann_class.f_ext()


    def export_paraview(self, filename):
        '''
        Export the system with the given information to paraview
        '''
        t1 = time.time()
        if len(self.T_output) is 0:
            self.T_output.append(0)
            self.u_output.append(np.zeros(self.mesh_class.no_of_dofs))
        print('Start exporting mesh for paraview to', filename)
        self.mesh_class.set_displacement_with_time(self.u_output, self.T_output)
        self.mesh_class.save_mesh_xdmf(filename)
        t2 = time.time()
        print('Mesh for paraview successfully exported in ', t2 - t1, 'seconds.')

    def M(self):
        '''
        Compute the Mass matrix of the dynamical system. 
        
        Parameters
        ----------
        None
        
        Returns
        -------
        M : sp.sparse.sparse_matrix
            Mass matrix with applied constraints in sparse csr-format
        '''
        M_unconstr = self.assembly_class.assemble_m()
        self.M_constr = self.constrain_matrix(M_unconstr)
        return self.M_constr
        
    def K(self, u=None, t=0):
        '''
        Compute the stiffness matrix of the mechanical system
        
        Parameters
        ----------
        u : ndarray, optional
            Displacement field in voigt notation
        t : float, optional
            Time
        
        Returns
        -------
        K : sp.sparse.sparse_matrix
            Stiffness matrix with applied constraints in sparse csr-format
        '''
        if u is None:
            u = np.zeros(self.dirichlet_class.no_of_constrained_dofs)

        K_unconstr, f_unconstr = \
            self.assembly_class.assemble_k_and_f(self.unconstrain_vec(u), t) 

        return self.constrain_matrix(K_unconstr)
        
    def f_int(self, u, t=0):
        '''Return the elastic restoring force of the system '''
        K_unconstr, f_unconstr = \
            self.assembly_class.assemble_k_and_f(self.unconstrain_vec(u), t) 
        return self.constrain_vec(f_unconstr)
        
    def f_ext(self, u, du, t):
        '''
        Return the nonlinear external force of the right hand side 
        of the equation, i.e. the excitation.
        '''
        return self.constrain_vec(self._f_ext_unconstr(t))

    def K_and_f(self, u=None, t=0):
        '''
        Compute tangential stiffness matrix and nonlinear force vector 
        in one assembly run.
        '''
        if u is None:
            u = np.zeros(self.dirichlet_class.no_of_constrained_dofs)
        K_unconstr, f_unconstr = \
            self.assembly_class.assemble_k_and_f(self.unconstrain_vec(u), t)
        K = self.constrain_matrix(K_unconstr)
        f = self.constrain_vec(f_unconstr)
        return K, f

    def S_and_res(self, u, du, ddu, dt, t, beta, gamma):
        r'''
        Compute jacobian and residual for implicit time integration. 
        
        Parameters
        ----------
        u : ndarray
            displacement; dimension (ndof,)
        du : ndarray
            velocity; dimension (ndof,)
        ddu : ndarray
            acceleration; dimension (ndof,)
        dt : float
            time step width
        t : float
            time of current time step (for time dependent loads)
        beta : float
            weighting factor for position in generalized-:math:`\alpha` scheme
        gamma : float
            weighting factor for velocity in generalized-:math:`\alpha` scheme
            
        Returns
        -------
        S : ndarray
            jacobian matrix of residual; dimension (ndof, ndof)
        res : ndarray
            residual; dimension (ndof,)
        
        Note
        ----
        Time integration scheme: The iteration matrix is composed using the
        generalized-:math:`\alpha` scheme: 
        
        .. math:: \mathbf S = \frac{1}{h^2\beta}\mathbf{M} 
                  + \frac{\gamma}{h\beta} \mathbf D + \mathbf K
                
        which bases on the time discretization of the velocity and the 
        displacement:
        
        .. math:: \mathbf{\dot{q}}_{n+1} & = \mathbf{\dot{q}}_{n} + (1-\gamma)h
                  \mathbf{\ddot{q}}_{n} + \gamma h \mathbf{\ddot{q}}_{n+1}
        
        .. math:: \mathbf{q}_{n+1} & = \mathbf{q}_n + h \mathbf{\dot{q}}_n + 
                  \left(\frac{1}{2} - \beta\right)h^2\mathbf{\ddot{q}}_n +
                  h^2\beta\mathbf{\ddot{q}}_{n+1} 
        
        This method is using the variables/methods
        
            - self.M()
            - self.M_constr
            - self.K_and_f()
            - self.f_ext()
        
        If these methods are implemented correctly in a daughter class, the 
        time integration interface should work properly. 
        
        '''
        # compute mass matrix only once if it hasnt's been computed yet        
        if self.M_constr is None:
            self.M()
            
        K, f = self.K_and_f(u, t)
        S = K + 1/(beta*dt**2)*self.M_constr
        res = f + self.f_ext(u, du, t) + self.M_constr.dot(ddu)

        return S, res
    
    def write_timestep(self, t, u):
        '''
        write the timestep to the mechanical_system class
        '''
        self.T_output.append(t)
        self.u_output.append(self.unconstrain_vec(u))



class ReducedSystem(MechanicalSystem):
    '''
    Class for reduced systems.
    It is directly inherited from MechanicalSystem.
    Provides the interface for an integration scheme and so on where a basis 
    vector is to be chosen...

    Notes
    -----
    The Basis V is a Matrix with x = V*q mapping the reduced set of coordinates 
    q onto the physical coordinates x. The coordinates x are constrained, i.e. 
    the x denotes the full system in the sense of the problem set and not of 
    the pure finite element set.

    The system runs without providing a V_basis when constructing the method 
    only for the unreduced routines.

    Examples
    --------
    TODO

    '''

    def __init__(self, V_basis=None, **kwargs):
        '''
        Parameters
        ----------
        V_basis : ndarray, optional
            Basis onto which the problem will be projected with an 
            Galerkin-Projection.
        **kwargs : dict, optional
            Keyword arguments to be passed to the mother class MechanicalSystem. 

        Returns
        -------
        None
        '''
        MechanicalSystem.__init__(self, **kwargs)
        self.V = V_basis

    def K_and_f(self, u=None, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])        
        V = self.V
        u_full = V.dot(u)
        K_unreduced, f_unreduced = MechanicalSystem.K_and_f(self, u_full, t)
        K = V.T.dot(K_unreduced.dot(V))
        f_int = V.T.dot(f_unreduced)
        return K, f_int

    def K(self, u=None, t=0):
        if u is None:
            u = np.zeros(self.V.shape[1])
        return self.V.T.dot(MechanicalSystem.K(self, self.V.dot(u), t).dot(self.V))

    def f_ext(self, u, du, t):
        return self.V.T.dot(MechanicalSystem.f_ext(self, self.V.dot(u), du, t))

    def f_int(self, u, t=0):
        return self.V.T.dot(MechanicalSystem.f_int(self, self.V.dot(u), t))

    def M(self):
        self.M_constr = self.V.T.dot(MechanicalSystem.M(self).dot(self.V))
        return self.M_constr

    def write_timestep(self, t, u):
        MechanicalSystem.write_timestep(self, t, self.V.dot(u))

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
            Stiffness matrix
        
        '''
        return MechanicalSystem.K(self, u, t)

    def f_int_unreduced(self, u, t=0):
        '''
        Internal nonlinear force of the unreduced system. 
        
        Parameters
        ----------
        u : ndarray
            displacement of unreduces system. 
        t : float, optional
            time, default value: 0.
            
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


class QMSystem(MechanicalSystem):
    '''
    Quadratic Manifold Finite Element system. 
    
    
    '''
    
    def __init__(self, **kwargs):
        MechanicalSystem.__init__(self, **kwargs)
        self.V = None
        self.Theta = None
        self.no_of_red_dofs = None
        self.u_red_output = []
    
    def M(self, u=None, t=0):
        # checks, if u is there and M is already computed
        if u is None:
            u = np.zeros(self.no_of_red_dofs)
        if self.M_constr is None:
            MechanicalSystem.M(self)
            
        P = self.V + 2*self.Theta.dot(u)
        M_red = P.T @ self.M_constr @ P
        return M_red
    
    def K_and_f(self, u=None, t=0):
        '''
        Take care here! It is not clear yet how to compute the tangential 
        stiffness matrix! 
        
        It seems to be like the contribution of geometric and material 
        stiffness. 
        '''
        if u is None:
            u = np.zeros(self.no_of_red_dofs)
        theta_u = self.Theta @ u
        u_full = (self.V + theta_u) @ u
        P = self.V + 2*theta_u
        K_unreduced, f_unreduced = MechanicalSystem.K_and_f(self, u_full, t)
        K1 = P.T @ K_unreduced @ P
        K2 = 2*self.Theta.T @ f_unreduced
        K = K1 + K2
        f = P.T @ f_unreduced
        return K, f
    
    def S_and_res(self, u, du, ddu, dt, t, beta, gamma):
        '''
        TODO: checking the contributions of the different parts of the 
        iteration matrix etc. 
        
        '''
        # checking out that constant unreduced M is built
        if self.M_constr is None:
            MechanicalSystem.M(self)
        M_unreduced = self.M_constr
        
        theta = self.Theta        
        theta_u = theta @ u        
        u_full = (self.V + theta_u) @ u
        
        K_unreduced, f_unreduced = MechanicalSystem.K_and_f(self, u_full, t)
        # nonlinear projector P
        P = self.V + 2*theta_u

        # computing the residual
        res_accel = M_unreduced @ (P @ ddu)
        res_gyro = M_unreduced @ (theta @ du) @ du
        res_full = res_accel + res_gyro + f_unreduced
        # the different contributions to stiffness
        K1 = 2 * theta.T @ res_full
        K2 = 2 * P.T @ M_unreduced @ (theta @ ddu)
        K3 = P.T @ K_unreduced @ P
        K = K1 + K2 + K3
        # gyroscopic matrix and reduced mass matrix
        G = 2 * P.T @ M_unreduced @ (theta @ du)
        M = P.T @ M_unreduced @ P

        res = P.T @ res_full
        S = 1/(dt**2 * beta) * M + gamma/(dt*beta) * G + K
        return S, res
        
    def write_timestep(self, t, u):
        u_full = self.V @ u + (self.Theta @ u) @ u
        MechanicalSystem.write_timestep(self, t, u_full)
        # own reduced output
        self.u_red_output.append(u.copy())
        
    
    
    
        

#pylint: disable=unused-argument
class ConstrainedMechanicalSystem():
    '''
    Mechanical System with constraints providing the interface for solvers.

    This is an anonymous class providing all interface functions with zero-outputs. 
    For practical use, inherit this class and overwrite the functions needed.

    '''

    def __init__(self):
        self.ndof = 0
        self.ndof_const = 0

    def M(self, q, dq):
        '''
        Return the mass matrix.

        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity

        Returns
        -------
        M : ndarray
            mass matrix of the system
        '''
        return np.zeros((self.ndof, self.ndof))

    def D(self, q, dq):
        '''
        Return the tangential damping matrix.

        The tangential damping matrix is the jacobian matrix of the nonlinear 
        forces with respect to the generalized velocities q.
        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity

        Returns
        -------
        D : ndarray
            tangential damping matrix of the system

        '''
        return np.zeros((self.ndof, self.ndof))

    def K(self, q, dq):
        '''
        Return the tangential stiffness matrix

        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity

        Returns
        -------
        K : ndarray
            tangential stiffness matrix of the system

        '''
        return np.zeros((self.ndof, self.ndof))

    def C(self, q, dq, t):
        '''
        Return the residual of the constraints.

        The constraints are given in the canonical form C=0. This function 
        returns the residual of the constraints, i.e. C=res.

        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity
        t : float
            current time

        Returns
        -------
        C : ndarray
            residual vector of the constraints

        '''
        return np.zeros(self.ndof_const)

    def B(self, q, dq, t):
        '''
        Return the Jacobian B of the constraints.

        The Jacobian matrix of the constraints B is the partial derivative of 
        the constraint vector C with respect to the generalized coordinates q, 
        i.e. B = dC/dq

        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity
        t : float
            current time

        Returns
        -------
        B : ndarray
            Jacobian of the constraint vector with respect to the generalized 
            coordinates
        '''
        return np.zeros((self.ndof_const, self.ndof))

    def f_non(self, q, dq):
        '''
        Nonlinear internal forces of the mechanical system.

        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity

        Returns
        -------
        f_non : ndarray
            Nonlinear internal force of the mechanical system

        '''
        return np.zeros(self.ndof)

    def f_ext(self, q, dq, t):
        '''
        External force of the mechanical system.

        This is the right hand side of the canonical dynamic equation giving 
        the external forcing.

        Parameters
        ----------
        q : ndarray
            generalized position
        dq : ndarray
            generalized velocity
        t : float
            current time

        Returns
        -------
        f_ext : ndarray
            External force of the mechanical system

        '''
        return np.zeros(self.ndof)
