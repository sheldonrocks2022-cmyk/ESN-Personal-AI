"""Step 58: customer-first RAM scheduling without overcommitting the Wings host."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import customer_capacity as cap
from scripts import jarvis_power as power

UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class FakePanel:
    def __init__(self):
        self.id = 3
        self.uuid = UUID
        self.memory = 12288
        self.allocated = 8500
        self.overallocate = 0
        self.patches = []
        self.list_calls = 0

    def _item(self):
        return {"object": "node", "attributes": {
            "id": self.id, "uuid": self.uuid, "memory": self.memory,
            "memory_overallocate": self.overallocate,
            "allocated_resources": {"memory": self.allocated, "disk": 0},
            "name": "ESN Node 3", "fqdn": "node3.esnoffical.com",
        }}

    def api(self, path, *, memory=None):
        if path.startswith("/api/application/nodes?"):
            self.list_calls += 1
            return {"data": [self._item()],
                    "meta": {"pagination": {"total_pages": 1}}}
        if path == "/api/application/nodes/3":
            if memory is not None:
                self.patches.append(memory)
                self.memory = memory
            return self._item()
        raise AssertionError("Unexpected Pterodactyl API call " + path)


class FakeSystemd:
    def __init__(self):
        self.calls = []
        self.state = {
            key: {"enabled": "enabled", "active": "active", "slice": power.JARVIS_SLICE}
            for key in power.SHUTDOWN_ORDER
        }

    def run(self, *args):
        self.calls.append(tuple(args))
        op = args[0]
        if op == "show":
            val = ("loaded" if "--property=LoadState" in args
                   else self.state[args[1]]["slice"])
            return subprocess.CompletedProcess(args, 0, val+"\n", "")
        if op == "is-enabled":
            val = self.state[args[1]]["enabled"]
            return subprocess.CompletedProcess(args, 0 if val=="enabled" else 1, val+"\n", "")
        if op == "is-active":
            val = self.state[args[1]]["active"]
            return subprocess.CompletedProcess(args, 0 if val=="active" else 3, val+"\n", "")
        if op in ("enable", "disable"):
            unit=args[-1]
            self.state[unit]["enabled"]="enabled" if op=="enable" else "disabled"
            if "--now" in args:
                self.state[unit]["active"]="inactive"
            return subprocess.CompletedProcess(args,0,"","")
        if op=="start":
            self.state[args[-1]]["active"]="active"
            return subprocess.CompletedProcess(args,0,"","")
        raise AssertionError("Unexpected systemctl operation " + str(args))


class CustomerCapacityTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        self.panel = FakePanel()
        self.wings = root/"wings.yml"
        self.wings.write_text("debug: false\nuuid: "+UUID+"\ntoken: REDACTED\n")
        self.env = root/"esn-jarvis.env"
        self.env.write_text("PTERO_BASE_URL=https://panel.esnoffical.com\nPTERO_API_KEY=FAKE_TOKEN_ONLY_FOR_TESTING\n")
        self.env.chmod(0o600)
        self.conf = root/"customer.json"
        self.fake = FakeSystemd()
        specs = [
            patch.object(cap,"WINGS_PATH",self.wings),
            patch.object(cap,"ENV_PATH",self.env),
            patch.object(cap,"CONFIG_PATH",self.conf),
            patch.object(cap,"_api",side_effect=self.panel.api),
            patch.object(cap,"_total_mib",return_value=24576),
            patch.object(cap,"_available_mib",return_value=20000),
            patch.object(power,"STATE_DIR",root),
            patch.object(power,"STATE_FILE",root/"power.json"),
            patch.object(power,"LOCK_FILE",root/"power.lock"),
            patch.object(power,"_reported_resources"),
            patch.object(power,"systemctl",side_effect=self.fake.run),
        ]
        for p in specs:
            p.start()
            self.addCleanup(p.stop)
        power.prepare_dir()

    def test_readonly_safety_planner_handles_massively_oversized_node(self):
        self.panel.id = 3
        self.panel.memory = 4294967295
        self.panel.allocated = 9216
        with patch.object(cap, "_total_mib", return_value=24032):
            proposal = cap.print_safe_plan()
        self.assertEqual(proposal["suggested_on_mib"], 11264)
        self.assertEqual(proposal["suggested_off_mib"], 19456)
        self.assertEqual(proposal["remaining_host_off_mib"], 4576)
        self.assertEqual(proposal["extra_customer_off_mib"], 8192)
        self.assertTrue(proposal["current_node_is_oversized"])
        self.assertEqual(self.panel.patches, [])
        self.assertFalse(self.conf.exists())

    def test_planner_refuses_to_reduce_below_existing_customer_allocations(self):
        self.panel.memory = 4294967295
        self.panel.allocated = 12000
        with patch.object(cap, "_total_mib", return_value=24032):
            with self.assertRaisesRegex(RuntimeError, "do not reduce|Do not reduce"):
                cap.plan_safe_limits()
        self.assertEqual(self.panel.patches, [])

    def test_planner_refuses_memory_overallocation(self):
        self.panel.overallocate = 10
        with self.assertRaisesRegex(RuntimeError, "overallocation"):
            cap.print_safe_plan()
        self.assertEqual(self.panel.patches, [])

    def test_readonly_check_and_enable_never_modify_panel(self):
        plan = cap.check()
        self.assertEqual(plan["extra_mib"],8192)
        self.assertEqual(plan["node_id"],3)
        self.assertEqual(plan["base_mib"],12288)
        self.assertEqual(plan["target_mib"],20480)
        self.assertEqual(self.panel.patches,[])
        cap.enable()
        self.assertEqual(self.panel.patches,[])
        self.assertEqual(self.conf.stat().st_mode & 0o777,0o600)
        self.assertIsNotNone(cap.config())

    def test_off_boosts_verified_node_only_and_on_restores_before_services(self):
        cap.enable()
        power.off()
        self.assertEqual(self.panel.patches,[20480])
        self.assertEqual(self.panel.memory,20480)
        self.assertTrue(power.STATE_FILE.exists())
        self.assertTrue(all(v["active"]=="inactive" for v in self.fake.state.values()))
        self.assertFalse(any(any(x in str(call) for x in ("wings","docker","nginx","pteroq"))
                             for call in self.fake.calls))
        power.on()
        self.assertEqual(self.panel.patches,[20480,12288])
        self.assertEqual(self.panel.memory,12288)
        self.assertFalse(power.STATE_FILE.exists())
        self.assertTrue(all(v["active"]=="active" for v in self.fake.state.values()))
        cap.disable()
        self.assertIsNone(cap.config())

    def test_customer_allocations_over_baseline_block_restart(self):
        cap.enable()
        power.off()
        self.panel.allocated=13500
        prior=len(self.fake.calls)
        with self.assertRaisesRegex(RuntimeError,"Jarvis stays OFF"):
            power.on()
        self.assertTrue(power.STATE_FILE.exists())
        # Read-only unit checks are allowed; no actual service may restart.
        new_calls = self.fake.calls[prior:]
        self.assertFalse(any(x[0] in ("enable","start") for x in new_calls))
        self.assertEqual(self.panel.memory,20480)
        self.panel.allocated=9000
        power.on()
        self.assertEqual(self.panel.memory,12288)

    def test_actual_low_free_ram_blocks_restart(self):
        cap.enable()
        power.off()
        with patch.object(cap,"_available_mib",return_value=6000):
            with self.assertRaisesRegex(RuntimeError,"insufficient actual"):
                power.on()
        self.assertTrue(power.STATE_FILE.exists())
        self.assertEqual(self.panel.memory,20480)

    def test_off_dry_run_never_stops_services_or_mutates_panel(self):
        cap.enable()
        power.off(dry_run=True)
        self.assertFalse(power.STATE_FILE.exists())
        self.assertEqual(self.panel.patches,[])
        self.assertTrue(all(v["active"]=="active" for v in self.fake.state.values()))

    def test_no_local_wings_identity_refuses_customer_boost(self):
        self.wings.unlink()
        with self.assertRaisesRegex(RuntimeError,"missing or symlinked"):
            cap.enable()
        self.assertEqual(self.panel.patches,[])
        self.assertFalse(self.conf.exists())

    def test_panel_uuid_mismatch_refuses_any_transition(self):
        self.panel.uuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        with self.assertRaisesRegex(RuntimeError,"uniquely match"):
            cap.check()
        self.assertEqual(self.panel.patches,[])

    def test_overallocation_or_host_shortage_refuse(self):
        self.panel.overallocate=20
        with self.assertRaisesRegex(RuntimeError,"overallocation"):
            cap.enable()
        self.panel.overallocate=0
        with patch.object(cap,"_total_mib",return_value=19000):
            with self.assertRaisesRegex(RuntimeError,"Insufficient physical RAM"):
                cap.enable()
        self.assertEqual(self.panel.patches,[])

    def test_oversold_node_refused(self):
        self.panel.allocated=13000
        with self.assertRaisesRegex(RuntimeError,"already overallocated"):
            cap.enable()

    def test_external_panel_edit_blocks_restart_without_overwriting_it(self):
        cap.enable()
        power.off()
        self.panel.memory=18000
        with self.assertRaisesRegex(RuntimeError,"changed externally"):
            power.on()
        self.assertEqual(self.panel.memory,18000)
        self.assertTrue(power.STATE_FILE.exists())

    def test_rejected_boost_keeps_jarvis_online(self):
        cap.enable()
        self.panel.memory=13000
        with self.assertRaisesRegex(RuntimeError,"differs from expected baseline"):
            power.off()
        self.assertFalse(power.STATE_FILE.exists())
        self.assertTrue(all(v["active"]=="active" for v in self.fake.state.values()))

    def test_disable_is_blocked_when_jarvis_off(self):
        cap.enable()
        power.off()
        with self.assertRaisesRegex(RuntimeError,"Cannot disable"):
            cap.disable(power_off_record_exists=True)

    def test_config_and_env_permissions(self):
        cap.enable()
        self.conf.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,"0600"):
            cap.config()
        self.conf.chmod(0o600)
        self.env.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,"0600"):
            cap._env()

    def test_wrong_ptero_origin_rejected_without_secret_leak(self):
        self.env.write_text("PTERO_BASE_URL=https://malicious.example\nPTERO_API_KEY=VERY_PRIVATE_API_KEY\n")
        self.env.chmod(0o600)
        with self.assertRaises(RuntimeError) as context:
            cap._env()
        self.assertNotIn("VERY_PRIVATE_API_KEY",str(context.exception))


if __name__ == "__main__":
    unittest.main()
