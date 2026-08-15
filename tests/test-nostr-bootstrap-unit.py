import os, subprocess, tempfile, pathlib, sys, shutil

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = str(REPO / "hermes-docker" / "cont-init.d" / "03-nostr-bootstrap")
PY = shutil.which("python3")
fails = []

def run(env_over, home):
    e = dict(os.environ)
    e["HERMES_HOME"] = home
    e["NOSTR_RELAYS"] = "ws://r1.example,wss://r2.example"
    e["NOSTR_GROUPS"] = "g1,g2"
    e["NOSTR_NSEC_PATH"] = "/nsec/nsec.txt"
    e.pop("NOSTR_BOOTSTRAP", None)
    e.update(env_over)
    return subprocess.run([PY, SCRIPT], env=e, capture_output=True, text=True)

def case(name, fn):
    try:
        fn()
        print(f"PASS {name}")
    except AssertionError as ex:
        fails.append(name)
        print(f"FAIL {name}: {ex}")

def t_fresh_render():
    with tempfile.TemporaryDirectory() as home:
        r = run({}, home)
        assert r.returncode == 0, r.stderr
        cfg = pathlib.Path(home, "config.yaml").read_text()
        assert "nostr:" in cfg and "- ws://r1.example" in cfg and "- g2" in cfg, cfg
        assert "platforms:" in cfg and "  nostr:" in cfg and "  api_server:" in cfg, cfg
        assert "nsec_path: /nsec/nsec.txt" in cfg, cfg
        assert oct(pathlib.Path(home, "config.yaml").stat().st_mode & 0o777) == "0o640"
        assert pathlib.Path(home, ".hermes").is_dir()

def t_idempotent():
    with tempfile.TemporaryDirectory() as home:
        run({}, home)
        p = pathlib.Path(home, "config.yaml")
        first = p.read_text()
        mtime1 = p.stat().st_mtime_ns
        r = run({}, home)
        assert r.returncode == 0, r.stderr
        assert "never clobber" in r.stdout, r.stdout
        assert p.read_text() == first
        assert p.stat().st_mtime_ns == mtime1, "file rewritten on second run"

def t_no_clobber_existing_nostr():
    with tempfile.TemporaryDirectory() as home:
        p = pathlib.Path(home, "config.yaml")
        p.write_text("model: gpt-x\nnostr:\n  relays:\n  - ws://custom\nplatforms:\n  nostr:\n    enabled: true\n")
        r = run({}, home)
        assert r.returncode == 0
        assert "never clobber" in r.stdout
        assert "ws://custom" in p.read_text()

def t_merge_into_existing_no_platforms():
    with tempfile.TemporaryDirectory() as home:
        p = pathlib.Path(home, "config.yaml")
        p.write_text("model: gpt-x\nagent:\n  x: 1\n")
        r = run({}, home)
        assert r.returncode == 0, r.stderr
        cfg = p.read_text()
        lines = cfg.splitlines()
        assert "nostr:" in lines and "platforms:" in lines, cfg
        assert lines[lines.index("platforms:") + 1] == "  nostr:", cfg
        assert lines[lines.index("platforms:") + 3] == "  api_server:", cfg
        assert "model: gpt-x" in lines

def t_merge_platforms_midfile():
    with tempfile.TemporaryDirectory() as home:
        p = pathlib.Path(home, "config.yaml")
        p.write_text("agent:\n  a: 1\nplatforms:\n  telegram:\n    enabled: false\nsecurity:\n  s: 1\n")
        r = run({}, home)
        assert r.returncode == 0, r.stderr
        cfg = p.read_text()
        lines = cfg.splitlines()
        pi = lines.index("platforms:")
        si = lines.index("security:")
        assert lines[pi + 1] == "  telegram:", cfg
        assert "  nostr:" in lines[pi:si] and "    enabled: true" in lines[pi:si], cfg
        assert lines.index("  nostr:", pi) < lines.index("  api_server:", pi), cfg
        assert lines[si - 1] == "    enabled: true", cfg

def t_no_relays_no_write():
    with tempfile.TemporaryDirectory() as home:
        r = run({"NOSTR_RELAYS": ""}, home)
        assert r.returncode == 0, r.stderr
        assert not os.path.exists(os.path.join(home, "config.yaml"))
        assert "nothing to bootstrap" in r.stdout, r.stdout

def t_existing_no_nostr_no_relays_untouched():
    with tempfile.TemporaryDirectory() as home:
        p = pathlib.Path(home, "config.yaml")
        p.write_text("model: gpt-x\n")
        r = run({"NOSTR_RELAYS": ""}, home)
        assert r.returncode == 0, r.stderr
        assert p.read_text() == "model: gpt-x\n"
        assert "leaving untouched" in r.stdout, r.stdout

def t_disabled():
    with tempfile.TemporaryDirectory() as home:
        r = run({"NOSTR_BOOTSTRAP": "0"}, home)
        assert r.returncode == 0
        assert not os.path.exists(os.path.join(home, "config.yaml"))

case("fresh_render", t_fresh_render)
case("idempotent", t_idempotent)
case("no_clobber_existing_nostr", t_no_clobber_existing_nostr)
case("merge_into_existing_no_platforms", t_merge_into_existing_no_platforms)
case("merge_platforms_midfile", t_merge_platforms_midfile)
case("no_relays_no_write", t_no_relays_no_write)
case("existing_no_nostr_no_relays_untouched", t_existing_no_nostr_no_relays_untouched)
case("disabled", t_disabled)
sys.exit(1 if fails else 0)
