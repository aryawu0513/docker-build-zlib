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
    Safely create a global wrapper for a 'local' function. 
    If the function is not local or parsing fails, returns the original code unchanged.
    """

    try:
        # Only wrap functions declared as 'local'
        if 'local' not in function_signature.split():
            print(f"Skipping non-local function: {function_signature}")
            return original_code

        # Extract function name and parameters
        m = re.search(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)', function_signature)
        if not m:
            print(f"Could not parse function name from signature (skipping): {function_signature}")
            return original_code

        name = m.group(1).strip()
        params_str = m.group(2).strip()  # may be empty

        # Extract return type and remove 'local' keyword
        ret_type_match = re.search(r'^(.*)\b' + re.escape(name) + r'\s*\(', function_signature)
        if not ret_type_match:
            print(f"Could not determine return type (skipping): {function_signature}")
            return original_code

        ret_type = ret_type_match.group(1).replace('local', '').strip()

        # Build call arguments for wrapper function
        if not params_str:
            call_args = ""
            wrapper_params = "void"
        else:
            cleaned = params_str.replace("OF((", "(").replace("))", ")")
            param_list = [p.strip() for p in cleaned.split(",") if p.strip()]

            arg_names = []
            wrapper_param_items = []
            for p in param_list:
                toks = p.split()
                if toks:
                    last = toks[-1].lstrip('*').rstrip(';')
                    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', last):
                        arg_names.append(last)
                        wrapper_param_items.append(p)
                    else:
                        wrapper_param_items.append(p)
            wrapper_params = ", ".join(wrapper_param_items)
            call_args = ", ".join(arg_names)

        # Locate full function body in original code
        sig_search = re.search(re.escape(function_signature.strip()) + r'\s*\{', original_code)
        if not sig_search:
            print(f"Could not find function {name} in source — skipping wrapper.")
            return original_code

        body_start = sig_search.end() - 1  # position of '{'
        brace_count = 1
        i = body_start + 1
        L = len(original_code)
        while i < L and brace_count > 0:
            if original_code[i] == "{":
                brace_count += 1
            elif original_code[i] == "}":
                brace_count -= 1
            i += 1

        if brace_count != 0:
            print(f"Unbalanced braces for {name} — skipping wrapper.")
            return original_code

        body_end = i

        # Build wrapper function
        wrapper = f"\n/* Auto-generated test wrapper */\n{ret_type} test_{name}({wrapper_params}) {{\n"

        # Decide how to call original function
        if not params_str or params_str.strip() == "void":
            call_expr = f"{name}()"
        else:
            call_expr = f"{name}({call_args})"

        if ret_type == "void":
            wrapper += f"    {call_expr};\n"
        else:
            wrapper += f"    return {call_expr};\n"

        wrapper += "}\n\n"

        # Insert wrapper after function body
        modified = original_code[:body_end] + wrapper + original_code[body_end:]
        print(f"Inserted wrapper test_{name} after function {name}")
        return modified

    except Exception as e:
        print(f"Error creating wrapper for {function_signature}: {e}")
        return original_code


if __name__ == "__main__":
    module_name = "zlib"
    data_pipeline_dir = Path(__file__).parent
    zlib_dir = data_pipeline_dir.parent / module_name
    source_file_path = zlib_dir / "trees.c"

    with open(source_file_path, 'r') as f:
        original_code = f.read()

    function_signature = "local void bi_flush(deflate_state *s)"
    # function_signature = "local void tr_static_init(void)"
    # function_signature = "local void send_bits(deflate_state *s, int value, int length)"
    # function_signature = "void ZLIB_INTERNAL _tr_flush_block(deflate_state *s, charf *buf, ulg stored_len, int last)"
    modified_code = create_global_wrapper_functions(original_code, function_signature)

    output_file_path = "trees_with_wrappers.c"
    with open(output_file_path, 'w') as f:
        f.write(modified_code)

    print(f"Modified code with global wrappers written to {output_file_path}")