import pickle
import types
import re
import io
import builtins
import functools
import copyreg
import ctypes

# Ensure that pickall has the same interface as pickle
__all__ = pickle.__all__
PickleError = pickle.PickleError
PicklingError = pickle.PicklingError
UnpicklingError = pickle.UnpicklingError
Unpickler = pickle.Unpickler

# Get references to types without any __qualname__-like reference
def closure_container(x=None):
    return type((lambda:x).__closure__[0])
cell = closure_container()
del closure_container

# Add SHOUTY_VARIABLES from pickle's globals
globals().update({k: v for k, v in vars(pickle).items()
                  if re.match("[A-Z][A-Z0-9_]+$", k)})

class _ChainedDictionary(dict):
    """A chained dictionary implementation."""
    def __init__(self, *dictionaries):
        super().__init__()
        self._dictionaries = dictionaries

    def __getitem__(self, key):
        if key in self:
            return super().__getitem__(key)
        for dictionary in self._dictionaries:
            if key in dictionary:
                return dictionary[key]
        raise KeyError("Key {} not in any of the dictionaries.".format(key))

# Function duplication magic.
class _DuplicateGlobals(_ChainedDictionary):
    def __init__(self, *dictionaries,
                 set_globals=None, builtins=vars(builtins)):
        if set_globals is None:
            set_globals = dictionaries[0]
        self._set_globals = set_globals
        super().__init__(*dictionaries, builtins)

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
    new_func.__doc__ = func.__doc__
    return new_func

def _no_globals(func):
    return _duplicate(func, {})

# Map of object to (module_name, qualname)
# Currently built for CPython; I might add dynamic collection back in later
# but my current implementation is flawed.
_resolvable_location = {
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
    functools._CacheInfo: ('functools', '_CacheInfo'),
    ctypes.pythonapi._FuncPtr: ('ctypes', 'pythonapi._FuncPtr'),
}

def resolve_location(obj):
    try:
        contains = obj in _resolvable_location
    except Exception:
        pass
    else:
        if contains:
            return _resolvable_location[obj]
    # More rules go here, if needed.
    return None

@_no_globals
def __newobj__(cls, *args):
    return cls.__new__(cls, *args)

# For function pickling
@_no_globals
def set_function_descriptors(f, annotations, kwdefaults):
    # WARNING: Must NOT have __annotations__ or __kwdefaults__!
    f.__annotations__ = annotations
    f.__kwdefaults__ = kwdefaults
    return f

