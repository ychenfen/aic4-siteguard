"""把回放数据和规则内联进 demo/template.html，生成可直接双击打开的 demo/index.html。"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tpl = (root / "demo" / "template.html").read_text(encoding="utf-8")
data = json.loads((root / "samples" / "site_demo.json").read_text(encoding="utf-8"))
rules = json.loads((root / "siteguard" / "rules.json").read_text(encoding="utf-8"))
html = tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False)) \
          .replace("/*RULES*/null", json.dumps(rules, ensure_ascii=False))
(root / "demo" / "index.html").write_text(html, encoding="utf-8")
print("wrote demo/index.html")
