import pickle
import types
import re
import io
import builtins
import sys

from .hacks import _duplicate

# Ensure that pickall has the same interface as pickle
__all__ = pickle.__all__
PickleError = pickle.PickleError
PicklingError = pickle.PicklingError
UnpicklingError = pickle.UnpicklingError

# Add SHOUTY_VARIABLES from pickle's globals
globals().update({k: v for k, v in vars(pickle).items()
                  if re.match("[A-Z][A-Z0-9_]+$", k)})

class _Pickler(pickle._Pickler):
    # dispatch is a dictionary where the keys are the type of object
    # and the values are save_x methods.
    dispatch = pickle._Pickler.dispatch.copy()
    del dispatch[types.FunctionType]

    def save_type(self, obj, *args, **kwargs):
        # save_type is called to save all instances of type.
        # This includes the types.XyzType types.
        
        # I'm implementing this here, as opposed to in separate
        # dispatches, because the types need to be implemented anyway
        # and I'd just be reprogramming the existing object pickling
        # code with a special case to avoid calling the dispatch for the
        # class.
        
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

_whichcache = {}
def whichmodule(obj, name):
    
    if getattr(sys.modules[getattr(obj, '__module__', None)],
               name, None) is not obj:
        for module_name, module in (('types', types)):
            if getattr(module, name, None) is obj:
                return module_name
    return pickle.whichmodule(obj, name)
