from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import tabulate
from scipy.optimize import curve_fit, brentq
from scipy.integrate import simps
from math import pi
import itertools
import pathlib
import numpy as np
import constants
import potentials
import numeric
import solution
import scipy.constants


class Task:
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.log_file = None
        self.plot_file = None

    def run(self, output_dir):
        raise NotImplementedError("Task.run() is not implemented")

    def _log(self, text):
        if self.log_file is None:
            raise RuntimeError("log_file is not initialized")
        message = f"{self.name}: {text}"
        print(message)
        self.log_file.write(message + "\n")
        self.log_file.flush()

    def _open_output_files(self, output_dir):
        if self.log_file is not None:
            raise RuntimeError("log_file is already initialized")

        self.plot_file = PdfPages(output_dir / f"{self.name}.pdf")
        self.log_file = (output_dir / f"{self.name}.log").open("wt", encoding="utf-8")

    def _close_output_files(self):
        self.plot_file.close()
        self.log_file.close()
        plt.clf()


class PointNucleus(Task):
    def __init__(self, rmin, rmax, n_grid_points, energies, **kwargs):
        super().__init__(**kwargs)
        self.rmin = rmin
        self.rmax = rmax
        self.n_grid_points = n_grid_points
        self.energies = energies

    def run(self, output_dir):
        self._open_output_files(pathlib.Path(output_dir))
        self._log(f"Start")
        r_grid = self._get_r_grid(
            rmin=self.rmin, rmax=self.rmax, n_grid_points=self.n_grid_points,
        )
        analytic_solution, numeric_solutions = self._solve(
            energies=self.energies, r_grid=r_grid
        )
        self._plot(analytic_solution, numeric_solutions)
        self._close_output_files()

    def _solve(self, energies, r_grid):
        numeric_solutions = self._get_numeric_solutions(r_grid, 0, energies)
        analytic_solution = self._get_analytic_solution(r_grid)
        return analytic_solution, numeric_solutions

    def _plot(self, analytic_solution, numeric_solutions):
        fig, (wave_ax, uwave_ax) = plt.subplots(1, 2, figsize=(12, 6))
        for numeric_solution in numeric_solutions:
            wave_ax.plot(
                numeric_solution.r_grid,
                numeric_solution.wave_function,
                label=f"$E$ = {numeric_solution.energy / constants.RY:6.2f}",
            )
            uwave_ax.plot(
                numeric_solution.r_grid,
                numeric_solution.uwave_function,
                label=f"$E$ = {numeric_solution.energy / constants.RY:6.2f}",
            )
        uwave_ax.plot(
            analytic_solution.r_grid,
            analytic_solution.uwave_function,
            "--",
            c="black",
            label=f"Analytic",
        )
        wave_ax.plot(
            analytic_solution.r_grid,
            analytic_solution.wave_function,
            "--",
            c="black",
            label=f"Analytic",
        )
        for ax in (wave_ax, uwave_ax):
            ax.legend()
            ax.set_xlabel(f"$r$ [fm]")
            ax.set_xlim(0.0, analytic_solution.r_grid[-1])
            ax.legend()
            ax.grid(True)

        wave_ax.set_ylabel(f"$\psi(r)$")
        uwave_ax.set_ylabel(f"$u(r)$")
        self.plot_file.savefig()

    def _get_r_grid(self, rmin, rmax, n_grid_points):
        return np.linspace(rmin, rmax, num=n_grid_points, endpoint=True)

    def _get_numeric_solutions(self, r_grid, l_level, energies):
        solutions = []
        for energy in energies:
            self._log(f"E={energy / constants.RY} Ry")
            solutions.append(
                numeric.numerov_wf(
                    energy,
                    1,
                    l_level,
                    potentials.get_coulomb_potential(
                        constants.Z * constants.HBARC * constants.ALPHA_FS
                    ),
                    r_grid,
                    mass_a=constants.N_NUCL,
                    mass_b=constants.M_PION,
                    should_find_wave=True,
                    numerov_case=numeric.NumerovCase.NON_RELATIVISTIC,
                )
            )
        return solutions

    def _get_analytic_solution(self, r_grid):
        uwave_exact = (
            lambda r: (2 / (constants.A_BHOR ** (3 / 2)))
            * np.exp(-r / constants.A_BHOR)
            * r
        )
        wave_exact = lambda r: (uwave_exact(r)) / r
        wave_function = solution.add_spherical_harmonic(
            np.array([wave_exact(r) for r in r_grid]), l_level=0, m_level=0
        )
        norm = solution.get_norm(wave_function, r_grid,)
        uwave_norm = solution.get_norm(uwave_exact(r_grid), r_grid)
        return solution.Solution(
            energy=0.0,
            n_level=1,
            l_level=0,
            m_level=0,
            wave_function=(1 / norm) * wave_function,
            uwave_function=(1 / uwave_norm) * np.array([uwave_exact(r) for r in r_grid]),
            r_grid=r_grid,
            steps=len(r_grid),
        )


