class SceneCraftError(Exception):
    """Expected, user-actionable workflow error."""


class ContractError(SceneCraftError):
    """An artifact does not satisfy a SceneCraft contract."""


class WorkerError(SceneCraftError):
    """The external Blender worker failed or produced an invalid result."""
