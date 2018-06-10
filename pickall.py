import pickle
import types

# Add everything from pickle's globals...
globals().update({k: v for k, v in vars(pickle).items()
                  if not k[:2] == "__" == k[-2:]})  # ... except f"__{foo}__"

def __duplicate(func):
    return types.FunctionType(
        func.__code__,
        globals(),
        func.__name__,
        func.__defaults__,
        func.__closure__
    )

for __key in dir():
    __value = globals()[__key]

    # Only want to work with what we've got from pickle.
    if hasattr(__value, "__module__") and __value.__module__ != "pickle":
        continue
    
    # Haven't used isinstance, just in case the pickle devs go crazy
    # and hackishly subclass function to do strange stuff.
    if type(__value) is types.FunctionType:
        # Replace the functions with versions that use this module's globals
        globals()[__key] = __duplicate(__value)

    if isinstance(__value, type):
        # Subclass, but duplicate all methods.
        # Current implementation may cause problems if pickle ever uses super.
        # To correct this, the methods must have custom __get__s, iirc.
        # Alternatively, it could be a sibling in the class hierarchy
        # instead of a child.
        globals()[__key] = type(
            __key,
            (__value,),
            {k: __duplicate(v)
             for k, v in vars(__value).items()
             if type(v) is types.FunctionType}
        )