class PointNucleusFindBoundState(Task):
    def __init__(
        self,
        rmin,
        max_radii,
        energy_min,
        energy_max,
        l_level,
        numbers_of_steps,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if energy_min >= energy_max:
            raise ValueError("energy_min must be less than energy_max")
        self.rmin = rmin
        self.max_radii = max_radii
        self.energy_min = energy_min
        self.energy_max = energy_max
        self.l_level = l_level
        self.numbers_of_steps = numbers_of_steps

    def run(self, output_dir):
        self._open_output_files(pathlib.Path(output_dir))
        self._log(f"Start")
        potential = potentials.get_coulomb_potential(
            constants.Z * constants.HBARC * constants.ALPHA_FS
        )

        steps_and_max_radius_to_bound_state = self._find_bounded_states(
            potential=potential,
            max_radii=self.max_radii,
            numbers_of_steps=self.numbers_of_steps,
        )
        self._plot(
            steps_and_max_radius_to_bound_state, self.max_radii, self.numbers_of_steps
        )
        self._close_output_files()

    def _plot(self, steps_and_max_radius_to_bound_state, max_radii, numbers_of_steps):
        for max_radius in max_radii:
            bounded_states = self._get_bounded_states_by_radius(
                max_radius, numbers_of_steps, steps_and_max_radius_to_bound_state
            )
            plt.loglog(
                [bounded_state.steps for bounded_state in bounded_states],
                [bounded_state.error for bounded_state in bounded_states],
                "-.s",
                label=f"R={max_radius / constants.A_BHOR} $a_B$",
            )
        #
        plt.xlabel(f"$N$")
        plt.ylabel(f"$\eta$")
        plt.xlim(min(numbers_of_steps), max(numbers_of_steps))
        # plt.ylim(1.0e-8, 0.1)
        plt.legend()
        plt.grid(True)
        self.plot_file.savefig()
        plt.close()
        # plot eta vs rmax
        self._plot_max_radius_to_error(
            steps_and_max_radius_to_bound_state, numbers_of_steps, max_radii
        )

    def _get_bounded_states_by_radius(
        self, max_radius, numbers_of_steps, steps_and_max_radius_to_bound_state
    ):
        return [
            steps_and_max_radius_to_bound_state[(steps, max_radius)]
            for steps in numbers_of_steps
        ]

    def _get_bounded_states_by_number_of_steps(
        self, number_of_steps, max_radii, steps_and_max_radius_to_bound_state
    ):
        return [
            steps_and_max_radius_to_bound_state[(number_of_steps, max_radius)]
            for max_radius in max_radii
        ]

    def _plot_max_radius_to_error(
        self, steps_and_max_radius_to_bound_state, numbers_of_steps, max_radii
    ):
        bounded_states = self._get_bounded_states_by_number_of_steps(
            max(numbers_of_steps), max_radii, steps_and_max_radius_to_bound_state
        )
        plt.semilogy(
            [
                bounded_state.r_max / constants.A_BHOR
                for bounded_state in bounded_states
            ],
            [bounded_state.error for bounded_state in bounded_states],
            "-s",
            label=f"N=$10^5$",
        )

        plt.xlabel(f"$R [a_B]$")
        plt.ylabel(f"$\eta$")
        plt.xlim(0.0, max(max_radii) / constants.A_BHOR)
        plt.legend()
        plt.grid(True)
        self.plot_file.savefig()
        plt.close()

    def _find_bounded_states(self, max_radii, numbers_of_steps, potential):
        steps_and_max_radius_to_bound_state = {}
        for max_radius, number_of_steps in itertools.product(
            max_radii, numbers_of_steps
        ):
            r_grid = np.linspace(
                self.rmin, max_radius, num=number_of_steps, endpoint=True
            )

            solution = numeric.find_bound_state(
                mass_a=constants.N_NUCL,
                mass_b=constants.M_PION,
                min_energy=self.energy_min,
                max_energy=self.energy_max,
                n_level=1,
                l_level=self.l_level,
                potential=potential,
                r_grid=r_grid,
                should_find_wave=True,
            )
            steps_and_max_radius_to_bound_state[
                (number_of_steps, max_radius)
            ] = solution

            self._log(
                f"Energy level #{1} R={max_radius:6.1f}  N={number_of_steps:7d} E [MeV] = {solution.energy:.6E}"
                + f"   Validation: 1-E/(-Ry/n^2) = {solution.error:.6E}"
            )
        return steps_and_max_radius_to_bound_state


class PointNucleusEnergyLevelsFindBoundState(Task):
    def __init__(self, n_max, l_levels, ngrid, rmin, **kwargs):
        super().__init__(**kwargs)
        self.n_max = n_max
        self.l_levels = l_levels
        self.ngrid = ngrid
        self.rmin = rmin

    def run(self, output_dir):
        self._open_output_files(pathlib.Path(output_dir))
        self._log(f"Start")

        potential = potentials.get_coulomb_potential(
            constants.Z * constants.HBARC * constants.ALPHA_FS
        )

        table_rows = []
        n_level_to_energy = [
            -0.8 * constants.RY / (n ** 2) if n > 0 else -1.1 * constants.RY
            for n in range(0, self.n_max + 1)
        ]
        for n_level in range(1, self.n_max + 1):
            for l_level in range(0, n_level):
                max_energy = n_level_to_energy[n_level - 1]
                min_energy = n_level_to_energy[n_level]
                r_max = (n_level + l_level) * 20 * constants.A_BHOR
                r_grid = np.linspace(self.rmin, r_max, num=self.ngrid, endpoint=True)
                solution = numeric.find_bound_state(
                    mass_a=constants.N_NUCL,
                    mass_b=constants.M_PION,
                    min_energy=max_energy,
                    max_energy=min_energy,
                    n_level=n_level,
                    l_level=l_level,
                    potential=potential,
                    r_grid=r_grid,
                    should_find_wave=False,
                )
                table_rows.append(
                    [
                        n_level,
                        l_level,
                        solution.energy,
                        solution.energy / constants.RY,
                        solution.rms_radius,
                        solution.rms_radius / constants.A_BHOR,
                        solution.at_infinity,
                        solution.error,
                    ]
                )
                self._log(
                    f"  n_level={n_level:2d} l={l_level:2d}   E [MeV] = {solution.energy:.4E}  "
                    f"E normalized [MeV] = {solution.energy / constants.RY:.4E}"
                    f"  radius [fm] = {solution.rms_radius:7.3f}"
                    + f"  radius [a_B] = {solution.rms_radius / constants.A_BHOR:7.4f}   "
                    f"u(r_max) = {solution.at_infinity:9.2E}"
                    f"  |1-E/(-Ry/n_level^2)| = {solution.error:.3E}"
                )
        self._log(
            "\n\n"
            + tabulate.tabulate(
                sorted(table_rows, key=lambda row: (row[0], row[1])),
                headers=[
                    "n_level",
                    "l_level",
                    "E",
                    "E/Ry",
                    "r",
                    "r/a_B",
                    "u(r_max)",
                    "error",
                ],
                tablefmt="fancy_grid",
            )
        )

        self._close_output_files()


class SmearedPotential(Task):
    def __init__(self, max_n_level, max_l_level, ngrid, **kwargs):
        super().__init__(**kwargs)
        self.max_n_level = max_n_level
        self.max_l_level = max_l_level
        self.ngrid = ngrid

    def run(self, output_dir):
        self._open_output_files(pathlib.Path(output_dir))
        self._log(f"Start")

        point_potential = potentials.get_coulomb_potential(
            constants.Z * constants.HBARC * constants.ALPHA_FS
        )
        smeared_potential = potentials.get_smeared_coulomb(
            (constants.Z * constants.ALPHA_FS * constants.HBARC)
            / ((4 / 3) * np.pi * constants.R_NUCL ** 3)
        )

        # n_level = radial excitation
        # l_level = orbital mometum
        self._log(f"\n Units MeV, fm")
        table_rows = []
        for n_level in range(1, self.max_n_level + 1):
            for l_level in range(0, min(n_level, self.max_l_level + 1)):
                n_level_to_energy = [
                    -0.8 * constants.RY / (n ** 2) if n > 0 else -1.1 * constants.RY
                    for n in range(0, self.max_n_level + 1)
                ]
                max_energy = n_level_to_energy[n_level - 1]
                min_energy = n_level_to_energy[n_level]
                rmin = 1e-6 * constants.A_BHOR
                rmax = (n_level + l_level) * 20 * constants.A_BHOR
                r_grid = np.linspace(rmin, rmax, num=self.ngrid, endpoint=True)
                point_solution = numeric.find_bound_state(
                    potential=point_potential,
                    r_grid=r_grid,
                    mass_a=constants.M_PION,
                    mass_b=constants.N_NUCL,
                    n_level=n_level,
                    l_level=l_level,
                    min_energy=min_energy,
                    max_energy=max_energy,
                    should_find_wave=False,
                )
                smeared_solution = numeric.find_bound_state(
                    potential=smeared_potential,
                    r_grid=r_grid,
                    mass_a=constants.M_PION,
                    mass_b=constants.N_NUCL,
                    n_level=n_level,
                    l_level=l_level,
                    min_energy=min_energy,
                    max_energy=max_energy,
                    should_find_wave=False,
                )
                energy_perturbation = numeric.energy_shift_perturbation(
                    r_grid=r_grid,
                    basic_solution=point_solution,
                    perturbation_potential=lambda r: smeared_potential(r)
                    - point_potential(r),
                )
                error = np.abs(
                    1
                    - energy_perturbation
                    / (smeared_solution.energy - point_solution.energy)
                )
                table_rows.append(
                    [
                        n_level,
                        l_level,
                        point_solution.energy,
                        smeared_solution.energy,
                        smeared_solution.energy - point_solution.energy,
                        energy_perturbation,
                        (smeared_solution.energy - point_solution.energy)
                        / point_solution.energy,
                        error,
                    ]
                )
                self._log(
                    f"  n_level={n_level:2d} l_level={l_level:2d}  "
                    f"Ep = {point_solution.energy:.6E}  Es = {smeared_solution.energy:.6e}"
                    + f"  dE_exct ={smeared_solution.energy - point_solution.energy:9.2e}  "
                    f"dE_prtb ={energy_perturbation:9.2e}" + f"  1-dE/E = "
                    f"{(smeared_solution.energy - point_solution.energy) / point_solution.energy:.2e} "
                    f" |1-dE_prtb/dE_exct| = {error:.2e}"
                )
        self._log(
            "\n\n"
            + tabulate.tabulate(
                sorted(table_rows, key=lambda row: (row[0], row[1])),
                headers=[
                    "n_level",
                    "l_level",
                    "Ep",
                    "Es",
                    "dE_exct",
                    "dE_prtb",
                    "1-dE/E",
                    "|1-dE_prtb/dE_exct|",
                ],
                tablefmt="fancy_grid",
            )
        )
        self._close_output_files()


class Relativistic(Task):
    def __init__(self, max_n_level, max_l_level, ngrid, **kwargs):
        super().__init__(**kwargs)
        self.max_n_level = max_n_level
        self.max_l_level = max_l_level
        self.ngrid = ngrid

    def run(self, output_dir):
        self._open_output_files(pathlib.Path(output_dir))
        self._log(f"Start")

        potential = potentials.get_coulomb_potential(
            constants.Z * constants.HBARC * constants.ALPHA_FS
        )

        # n = radial excitation
        # l = orbital mometum
        self._log(f"\n Units MeV, fm")
        table_rows = []
        for n_level in range(1, self.max_n_level + 1):
            for l_level in range(0, min(n_level, self.max_l_level + 1)):
                n_level_to_energy = [
                    -0.7 * constants.RY / (n ** 2) if n > 0 else -1.3 * constants.RY
                    for n in range(0, self.max_n_level + 1)
                ]

                min_energy = n_level_to_energy[n_level - 1]
                max_energy = n_level_to_energy[n_level]
                min_radius = 1e-6 * constants.A_BHOR
                max_radius = (n_level + l_level) * 25 * constants.A_BHOR
                r_grid = np.linspace(
                    min_radius, max_radius, num=self.ngrid, endpoint=True
                )

                rel_solution = numeric.find_bound_state(
                    potential=potential,
                    r_grid=r_grid,
                    mass_a=constants.M_PION,
                    mass_b=constants.N_NUCL,
                    n_level=n_level,
                    l_level=l_level,
                    min_energy=min_energy,
                    max_energy=max_energy,
                    should_find_wave=False,
                    numerov_case=numeric.NumerovCase.RELATIVISTIC,
                )
                non_rel_solution = numeric.find_bound_state(
                    potential=potential,
                    r_grid=r_grid,
                    mass_a=constants.M_PION,
                    mass_b=constants.N_NUCL,
                    n_level=n_level,
                    l_level=l_level,
                    min_energy=min_energy,
                    max_energy=max_energy,
                    should_find_wave=False,
                    numerov_case=numeric.NumerovCase.NON_RELATIVISTIC,
                )
                diff = 1 - rel_solution.energy / non_rel_solution.energy
                table_rows.append(
                    [
                        n_level,
                        l_level,
                        non_rel_solution.energy,
                        rel_solution.energy,
                        non_rel_solution.energy / constants.RY,
                        rel_solution.energy / constants.RY,
                        diff,
                    ]
                )
                self._log(
                    f"  n={n_level:2d} l={l_level:2d}  "
                    f"E_NR = {non_rel_solution.energy:.6E}  E_KG = {rel_solution.energy:.6e}"
                    + f"  E_NR/Ry = {non_rel_solution.energy / constants.RY:.6e}  "
                    f"E_KG/Ry = {rel_solution.energy / constants.RY:.6e} "
                    f" |1-E_KG/E_NR| = {diff:.3e}"
                )

        self._log(
            "\n\n"
            + tabulate.tabulate(
                sorted(table_rows, key=lambda row: (row[0], row[1])),
                headers=[
                    "n",
                    "l",
                    "E_NR",
                    "E_KG",
                    "E_NR/Ry",
                    "E_KG/Ry",
                    "|1-E_KG/E_NR|",
                ],
                tablefmt="fancy_grid",
            )
        )
        self._close_output_files()
