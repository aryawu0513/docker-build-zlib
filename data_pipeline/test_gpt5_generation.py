import dspy
import os
from tree_sitter import Language, Parser
import tree_sitter_c as tsc
import re
from pathlib import Path
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_ZLIB_PATH = os.path.join(SCRIPT_DIR, '..', 'zlib')
HOST_ZLIB_PATH = os.path.abspath(HOST_ZLIB_PATH)
INJECTABLE_FUNCTION_PATH = os.path.join(HOST_ZLIB_PATH, 'injectable_functions')


def get_function_info(c_file, parser):
    """
    Extract detailed information about all functions (except main).
    
    Args:
        c_file: Path to the C source file
        parser: tree-sitter Parser instance
    
    Returns:
        List of dicts with keys: 'name', 'start_byte', 'end_byte', 'code', 'signature'
    """
    # Parse the code
    with open(c_file, 'rb') as f:
        c_code = f.read()
    tree = parser.parse(c_code)
    
    functions = []
    
    def get_function_signature(func_def_node):
        """Extract the function signature (return type + declarator)"""
        signature_parts = []
        
        for child in func_def_node.children:
            # Get everything before the compound_statement (function body)
            if child.type == 'compound_statement':
                break
            signature_parts.append(c_code[child.start_byte:child.end_byte])
        
        return b' '.join(signature_parts).decode('utf-8').strip()
    
    def filter_trivial_function(func_code, min_lines):
        """Return True if function has fewer than min_lines of code"""
        # Count non-empty lines
        lines = [line for line in func_code.splitlines() if line.strip()]
        return len(lines) < min_lines
        
    def traverse_tree(node):
        """Recursively traverse to find function definitions"""
        if node.type == 'function_definition':
            # Extract function name
            func_name = None
            for child in node.children:
                if child.type == 'function_declarator':
                    for subchild in child.children:
                        if subchild.type == 'identifier':
                            func_name = c_code[subchild.start_byte:subchild.end_byte].decode('utf-8')
                            break
                    break
            
            # Skip main function
            if func_name and func_name != 'main':
                func_code = c_code[node.start_byte:node.end_byte].decode('utf-8')
                
                # Skip functions that are too small
                if filter_trivial_function(func_code, 10):
                    return
                
                signature = get_function_signature(node)
                
                functions.append({
                    'name': func_name,
                    'start_byte': node.start_byte,
                    'end_byte': node.end_byte,
                    'code': func_code,
                    'signature': signature
                })
        
        # Recursively traverse children
        for child in node.children:
            traverse_tree(child)
    
    traverse_tree(tree.root_node)
    return functions

class FunctionToUnityTests(dspy.Signature):
    """
    You will be given a zlib source module and its contents, along with the name of a SPECIFIC FUNCTION within it.
    Your task is to write a standalone test suite (tests_{module_name}_{function_name}.c) that thoroughly tests ONLY this specific function, using the Unity Testing Framework.

    CONTEXT:
    You should call the function directly without redefining it in the test file.
    In the case where the function given to you is declared local in the source code, I have added a global wrapper function named test_{function_name} in the source code for you to call instead. You should call the global wrapper test_{function_name} instead of the original local function.
    Do not redefine internal structs, functions, or macros from the zlib source — this can cause compilation errors or runtime issues. Use the existing definitions. 

    REQUIRED FORMAT for `tests_{module_name}_{function_name}.c`: A Unity test file that thoroughly tests the given function's functionality.
    - At the top of the file, add 
        ```c
        #include "unity/unity.h"
        #include "zlib.h"
        ```
        Also include any other standard headers needed for the test code itself (e.g., stdlib.h, string.h, math.h).
    - Implement setUp() and tearDown() functions for Unity:
        ```c
        void setUp(void) {
        /* Setup code here, or leave empty */
        }
        void tearDown(void) {
        /* Cleanup code here, or leave empty */
        }
        ```
    - Create multiple test functions: void test_<function_name>_xxx(void) { ... }. Each test function should set up the necessary preconditions, call the target function, and use Unity assertions to verify expected outcomes.
    - Define main() that calls UNITY_BEGIN(), RUN_TEST() for each test, and returns UNITY_END().
    - CRITICAL RULES FOR STDOUT/STDERR REDIRECTION: Unity's TEST_ASSERT macros write to stdout. If your test redirects stdout (common for I/O testing), do NOT use TEST_ASSERT macros while stdout is redirected. Use simple if-checks with return NULL for errors. Only use TEST_ASSERT before redirection or after restoration.
    """
    module_name : str = dspy.InputField(description="The zlib source module filename (e.g., 'gzread.c')")
    module_code: str = dspy.InputField(description="The full contents of the zlib source file")
    target_function_name: str = dspy.InputField(description="Name of the specific function to test")
    tests_c: str = dspy.OutputField(description="Complete Unity test file that thoroughly tests ONLY the target function")

def initialize_llm():
    """
    Initialize the LLM once and return the configured converter.
    This should be called once at the start of the program.
    """
    print("Initializing LLM...")
    lm = dspy.LM(
        "gpt-5",
        model_type="chat",
        temperature=1.0,
        max_tokens=16000,  # these are required by gpt5
    )
    dspy.configure(lm=lm)
    converter = dspy.ChainOfThought(FunctionToUnityTests)
    print("  ✓ LLM initialized successfully")
    return converter

