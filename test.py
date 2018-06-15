import unittest
import pickall
import pickle

# Documented
class FunctionPicklingTestCase(unittest.TestCase):
    def test_isolated_function(self):
        def original(a, b=12, *args, c=42, **kwargs):
            return a, b, c, args, kwargs
        original = pickall._duplicate(original, {})

        pickle_string = pickall.dumps(original)
        new_func = pickle.loads(pickle_string)
        
        self.assertEqual(original(1, 2, 3, test=4),
                         new_func(1, 2, 3, test=4),
                         "(1, 2, 3, test=4) didn't work.")

# Undocumented
class _duplicateTestCase(unittest.TestCase):
    def test_optional_kwonly(self):
        # Issue #1
        def original(*, kwonly="default"):
            return kwonly
        new_func = pickall._duplicate(original)
        self.assertEqual(new_func(), "default",
                         "kwonly default value is wrong")
        self.assertEqual(new_func(kwonly="overridden"), "overridden",
                         "kwonly overridden value is wrong")

if __name__ == '__main__':
    unittest.main()
