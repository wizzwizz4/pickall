import unittest
import pickall
import pickle

# Documented
class FunctionPicklingTestCase(unittest.TestCase):
    def test_basic_isolated_function(self):
        @pickall._no_globals
        def original(a):
            return a * 2

        pickle_string = pickall.dumps(original)
        new_func = pickle.loads(pickle_string)

        self.assertEqual(original(3),
                         new_func(3))
    
    def test_complex_isolated_function(self) -> tuple:
        @pickall._no_globals
        def original(a: int, b=12, *args, c=42, **kwargs):
            return a, b, c, args, kwargs

        pickle_string = pickall.dumps(original)
        new_func = pickle.loads(pickle_string)

        for attribute in ('__annotations__', '__kwdefaults__', '__name__'):
            with self.subTest(attribute=attribute):
                self.assertEqual(getattr(original, attribute),
                                 getattr(new_func, attribute))

        for arguments in (((1, 2, 3), {'test': 4}),
                          ((), {}),
                          ((), {'a': 7})):
            args, kwargs = arguments
            with self.subTest(args=args, kwargs=kwargs):
                self.assertEqual(original(1, 2, 3, test=4),
                                 new_func(1, 2, 3, test=4))

    def test_isolated_function_dictionary(self):
        @pickall._no_globals
        def original():
            pass
        original.a = "this is a"
        original.b = "this is b"
        original.c = ("this is a complex", "value for c")

        pickle_string = pickall.dumps(original)
        new_func = pickle.loads(pickle_string)

        for attribute in 'abc':
            with self.subTest(attribute=attribute):
                self.assertEqual(getattr(original, attribute),
                                 getattr(new_func, attribute))

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
