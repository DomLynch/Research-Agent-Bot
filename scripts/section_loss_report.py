#!/usr/bin/env python3
"""Compare per-section word counts as BUILT vs as RENDERED, per run.

Reads manifest.json section_words (written at render time) against the
section body in full_paper.md, for the SAME run. Comparing across runs or
against already-finalized files produced four wrong conclusions on
2026-08-08; this pins both numbers to one run id.

Measured over 735 completed runs: rendered normally EXCEEDS built (median
+52, the finalizer adds deterministic content). The failure mode is bimodal --
64/735 runs render the section as 0 words, i.e. the section is absent despite
being built. That total loss, not gradual erosion, is what fails the surface
gate. Read-only.
"""
import glob
import json
import os
import re
rows=[]
for man in glob.glob("runs/synthesis-*/manifest.json"):
    d=os.path.dirname(man); paper=os.path.join(d,"full_paper.md")
    if not os.path.exists(paper): continue
    try: sw=(json.load(open(man)) or {}).get("section_words") or {}
    except Exception: continue
    b=sw.get("cross_domain_synthesis")
    if not b: continue
    t=open(paper,errors="replace").read()
    m=re.search(r"^##\s+Cross-Domain Synthesis\b.*?\n(.*?)(?=^##\s+|\Z)", t, re.M|re.S)
    r=len(re.findall(r"\b\w+\b", m.group(1))) if m else 0
    rows.append((b-r, b, r, os.path.basename(d)[:44]))
rows.sort(reverse=True)
print(f"completed runs with both artifacts: {len(rows)}")
if rows:
    losses=[x[0] for x in rows]
    pos=[l for l in losses if l>0]
    print(f"  runs where rendered < built: {len(pos)}/{len(rows)}")
    print(f"  median loss: {sorted(losses)[len(losses)//2]}")
    print("  largest losses:")
    for l,b,r,n in rows[:4]: print(f"    -{l:<5} built={b:<5} rendered={r:<5} {n}")
    print("  smallest:")
    for l,b,r,n in rows[-3:]: print(f"    {-l:<6} built={b:<5} rendered={r:<5} {n}")
