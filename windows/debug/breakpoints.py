from collections import OrderedDict

import windows
from windows.generated_def.winstructs import *
from windows.generated_def import windef
from windows.winobject.process import WinProcess, WinThread


STANDARD_BP = "BP"
HARDWARE_EXEC_BP = "HXBP"
MEMORY_BREAKPOINT = "MEMBP"

class Breakpoint(object):
    """An standard (Int3) breakpoint (type == ``STANDARD_BP``)"""
    type = STANDARD_BP # REAL BP
    def __init__(self, addr):
        self.addr = addr

    def apply_to_target(self, target):
        return isinstance(target, WinProcess)

    def trigger(self, dbg, exception):
        """Called when breakpoint is hit"""
        pass


class ProxyBreakpoint(Breakpoint):
    def __init__(self, target, addr, type):
        self.target = target
        self.addr = addr
        self.type = type

    def trigger(self, dbg, exception):
        return self.target(dbg, exception)


class HXBreakpoint(Breakpoint):
    """An hardware-execution breakpoint (type == ``HARDWARE_EXEC_BP``)"""
    type = HARDWARE_EXEC_BP

    def apply_to_target(self, target):
        return isinstance(target, WinThread)

class MemoryBreakpoint(Breakpoint):
    """A memory breakpoint (type == ``MEMORY_BREAKPOINT``)"""
    type = MEMORY_BREAKPOINT
    DEFAULT_EVENTS = "RWX"
    DEFAULT_SIZE = 0x1000
    def __init__(self, addr, size=None, events=None):
        """``size``: the size of the memory breakpoint.

        ``events``: a string representing the events that interest the BP (any of "RWX")"""
        super(MemoryBreakpoint, self).__init__(addr)
        self.size = size if size is not None else self.DEFAULT_SIZE
        events = events if events is not None else self.DEFAULT_EVENTS
        self.events = set(events)

    def trigger(self, dbg, exception):
        """Called when breakpoint is hit"""
        pass


## Arguments Helper (need to move this elsewhere)
class X86ArgumentRetriever(object):
    def get_arg(self, nb, proc, thread):
        return proc.read_dword(thread.context.sp + 4 + (4 * nb))

class X64ArgumentRetriever(object):
    REG_ARGS = ["Rcx", "Rdx", "R8", "R9"]
    def get_arg(self, nb, proc, thread):
        if nb < len(self.REG_ARGS):
            return getattr(thread.context, self.REG_ARGS[nb])
        return proc.read_qword(thread.context.sp + 8 + (8 * nb))

## Behaviour breakpoint !
# class FunctionParamDumpBP(Breakpoint):
class FunctionParamDumpBPAbstract(object):
    def __init__(self, addr=None, target=None):
        if target is None:
            try:
                target = self.TARGET
            except AttributeError as e:
                raise ValueError("{0} bp without a <target> must have a <TARGET> class attribute")
        if addr is None:
            addr = "{0}!{1}".format(target.target_dll, target.target_func)
        super(FunctionParamDumpBPAbstract, self).__init__(addr)
        self.target = target
        self.target_args = target.prototype._argtypes_
        self.target_params = target.params

    def extract_arguments_32bits(self, cproc, cthread):
        x = windows.debug.X86ArgumentRetriever()
        res = OrderedDict()
        for i, (name, type) in enumerate(zip(self.target_params, self.target_args)):
            value = x.get_arg(i, cproc, cthread)
            rt = windows.remotectypes.transform_type_to_remote32bits(type)
            if issubclass(rt, windows.remotectypes.RemoteValue):
                t = rt(value, cproc)
            else:
                t = rt(value)
            if not hasattr(t, "contents"):
                try:
                    t = t.value
                except AttributeError:
                    pass
            res[name[1]] = t
        return res

    def extract_arguments_64bits(self, cproc, cthread):
        x = windows.debug.X64ArgumentRetriever()
        res = OrderedDict()
        for i, (name, type) in enumerate(zip(self.target_params, self.target_args)):
            value = x.get_arg(i, cproc, cthread)
            rt = windows.remotectypes.transform_type_to_remote64bits(type)
            if issubclass(rt, windows.remotectypes.RemoteValue):
                t = rt(value, cproc)
            else:
                t = rt(value)
            if not hasattr(t, "contents"):
                try:
                    t = t.value
                except AttributeError:
                    pass
            res[name[1]] = t
        return res

    def extract_arguments(self, cproc, cthread):
        """Extracts the functions parameters in an :class:`OrderedDict`"""
        if windows.current_process.bitness == 32:
            return self.extract_arguments_32bits(cproc, cthread)
        if cproc.bitness == 64:
            return self.extract_arguments_64bits(cproc, cthread)
        # SysWow process from a 64bits debugger, handle bitness with CS
        if cthread.context.SegCs == windows.syswow64.CS_32bits:
            return self.extract_arguments_32bits(cproc, cthread)
        return self.extract_arguments_64bits(cproc, cthread)

class FunctionParamDumpBP(FunctionParamDumpBPAbstract, Breakpoint):
    pass

class FunctionParamDumpHXBP(FunctionParamDumpBPAbstract, HXBreakpoint):
    pass

class FunctionRetBP(Breakpoint):
    def __init__(self, addr, initial_breakpoint):
        super(FunctionRetBP, self).__init__(addr)
        self.initial_breakpoint = initial_breakpoint

    def trigger(self, dbg, exc):
        dbg.del_bp(self, targets=[dbg.current_process])
        return self.initial_breakpoint.ret_trigger(dbg, exc)


class FunctionCallBP(Breakpoint):
    def break_on_ret(self, dbg, exception):
        """Setup a breakpoint at the return address of the function, this breakpoint will call :func:`ret_trigger`"""
        cproc = dbg.current_process
        return_addr = dbg.current_process.read_ptr(dbg.current_thread.context.sp)
        dbg.add_bp(FunctionRetBP(return_addr, self), target=dbg.current_process)

    def ret_trigger(self, dbg, exception):
        """Called at the return of the function if :func:`break_on_ret` was called"""
        raise NotImplementedError("ret_trigger")


class FunctionBP(FunctionCallBP, FunctionParamDumpBP):
    """A breakpoint that accepts a function from :mod:`windows.winproxy` and able to:

        - Extract the arguments of the functions
        - Break at the return of the function
    """

class PrintBP(Breakpoint):
    def __init__(self, addr, format, func=None):
        super(PrintBP, self).__init__(addr)
        self.format = format
        self.func = func

    def trigger(self, dbg, exc):
        thread = dbg.current_thread
        format_dict = {"dbg": dbg, "exc": exc, "proc": dbg.current_process, "thread": thread, "ctx": thread.context}
        if self.func:
            format_dict.update(self.func(**format_dict))
        print(self.format.format(**format_dict))