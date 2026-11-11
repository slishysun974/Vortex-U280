"""Package/lineage rejection tests; no Vivado or FPGA acceptance is simulated."""
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment/u280-fpga"))
sys.path.insert(0, str(ROOT / "scripts"))
from build_prepared import digest, validate_input, validate_xo, prepare_flow
from u280_remote_xo import unpack_archive


class PreparedBuildTests(unittest.TestCase):
    def setUp(self):
        if not (ROOT / "results/ab-d8-u280-source-20261109-v1/package").is_dir():
            self.skipTest("Archived D8 RTL input package is required")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        shutil.copytree(ROOT / "results/ab-d8-u280-source-20261109-v1/package", self.package)

    def change_manifest(self, change):
        path = self.package / "manifest.json"
        manifest = json.loads(path.read_text())
        change(manifest)
        path.write_text(json.dumps(manifest))

    def test_d8_input_accepted(self):
        cfg, identity = validate_input(self.package)
        self.assertEqual(identity["input_files"], 288)
        self.assertEqual(cfg["defines"]["VX_CFG_NUM_WARPS"], 8)

    def test_extra_file_rejected(self):
        (self.package / "src/untracked.sv").write_text("module untracked; endmodule")
        with self.assertRaisesRegex(ValueError, "inventory"):
            validate_input(self.package)

    def test_omitted_source_rejected(self):
        self.change_manifest(lambda m: m.remove(next(x for x in m if x["path"].startswith("src/"))))
        with self.assertRaisesRegex(ValueError, "inventory"):
            validate_input(self.package)

    def test_corrupt_source_rejected(self):
        path = self.package / "src/vortex_afu.v"
        path.write_bytes(path.read_bytes() + b"\n// changed\n")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            validate_input(self.package)

    def test_duplicate_and_traversal_rejected(self):
        path = self.package / "manifest.json"
        original = path.read_text()
        for name in ("fpga.json", "../outside", "/absolute", "src/../fpga.json", "C:/file"):
            with self.subTest(name=name):
                manifest = json.loads(original)
                manifest.append(dict(path=name, sha256="0" * 64, bytes=0))
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "unsafe/duplicate"):
                    validate_input(self.package)

    def test_xo_requires_complete_input_identity_and_artifact(self):
        identity = validate_input(self.package)[1]
        prior = self.root / "prior"
        (prior / "out").mkdir(parents=True)
        xo = prior / "out/vortex_afu.xo"
        xo.write_bytes(b"test-only artifact, never a hardware result")
        record = dict(identity, status="PASS", exit_code=0, stage="xo",
                      artifact=dict(path="out/vortex_afu.xo", bytes=xo.stat().st_size, sha256=digest(xo)))
        (prior / "result.json").write_text(json.dumps(record))
        self.assertEqual(validate_xo(prior, identity), xo)
        wrong = dict(identity, input_manifest_sha256="different input, same lock")
        with self.assertRaisesRegex(ValueError, "complete input"):
            validate_xo(prior, wrong)
        xo.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "artifact identity"):
            validate_xo(prior, identity)

    def test_archive_rejects_escape_link_and_duplicate(self):
        for kind in ("escape", "symlink", "duplicate"):
            with self.subTest(kind=kind):
                archive = self.root / (kind + ".tar.gz")
                with tarfile.open(archive, "w:gz") as tar:
                    member = tarfile.TarInfo("../escape" if kind == "escape" else "u280-rtl-input/a")
                    if kind == "symlink":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "/tmp/other"
                    tar.addfile(member, io.BytesIO(b""))
                    if kind == "duplicate":
                        tar.addfile(member, io.BytesIO(b""))
                with self.assertRaisesRegex(ValueError, "unsafe/duplicate"):
                    unpack_archive(archive, self.root / kind)
                self.assertFalse((self.root / kind).exists())

    def test_actual_archive_roundtrip(self):
        out = self.root / "extracted"
        unpack_archive(ROOT / "results/ab-d8-u280-source-20261109-v1/u280-rtl-input.tar.gz", out)
        self.assertEqual(validate_input(out / "u280-rtl-input")[1], validate_input(self.package)[1])

    def test_build_patch_is_separate_and_keeps_interface_gate(self):
        original = validate_input(self.package)[1]
        work = self.root / "work"
        work.mkdir()
        flow, identity = prepare_flow(self.package, work, "ip-ooc-v1")
        self.assertEqual(validate_input(self.package)[1], original)
        patch = json.loads((work / "flow_patch.json").read_text())
        self.assertEqual(len(patch["patches"]), 4)
        self.assertEqual(identity["flow_sha256"], digest(work / "flow_patch.json"))
        self.assertEqual(digest(flow / "scripts/xilinx_interface_check.tcl"),
                         digest(self.package / "scripts/xilinx_interface_check.tcl"))
        gate = (flow / "scripts/xilinx_elab_check.tcl").read_text(encoding="utf-8")
        self.assertIn('set mic_mode "error"', gate)
        self.assertIn("synth_design -rtl -flatten_hierarchy none", gate)
        second = self.root / "second"
        second.mkdir()
        self.assertEqual(prepare_flow(self.package, second, "ip-ooc-v1")[1], identity)


if __name__ == "__main__":
    unittest.main()
