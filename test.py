import unittest
import doctest
import pickall
import pickle

# Utilities
class UnitTestDocTestRunner(doctest.DocTestRunner):
    def __init__(self, checker=None, optionflags=0, *args,
                 unittest_testcase, **kwargs):
        super().__init__(checker, False, optionflags, *args, **kwargs)
        self.unittest_testcase = unittest_testcase
        self._unittest_subtest = None

    def report_start(self, out, test, example):
        assert self._unittest_subtest is None
        self._unittest_subtest = self.unittest_testcase.subTest(
            out=out, test=test, example=example)
        self._unittest_subtest.__enter__()

    def report_success(self, out, test, example, got):
        self._unittest_subtest.__exit__(None, None, None)
        self._unittest_subtest = None

    def report_failure(self, out, test, example, got):
        self.unittest_testcase.assertEqual(example.want, got)
        self._unittest_subtest.__exit__(None, None, None)
        self._unittest_subtest = None

    def report_unexpected_exception(self, out, test, example, exc_info):
        self._unittest_subtest.__exit__(*exc_info)
        self._unittest_subtest = None
    

# Backwards- (pickle-)compatibility
class DoctestTestCase(unittest.TestCase):
    def test_all(self):
        """Tests nothing; here for completeness only."""
        tests = [
            test
            for name in pickle.__all__
            for test in doctest.DocTestFinder().find(getattr(pickle, name),
                                                     name)
        ]

        runner = UnitTestDocTestRunner(unittest_testcase=self)
        for test in tests:
            test.globs = vars(pickall).copy()
            runner.run(test)

class ImportTestCase(unittest.TestCase):
    def test_star(self):
        exec("from pickall import *")

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

    def test_isolated_closure(self):
        def wrapper():
            x = 0
            @pickall._no_globals
            def original():
                nonlocal x
                x += 1
                return x, y
            y = 24
            return original
        original = wrapper()

        pickle_string = pickall.dumps(original)
        new_func = pickle.loads(pickle_string)

        for i in range(100):
            with self.subTest(call_n=i):
                self.assertEqual(original(),
                                 new_func())

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
