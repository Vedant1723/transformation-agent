"""Keep an owned training child inside a kill-on-parent-exit Windows job.

The child receives no training input until containment succeeds. Closing the
handle (including abrupt parent termination) terminates remaining descendants.
"""
import ctypes
import os
from ctypes import wintypes


def process_identity(pid):
    """Creation time disambiguates reused PIDs. Access failures are not death."""
    if os.name!='nt':raise OSError('Windows process identity required')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.GetProcessTimes.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        if ctypes.get_last_error()==87:return None
        raise OSError('Cannot verify process identity')
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):
            raise OSError('Cannot read process identity')
        if times[1].dwHighDateTime or times[1].dwLowDateTime:return None
        return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    finally:kernel.CloseHandle(handle)


class WindowsJob:
    def __init__(self, process):
        self.handle = None
        if os.name != 'nt':
            return
        class BasicLimits(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                        ('Flags', wintypes.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                        ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcesses', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('Priority', wintypes.DWORD),
                        ('Scheduling', wintypes.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('Basic', BasicLimits), ('Io', IoCounters),
                        ('ProcessMemory', ctypes.c_size_t), ('JobMemory', ctypes.c_size_t),
                        ('PeakProcessMemory', ctypes.c_size_t), ('PeakJobMemory', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        handle = self.kernel.CreateJobObjectW(None, None)
        if not handle:
            raise OSError('Cannot create training process containment.')
        self.handle = handle
        limits = ExtendedLimits()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError('Cannot configure training process containment.')
            if not self.kernel.AssignProcessToJobObject(handle, wintypes.HANDLE(int(process._handle))):
                raise OSError('Cannot contain training process; training refused.')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            self.kernel.CloseHandle(handle)
