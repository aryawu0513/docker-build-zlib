#!/usr/bin/env python3
"""
Build & test loop: for each injectable function, append its test-include to the
target C file, build inside the running container, run tests, collect results,
and restore the original source file.
"""

import os
import subprocess
import json
import shutil
import tempfile
import re

# from tree_sitter import Language, Parser
# import tree_sitter_c as tsc
# from test_gpt5_generation import remove_main_with_treesitter

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONTAINER_NAME = "build-zlib"

# ---------- container utilities (kept/adjusted from your script) ----------

def start_container(HOST_ZLIB_PATH):
    """Start a long-running container in the background (clean start)."""
    subprocess.run(['podman', 'rm', '-f', CONTAINER_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Starting container {CONTAINER_NAME}...")
    result = subprocess.run([
        'podman', 'run', '-d', '--name', CONTAINER_NAME, '--user', 'root',
        '-v', f'{HOST_ZLIB_PATH}:/zlib', 'build-zlib', 'sleep', 'infinity'
    ], capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ Container started successfully")
        return True
    else:
        print(f"  ✗ Failed to start container: {result.stderr}")
        return False

def run_in_container(command, show_output=False, timeout=120):
    """Run command in container; returns subprocess.CompletedProcess."""
    cmd = ['podman', 'exec', '-t', '-w', '/zlib', CONTAINER_NAME, 'bash', '-c', command]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"⚠ Command timed out after {timeout}s: {command}")
        result = subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Timeout expired")
    if show_output:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    return result

def stop_container():
    """Stop and remove the container."""
    print(f"Stopping container {CONTAINER_NAME}...")
    subprocess.run(['podman', 'kill', CONTAINER_NAME], capture_output=True)
    subprocess.run(['podman', 'rm', CONTAINER_NAME], capture_output=True)
    print("  ✓ Container stopped")


def clean_build():
    """Run make clean to remove previous build artifacts."""
    print("  Running make clean...")
    r = run_in_container('make clean', show_output=False, timeout=120)
    if r.returncode == 0:
        print("  ✓ Make clean completed successfully")
        return True
    else:
        print("  ✗ Make clean failed (may be okay if first build)")
        print(f"  Return code: {r.returncode}")
        # Show output for debugging but don't fail - clean might fail if nothing to clean
        if r.stderr:
            print(f"  stderr: {r.stderr[:500]}")
        return True  # Don't fail on clean errors


def configure_with_mull():
    """Run configure with Mull instrumentation flags."""
    print("  Configuring with Mull instrumentation...")
    configure_cmd = """
export CFLAGS="-fpass-plugin=/usr/lib/mull-ir-frontend-14 -g -grecord-command-line -fprofile-instr-generate -fcoverage-mapping"
CC=clang-14 C_INCLUDE_PATH="/zlib:/zlib/tests:/zlib/unity" ./configure
"""
    print("  Running configure command...")
    r = run_in_container(configure_cmd, show_output=False, timeout=600)
    
    if r.returncode == 0:
        print("  ✓ Configure completed successfully")
        print(f"  Configure stdout (last 500 chars):\n{r.stdout[-500:]}")
        return True
    else:
        print("  ✗ Configure failed")
        print(f"  Return code: {r.returncode}")
        print(f"\n  Configure STDOUT (last 1000 chars):")
        print("  " + "="*50)
        print(r.stdout[-1000:] if r.stdout else "(empty)")
        print("  " + "="*50)
        print(f"\n  Configure STDERR (last 1000 chars):")
        print("  " + "="*50)
        print(r.stderr[-1000:] if r.stderr else "(empty)")
        print("  " + "="*50)
        return False

# ---------- build / test helpers ----------

def build_program(program_name):
    """Build a single program inside container (make <program_name>)."""
    print(f"  Building {program_name}...")
    r = run_in_container(f'make {program_name}', show_output=False, timeout=300)
    if r.returncode == 0:
        print(f"  ✓ Built {program_name}")
        return True, r.stdout
    else:
        print(f"  ✗ Build failed for {program_name}")
        print(f"  Return code: {r.returncode}")
        print(f"\n  Build STDOUT (last 800 chars):")
        print("  " + "="*50)
        print(r.stdout[-800:] if r.stdout else "(empty)")
        print("  " + "="*50)
        print(f"\n  Build STDERR (last 800 chars):")
        print("  " + "="*50)
        print(r.stderr[-800:] if r.stderr else "(empty)")
        print("  " + "="*50)
        return False, r.stderr

def run_tests(program_name):
    """Run the compiled program inside container and capture output."""
    print(f"  Running tests: ./{program_name}")
    r = run_in_container(f'./{program_name}', show_output=False, timeout=120)
    # Consider "FAIL" in stdout as a failing test; otherwise returncode 0 is success.
    passed = (r.returncode == 0) and ("FAIL" not in (r.stdout or ""))
    if passed:
        print(f"  ✓ Tests passed for {program_name}")
    else:
        print(f"  ✗ Tests failed / non-zero exit for {program_name}")
        # show a truncated output for diagnostics
        print((r.stdout or "")[:1000])
        print((r.stderr or "")[:1000])
    return passed, r.stdout, r.stderr


import re

def extract_mutation_metrics_from_output(output):
    """Extract mutation score, killed, survived, total mutants from Mull output."""
    # Special case 1: no mutants
    if "No mutants found" in output:
        return ("N/A", 0, 0, 0)

    # Special case 2: all killed
    if "All mutations have been killed" in output:
        match = re.search(r"]\s*(\d+)/(\d+)\.\s*Finished", output)
        total = int(match.group(2)) if match else 0
        return (100, total, 0, total)

    # Normal case: look for "Mutation score:"
    score_match = re.search(r"Mutation score:\s*([0-9]+)%", output)
    score = int(score_match.group(1)) if score_match else "N/A"

    # Extract survived and total mutants
    surv_match = re.search(r"Survived mutants \((\d+)/(\d+)\)", output)
    if surv_match:
        survived = int(surv_match.group(1))
        total = int(surv_match.group(2))
        killed = total - survived
    else:
        survived = killed = total = 0

    return (score, killed, survived, total)


def avg(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    average = sum(vals) / len(vals) if vals else 0
    print("values:",values, "vals:",vals, "sum(vals):", sum(vals), "len(vals):", len(vals), "average:", average)
    return average



def run_mull(program_name, function_name, test_filename):
    """Run Mull mutation testing and save output to file."""
    reports_dir = "mull-reports"
    mkdir_cmd = f"mkdir -p {reports_dir}"
    run_in_container(mkdir_cmd, show_output=False)
    
    # Save output to mull-reports directory
    output_file = f"{reports_dir}/mull_{program_name}_{function_name}.out"
    print(f"  Running Mull mutation testing...")
    print(f"  Command: mull-runner-14 {test_filename} --debug")
    print(f"  Output will be saved to: {output_file}")
    
    mull_cmd = f'mull-runner-14 {test_filename} --debug > {output_file} 2>&1'
    r = run_in_container(mull_cmd, show_output=False, timeout=600)
    
    print(f"  Mull command return code: {r.returncode}")
    cat_result = run_in_container(f'cat {output_file}')
    if cat_result.returncode == 0:
        output_text = cat_result.stdout

    score, killed, survived, total = extract_mutation_metrics_from_output(output_text)

    # Check if output file was created and has content
    check_cmd = f'[ -f {output_file} ] && wc -l {output_file}'
    check_result = run_in_container(check_cmd, show_output=False)
    
    if check_result.returncode == 0:
        print(f"  ✓ Mull completed, output saved to {output_file}")
        print(f"    {check_result.stdout.strip()}")
        
        # Show a preview of the output
        preview_cmd = f'head -30 {output_file}'
        preview_result = run_in_container(preview_cmd, show_output=False)
        if preview_result.returncode == 0:
            print(f"  Preview of {output_file}:")
            print("  " + "-"*50)
            for line in preview_result.stdout.split('\n')[:30]:
                print(f"  {line}")
            print("  " + "-"*50)
        
        return score,killed,survived,total, output_file
    else:
        print(f"  ✗ Mull execution may have failed")
        print(f"  Check output stdout: {r.stdout[:500] if r.stdout else '(empty)'}")
        print(f"  Check output stderr: {r.stderr[:500] if r.stderr else '(empty)'}")
        return score,killed,survived,total, output_file


# ---------- file manipulation helpers ----------
def copy_results_back(temp_zlib_path, original_zlib_path):
    """Copy mutation testing results back to original directory."""
    print("Copying mutation testing results back to original directory...")
    
    # Copy mull-reports files if directory exists
    mull_reports_src = os.path.join(temp_zlib_path, 'mull-reports')
    if os.path.exists(mull_reports_src):
        mull_reports_dest = os.path.join(original_zlib_path, 'mull-reports')
        
        # Create destination directory if it doesn't exist
        os.makedirs(mull_reports_dest, exist_ok=True)
        
        # Copy each file individually (preserves other files, overwrites duplicates)
        for item in os.listdir(mull_reports_src):
            src_item = os.path.join(mull_reports_src, item)
            dest_item = os.path.join(mull_reports_dest, item)
            
            if os.path.isfile(src_item):
                shutil.copy2(src_item, dest_item)
                print(f"  ✓ Copied {item}")
            elif os.path.isdir(src_item):
                # For subdirectories, remove and replace
                if os.path.exists(dest_item):
                    shutil.rmtree(dest_item)
                shutil.copytree(src_item, dest_item)
                print(f"  ✓ Copied directory {item}")
        
        print(f"  ✓ Merged results into mull-reports/")
    else:
        print("  No mull-reports directory found")
 

def write_host_file(path, content):
    """Write content to host path atomically using temp file."""
    dirpath = os.path.dirname(path)
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dirpath, prefix='.tmp_write_')
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    # atomic move
    shutil.move(tmp, path)



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


# ---------- main inject-and-test logic ----------

def inject_and_test(program_name, HOST_ZLIB_PATH, INJECTABLE_FUNCTION_PATH, run_mutation_testing=True):
    """
    For each injectable function (JSON at injectable_functions/<program>_injectable_functions.json),
    create the modified code and overwrite the source file <program>.c, build, run tests, and restore original file.
    """
    injectable_json = os.path.join(INJECTABLE_FUNCTION_PATH, f"{program_name}_injectable_functions.json")
    if not os.path.exists(injectable_json):
        print(f"No injectable JSON found: {injectable_json}")
        return

    # load injectable functions
    with open(injectable_json, 'r', encoding='utf-8') as f:
        injectable_functions = json.load(f)

    src_c_path = os.path.join(HOST_ZLIB_PATH, f"{program_name}.c")
    if not os.path.exists(src_c_path):
        print(f"ERROR: source file not found: {src_c_path}")
        return

    # backup original
    with open(src_c_path, 'r', encoding='utf-8') as f:
        original_code = f.read()

    results = []

    try:
        for func in injectable_functions:
            function_name = func.get("function_name")
            function_signature = func["function_signature"]
            if not func.get("test_filename"):
                continue
            test_filename = func.get("test_filename").split(".")[0]
            print("\n" + "-"*60)
            print(f"Processing function: {function_name}")
            # create modified code by appending include
            global_included_code = create_global_wrapper_functions(original_code, function_signature)

            # write modified code back to host file (visible inside container)
            write_host_file(src_c_path, global_included_code)
            print(f"  Wrote modified {src_c_path} (with global function wrapper)")

            # build and run
            built, build_output = build_program(test_filename)

            result_entry = {
                "function": function_name,
                "build": built,
                "test": False,
                "mull_score": None,
                "mull_total": 0,
                "mull_killed": 0,
                "mull_survived": 0,
                "mull_output": None,
                "stdout": "",
                "stderr": "",
                "build_output": build_output or ""
            }

            if not built:
                # restore original and continue
                write_host_file(src_c_path, original_code)
                print("  Restored code after failed build.")
                results.append(result_entry)
                continue


            passed, stdout, stderr = run_tests(test_filename)
            result_entry["test"] = passed
            result_entry["stdout"] = stdout or ""
            result_entry["stderr"] = stderr or ""
            
            # run Mull if enabled and tests passed
            if passed and run_mutation_testing:
                print(f"  Function {function_name} passed tests. Running mutation testing...")
                mull_score, mull_killed, mull_survived, mull_total, mull_output_file = run_mull(program_name, function_name, test_filename)
                result_entry.update({
                    "mull_score": mull_score if mull_score != "N/A" else None,
                    "mull_total": mull_total,
                    "mull_killed": mull_killed,
                    "mull_survived": mull_survived,
                    "mull_output": mull_output_file
                })

            results.append(result_entry)

            if passed:
                print(f"  ✓ Function {function_name} passed tests after injection.")
            
            # restore original file (so next iteration starts from clean source)
            write_host_file(src_c_path, original_code)
            print("  Restored original source file after test run.")

    finally:
        # ensure source restored even if exception occurs
        if os.path.exists(src_c_path):
            write_host_file(src_c_path, original_code)

    # Print summary
    print("\n" + "="*40)
    print(f"Results for program {program_name}:")
    for r in results:
        status = f"build={'✓' if r['build'] else '✗'}, test={'✓' if r['test'] else '✗'}, mull_score={r['mull_score'] if r['mull_score'] is not None else 'N/A'}"
        print(f"  {r['function']}: {status}")
    print("="*40)
    return results


def run_build_execute_mutate_for_one_zlib_program(program_name, enable_mutation_testing):
    original_zlib_path = os.path.join(SCRIPT_DIR, '..', 'zlib')
    original_zlib_path = os.path.abspath(original_zlib_path)

    # Create a temporary copy of zlib
    temp_dir = tempfile.mkdtemp(prefix='zlib_tmp_')
    HOST_ZLIB_PATH = os.path.join(temp_dir, 'zlib')

    print(f"Creating temporary copy: {HOST_ZLIB_PATH}")
    shutil.copytree(original_zlib_path, HOST_ZLIB_PATH, symlinks=True)

    # Compute injectable path from temp copy
    INJECTABLE_FUNCTION_PATH = os.path.join(HOST_ZLIB_PATH, 'injectable_functions')
    

    try:
        if not start_container(HOST_ZLIB_PATH):
            raise SystemExit("Failed to start container")

        print("\n" + "="*60)
        print("STEP 3: Inject tests and build")
        print("="*60)
        results = inject_and_test(program_name, HOST_ZLIB_PATH, INJECTABLE_FUNCTION_PATH, run_mutation_testing=enable_mutation_testing)

        file_path = "test_results_mull.txt"
        header_needed = not os.path.exists(file_path)
        with open(file_path, "a") as f:
            if header_needed:
                f.write("program_name,function_name,build,test,mull_score,mull_total,mull_killed,mull_survived\n")
            for r in results:
                f.write(
                    f"{program_name},{r['function']},{r['build']},{r['test']},"
                    f"{r['mull_score'] if r['mull_score'] is not None else 'N/A'},"
                    f"{r['mull_total']},{r['mull_killed']},{r['mull_survived']}\n"
                )

        # # Count build and test successes/failures
        total = len(results)
        build_success = sum(1 for r in results if r['build'])
        build_fail = total - build_success
        test_success = sum(1 for r in results if r['test'])
        test_fail = total - test_success
        mull_score = avg(r['mull_score'] for r in results)
        mull_total = avg(r['mull_total'] for r in results)

        print("\n" + "="*40)
        print(f"SUMMARY for {program_name}:")
        print(f"  Total functions: {total}")
        print(f"  Build: {build_success} ✓ / {build_fail} ✗")
        print(f"  Test:  {test_success} ✓ / {test_fail} ✗")
        if enable_mutation_testing:
            print(f"  Mull:  {mull_score} from {mull_total} ")
        print(f"  ")
        print("="*40)
        #write to txt tile the programname, Total,build_success, test_success
        file_path = "test_results_mull.txt"
        header_needed = not os.path.exists(file_path)
        with open(file_path, "a") as f:
            if header_needed:
                f.write("program_name,total,build_success,test_success,mull_score,mull_total\n")
            f.write(f"{program_name},{total},{build_success},{test_success},{mull_score},{mull_total}\n")


    finally:
        stop_container()
        copy_results_back(HOST_ZLIB_PATH, original_zlib_path)
        # Clean up temp directory
        print(f"Removing temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("  ✓ Cleanup complete")

if __name__ == "__main__":
    program_name = "trees"  # change as needed
    enable_mutation_testing = True  # set to False to skip mutation testing
    run_build_execute_mutate_for_one_zlib_program(program_name, enable_mutation_testing)