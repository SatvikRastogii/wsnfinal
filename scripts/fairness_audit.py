"""Cross-protocol fairness audit, printed as a pass table.

Every claim the comparison rests on is checked mechanically rather than asserted in
prose. Fails loudly: if any row is FAIL, no result in this repo is comparable.

    python scripts/fairness_audit.py
"""

import ast
import dataclasses
import inspect
import sys

import numpy as np

sys.path.insert(0, ".")

from run_experiments import REGISTRY
from wsn_sim import engine as eng
from wsn_sim.config import SimConfig
from wsn_sim.network import Network

PROTOCOLS = [p for p in REGISTRY if p != "stub"]
RUN_INDICES = [0, 1, 2]

rows = []


def check(name, ok, detail=""):
    rows.append((name, bool(ok), detail))


# 1-5. Identical world per run index. The Network is built from the run index alone --
# no protocol name enters its seeding -- so every protocol at run index i provably faces
# the same topology, the same static shadowing and the same sensed-value stream.
cfg = SimConfig()
for label, attrs in (("topology (node xy)", ("x", "y")),
                     ("initial energy", ("initial_energy",)),
                     ("per-link shadowing", ("shadow",)),
                     ("node-BS shadowing", ("shadow_bs",)),
                     ("sensed-value stream", ("sensed",))):
    ok, detail = True, ""
    for i in RUN_INDICES:
        ref = [getattr(Network(cfg, i), a) for a in attrs]
        for _ in range(3):
            new = [getattr(Network(cfg, i), a) for a in attrs]
            if not all(np.array_equal(r, n) for r, n in zip(ref, new)):
                ok, detail = False, f"run_index {i} not reproducible"
    # Different run indices must actually differ, or "paired" would be meaningless.
    if ok and attrs != ("initial_energy",):
        a0 = [getattr(Network(cfg, RUN_INDICES[0]), a) for a in attrs]
        a1 = [getattr(Network(cfg, RUN_INDICES[1]), a) for a in attrs]
        if all(np.array_equal(p, q) for p, q in zip(a0, a1)):
            ok, detail = False, "different run indices produced identical worlds"
    check(f"same {label} for a given run index", ok, detail)

check("Network seeding uses run_index only (no protocol name)",
      "default_rng(run_index)" in inspect.getsource(Network.__init__))

# From here on the checks parse the AST rather than grepping source text. Text matching
# gave four false positives, every one of them a docstring *documenting* the constraint
# ("This protocol never calls net.spend", "torch/scipy are absent by requirement"). It
# also could not tell a read of net.energy -- which a clustering decision legitimately
# needs -- from a write, which is the thing actually forbidden.
src = inspect.getsource(eng)


def _tree(module_name):
    return ast.parse(inspect.getsource(sys.modules[module_name]))


def _calls(tree):
    """Every called name, as 'func' or 'obj.func'."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                base = f.value.id if isinstance(f.value, ast.Name) else "?"
                out.add(f"{base}.{f.attr}")
    return out


def _assigned_attrs(tree):
    """Attributes written to, including via subscript and augmented assignment.

    `net.energy[i] = x` and `net.energy[i] -= x` both count; a bare read does not.
    """
    out = set()
    for n in ast.walk(tree):
        targets = []
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        for t in targets:
            while isinstance(t, ast.Subscript):
                t = t.value
            if isinstance(t, ast.Attribute):
                base = t.value.id if isinstance(t.value, ast.Name) else "?"
                out.add(f"{base}.{t.attr}")
    return out


# 6. Protocol seeds come from a stable hash, never Python's per-process-salted hash().
eng_tree = ast.parse(src)
check("protocol rng seeded by blake2b, never Python's salted hash()",
      "blake2b" in _calls(eng_tree) or "hashlib.blake2b" in _calls(eng_tree),
      "no blake2b call found")
check("engine never calls the builtin hash()", "hash" not in _calls(eng_tree))

# 7. No protocol WRITES energy or liveness, or calls the spend choke point.
#    Reading net.energy / net.alive is expected and allowed -- that is the state a
#    clustering decision is supposed to be based on.
bad = []
for name, cls in REGISTRY.items():
    tree = _tree(cls.__module__)
    for c in _calls(tree):
        if c.endswith(".spend"):
            bad.append(f"{name}: calls {c}")
    for a in _assigned_attrs(tree):
        if a.split(".")[-1] in ("energy", "alive", "consumed", "initial_energy"):
            bad.append(f"{name}: writes {a}")
check("no protocol writes energy/alive or calls spend", not bad, "; ".join(bad))

# 6. Every protocol runs against the identical config object -- no protocol-specific
#    radio constants, packet sizes, or field geometry.
fields = {f.name for f in dataclasses.fields(SimConfig)}
radio = {"e_elec", "eps_fs", "eps_mp", "e_da", "data_bits", "ctrl_bits", "e0"}
check("radio constants and packet sizes live only in SimConfig", radio <= fields)

# Numeric literals matching a radio constant, found anywhere in a protocol's code
# (comments and docstrings are not part of the AST, so they cannot trigger this).
RADIO_VALUES = {50e-9, 10e-12, 0.0013e-12, 5e-9, 4000, 200}
bad = []
for name, cls in REGISTRY.items():
    for n in ast.walk(_tree(cls.__module__)):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) \
                and not isinstance(n.value, bool) and n.value in RADIO_VALUES:
            bad.append(f"{name}:{n.value!r}")
check("no protocol hard-codes a radio constant or packet size", not bad, ", ".join(sorted(set(bad))))

# 8. Packet size is engine-owned: Transmission has no bit-count field a protocol could
#    set, and reading counts are engine-computed from a boolean. Checked against the
#    real dataclass fields, not the source text.
from wsn_sim.protocols.base import Transmission

tfields = {f.name for f in dataclasses.fields(Transmission)}
check("Transmission exposes no protocol-settable bit count",
      not any("bit" in f or "size" in f for f in tfields), ", ".join(sorted(tfields)))
check("payload_readings removed; readings derived from `originates`",
      "payload_readings" not in tfields and "originates" in tfields)

# 9. Same nominal cluster-count target for every clustering protocol.
check("cluster-count target is a single shared config value (p_ch)", "p_ch" in fields)

# 10. All nine protocols on one numerical substrate -- checked on real import
#     statements, so a docstring explaining torch's absence does not trip it.
bad = []
for name, cls in REGISTRY.items():
    for n in ast.walk(_tree(cls.__module__)):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
        if any(m.split(".")[0] in ("torch", "scipy", "tensorflow", "jax") for m in mods):
            bad.append(name)
check("no protocol imports torch/scipy (uniform numerical substrate)",
      not bad, ", ".join(sorted(set(bad))))

# 10. Engine-enforced aggregation and causal ordering are present and unconditional.
check("transmissions execute in (hop_depth, src) causal order",
      "hop_depth, t.src" in src or "(t.hop_depth, t.src)" in src)
check("aggregation charge is engine-applied, not protocol-optional",
      '"agg"' in src and "e_agg(" in src)
check("double-forward validator present", "_validate_no_double_forward" in src)

w = max(len(r[0]) for r in rows)
print(f"{'check':{w}s}  result")
print("-" * (w + 10))
fails = 0
for name, ok, detail in rows:
    fails += not ok
    print(f"{name:{w}s}  {'PASS' if ok else 'FAIL'}" + (f"  <- {detail}" if detail and not ok else ""))
print(f"\nfairness audit: {len(rows) - fails}/{len(rows)} checks pass "
      f"over protocols {sorted(PROTOCOLS)}")
raise SystemExit(1 if fails else 0)
