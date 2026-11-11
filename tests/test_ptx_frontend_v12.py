"""Frontend author tests, not a frozen independent E acceptance suite."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ptx_frontend_v12 as ptx

HEADER = ".version 7.0\n.target sm_70\n.address_size 64\n"


def program(body, params=".param .u64 ptr, .param .u32 n", declarations=None):
    if declarations is None:
        declarations = ".reg .b32 %r<8>; .reg .b64 %a<4>; .reg .pred %p, %q;"
    return HEADER + ".visible .entry arbitrary(" + params + ") {\n" + declarations + "\n" + body + "\nret;\n}\n"


class FrontendTests(unittest.TestCase):
    def reject(self, source, code=None):
        with self.assertRaises(ptx.PtxError) as caught:
            ptx.parse(source, "bad.ptx")
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.location["file"], "bad.ptx")
        self.assertGreater(caught.exception.location["line"], 0)
        return caught.exception

    def test_three_parameterized_samples(self):
        expected = {"copy_u32": (24, [0, 8, 16]), "vadd_u32": (32, [0, 8, 16, 24]),
                    "affine_u32": (32, [0, 8, 16, 24, 28])}
        for name, (size, offsets) in expected.items():
            ir = ptx.parse((ptx.PROJECT / "ptx/samples" / (name + ".ptx")).read_text())
            self.assertEqual(ir["params_size"], size)
            self.assertEqual([p["offset"] for p in ir["params"]], offsets)

    def test_author_samples_cover_every_declared_instruction_form(self):
        observed = set()
        for path in (ptx.PROJECT / "ptx/samples").glob("*.ptx"):
            observed.update(ins["opcode"] for ins in ptx.parse(path.read_text())["instructions"])
        self.assertEqual(observed, set(ptx.OPS))

    def test_profile_metadata_matches_implementation(self):
        profile = json.loads((ptx.PROJECT / "configs/ptx_frontend/v1/profile.json").read_text())
        abi = json.loads((ptx.PROJECT / "configs/ptx_frontend/v1/abi.json").read_text())
        self.assertEqual(profile["profile"], ptx.PROFILE)
        self.assertEqual(set(profile["instruction_forms"]), set(ptx.OPS))
        self.assertEqual(abi["abi_version"], ptx.ABI)
        self.assertFalse(abi["loadable"])

    def test_wrong_target_rejected_before_artifacts_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            for lock in (dict(xlen=32, endianness="little"), dict(xlen=64, endianness="big"), []):
                target.write_text(json.dumps(lock))
                with self.assertRaises(ptx.PtxError) as caught:
                    ptx.compile_source(program(""), root / "out", target_lock=target)
                self.assertEqual(caught.exception.code, "E_TARGET_MISMATCH")
                self.assertFalse((root / "out").exists())

    def test_names_have_no_semantic_dispatch(self):
        source = (ptx.PROJECT / "ptx/samples/vadd_u32.ptx").read_text()
        a = ptx.parse(source)
        b = ptx.parse(source.replace("vadd_u32", "different_$entry").replace("%r", "$word").replace("%a", "%addr"))
        self.assertEqual(ptx.emit_cpp(a)[0], ptx.emit_cpp(b)[0])

    def test_comments_whitespace_and_source_coordinates(self):
        src = program("/* first\nsecond */\n  mov.u32 %r0, 7; // ignored")
        ir = ptx.parse(src, "comments.ptx")
        self.assertEqual(ir["instructions"][0]["source_location"], dict(file="comments.ptx", line=8, column=3))
        cpp, mapping = ptx.emit_cpp(ir)
        self.assertIn("v0 = UINT32_C(7);", cpp.splitlines()[mapping[0]["generated_line"] - 1])

    def test_named_registers_and_arrays(self):
        ir = ptx.parse(program("mov.u32 value, 1;", declarations=".reg .b32 value, %r<2>;"))
        self.assertEqual(set(ir["registers"]), {"value", "%r0", "%r1"})

    def test_integer_bases_sign_and_use_site_truncation(self):
        ir = ptx.parse(program("mov.u32 %r0, -1; mov.u32 %r1, 0x100000001U; mov.u32 %r2, 077; mov.u32 %r3, 0b101;"))
        self.assertEqual([i["operands"][1]["value"] for i in ir["instructions"][:-1]], [0xffffffff, 1, 63, 5])

    def test_integer_literal_out_of_range(self):
        self.reject(program("mov.u64 %a0, 18446744073709551616;"), "E_TYPE")

    def test_invalid_octal(self):
        self.reject(program("mov.u32 %r0, 09;"), "E_TYPE")

    def test_version_target_and_address_width(self):
        for before, after in (("7.0", "8.0"), ("sm_70", "sm_80"), (".address_size 64", ".address_size 32")):
            self.reject(program("").replace(before, after), "E_PTX_VERSION")

    def test_unknown_instruction_and_modifiers(self):
        for opcode in ("mad.wide.u32", "add.s32", "add.cc.u32", "and.b32", "shl.b32", "ld.global.ca.u32", "ld.volatile.global.u32"):
            self.reject(program(opcode + " %r0, %r1, 1;"), "E_UNSUPPORTED")

    def test_control_flow_barrier_fp_and_warp_rejection(self):
        for text in ("bra label;", "bar.sync 0;", "add.rn.f32 %r0, %r1, %r2;", "vote.ballot.b32 %r0, %p;", "label:"):
            self.reject(program(text), "E_UNSUPPORTED")

    def test_unknown_directive_not_silently_skipped(self):
        for directive in (".shared .b32 data;", ".pragma ignored;", ".loc 1 2 3;"):
            self.reject(program(directive))

    def test_duplicate_and_out_of_range_registers(self):
        self.reject(program("", declarations=".reg .b32 %r<2>, %r1;"), "E_TYPE")
        self.reject(program("mov.u32 %r8, 0;"), "E_TYPE")

    def test_array_size_limits(self):
        for n in (0, -1, 4097):
            self.reject(program("", declarations=f".reg .b32 %r<{n}>;"), "E_TYPE")

    def test_duplicate_parameter_and_symbol_collision(self):
        self.reject(program("", params=".param .u32 n, .param .u32 n"), "E_PARAM_LAYOUT")
        self.reject(program("", declarations=".reg .b32 n;"), "E_TYPE")

    def test_wrong_register_width(self):
        self.reject(program("mov.u32 %a0, 1;"), "E_TYPE")
        self.reject(program("mov.u64 %a0, 1; add.u32 %r0, %a0, 1;"), "E_TYPE")

    def test_uninitialized_read(self):
        self.reject(program("add.u32 %r0, %r1, 1;"), "E_TYPE")

    def test_guarded_definition_same_predicate_allowed(self):
        ptx.parse(program("setp.eq.u32 %p, 1, 1; @%p mov.u32 %r0, 4; @%p add.u32 %r1, %r0, 2;"))

    def test_guarded_definition_cannot_escape(self):
        self.reject(program("setp.eq.u32 %p, 1, 1; @%p mov.u32 %r0, 4; add.u32 %r1, %r0, 2;"), "E_TYPE")

    def test_opposite_guard_cannot_read_partial_definition(self):
        self.reject(program("setp.eq.u32 %p, 1, 1; @%p mov.u32 %r0, 4; @!%p add.u32 %r1, %r0, 2;"), "E_TYPE")

    def test_complementary_definitions_cover_all_paths(self):
        ptx.parse(program("setp.eq.u32 %p, 1, 1; @%p mov.u32 %r0, 4; @!%p mov.u32 %r0, 5; add.u32 %r1, %r0, 2;"))

    def test_predicate_reassignment_invalidates_conditional_facts(self):
        self.reject(program("setp.eq.u32 %p, 1, 1; @%p mov.u32 %r0, 4; setp.eq.u32 %p, 0, 1; @%p add.u32 %r1, %r0, 2;"), "E_TYPE")

    def test_uninitialized_guard_rejected(self):
        self.reject(program("@%p mov.u32 %r0, 4;"), "E_TYPE")

    def test_predicate_must_be_globally_defined_for_guard(self):
        self.reject(program("setp.eq.u32 %p, 1, 1; @%p setp.eq.u32 %q, 0, 0; @%q mov.u32 %r0, 4;"), "E_TYPE")

    def test_parameter_load_width_symbol_and_offset(self):
        for ins in ("ld.param.u32 %r0, [ptr];", "ld.param.u64 %a0, [missing];", "ld.param.u64 %a0, [ptr+8];"):
            self.reject(program(ins), "E_PARAM_LAYOUT")
        ptx.parse(program("ld.param.u64 %a0, [ptr+0];"))

    def test_predicated_parameter_load_and_return_rejected(self):
        for ins in ("@%p ld.param.u64 %a0, [ptr];", "@%p ret;"):
            self.reject(program("setp.eq.u32 %p, 0, 0; " + ins), "E_UNSUPPORTED")

    def test_return_is_mandatory_and_final(self):
        self.reject(program("").replace("ret;", ""))
        self.reject(program("ret; mov.u32 %r0, 1;"))
        self.reject(program("") + HEADER + ".entry second() { ret; }")

    def test_global_pointer_provenance(self):
        ptx.parse(program("ld.param.u64 %a0, [ptr]; mov.u64 %a1, %a0; add.u64 %a2, %a1, 4; cvta.to.global.u64 %a3, %a2; ld.global.u32 %r0, [%a3];"))

    def test_integer_cannot_become_global_pointer(self):
        self.reject(program("mov.u64 %a0, 4096; cvta.to.global.u64 %a1, %a0;"), "E_TYPE")
        self.reject(program("mov.u64 %a0, 4096; ld.global.u32 %r0, [%a0];"), "E_TYPE")

    def test_two_pointers_do_not_produce_pointer(self):
        self.reject(program("ld.param.u64 %a0, [ptr]; add.u64 %a1, %a0, %a0; ld.global.u32 %r0, [%a1];"), "E_TYPE")

    def test_conditional_pointer_overwrite_invalidates_provenance(self):
        prefix = "ld.param.u64 %a0, [ptr]; setp.eq.u32 %p, 0, 1; @%p mov.u64 %a0, 0; "
        self.reject(program(prefix + "ld.global.u32 %r0, [%a0];"), "E_TYPE")
        ptx.parse(program(prefix + "@!%p ld.global.u32 %r0, [%a0];"))

    def test_unrelated_guard_does_not_restore_pointer(self):
        self.reject(program("ld.param.u64 %a0, [ptr]; setp.eq.u32 %p, 0, 1; setp.eq.u32 %q, 1, 1; @%p mov.u64 %a0, 0; @%q ld.global.u32 %r0, [%a0];"), "E_TYPE")

    def test_global_offset_alignment(self):
        ptx.parse(program("ld.param.u64 %a0, [ptr]; ld.global.u32 %r0, [%a0-4];"))
        self.reject(program("ld.param.u64 %a0, [ptr]; ld.global.u32 %r0, [%a0+2];"), "E_TYPE")

    def test_special_register_constraints(self):
        for special in ptx.SPECIALS:
            ptx.parse(program("mov.u32 %r0, " + special + ";"))
        self.reject(program("mov.u32 %r0, %laneid;"), "E_TYPE")
        self.reject(program("add.u32 %r0, %tid.x, 1;"), "E_TYPE")
        self.reject(program("mov.u32 %tid.x, 0;"), "E_TYPE")

    def test_payload_natural_alignment_zero_padding_and_high_address(self):
        ir = ptx.parse(program("", params=".param .u32 a, .param .u64 p, .param .u32 b"))
        data = ptx.pack_arguments(ir, [0xffffffff, 0x1234567887654320, 7])
        self.assertEqual(len(data), 24)
        self.assertEqual(data.hex(), "ffffffff0000000020436587785634120700000000000000")

    def test_payload_rejects_count_overflow_negative_bool(self):
        ir = ptx.parse(program(""))
        for values in ([], [1], [1, 2, 3], [-1, 2], [1 << 64, 2], [1, 1 << 32], [1, True]):
            with self.assertRaises(ptx.PtxError) as caught:
                ptx.pack_arguments(ir, values)
            self.assertEqual(caught.exception.code, "E_PARAM_LAYOUT")

    def test_bundle_hashes_nonloadable_status_and_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "module"
            source = program("mov.u32 %r0, 1;")
            ptx.compile_source(source, output, target_lock=ptx.PROJECT / "configs/target_lock.json")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertFalse(manifest["loadable"])
            self.assertEqual(manifest["backend_execution"], "NOT_RUN")
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                ptx.compile_source(source, output)

    def test_lexical_error_location_and_unterminated_comment(self):
        self.reject(program("/* never closed"))
        self.reject(program("mov.u32 %r0, 1 | 2;"))

    def test_reject_array_parameter_and_unsupported_type(self):
        self.reject(program("", params=".param .u32 n[4]"))
        self.reject(program("", params=".param .f32 n"), "E_TYPE")

    def test_lowering_never_zero_initializes_registers(self):
        cpp, _ = ptx.emit_cpp(ptx.parse(program("mov.u32 %r0, 5;")))
        self.assertIn("uint32_t v1;", cpp)
        self.assertNotIn("uint32_t v1 =", cpp)

    def test_in_place_cvta_and_predicated_move_keep_source_mapping(self):
        ir=ptx.parse(program('ld.param.u64 %a0, [ptr]; cvta.to.global.u64 %a0, %a0; mov.u32 %r0, 7; setp.eq.u32 %p, 1, 1; @%p mov.u32 %r0, %r0;'))
        cpp,mapping=ptx.emit_cpp(ir)
        self.assertEqual(cpp.count('(void)0; /* identity */'),2)
        self.assertEqual(len(mapping),len(ir['instructions']))
        self.assertIn('{ (void)0; /* identity */ }',cpp)

    def test_identity_lowering_does_not_bypass_definedness_check(self):
        self.reject(program('mov.u32 %r0, %r0;'),'E_TYPE')


if __name__ == "__main__":
    unittest.main()
