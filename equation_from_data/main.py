# -*- coding: utf-8 -*-
"""
Created on Mon Sep  9 10:52:11 2024

@author: song
"""

import os
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parent.parent


class FD:
    def __init__(self, data_u, delta_x, data_t):
        self.data_u = data_u
        self.data_t = data_t

        self.delta_h = delta_x

        for i in range(1, self.data_u.shape[1]):
            delta = (self.data_u[:, i] - self.data_u[:, i - 1]) / (self.data_t)
            if i == 1:
                ut = delta
            elif i != 1:
                ut = np.vstack((ut, delta))

        for i in range(1, self.data_u.shape[0] - 1):
            delta = 0.5 * (self.data_u[i + 1, :] - self.data_u[i - 1, :]) / self.delta_h
            if i == 1:
                ux = delta
            elif i != 1:
                ux = np.vstack((ux, delta))

        for i in range(1, self.data_u.shape[0] - 1):
            delta = (
                self.data_u[i + 1, :] - 2 * self.data_u[i, :] + self.data_u[i - 1, :]
            ) / np.square(self.delta_h)
            if i == 1:
                u2x = delta
            elif i != 1:
                u2x = np.vstack((u2x, delta))

        for i in range(2, self.data_u.shape[0] - 2):
            delta = (
                0.5 * self.data_u[i + 2, :]
                - self.data_u[i + 1, :]
                + self.data_u[i - 1, :]
                - 0.5 * self.data_u[i - 2, :]
            ) / np.power(self.delta_h, 3)
            if i == 2:
                u3x = delta
            elif i != 2:
                u3x = np.vstack((u3x, delta))

        self.u = self.data_u[2:-2, 1:]
        self.ut = ut.T[2:-2, 0:]
        self.ux = ux[1:-1, 1:]
        self.u2x = u2x[1:-1, 1:]
        self.u3x = u3x[0:, 1:]
        self.u_2 = np.power(self.u, 2)
        self.ux_2 = np.power(self.ux, 2)
        self.u2x_2 = np.power(self.u2x, 2)
        self.u3x_2 = np.power(self.u3x, 2)
        self.u_ux = self.u * self.ux
        self.u_u2x = self.u * self.u2x
        self.u_u3x = self.u * self.u3x
        self.ux_u2x = self.ux * self.u2x
        self.ux_u3x = self.ux * self.u3x
        self.u2x_u3x = self.u2x * self.u3x

    def generate_lib(self, N_u=None):

        candidate_lib = [
            self.u,
            self.ux,
            self.u2x,
            self.u3x,
            self.u_2,
            self.ux_2,
            self.u_ux,
            self.u_u2x,
            self.u_u3x,
            self.u2x_2,
            self.u3x_2,
            self.ux_u2x,
            self.ux_u3x,
            self.u2x_u3x,
            self.ut,
        ]

        data_list = []
        for i in range(len(candidate_lib)):
            _u = candidate_lib[i]
            _u = np.vstack(
                (
                    np.full([2, _u.shape[1]], np.nan),
                    np.vstack((_u, np.full([2, _u.shape[1]], np.nan))),
                )
            )
            _u = np.concatenate((np.full([_u.shape[0], 1], np.nan), _u), axis=1)
            __u = _u[2:-2, 1:]
            data_list.append(__u.flatten()[:, None])

        for i in range(len(data_list)):

            if i == 0:
                candi_lib = data_list[i]
            else:
                _candi_lib = data_list[i]
                candi_lib = np.hstack((candi_lib, _candi_lib))

        return candi_lib


"""
codes from https://github.com/snagcliffs/PDE-FIND   

Rudy, Samuel H., et al. "Data-driven discovery of partial differential equations." Science advances 3.4 (2017): e1602614.

"""


def TrainSTRidge(
    R,
    Ut,
    lam,
    d_tol,
    maxit=25,
    STR_iters=10,
    l0_penalty=None,
    normalize=2,
    split=0.8,
    print_best_tol=False,
):
    """
    This function trains a predictor using STRidge.

    It runs over different values of tolerance and trains predictors on a training set, then evaluates them
    using a loss function on a holdout set.

    Please note published article has typo.  Loss function used here for model selection evaluates fidelity using 2-norm,
    not squared 2-norm.
    """

    # Split data into 80% training and 20% test, then search for the best tolderance.
    np.random.seed(0)  # for consistancy
    n, _ = R.shape
    train = np.random.choice(n, int(n * split), replace=False)
    test = [i for i in np.arange(n) if i not in train]
    TrainR = R[train, :]
    TestR = R[test, :]
    TrainY = Ut[train, :]
    TestY = Ut[test, :]
    D = TrainR.shape[1]

    # Set up the initial tolerance and l0 penalty
    d_tol = float(d_tol)
    tol = d_tol
    if l0_penalty == None:
        l0_penalty = 0.001 * np.linalg.cond(R)

    # Get the standard least squares estimator
    w = np.zeros((D, 1))
    w_best = np.linalg.lstsq(TrainR, TrainY, rcond=None)[0]
    err_best = np.linalg.norm(
        TestY - TestR.dot(w_best), 2
    ) + l0_penalty * np.count_nonzero(w_best)
    tol_best = 0

    # Now increase tolerance until test performance decreases
    for iter in range(maxit):

        # Get a set of coefficients and error
        w = STRidge(TrainR, TrainY, lam, STR_iters, tol, normalize=normalize)
        err = np.linalg.norm(TestY - TestR.dot(w), 2) + l0_penalty * np.count_nonzero(w)

        # Has the accuracy improved?
        if err <= err_best:
            err_best = err
            w_best = w
            tol_best = tol
            tol = tol + d_tol

        else:
            tol = max([0, tol - 2 * d_tol])
            d_tol = 2 * d_tol / (maxit - iter)
            tol = tol + d_tol

    if print_best_tol:
        print("Optimal tolerance:", tol_best)

    return w_best


