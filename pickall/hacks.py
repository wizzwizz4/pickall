import . as pickall

# Function duplication magic.
class _DuplicateGlobals(dict):
    """A chained dictionary implementation."""
    def __init__(self, *globalss,
                 set_globals=None, builtins=vars(builtins)):
        if set_globals is None:
            set_globals = globalss[0]
        self._set_globals = set_globals
        self._globalss = globalss + (builtins,)

    def __getitem__(self, key):
        for globals_ in self._globalss:
            if key in globals_:
                return globals_[key]
        raise KeyError("Key {} not in any of the globalss.".format(key))

    def __setitem__(self, key, value):
        self._set_globals[key] = value

def _duplicate(func, globals_=_DuplicateGlobals(vars(pickall), vars(pickle))):
    # Replace the functions with versions that use this module's globals in
    # preference to this function's globals.
    return types.FunctionType(
        func.__code__,
        globals_,
        func.__name__,
        func.__defaults__,
        func.__closure__
    )
