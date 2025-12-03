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
    module_name = "gzread"
    generate_tests_for_one_zlib_file(module_name)