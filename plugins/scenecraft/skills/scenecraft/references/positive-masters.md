# Positive masters

This mode produces the positive object that silicone is poured around, not a negative mold cavity. Use `init --asset-type positive-master` and `schemas/object-spec.schema.json`.

Confirm target width, depth, height, units, minimum meaningful feature size, and intended demolding method. A photograph alone cannot establish those dimensions. Record the source in `manufacturing.scale_source`. Discuss undercuts and whether a cut/split silicone mold is intended; do not silently erase important details to simplify demolding.

Represent forms with box, sphere, cylinder, cone, torus, or explicit local mesh vertices/faces. The trusted runner combines the ordered operands using union/difference. Mesh dimensions specify the bounding size before rotation; vertices define normalized local shape, and center is the local origin's world position. Keep all scene coordinates in meters. Do not generate Python to expand the operation vocabulary. If a form cannot be represented reliably, report the limitation.

The native file retains named source operands, while exported GLB and STL contain the finished object. STL is unitless by format; SceneCraft deliberately writes millimeter coordinates to `master-mm.stl`, while `.blend` and GLB stay in meters.

Before visual approval, inspect the geometry report and finished mesh from additional angles. The automated gate checks a closed, consistently oriented, single connected component, positive volume, no detected nonadjacent intersections, and dimensions within tolerance. It does not certify all self-intersections, wall/neck thickness, printer suitability, material compatibility, or demolding. `master-minimum-features`, `master-undercuts-and-release`, `master-surface-and-printability`, and `master-scale-confirmed` must have concrete reviewed observations. Do not check these off from the hero image alone or invent a process approval.

Visual acceptance means the declared view matches the supplied evidence. It does not establish unseen anatomy or make a fabrication guarantee. Keep uncertainties in the deliverable and request extra views when they materially constrain the figure.
