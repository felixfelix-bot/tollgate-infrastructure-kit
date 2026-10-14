#!/usr/bin/env python3
"""Unit tests for templates/ssh-config-fips.conf — FIPS ProxyJump SSH template.

Validates the operator-facing SSH config fragment that reaches home FIPS
nodes by jumping through VPS2 (23.182.128.51). Uses `ssh -G` (the real
OpenSSH parser) so a passing suite proves the file parses, not just that
strings exist. No network connections are made: `ssh -G` only prints the
resolved configuration.

Ground truth for mesh addresses (verified 2026-10-14 from the live FIPS
DNS resolver `dig AAAA <name>.fips @::1 -p 5354` on CobradorWave, and
cross-checked against the deterministic npub->fd00:: derivation):
  dq05     fdb0:bf34:d648:96ac:f65a:3fd6:358:710b  (npub1ggl...v86t)
  t470     fd97:77d4:cd27:a6ae:1b29:e92e:fd96:dee8  (npub1eak...kac72)
  t14gen5  fd79:f451:67b1:8084:2b2a:5b1e:9110:26d0  (npub1srs...ufhh)
NOTE: dq05 and t470 are SEPARATE machines (the 2026-08 docs claiming they
share one mesh address are stale — dq05 got its own FIPS identity later).

Run:
    python3 -m unittest tests.test_ssh_fips_config -v
"""

import os
import re
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO_ROOT, "templates", "ssh-config-fips.conf")

VPS2_PUBLIC = "23.182.128.51"
DQ05_MESH = "fdb0:bf34:d648:96ac:f65a:3fd6:358:710b"
T470_MESH = "fd97:77d4:cd27:a6ae:1b29:e92e:fd96:dee8"
T14GEN5_MESH = "fd79:f451:67b1:8084:2b2a:5b1e:9110:26d0"


def ssh_g(alias):
    """Return dict of resolved options for `alias` via the real ssh parser."""
    proc = subprocess.run(
        ["ssh", "-G", "-F", CONF, alias],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"ssh -G failed for {alias} (config does not parse): {proc.stderr.strip()}"
        )
    opts = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(" ")
        opts.setdefault(key.lower(), value.strip())
    return opts


class TestParses(unittest.TestCase):
    """Acceptance: `ssh -G` must parse every alias without error."""

    def test_all_aliases_parse(self):
        for alias in ("vps2", "dq05.fips", "t470.fips", "t14gen5.fips", "futurenode.fips"):
            with self.subTest(alias=alias):
                ssh_g(alias)


class TestJumpHost(unittest.TestCase):
    def test_vps2_block(self):
        opts = ssh_g("vps2")
        self.assertEqual(opts["hostname"], VPS2_PUBLIC)
        self.assertEqual(opts["user"], "root")
        self.assertEqual(opts["serveraliveinterval"], "30")
        self.assertEqual(opts["serveralivecountmax"], "3")


class TestNodeBlocks(unittest.TestCase):
    def test_dq05_address(self):
        opts = ssh_g("dq05.fips")
        self.assertEqual(opts["hostname"], DQ05_MESH)
        self.assertEqual(opts["proxyjump"], "vps2")

    def test_t470_address(self):
        opts = ssh_g("t470.fips")
        self.assertEqual(opts["hostname"], T470_MESH)
        self.assertEqual(opts["proxyjump"], "vps2")

    def test_t14gen5_address(self):
        opts = ssh_g("t14gen5.fips")
        self.assertEqual(opts["hostname"], T14GEN5_MESH)
        self.assertEqual(opts["proxyjump"], "vps2")

    def test_dq05_and_t470_are_distinct_machines(self):
        self.assertNotEqual(ssh_g("dq05.fips")["hostname"], ssh_g("t470.fips")["hostname"])

    def test_nodes_use_operator_user_not_root(self):
        for alias in ("dq05.fips", "t470.fips", "t14gen5.fips"):
            with self.subTest(alias=alias):
                self.assertEqual(ssh_g(alias)["user"], "c03rad0r")

    def test_nodes_use_ed25519_key(self):
        for alias in ("dq05.fips", "t470.fips", "t14gen5.fips"):
            with self.subTest(alias=alias):
                self.assertEqual(ssh_g(alias)["identityfile"], "~/.ssh/id_ed25519")

    def test_node_keepalives(self):
        for alias in ("dq05.fips", "t470.fips", "t14gen5.fips"):
            with self.subTest(alias=alias):
                opts = ssh_g(alias)
                self.assertEqual(opts["serveraliveinterval"], "30")
                self.assertEqual(opts["serveralivecountmax"], "3")
                self.assertEqual(opts["connecttimeout"], "30")


