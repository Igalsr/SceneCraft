import math
import unittest

from scenecraft.contracts import validate_building_spec
from scenecraft.errors import ContractError
from tests.helpers import SPEC


class ContractTests(unittest.TestCase):
    def test_unknown_fields_non_finite_values_and_short_vectors_are_rejected(self):
        with self.assertRaises(ContractError):
            validate_building_spec({**SPEC, "unexpected": True})
        with self.assertRaises(ContractError):
            validate_building_spec({**SPEC, "wall_thickness": math.nan})
        with self.assertRaises(ContractError):
            validate_building_spec({**SPEC, "camera": {**SPEC["camera"], "position": []}})

    def test_uncertainty_items_are_strict(self):
        with self.assertRaises(ContractError):
            validate_building_spec({**SPEC, "uncertainties": [{"reason": "hidden"}]})


if __name__ == "__main__":
    unittest.main()
