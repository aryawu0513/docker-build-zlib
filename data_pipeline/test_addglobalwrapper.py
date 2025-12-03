import dspy
import os
from tree_sitter import Language, Parser
import tree_sitter_c as tsc
import re
from pathlib import Path
import json
import re

def create_global_wrapper_functions(original_code, function_signature):
    """
    For a given function, if its signature contains 'local',
    generate a global wrapper and append it after the original function's full code.

    local int gz_skip(gz_statep state, z_off64_t len)
    -->
    int test_gz_skip(gz_statep state, z_off64_t len) {
        return gz_skip(state, len);
    }

    if it's not local, return the original code unchanged.
    """

    # Convert `function_signature` into a matching regex
    # e.g. "local int gz_skip(gz_statep state, z_off64_t len)"
    sig_regex = (
        r'\b' +
        re.escape("local") + r'\s+' +
        r'([^\(\)]+?)\s+' +                  # return type
        r'(' + re.escape(function_signature.split()[2].split("(")[0]) + r')\s*' +
        r'\(([^)]*)\)'                       # parameters
    )
    pattern = re.compile(sig_regex, re.MULTILINE)

    match = pattern.search(original_code)
    if not match:
        print("No local function match found for signature:", function_signature)
        return original_code  # not a local function → no wrapper

    ret_type = match.group(1).strip()
    name = match.group(2).strip()
    params = match.group(3).strip()

    # Extract argument names for the call
    if not params.strip():
        call_args = ""
    else:
        call_args = ", ".join(p.split()[-1] for p in params.split(","))

    # ---- Find the FULL function body ----
    sig_end = match.end()
    body_start = original_code.find("{", sig_end)
    if body_start == -1:
        return original_code

    # Match braces to find end of function
    brace_count = 1
    i = body_start + 1
    while i < len(original_code) and brace_count > 0:
        if original_code[i] == "{":
            brace_count += 1
        elif original_code[i] == "}":
            brace_count -= 1
        i += 1
    body_end = i  # index after closing }

    # ---- Build wrapper ----
    wrapper = (
        f"\n{ret_type} test_{name}({params}) {{\n"
        f"    return {name}({call_args});\n"
        f"}}\n\n"
    )

    # ---- Insert wrapper after full function ----
    modified = original_code[:body_end] + wrapper + original_code[body_end:]
    return modified

if __name__ == "__main__":
    module_name = "zlib"
    data_pipeline_dir = Path(__file__).parent
    zlib_dir = data_pipeline_dir.parent / module_name
    source_file_path = zlib_dir / "gzread.c"

    with open(source_file_path, 'r') as f:
        original_code = f.read()

    function_signature = "int ZEXPORT gzungetc(int c, gzFile file)"
    modified_code = create_global_wrapper_functions(original_code, function_signature)

    output_file_path = "gzread_with_wrappers.c"
    with open(output_file_path, 'w') as f:
        f.write(modified_code)

    print(f"Modified code with global wrappers written to {output_file_path}")