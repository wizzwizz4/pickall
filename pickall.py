import pickle
import types
import re
import io
import builtins

# Ensure that pickall has the same interface as pickle
__all__ = pickle.__all__
PickleError = pickle.PickleError
PicklingError = pickle.PicklingError
UnpicklingError = pickle.UnpicklingError

# Add SHOUTY_VARIABLES from pickle's globals
globals().update({k: v for k, v in vars(pickle).items()
                  if re.match("[A-Z][A-Z0-9_]+$", k)})

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

def _duplicate(func, globals_ = _DuplicateGlobals(globals(), vars(pickle))):
    # Replace the functions with versions that use this module's globals in
    # preference to this function's globals.
    return types.FunctionType(
        func.__code__,
        globals_,
        func.__name__,
        func.__defaults__,
        func.__closure__
    )

class _Pickler(pickle._Pickler):
    # dispatch is a dictionary where the keys are the type of object
    # and the values are save_x methods.
    dispatch = pickle._Pickler.dispatch.copy()
    del dispatch[types.FunctionType]

    def save_type(self, obj, *args, **kwargs):
        # save_type is called to save all instances of type.
        # This includes the types.XyzType types.
        
        # I'm implementing this here, as opposed to in separate dispatches,
        # because the types need to be implemented anyway and I'd just be
        # reprogramming the existing object pickling code with a special case
        # to avoid calling the dispatch for the class.
        
        if obj in map(vars(types).__getitem__, types.__all__):
            name = next(k for k, v in vars(types).items()
                        if v is obj)
            
            # I'm calling save_global here because I want this to work
            # even if the pickle protocol optimises this; if I implemented this
            # here using self.write it would be using protocol 4 max.
            # This means that I have to also override whichmodule, which means
            # that I have to _duplicate save_global.
            return self.save_global(obj, name=name)
        return super().save_type(obj, *args, **kwargs)
    dispatch[type] = save_type  # Mustn't forget this!

    # For explanation, see comments in save_type
    save_global = _duplicate(pickle._Pickler.save_global)

def whichmodule(obj, name):
    if getattr(obj, '__module__', None) == 'builtins':
        if (obj not in vars(builtins).values()
            and obj in vars(types).values()):
            return 'types'
    return pickle.whichmodule(obj, name)