def fix_stdout_stderr(code):
    """Add fflush calls before fork() to prevent duplicate output in child processes."""
    if "pid_t pid = fork();" in code:
        # Add fflush statements before the fork line
        code = code.replace(
            "pid_t pid = fork();",
            "fflush(stdout);\n    fflush(stderr);\n    pid_t pid = fork();"
        )
    return code


def generate_unity_tests_with_llm(converter, module_name, module_code, target_function_name):
    """
    Generate Unity tests using a pre-initialized LLM converter.
    
    Args:
        converter: Pre-initialized dspy.ChainOfThought(FunctionToUnityTests) instance
        module_name: The zlib source module filename (e.g., 'gzread.c')
        module_code: The full contents of the zlib source module
        target_function_name: Name of the specific function to test
    Returns:
        String containing the generated C code, or False on failure
    """
    try:
        print(f"  Generating tests for {target_function_name} in {module_name}...")
        
        # Generate the Unity tests
        result = converter(
            module_name=module_name,
            module_code=module_code,
            target_function_name=target_function_name
        )

        print(f"  ✓ LLM generation completed for {target_function_name}")
        
        # Extract the generated tests.c code
        tests_c = result.tests_c.strip()
        
        # Check if generation failed (empty string)
        if not tests_c:
            print(f"  ✗ LLM returned empty tests for {target_function_name}")
            return False
        
        # Remove markdown code blocks if present
        if "```c" in tests_c:
            tests_c = tests_c.split("```c")[1].split("```")[0]
        elif "```" in tests_c:
            tests_c = tests_c.split("```")[1].split("```")[0]

        # Fix stdout/stderr flushing before fork
        tests_c = fix_stdout_stderr(tests_c)
        
        return tests_c.strip()
        
    except Exception as e:
        print(f"  ✗ Error generating tests with LLM for {target_function_name}: {e}")
        return False
    

#for functions that are local, we need to create a global wrapper function for the tests code to call
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

def generate_tests_for_one_zlib_file(module_name):
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    # print(f"Generating Unity tests for {module_name}...")

    src_c_path = os.path.join(HOST_ZLIB_PATH, f"{module_name}.c")
    tests_dir_path = os.path.join(HOST_ZLIB_PATH, 'tests')
    
    # Check that the source file exists
    if not os.path.exists(src_c_path):
        raise FileNotFoundError(f"Required source file does not exist: {src_c_path}")

    # Check that the tests directory exists
    if not os.path.exists(tests_dir_path):
        os.makedirs(tests_dir_path, exist_ok=True)
        print(f"Required tests directory does not exist: {tests_dir_path}. Making the directory.")
    
    os.makedirs(INJECTABLE_FUNCTION_PATH, exist_ok=True)
    injectable_json_path = os.path.join(INJECTABLE_FUNCTION_PATH, f"{module_name}_injectable_functions.json")

    with open(src_c_path, 'r') as f:
        original_code = f.read()

    function_info = get_function_info(src_c_path, parser)

    # Initialize LLM once for all functions
    converter = initialize_llm()
    
    injectable_functions = []

    for i, func in enumerate(function_info, 1):
        function_name = func['name']
        function_name_clean = re.sub(r'[^0-9a-zA-Z_]', '_', function_name)
        function_signature = func['signature']
        print(f"\n[{i}/{len(function_info)}] Processing function: {function_name}")

        #call the helper function to check if the function is local and create a global wrapper if needed
        global_included_code = create_global_wrapper_functions(original_code, function_signature)
        
        # Reuse the same converter for all functions
        tests_c_result = generate_unity_tests_with_llm(
            converter,
            module_name, 
            global_included_code, 
            function_signature
        )

        # Write test file for this function
        test_filename = f"tests_{module_name}_{function_name_clean}.c"
        tests_c_per_function_path = os.path.join(tests_dir_path, test_filename)
        if tests_c_result:
            print(f"  ✓ Writing generated tests to {tests_c_per_function_path}")
            with open(tests_c_per_function_path, "w") as f:
                f.write(tests_c_result)
        else:
            print(f"  ✗ Failed to generate tests for function: {function_name}")

        injectable_functions.append({
            "function_name": function_name,
            "function_signature": function_signature,
            "test_filename": test_filename if tests_c_result else None
        })

        # Write JSON after each function (real-time)
        with open(injectable_json_path, "w") as f:
            json.dump(injectable_functions, f, indent=2)

    # Save injectable functions metadata
    # print(f"\n  Writing injectable functions metadata to {injectable_json_path}")
    # with open(injectable_json_path, "w") as f:
    #     json.dump(injectable_functions, f, indent=2)

    # print("\n" + "="*60)
    # print("COMPLETE")
    # print("="*60)
    print(f"Generated tests for {len(injectable_functions)} functions")

if __name__ == "__main__":
    module_name = "trees"
    generate_tests_for_one_zlib_file(module_name)