"""Global memory still translates when a constant buffer has only a U32x4 view.

MoltenVK cannot put two descriptor arrays on one binding, so descriptor aliasing is off and a constant buffer is the
U32x4 view alone. The global-memory helper used to OpAccessChain the U32x2 view, whose id was never defined: Sirit
aborts on a zero id, and shader preparation died in DefineGlobalMemoryFunctions. The address and the size are read out
of the view that exists, and a 64- or 128-bit access with no storage view of that width is that many 32-bit accesses.
python -I -B tests/test_moltenvk_global_cbuf.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "gpu" / "vk" / "eden" / "shader_recompiler" / "backend" / "spirv" / "spirv_emit_context.cpp"
SHADER = ROOT / "gpu" / "vk" / "vk_shader.cpp"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    shader = SHADER.read_text(encoding="utf-8")
    if "p.support_descriptor_aliasing = dev.driver_id != VK_DRIVER_ID_MOLTENVK;" not in shader:
        raise SystemExit("vk_shader.cpp: MoltenVK still aliases descriptors")
    body = block(CONTEXT.read_text(encoding="utf-8"), "void EmitContext::DefineGlobalMemoryFunctions(")
    if "cbufs[ssbo.cbuf_index].U32x2, zero" in body or "cbufs[table.cbuf_index].U32x2, zero" in body:
        raise SystemExit("DefineGlobalMemoryFunctions still access-chains a U32x2 constant buffer that may not exist")
    for piece in ("cbuf_u32x2", "uniform_types.U32x4", "define_wide_from_u32", "load_global_func_u32"):
        if piece not in body:
            raise SystemExit("DefineGlobalMemoryFunctions has no %s" % piece)
    guarded = body[body.index("const auto cbuf_u32x2"):body.index("const auto struct_pointer_of")]
    if "ValidId(uniform_types.U32x2)" not in guarded or "ValidId(cbufs[cbuf_index].U32x2)" not in guarded:
        raise SystemExit("the U32x2 constant-buffer load is not skipped when that view was not defined")
    print("global memory reads the constant buffer view that exists")


if __name__ == "__main__":
    main()