def STRidge(X0, y, lam, maxit, tol, normalize=2, print_results=False):
    """
    Sequential Threshold Ridge Regression algorithm for finding (hopefully) sparse
    approximation to X^{-1}y.  The idea is that this may do better with correlated observables.

    This assumes y is only one column
    """

    n, d = X0.shape
    X = np.zeros((n, d), dtype=np.complex64)
    # First normalize data
    if normalize != 0:
        Mreg = np.zeros((d, 1))
        for i in range(0, d):
            Mreg[i] = 1.0 / (np.linalg.norm(X0[:, i], normalize))
            X[:, i] = Mreg[i] * X0[:, i]
    else:
        X = X0

    # Get the standard ridge esitmate
    if lam != 0:
        w = np.linalg.lstsq(X.T.dot(X) + lam * np.eye(d), X.T.dot(y), rcond=None)[0]
    else:
        w = np.linalg.lstsq(X, y, rcond=None)[0]
    num_relevant = d
    biginds = np.where(abs(w) > tol)[0]

    # Threshold and continue
    for j in range(maxit):

        # Figure out which items to cut out
        smallinds = np.where(abs(w) < tol)[0]
        new_biginds = [i for i in range(d) if i not in smallinds]

        # If nothing changes then stop
        if num_relevant == len(new_biginds):
            break
        else:
            num_relevant = len(new_biginds)

        # Also make sure we didn't just lose all the coefficients
        if len(new_biginds) == 0:
            if j == 0:
                # if print_results: print "Tolerance too high - all coefficients set below tolerance"
                return w
            else:
                break
        biginds = new_biginds

        # Otherwise get a new guess
        w[smallinds] = 0
        if lam != 0:
            w[biginds] = np.linalg.lstsq(
                X[:, biginds].T.dot(X[:, biginds]) + lam * np.eye(len(biginds)),
                X[:, biginds].T.dot(y),
                rcond=None,
            )[0]
        else:
            w[biginds] = np.linalg.lstsq(X[:, biginds], y, rcond=None)[0]

    # Now that we have the sparsity pattern, use standard least squares to get w
    if biginds != []:
        w[biginds] = np.linalg.lstsq(X[:, biginds], y, rcond=None)[0]

    if normalize != 0:
        return np.multiply(Mreg, w)
    else:
        return w


def print_pde(w, ut="u_t"):
    rhs_description = [
        "u",
        "u_x",
        "u_xx",
        "u_xxx",
        "u^2",
        "u_x^2",
        "uu_x",
        "uu_xx",
        "u_u_xxx",
        "u_xx^2",
        "uxxx^2",
        "ux uxx",
        "ux uxxx",
        "uxx uxxx",
    ]
    pde = ut + " = "
    first = True
    for i in range(len(w)):
        if w[i] != 0:
            if not first:
                pde = pde + " + "
            pde = (
                pde
                + "(%05f %+05fi)" % (w[i].real, w[i].imag)
                + rhs_description[i]
                + "\n   "
            )
            first = False
    print(pde)


if __name__ == "__main__":
    x_file = os.path.join(PROJECT_DIR, "equation_from_data", "x.npy")
    t_file = os.path.join(PROJECT_DIR, "equation_from_data", "t.npy")
    h_file = os.path.join(PROJECT_DIR, "equation_from_data", "h.npy")
    x = np.load(x_file)
    t = np.load(t_file)
    u = np.load(h_file)

    diff_er = FD(u.T, x[1] - x[0], t[1] - t[0])

    candidates = diff_er.generate_lib()

    dx = x[1] - x[0]
    dt = t[1] - t[0]

    R = candidates[:, :-1]
    Ut = candidates[:, -1:]

    discovered_eq_coef = TrainSTRidge(R, Ut, lam=10**-5, d_tol=1)
    print("Discovered PDE:")
    print_pde(discovered_eq_coef)
