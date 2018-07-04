import pickle
import types
import re
import io
import builtins
import functools
import copyreg
import ctypes
import sys
import weakref

# Ensure that pickall has the same interface as pickle
__all__ = pickle.__all__
PickleError = pickle.PickleError
PicklingError = pickle.PicklingError
UnpicklingError = pickle.UnpicklingError
Unpickler = pickle.Unpickler
load = pickle.load
loads = pickle.loads

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
    re._pattern_type: ('re', '_pattern_type'),
    weakref.ref: ('weakref', 'ref'),
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

    def save(self, obj, save_persistent_id=True, *args, **kwargs):
        # dispatch_singletons is a dictionary where the keys are the object's
        # id and the values are save_x methods.
        if id(obj) not in self.dispatch_singletons:
            return super().save(obj, save_persistent_id, *args, **kwargs)

        # Housekeeping
        self.framer.commit_frame()
        if save_persistent_id:
            pid = self.persistent_id(obj)  # Has priority over dispatch_x
            if pid is not None:
                self.save_pers(pid)
                return
        if obj in self.memo:  # Has priority over dispatch_x
            self.write(self.get(self.memo[obj])[0])
            return

        self.dispatch_singletons[id(obj)](self)

    def save_function_call(self, func, *args):
        """Save a function and arguments, then call the function.
        
        The first argument should be a callable (convenience) or a tuple
        as defined below.
        
        Each subsequent argument should be a tuple containing an int and
        some number of other items.
        When the int is 0, there should be just one other item of the tuple,
        which is the argument to be passed to the function.
        When the int is 1, the subsequent items of the tuple represent the
        arguments passed to save_function_call; it means that one of the
        arguments passed to the function is a function call.
        When it's 2, the arguments should be a function, then an args tuple,
        then an optional kwargs dictionary; this should be a function that when
        called with *args and **kwargs pushes one item onto the pickle stack.
        Alas, we all know that what _should be_, and what _is_, are two
        different things. Just please don't write an unmatched MARK.
        
        More observant readers may have noticed that 1 is just a special case
        of 2; this is technically true but it's a lot more useful to be able
        to write nested function calls with only one level of nested tuples
        than of 2. Also, these readers may have noticed that magic numbers as
        opposed to enums or PSEUDO_CONSTANTS have been used here. This is to
        discourage people from using what is basically a utility function for
        a last-resort hackish, hackish way of pickling.
        """
        modes = self.save_function_call.modes
        
        if callable(func):
            self.save(func)
        else:
            mode, *arg = func
            try:
                mode_f = modes[mode]
            except KeyError as e:
                raise ValueError("{} is not a valid mode".format(mode)) from e
            mode_f(self, *arg)
            
        if not args:
            self.save_tuple(())  # No point reimplementing this logic
        
        if self.proto >= 2 and len(args) <= 3:
            pass  # TUPLE1, TUPLE2 and TUPLE3 can be used.
        else:
            # Start a variable-length tuple
            self.write(MARK)

        for mode, *arg in args:
            try:
                mode_f = modes[mode]
            except KeyError as e:
                raise ValueError("{} is not a valid mode".format(mode)) from e
            mode_f(self, *arg)

        if self.proto >= 2 and len(args) <= 3:
            # Write TUPLE1, TUPLE2 or TUPLE3
            self.write(pickle._tuplesize2code[len(args)])
        else:
            # End a variable-length tuple
            self.write(TUPLE)
        self.write(REDUCE)  # Call the function
    save_function_call.modes = {
        0: (lambda self, value: self.save(value)),  # No special mode.
        1: (lambda self, *args: self.save_function_call(*args)),
        2: (lambda self, f, args=(), kwargs={}: f(self, *args, **kwargs))
    }

    def save_type(self, obj):
        # save_type is called to save all instances of type.
        # This includes the types.XyzType types.
        # It does not include classes with a different metaclass.
        
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
                return
            except PicklingError:
                pass
        
        func = types.FunctionType
        pre_args = ()
        if self.proto >= 2:
            # __newobj__ is supported
            # Since __newobj__ is a function, this MUST not be used
            # unless __newobj__ will definitely not actually be pickled.
            pre_args = (func,)
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
            func, pre_args +
            (obj.__code__, obj.__globals__,
             # Afaik, function() copes with the optional arguments being
             # the default "empty" values.
             obj.__name__, obj.__defaults__, obj.__closure__),
            state=vars(obj),
            # Can't put __annotations__ and __kwdefaults__ here, since
            # they're descriptors that don't match a constructor argument.
            obj=obj
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

    def save_code(self, obj):
        # This one's not much easier than function.
        func = types.CodeType
        pre_args = ()
        if self.proto >= 2:
            # code is required to pickle __newobj__, so it's very important
            # not to use it if it's got a chance of actually being pickled.
            pre_args = (func,)
            func = __newobj__
        self.save_reduce(
            func, pre_args +
            (obj.co_argcount, obj.co_kwonlyargcount,
             obj.co_nlocals, obj.co_stacksize, obj.co_flags, obj.co_code,
             obj.co_consts, obj.co_names, obj.co_varnames, obj.co_filename,
             obj.co_name, obj.co_firstlineno, obj.co_lnotab, obj.co_freevars,
             obj.co_cellvars),
            obj=obj
        )
    dispatch[types.CodeType] = save_code

    def save_cell(self, obj):
        self.save_function_call(
            getattr, (1,
                ctypes.cast, (1,
                    ctypes.pythonapi.PyCell_New, (1,
                        ctypes.py_object, (0, obj.cell_contents)
                    )
                ),
                (0, ctypes.py_object)
            ), (0, "value")
        )
    dispatch[cell] = save_cell

    def save_compiled_regex(self, obj):
        self.save_function_call(
            re._compile,
            (0, obj.pattern),
            (0, obj.flags)
        )
    dispatch[re._pattern_type] = save_compiled_regex

    # dispatch_table is a registry of reduction functions
    dispatch_table = _ChainedDictionary(copyreg.dispatch_table)

    # pickle functions from arbitrary CDLLs
    def _ctypes_FuncPtr(name):
        basename = name + '.'
        p= lambda f: basename + f.__name__
        p.__name__ = "pickle_ctypes_{}_FuncPtr".format(name)
        return p
    dispatch_table[ctypes.pythonapi._FuncPtr] = _ctypes_FuncPtr('pythonapi')
    dispatch_table[ctypes.PyDLL] = lambda d: "pythonapi"

    # sys
    dispatch_table[sys.version_info.__class__] = lambda v: "version_info"
    dispatch_table[sys.thread_info.__class__] = lambda t: "thread_info"
    dispatch_table[sys.hash_info.__class__] = lambda h: "hash_info"

    # dispatch_singletons is documented in save
    # It's like dispatch, but for singletons and using ids as keys.
    dispatch_singletons = {}
    dispatch_singletons[id(cell)] = lambda s, d={}: s.save_function_call(
        (1,
            getattr,  # Takes three arguments; last one has default value None
            (0, d),
            (0, "__getitem__"),
            (1,        # exec returns None, which needs to be discarded from
                exec,  # the stack; placing it as the third argument to getattr
                (0,    # serves to discard it
                    # Golfed quite a bit.
                    "cell=(lambda x:lambda:x)(0).__closure__[0].__class__"
                ),
                (0, d)  # Variable "cell" is put into this dictionary.
            )
        ),  # d.__getitem__
        (0, "cell")
    )

