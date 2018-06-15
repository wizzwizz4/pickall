import pickle
import types
import re
import io
import builtins
import functools

# Ensure that pickall has the same interface as pickle
__all__ = pickle.__all__
PickleError = pickle.PickleError
PicklingError = pickle.PicklingError
UnpicklingError = pickle.UnpicklingError
Unpickler = pickle.Unpickler

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

def _duplicate(func, globals_=_DuplicateGlobals(globals(), vars(pickle))):
    # Replace the functions with versions that use this module's globals in
    # preference to this function's globals.
    new_func = types.FunctionType(
        func.__code__,
        globals_,
        func.__name__,
        func.__defaults__,
        func.__closure__
    )
    new_func.__annotations__ = func.__annotations__
    new_func.__kwdefaults__ = func.__kwdefaults__
    return new_func

# Map of object to (module_name, qualname)
# Currently built for CPython; I might add dynamic collection back in later
# but my current implementation is flawed.
resolvable_location = {
    types.BuiltinFunctionType: ('types', 'BuiltinFunctionType'),
    types.CodeType: ('types', 'CodeType'),
    types.CoroutineType: ('types', 'CoroutineType'),
    types.FrameType: ('types', 'FrameType'),
    types.FunctionType: ('types', 'FunctionType'),
    types.GeneratorType: ('types', 'GeneratorType'),
    types.GetSetDescriptorType: ('types', 'GetSetDescriptorType'),
    types.MappingProxyType: ('types', 'MappingProxyType'),
    types.MemberDescriptorType: ('types', 'MemberDescriptorType'),
    types.MethodType: ('types', 'MethodType'),
    types.ModuleType: ('types', 'ModuleType'),
    types.TracebackType: ('types', 'TracebackType'),
    functools._CacheInfo: ('functools', '_CacheInfo')
}

def __newobj__(cls, *args):
    return cls.__new__(cls, *args)

class _Pickler(pickle._Pickler):
    # dispatch is a dictionary where the keys are the type of object
    # and the values are save_x methods.
    dispatch = pickle._Pickler.dispatch.copy()

    def save_type(self, obj):
        # save_type is called to save all instances of type.
        # This includes the types.XyzType types.
        
        # I'm implementing this here, as opposed to in separate
        # dispatches, because the types need to be implemented anyway
        # and I'd just be reprogramming the existing object pickling
        # code with a special case to avoid calling the dispatch for the
        # class.
        
        if obj in resolvable_location:
            name = resolvable_location[obj][1]
            
            # I'm calling save_global here because I want this to work
            # even if the pickle protocol optimises this; if I implemented this
            # here using self.write it would be using protocol 4 max.
            # This means that I have to also override whichmodule, which means
            # that I have to _duplicate save_global.
            return self.save_global(obj, name=name)
        return super().save_type(obj)
    dispatch[type] = save_type  # Mustn't forget this!

    # For explanation, see comments in save_type
    save_global = _duplicate(pickle._Pickler.save_global)

    def save_function(self, obj):
        func = types.FunctionType
        if self.proto >= 2:
            # __newobj__ is supported
            func = __newobj__
        return self.save_reduce(
            func,
            (types.FunctionType, obj.__code__, obj.__globals__,
             # Afaik, function() copes with the optional arguments being
             # the default "empty" values.
             obj.__name__, obj.__defaults__, obj.__closure__),
            state={
                '__annotations__': obj.__annotations__,
                '__kwdefaults__': obj.__kwdefaults__
            }
        )
    dispatch[types.FunctionType] = save_function

    def save_code(self, obj):
        # This one's much easier than function.
        func = types.CodeType
        if self.proto >= 2:
            # __newobj__ is supported
            func = __newobj__
        return self.save_reduce(
            func,
            (types.CodeType, obj.co_argcount, obj.co_kwonlyargcount,
             obj.co_nlocals, obj.co_stacksize, obj.co_flags, obj.co_code,
             obj.co_consts, obj.co_names, obj.co_varnames, obj.co_filename,
             obj.co_name, obj.co_firstlineno, obj.co_lnotab, obj.co_freevars,
             obj.co_cellvars)
        )
    dispatch[types.CodeType] = save_code

def whichmodule(obj, name):
    if obj in resolvable_location:
        # resolvable_location[obj][1] should == name
        return resolvable_location[obj][0]
    return pickle.whichmodule(obj, name)

# Shorthands
_dump = _duplicate(pickle._dump)
_dumps = _duplicate(pickle._dumps)
_load = _duplicate(pickle._load)
_loads = _duplicate(pickle._loads)

# Use the faster _pickall if I ever get around to writing it
# Use the faster _pickle if possible
try:
    from _pickall import (
        Pickler,
        dump,
        dumps,
        load,
        loads
    )
except ImportError:
    Pickler = _Pickler
    dump, dumps, load, loads = _dump, _dumps, _load, _loads
