# Startet screenshot_tool.py ohne CMD-Fenster (Windows pythonw.exe)
# Einfach per Doppelklick starten!
import runpy, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
runpy.run_module('screenshot_tool', run_name='__main__', alter_sys=True)
