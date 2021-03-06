# -*- coding: utf-8 -*-
# Copyright (c) 2017, Lehrstuhl fuer Angewandte Mechanik, Technische
# Universitaet Muenchen.
#
# Distributed under BSD-3-Clause License. See LICENSE-File for more information
#
"""
"""


import numpy as np
import scipy as sp
import time

import amfe



gmsh_input_file = amfe.amfe_dir('meshes/gmsh/c_bow_coarse.msh')
paraview_output_file = amfe.amfe_dir('results/c_bow_coarse/bogen_grob')


my_material = amfe.KirchhoffMaterial()
my_system = amfe.MechanicalSystem()

my_system.load_mesh_from_gmsh(gmsh_input_file, 15, my_material)
# Test the paraview basic output
# my_system.export_paraview(paraview_output_file)

my_system.apply_dirichlet_boundaries(13, 'xy')

harmonic_x = lambda t: np.sin(2*np.pi*t*30)
harmonic_y = lambda t: np.sin(2*np.pi*t*50)

my_system.apply_neumann_boundaries(14, 1E8, (1,0), harmonic_x)
my_system.apply_neumann_boundaries(14, 1E8, (0,1), harmonic_y)


###############################################################################
## time integration
###############################################################################

ndof = my_system.dirichlet_class.no_of_constrained_dofs
q0 = np.zeros(ndof)
dq0 = np.zeros(ndof)
dt = 1E-3
T = np.arange(0,0.1, dt)

#%%
amfe.integrate_nonlinear_gen_alpha(my_system, q0, dq0, time_range=T, dt=dt,
                                   track_niter=True)

my_system.export_paraview(paraview_output_file)

# investigate the time integration
niter = my_system.iteration_info

#%%
amfe.integrate_linear_gen_alpha(my_system, q0, dq0, T, dt)
my_system.export_paraview(paraview_output_file + '_linear_gen_alpha')

#%%
amfe.integrate_linear_system(my_system, q0, dq0, T, dt)
my_system.export_paraview(paraview_output_file + '_linear')
