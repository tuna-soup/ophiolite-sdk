"""Residual at wells (E119b, the reference residual procedure): for each selected wellbore and each top of the
formation, the top's measured depth minus the measured depth where the surface crosses the wellbore's trajectory
nearest that top, in metres; or the reason none is given. The computation is `ophiolite.residuals.compute`, which uses
the one trajectory geometry's `crossings` and `nearest` (E119a)."""
from ophiolite import procedure, residuals
from ophiolite.writers import well_residual


@procedure
def residuals_at_wells(inputs, settings):
    return {'residuals': well_residual(residuals.from_inputs(inputs, settings))}