def whichmodule(obj, name):
    location = resolve_location(obj)
    if location is not None:
        # resolvable_location(obj)[1] should == name
        return location[0]
    return pickle.whichmodule(obj, name)

class DebugUnpickler(pickle._Unpickler):
    """Only exists for debugging porpoises.

    Do NOT attempt to debug other mammals."""
    def load(self):
        try:
            super().load()
        except AttributeError:
            # Hijacked. Yay!
            pass

        from code import InteractiveConsole
        
        while True:
            try:
                key = self.read(1)
                print("Executing", next(k for k, v in vars(pickle).items()
                                        if v == key), end='')
                if not key:
                    raise EOFError
                self.dispatch[key[0]](self)
                if input():
                    InteractiveConsole(locals=locals()).interact(banner="")
            except pickle._Stop as stopinst:
                print()
                InteractiveConsole(locals=locals()).interact(banner="Stopped!")

    def __getattribute__(self, key):
        if key == "read":
            import inspect
            frame = inspect.stack()[1]
            if frame.function == "load" and frame.filename == pickle.__file__:
                raise AttributeError("Stop load from running!")
        return super().__getattribute__(key)
            
# Shorthands
_dump = _duplicate(pickle._dump)
_dumps = _duplicate(pickle._dumps)

# Use the faster _pickall if I ever get around to writing it
try:
    from _pickall import (
        Pickler,
        dump,
        dumps,
    )
except ImportError:
    Pickler = _Pickler
    dump, dumps = _dump, _dumps
