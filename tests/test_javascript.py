"""Check browser script syntax with macOS's native JavaScriptCore (no Node)."""
import ctypes
import sys
import unittest
from pathlib import Path

@unittest.skipUnless(sys.platform=='darwin','JavaScriptCore is macOS-specific')
class JavaScriptTests(unittest.TestCase):
 def test_native_browser_javascript_syntax(self):
  lib=ctypes.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')
  pointer=ctypes.c_void_p
  lib.JSGlobalContextCreate.argtypes=[pointer];lib.JSGlobalContextCreate.restype=pointer
  lib.JSStringCreateWithUTF8CString.argtypes=[ctypes.c_char_p];lib.JSStringCreateWithUTF8CString.restype=pointer
  lib.JSCheckScriptSyntax.argtypes=[pointer,pointer,pointer,ctypes.c_int,ctypes.POINTER(pointer)];lib.JSCheckScriptSyntax.restype=ctypes.c_bool
  lib.JSStringRelease.argtypes=[pointer];lib.JSGlobalContextRelease.argtypes=[pointer]
  context=lib.JSGlobalContextCreate(None)
  try:
   for file in (Path(__file__).resolve().parent.parent/'app/static').glob('*.js'):
    script=lib.JSStringCreateWithUTF8CString(file.read_bytes());exception=pointer()
    try:self.assertTrue(lib.JSCheckScriptSyntax(context,script,None,1,ctypes.byref(exception)),str(file))
    finally:lib.JSStringRelease(script)
  finally:lib.JSGlobalContextRelease(context)
