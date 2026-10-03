# -*- coding: utf-8 -*-
"""确保 ``app`` 包可被导入（pytest 从项目根运行时）。"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