class TestWildcardDefaults(unittest.TestCase):
    """`Host *.fips` defaults must reach nodes the file never names."""

    def test_future_node_inherits_defaults(self):
        opts = ssh_g("futurenode.fips")
        self.assertEqual(opts["proxyjump"], "vps2")
        self.assertEqual(opts["user"], "c03rad0r")
        self.assertEqual(opts["identityfile"], "~/.ssh/id_ed25519")
        self.assertEqual(opts["connecttimeout"], "30")
        self.assertEqual(opts["serveraliveinterval"], "30")
        self.assertEqual(opts["serveralivecountmax"], "3")

    def test_specific_blocks_override_wildcard(self):
        self.assertEqual(ssh_g("dq05.fips")["hostname"], DQ05_MESH)

    def test_future_node_can_override_wildcard_defaults(self):
        """Regression (cold-review major): ssh_config first-obtained-value
        semantics mean the `Host *.fips` block must come AFTER all specific
        blocks, or a future node could never override User/IdentityFile/
        ProxyJump. Simulates extending the template with a divergent node."""
        with open(CONF) as f:
            text = f.read()
        # Insert per the template's documented extension method: ABOVE the
        # `Host *.fips` wildcard (ssh_config first-obtained-value semantics).
        wildcard_pos = text.index("Host *.fips")
        extended = (
            text[:wildcard_pos]
            + "# appended by test: future node with divergent settings\n"
            "Host divergent.fips\n"
            "    HostName fd00::dead:beef\n"
            "    User root\n"
            "    IdentityFile ~/.ssh/id_rsa_special\n"
            "    ProxyJump otherjump\n\n"
            + text[wildcard_pos:]
        )
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as tmp:
            tmp.write(extended)
            path = tmp.name
        try:
            proc = subprocess.run(
                ["ssh", "-G", "-F", path, "divergent.fips"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            opts = {}
            for line in proc.stdout.splitlines():
                key, _, value = line.partition(" ")
                opts.setdefault(key.lower(), value.strip())
            self.assertEqual(opts["user"], "root")
            self.assertEqual(opts["identityfile"], "~/.ssh/id_rsa_special")
            self.assertEqual(opts["proxyjump"], "otherjump")
            self.assertEqual(opts["hostname"], "fd00::dead:beef")
        finally:
            os.unlink(path)

    def test_wildcard_block_is_last(self):
        """Structural guard: every specific Host block must precede `Host *.fips`
        so it can never shadow future node overrides (first-obtained-value)."""
        with open(CONF) as f:
            lines = f.readlines()
        host_lines = [
            (i, l.strip()) for i, l in enumerate(lines)
            if l.strip().lower().startswith("host ")
        ]
        wildcard_idx = [i for i, l in host_lines if l.split()[1] == "*.fips"]
        self.assertEqual(len(wildcard_idx), 1, "exactly one wildcard block expected")
        for i, l in host_lines:
            if i != wildcard_idx[0]:
                self.assertLess(
                    i, wildcard_idx[0],
                    f"specific block {l!r} must precede the *.fips wildcard",
                )


class TestNoSecrets(unittest.TestCase):
    """Acceptance: key-based auth only; no passwords/keys/tokens embedded."""

    SECRET_PATTERNS = [
        r"(?i)password",
        r"BEGIN [A-Z ]*PRIVATE KEY",
        r"(?i)token",
        r"(?i)nsec1[a-z0-9]{20,}",
        r"(?i)authorization",
    ]

    def test_no_secret_material(self):
        with open(CONF) as f:
            text = f.read()
        for pat in self.SECRET_PATTERNS:
            self.assertIsNone(
                re.search(pat, text), f"secret-like pattern {pat!r} found in template"
            )

    def test_no_todo_placeholders_left(self):
        with open(CONF) as f:
            self.assertIsNone(re.search(r"TODO:", f.read()), "unresolved TODO placeholder")


if __name__ == "__main__":
    unittest.main()