class _Pickler(pickle._Pickler):
    # dispatch is a dictionary where the keys are the type of object
    # and the values are save_x methods.
    dispatch = pickle._Pickler.dispatch.copy()
    del dispatch[types.FunctionType]  # Don't treat it as a global

    def save_function_call(self, func, *args):
        """Save a function and arguments, then call the function.
        
        The first argument should be a callable.
        
        Each subsequent argument should be a tuple containing an int and
        some number of other items.
        When the int is 0, there should be just one other item of the tuple,
        which is the argument to be passed to the function.
        When the int is 1, the subsequent items of the tuple represent the
        arguments passed to save_function_call; it means that one of the
        arguments passed to the function is a function call.
        When it's 2, the arguments should be a function, then an args tuple;
        this should be a function that when called with *args pushes one item
        onto the pickle stack. Alas, we all know that what _should be_, and
        what _is_, are two different things. Just please don't write an
        unmatched MARK.
        
        More observant readers may have noticed that 1 is just a special case
        of 2; this is technically true but it's a lot more useful to be able
        to write nested function calls with only one level of nested tuples
        instead of 2. Also, these readers may have noticed that magic numbers
        as opposed to enums or PSEUDO_CONSTANTS have been used here. This is to
        discourage people from using what is basically a utility function for
        a last-resort hackish, hackish way of pickling.
        """
        self.save(func)
        if not args:
            self.save_tuple(())  # No point reimplementing this logic
        
        if self.proto >= 2 and len(args) <= 3:
            pass  # TUPLE1, TUPLE2 and TUPLE3 can be used.
        else:
            # Start a variable-length tuple
            self.write(MARK)

        for mode, *arg in args:
            if mode == 0:
                # No special mode.
                self.save(arg[0])
                continue
            if mode == 1:
                self.save_function_call(*arg)
                continue
            if mode == 2:
                # Structured like this to support the possibility of adding
                # **kwargs in future; this is restricted by self.proto and I
                # don't know what to do if it isn't supported so haven't
                # implemented it.
                f, f_args = arg
                f(*f_args)
                continue
            raise ValueError("{} is not a valid mode".format(mode))

        if self.proto >= 2 and len(args) <= 3:
            # Write TUPLE1, TUPLE2 or TUPLE3
            self.write(pickle._tuplesize2code[len(args)])
        else:
            # End a variable-length tuple
            self.write(TUPLE)

    def save_type(self, obj):
        # save_type is called to save all instances of type.
        # This includes the types.XyzType types.
        
        # I'm implementing this here, as opposed to in separate
        # dispatches, because the types need to be implemented anyway
        # and I'd just be reprogramming the existing object pickling
        # code with a special case to avoid calling the dispatch for the
        # class.

        location = resolve_location(obj)
        if location is not None:
            qualname = location[1]
            
            # I'm calling save_global here because I want this to work
            # even if the pickle protocol optimises this; if I implemented this
            # here using self.write it would be using protocol 4 max.
            # This means that I have to also override whichmodule, which means
            # that I have to _duplicate save_global.
            return self.save_global(obj, name=qualname)
        return super().save_type(obj)
    dispatch[type] = save_type  # Mustn't forget this!

    # For explanation, see comments in save_type
    save_global = _duplicate(pickle._Pickler.save_global)

    def save_function(self, obj):
        # TODO: Be able to remove me!
        if obj.__module__ in ('ctypes',):
            try:
                self.save_global(obj)
            except PicklingError:
                print("ASSUMPTION IN save_function({}) FAILED!".format(obj))
                pass
            return
        
        func = types.FunctionType
        if self.proto >= 2:
            # __newobj__ is supported
            # Since __newobj__ is a function, this MUST not be used
            # unless __newobj__ will definitely not actually be pickled.
            func = __newobj__

        # Since __annotations__ and __kwdefaults__ are implemented as
        # descriptors, but aren't provided as arguments, they can't be
        # set in any way that pickle natively supports. Pickle does, however,
        # support arbitrary code execution.
        has_descriptors = bool(obj.__annotations__) or bool(obj.__kwdefaults__)
        if has_descriptors:
            # Save function, then arguments.
            self.save(set_function_descriptors)
            # Arguments have to be a tuple, which must include the function...
            # Manually constructing a tuple is easiest.
            if self.proto >= 2:
                # As there are only three arguments (obj, annnot, kwdef),
                # TUPLE3 can be used.
                # This involves simply pushing the items to the stack.
                pass
            else:
                # We have to use variable-length tuple code.
                self.write(MARK)
            
        self.save_reduce(
            func,
            (types.FunctionType, obj.__code__, obj.__globals__,
             # Afaik, function() copes with the optional arguments being
             # the default "empty" values.
             obj.__name__, obj.__defaults__, obj.__closure__),
            state=vars(obj)
            # Can't put __annotations__ and __kwdefaults__ here, since
            # they're descriptors that don't match a constructor argument.
        )

        if has_descriptors:
            self.save(obj.__annotations__)
            self.save(obj.__kwdefaults__)
            if self.proto >= 2:
                # Same as above; TUPLE3 can be used.
                self.write(TUPLE3)
            else:
                self.write(TUPLE)
            # Don't memoize because this isn't a real tuple,
            # so nothing else will reference it.
            self.write(REDUCE)  # Mutate the function object with set_funct...;
                                # new version is automatically in the memo
                                # because it's still the same object.
    dispatch[types.FunctionType] = save_function

    def save_cell(self, obj):
        self.save_function_call(
            ctypes.cast, (1,
                ctypes.pythonapi.PyCell_Get, (1,
                    ctypes.py_object, (0, obj.cell_contents)
                )
            ),
            (0, ctypes.py_object)
        )
    dispatch[cell] = save_cell

    # dispatch_table is a registry of reduction functions
    dispatch_table = _ChainedDictionary(copyreg.dispatch_table)

    # This one's MUCH easier than function.
    dispatch_table[types.CodeType] = lambda c: (
        __newobj__,
        (types.CodeType, c.co_argcount, c.co_kwonlyargcount, c.co_nlocals,
         c.co_stacksize, c.co_flags, c.co_code, c.co_consts, c.co_names,
         c.co_varnames, c.co_filename, c.co_name, c.co_firstlineno,
         c.co_lnotab, c.co_freevars, c.co_cellvars)
    )

    # pickle functions from arbitrary CDLLs
    def _ctypes_FuncPtr(name):
        basename = name + '.'
        p= lambda f: basename + f.__name__
        p.__name__ = "pickle_ctypes_{}_FuncPtr".format(name)
        return p
    dispatch_table[ctypes.pythonapi._FuncPtr] = _ctypes_FuncPtr('pythonapi')

def whichmodule(obj, name):
    location = resolve_location(obj)
    if location is not None:
        # resolvable_location(obj)[1] should == name
        return location[0]
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
