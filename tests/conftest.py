# -*- coding: utf-8 -*-
"""pytest 公共夹具：把 backend 加进 sys.path，并强制离线演示模式。

离线模式（DEMO_MODE=offline）不需要任何密钥即可跑通全部用例 —— 这是评审拿到仓库后的真实起点。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ["DEMO_MODE"] = "offline"
os.environ.setdefault("KB_PATH", str(ROOT / "kb"))
